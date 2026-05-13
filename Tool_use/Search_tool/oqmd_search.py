"""
oqmd_search.py
──────────────────────────────────────────────
OQMD (Open Quantum Materials Database) 结构查询服务

特点：
  • 无需 API Key（OQMD 完全开放）
  • 直接调用 REST API（http://oqmd.org/oqmdapi/formationenergy）
  • 复用 search.py 中的缓存、重试、结构转换工具
  • 接口设计与 MPQueryService 对齐，便于上层统一调用
──────────────────────────────────────────────
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import requests
from pymatgen.core import Lattice, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from search import (
    _TTLCache,
    _retry,
    _safe_round,
    get_conventional,
    save_structure_to_disk,
    structure_to_cif,
    structure_to_poscar,
    structure_to_xyz,
)

logger = logging.getLogger("OQMDQueryService")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────
# OQMD REST API 配置
# ──────────────────────────────────────────────
_OQMD_BASE_URL = "http://oqmd.org/oqmdapi/formationenergy"

# 请求的字段列表（不含 sites/unit_cell 时结构不可用，但查询速度快）
_OQMD_FIELDS_LIGHT = (
    "name,entry_id,delta_e,band_gap,stability,"
    "spacegroup,prototype,natoms,ntypes,volume"
)
# 含结构数据（用于 fetch/download）
_OQMD_FIELDS_FULL = _OQMD_FIELDS_LIGHT + ",unit_cell,sites"


# ──────────────────────────────────────────────
# 结构解析
# ──────────────────────────────────────────────

def _parse_structure(
    unit_cell: List[List[float]],
    sites: List[str],
) -> Optional[Structure]:
    """
    从 OQMD REST API 返回的 unit_cell + sites 组装 pymatgen Structure。

    sites 格式为字符串列表，每条形如 "Fe @ 0.123 0.456 0.789"
    （分数坐标）。
    """
    try:
        lattice = Lattice(np.array(unit_cell))
        species: List[str] = []
        coords:  List[List[float]] = []
        for site in sites:
            elem_part, xyz_part = site.split("@", 1)
            species.append(elem_part.strip())
            coords.append([float(x) for x in xyz_part.strip().split()])
        return Structure(lattice, species, coords)
    except Exception as exc:
        logger.warning("OQMD 结构解析失败：%s", exc)
        return None


# ──────────────────────────────────────────────
# 单条结果构建
# ──────────────────────────────────────────────

def _build_result(
    data: Dict[str, Any],
    include_angles: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    将 OQMD API 返回的单条 dict 转换为标准化结果。
    含 unit_cell/sites 时一并构建结构文件字符串。
    """
    try:
        entry_id = data.get("entry_id")
        formula  = data.get("name", "?")
        stab     = data.get("stability")

        result: Dict[str, Any] = {
            "entry_id":                 entry_id,
            "formula":                  formula,
            "space_group":              data.get("spacegroup"),
            "prototype":                data.get("prototype"),
            "nsites":                   data.get("natoms"),
            "ntypes":                   data.get("ntypes"),
            "volume":                   _safe_round(data.get("volume"),  4),
            "band_gap":                 _safe_round(data.get("band_gap"), 4),
            "formation_energy_per_atom":_safe_round(data.get("delta_e"), 4),
            "stability":                _safe_round(stab, 4),
            "is_stable":                (stab is not None and stab <= 0.001),
        }

        unit_cell = data.get("unit_cell")
        sites     = data.get("sites")
        if unit_cell and sites:
            struct = _parse_structure(unit_cell, sites)
            if struct:
                conv    = get_conventional(struct)
                lat     = conv.lattice
                comment = f"{formula} | oqmd-{entry_id}"
                try:
                    cs = SpacegroupAnalyzer(conv, symprec=1e-3).get_crystal_system().value
                except Exception:
                    cs = None
                result.update({
                    "crystal_system": cs,
                    "a": _safe_round(lat.a, 4),
                    "b": _safe_round(lat.b, 4),
                    "c": _safe_round(lat.c, 4),
                    "cif":        structure_to_cif(conv),
                    "poscar":     structure_to_poscar(conv, comment),
                    "xyz":        structure_to_xyz(conv, comment),
                    "_structure": conv,
                })
                if include_angles:
                    result.update({
                        "alpha": _safe_round(lat.alpha, 2),
                        "beta":  _safe_round(lat.beta,  2),
                        "gamma": _safe_round(lat.gamma, 2),
                    })

        return result

    except Exception as exc:
        logger.warning("构建 OQMD 结果失败 entry_id=%s：%s",
                       data.get("entry_id", "?"), exc)
        return None


# ──────────────────────────────────────────────
# OQMDQueryService 主类
# ──────────────────────────────────────────────

class OQMDQueryService:
    """
    OQMD 结构查询服务（多策略查询 + TTL 缓存 + 自动重试）。

    无需 API Key。接口与 MPQueryService 对齐：
        svc.query_by_formula("Fe2O3")
        svc.query_by_entry_id(4061139)
        svc.query_by_elements(["Fe", "O"])
        svc.query_by_criteria(band_gap_min=1.0, stability_max=0.0)
    """

    def __init__(
        self,
        max_results:    int  = 20,
        cache_ttl:      int  = 300,
        include_angles: bool = False,
        timeout:        int  = 30,
    ):
        self.max_results    = max_results
        self.include_angles = include_angles
        self.timeout        = timeout
        self._cache         = _TTLCache(ttl=cache_ttl)

    # ── 底层 HTTP 请求 ────────────────────────
    @_retry(max_attempts=3, backoff=1.0)
    def _fetch_raw(self, params: Dict[str, Any], full: bool = True) -> List[Dict]:
        params = {k: v for k, v in params.items() if v is not None}
        params["fields"]  = _OQMD_FIELDS_FULL if full else _OQMD_FIELDS_LIGHT
        params["format"]  = "json"
        params["limit"]   = params.get("limit", self.max_results)
        logger.info("[OQMD API] GET %s params=%s", _OQMD_BASE_URL, params)
        resp = requests.get(_OQMD_BASE_URL, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("data", [])

    # ── 后处理（含客户端过滤） ────────────────
    def _post_process(
        self,
        raw: List[Dict],
        client_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        构建标准化结果列表，并施加客户端补充过滤。

        client_filters 格式：
            {"band_gap_max": 3.0, "formation_energy_min": -2.0, ...}
        """
        out = []
        for item in raw:
            result = _build_result(item, include_angles=self.include_angles)
            if result is None:
                continue
            if client_filters:
                if not _apply_client_filters(result, client_filters):
                    continue
            out.append(result)
            if len(out) >= self.max_results:
                break
        return out

    def _cached_query(
        self,
        cache_key:      str,
        params:         Dict[str, Any],
        full:           bool = True,
        client_filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("[cache] %s", cache_key)
            return cached
        raw     = self._fetch_raw(params, full=full)
        results = self._post_process(raw, client_filters)
        self._cache.set(cache_key, results)
        # Cross-populate per-entry cache so oqmd_fetch/oqmd_download can reuse
        # structure data from search results without re-hitting the API.
        # (The OQMD API's ?entry_id=X filter is unreliable for exact lookup.)
        for r in results:
            eid = r.get("entry_id")
            if eid is not None:
                eid_key = f"oqmd::eid::{eid}"
                if self._cache.get(eid_key) is None:
                    self._cache.set(eid_key, [r])
        return results

    # ── 公开查询方法 ──────────────────────────

    def query_by_formula(
        self,
        composition:  str,
        only_stable:  bool = False,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"composition": composition}
        if only_stable:
            params["stability"] = "<0.001"
        key = f"oqmd::formula::{composition}::{only_stable}"
        return self._cached_query(key, params)

    def query_by_elements(
        self,
        elements:     Sequence[str],
        num_elements: Optional[int] = None,
        only_stable:  bool = False,
    ) -> List[Dict[str, Any]]:
        # OQMD element_set: 逗号分隔表示 AND
        els    = [e.capitalize() for e in elements]
        params: Dict[str, Any] = {"element_set": ",".join(els)}
        if num_elements is not None:
            params["ntypes"] = num_elements
        if only_stable:
            params["stability"] = "<0.001"
        key = f"oqmd::els::{'_'.join(els)}::{num_elements}::{only_stable}"
        return self._cached_query(key, params)

    def query_by_criteria(self, **criteria) -> List[Dict[str, Any]]:
        """
        多条件过滤。支持字段：
            elements, composition, num_elements,
            band_gap_min, band_gap_max,
            stability_max,
            formation_energy_min, formation_energy_max,
            prototype, spacegroup, natom_max,
            only_stable
        """
        if not criteria:
            raise ValueError("query_by_criteria 至少需要一个过滤条件")

        params:         Dict[str, Any] = {}
        client_filters: Dict[str, Any] = {}

        if "elements" in criteria and criteria["elements"]:
            els = [e.capitalize() for e in criteria["elements"]]
            params["element_set"] = ",".join(els)

        if "composition" in criteria and criteria["composition"]:
            params["composition"] = criteria["composition"]

        if "num_elements" in criteria and criteria["num_elements"] is not None:
            params["ntypes"] = criteria["num_elements"]

        if "natom_max" in criteria and criteria["natom_max"] is not None:
            params["natom"] = f"<{criteria['natom_max'] + 1}"

        if "prototype" in criteria and criteria["prototype"]:
            params["prototype"] = criteria["prototype"]

        if "spacegroup" in criteria and criteria["spacegroup"]:
            params["spacegroup"] = criteria["spacegroup"]

        # stability
        stab_max = criteria.get("stability_max")
        if criteria.get("only_stable"):
            params["stability"] = "<0.001"
        elif stab_max is not None:
            params["stability"] = f"<{stab_max}"

        # band_gap：min 端服务端过滤，max 端客户端补充
        bg_min = criteria.get("band_gap_min")
        bg_max = criteria.get("band_gap_max")
        if bg_min is not None:
            params["band_gap"] = f">{bg_min}"
        if bg_max is not None:
            client_filters["band_gap_max"] = bg_max

        # formation_energy：min 端服务端，max 端客户端
        fe_min = criteria.get("formation_energy_min")
        fe_max = criteria.get("formation_energy_max")
        if fe_min is not None:
            params["delta_e"] = f">{fe_min}"
        if fe_max is not None:
            client_filters["formation_energy_max"] = fe_max

        key = "oqmd::crit::" + "::".join(
            f"{k}={v}" for k, v in sorted({**params, **client_filters}.items())
        )
        return self._cached_query(
            key, params,
            client_filters=client_filters if client_filters else None,
        )

    def query_by_entry_id(
        self,
        entry_ids: Union[int, Sequence[int]],
    ) -> List[Dict[str, Any]]:
        """按 OQMD entry_id 精确获取（含完整结构数据）。"""
        if isinstance(entry_ids, int):
            ids = [entry_ids]
        else:
            ids = list(entry_ids)

        results = []
        for eid in ids:
            key = f"oqmd::eid::{eid}"
            cached = self._cache.get(key)
            if cached is not None:
                results.extend(cached)
                continue
            raw = self._fetch_raw({"entry_id": eid}, full=True)
            # The OQMD API treats ?entry_id=X as >= X (not exact match),
            # returning multiple entries in descending entry_id order.
            # Filter client-side to guarantee we only keep the requested entry.
            exact_raw = [item for item in raw if item.get("entry_id") == eid]
            if exact_raw:
                items = self._post_process(exact_raw)
            else:
                got_ids = [item.get("entry_id") for item in raw[:5]]
                logger.warning(
                    "OQMD entry_id=%s not in API response (got: %s). "
                    "Run a search first so the entry can be found via cache.",
                    eid, got_ids,
                )
                items = []
            self._cache.set(key, items)
            results.extend(items)
        return results

    def get_structure(self, entry_id: int) -> Optional[Structure]:
        results = self.query_by_entry_id(entry_id)
        return results[0].get("_structure") if results else None

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("OQMD 缓存已清空")


# ──────────────────────────────────────────────
# 客户端补充过滤器
# ──────────────────────────────────────────────

def _apply_client_filters(
    result: Dict[str, Any],
    filters: Dict[str, Any],
) -> bool:
    """对 _build_result 结果施加客户端补充条件，返回是否通过。"""
    bg  = result.get("band_gap")
    fe  = result.get("formation_energy_per_atom")

    if "band_gap_max" in filters:
        if bg is None or bg > filters["band_gap_max"]:
            return False

    if "formation_energy_max" in filters:
        if fe is None or fe > filters["formation_energy_max"]:
            return False

    return True
