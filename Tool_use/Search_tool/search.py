"""
mp_query_service.py  (refactored + download support)
───────────────────────────────────────────────
Materials Project 结构查询服务

本次新增：
  save_structure_to_disk() —— 将结构保存为 CIF / POSCAR / XYZ 文件
  与 mp_tool_use.py 的 mp_download 工具对接
───────────────────────────────────────────────
"""

import re
import time
import logging
import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from mp_api.client import MPRester
from pymatgen.core import Structure
from pymatgen.io.cif import CifWriter
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

logger = logging.getLogger("MPQueryService")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────
# MP 请求字段（扩展版）
# ──────────────────────────────────────────────
_MP_FIELDS: List[str] = [
    "material_id", "formula_pretty", "structure", "symmetry",
    "nsites", "volume", "density",
    "band_gap", "is_metal",
    "formation_energy_per_atom", "energy_above_hull", "is_stable",
    "is_magnetic", "total_magnetization",
    "theoretical",
]

Range = Tuple[Optional[float], Optional[float]]

# ──────────────────────────────────────────────
# 重试装饰器
# ──────────────────────────────────────────────
def _retry(max_attempts: int = 3, backoff: float = 1.0):
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts:
                        raise
                    wait = backoff * (2 ** (attempt - 1))
                    logger.warning("[%s] 第%d次失败：%s，%.1fs后重试",
                                   func.__name__, attempt, exc, wait)
                    time.sleep(wait)
        return wrapper
    return decorator

# ──────────────────────────────────────────────
# TTL 缓存
# ──────────────────────────────────────────────
class _TTLCache:
    def __init__(self, ttl: int = 300, maxsize: int = 256):
        self._ttl, self._maxsize = ttl, maxsize
        self._store: Dict[str, Any] = {}
        self._ts:    Dict[str, float] = {}
        self._lock   = threading.RLock()

    def get(self, key):
        with self._lock:
            if key not in self._store: return None
            if time.time() - self._ts[key] > self._ttl:
                del self._store[key], self._ts[key]; return None
            return self._store[key]

    def set(self, key, value):
        with self._lock:
            if len(self._store) >= self._maxsize:
                oldest = min(self._ts, key=lambda k: self._ts[k])
                del self._store[oldest], self._ts[oldest]
            self._store[key] = value
            self._ts[key]    = time.time()

    def clear(self):
        with self._lock:
            self._store.clear(); self._ts.clear()

# ──────────────────────────────────────────────
# 结构转换工具
# ──────────────────────────────────────────────
def get_conventional(struct: Structure) -> Structure:
    """转换为标准惯用晶胞。"""
    try:
        return SpacegroupAnalyzer(
            struct, symprec=1e-3
        ).get_conventional_standard_structure()
    except Exception:
        logger.warning("SpacegroupAnalyzer 失败，使用原始结构")
        return struct

def structure_to_xyz(struct: Structure, comment: str = "") -> str:
    """Structure → XYZ 格式字符串（含笛卡尔坐标）。"""
    lines = [str(len(struct)), comment or struct.composition.reduced_formula]
    for site in struct.sites:
        x, y, z = site.coords
        lines.append(f"{site.specie.symbol} {x:.6f} {y:.6f} {z:.6f}")
    return "\n".join(lines)

def structure_to_cif(struct: Structure) -> str:
    """Structure → CIF 格式字符串。"""
    try:
        return str(CifWriter(struct))
    except Exception as e:
        logger.warning("CIF 转换失败：%s", e)
        return ""

def structure_to_poscar(struct: Structure, comment: str = "") -> str:
    """Structure → POSCAR 格式字符串（VASP 输入）。"""
    try:
        return Poscar(
            struct,
            comment=comment or struct.composition.reduced_formula
        ).get_str()
    except Exception as e:
        logger.warning("POSCAR 转换失败：%s", e)
        return ""

# 格式扩展名映射
_FMT_EXT: Dict[str, str] = {
    "cif":    ".cif",
    "poscar": "",          # POSCAR 无扩展名（VASP 惯例）
    "xyz":    ".xyz",
}

def save_structure_to_disk(
    struct:   Structure,
    save_dir: Union[str, Path] = "./structures",
    filename: str              = "structure",
    fmt:      str              = "cif",
) -> List[str]:
    """
    将 pymatgen Structure 保存为指定格式的文件。

    Parameters
    ----------
    struct   : pymatgen Structure 对象
    save_dir : 保存目录（不存在时自动创建）
    filename : 文件名（不含扩展名；POSCAR 直接作为文件名）
    fmt      : 输出格式，支持 "cif" | "poscar" | "xyz"

    Returns
    -------
    List[str] : 成功保存的文件绝对路径列表；失败时返回空列表

    Examples
    --------
    >>> saved = save_structure_to_disk(struct, "./out", "mp-19770_Fe2O3", "cif")
    >>> print(saved)
    ['D:/workflow/.../out/mp-19770_Fe2O3.cif']
    """
    fmt = fmt.lower().strip()
    if fmt not in _FMT_EXT:
        logger.error("不支持的格式：%s（支持：%s）", fmt, list(_FMT_EXT))
        return []

    # ── 准备目录 ──────────────────────────────
    save_path = Path(save_dir)
    try:
        save_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("无法创建目录 %s：%s", save_path, e)
        return []

    # ── 生成文件内容字符串 ─────────────────────
    comment = filename  # 用文件名作为结构注释

    if fmt == "cif":
        content = structure_to_cif(struct)
        # CifWriter 失败时返回空字符串
        if not content:
            logger.error("CIF 内容为空，跳过保存")
            return []

    elif fmt == "poscar":
        content = structure_to_poscar(struct, comment=comment)
        if not content:
            logger.error("POSCAR 内容为空，跳过保存")
            return []

    elif fmt == "xyz":
        content = structure_to_xyz(struct, comment=comment)
        if not content:
            logger.error("XYZ 内容为空，跳过保存")
            return []

    # ── 构造文件路径 ───────────────────────────
    ext      = _FMT_EXT[fmt]
    # POSCAR 惯例：文件名直接为 "POSCAR"（或带前缀）
    basename = f"{filename}{ext}" if fmt != "poscar" else f"POSCAR_{filename}"
    filepath = save_path / basename

    # ── 写入文件 ───────────────────────────────
    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info("✅ 已保存：%s", filepath.resolve())
        return [str(filepath.resolve())]
    except OSError as e:
        logger.error("写入失败 %s：%s", filepath, e)
        return []

# ──────────────────────────────────────────────
# 单条结果构建（扩展字段）
# ──────────────────────────────────────────────
def _safe_round(x, n=4):
    return round(x, n) if isinstance(x, (int, float)) else None

def _build_result(doc: Any, include_angles: bool = False) -> Optional[Dict[str, Any]]:
    """构建标准化结果 dict。include_angles 控制是否输出 alpha/beta/gamma。"""
    try:
        struct: Structure = doc.structure
        if struct is None:
            logger.warning("material_id=%s 无结构数据，跳过", doc.material_id)
            return None

        conv    = get_conventional(struct)
        lat     = conv.lattice
        mid     = str(doc.material_id)
        formula = doc.formula_pretty or conv.composition.reduced_formula
        comment = f"{formula} | {mid}"

        sym            = doc.symmetry
        space_group    = getattr(sym, "symbol",         "?") if sym else "?"
        crystal_system = getattr(sym, "crystal_system", "?") if sym else "?"

        result: Dict[str, Any] = {
            "material_id":    mid,
            "formula":        formula,
            "space_group":    space_group,
            "crystal_system": crystal_system,
            "a": _safe_round(lat.a, 4),
            "b": _safe_round(lat.b, 4),
            "c": _safe_round(lat.c, 4),
            "nsites":  getattr(doc, "nsites",  None),
            "volume":  _safe_round(getattr(doc, "volume",  None), 4),
            "density": _safe_round(getattr(doc, "density", None), 4),
            "band_gap": _safe_round(getattr(doc, "band_gap", None), 4),
            "is_metal": getattr(doc, "is_metal", None),
            "formation_energy_per_atom": _safe_round(
                getattr(doc, "formation_energy_per_atom", None), 4),
            "energy_above_hull": _safe_round(
                getattr(doc, "energy_above_hull", None), 4),
            "is_stable":           getattr(doc, "is_stable",           None),
            "is_magnetic":         getattr(doc, "is_magnetic",         None),
            "total_magnetization": _safe_round(
                getattr(doc, "total_magnetization", None), 4),
            "theoretical": getattr(doc, "theoretical", None),
            # 结构文件字符串（供 _download 直接使用，避免二次转换）
            "xyz":    structure_to_xyz(conv, comment),
            "cif":    structure_to_cif(conv),
            "poscar": structure_to_poscar(conv, comment),
            # 后端计算用
            "_structure": conv,
        }

        if include_angles:
            result.update({
                "alpha": _safe_round(lat.alpha, 2),
                "beta":  _safe_round(lat.beta,  2),
                "gamma": _safe_round(lat.gamma, 2),
            })
        return result

    except Exception as e:
        logger.warning("构建结果失败 %s：%s", getattr(doc, "material_id", "?"), e)
        return None

# ──────────────────────────────────────────────
# MPQueryService 主类（多策略查询）
# ──────────────────────────────────────────────
class MPQueryService:
    """
    Materials Project 结构查询服务（多模式 + 自定义过滤）。

    四种查询入口：
        svc.query_by_formula("Fe2O3")
        svc.query_by_material_id("mp-126")
        svc.query_by_elements(["Fe", "O"])
        svc.query_by_criteria(elements=["Fe","O"], band_gap=(1.0, 3.0))

    统一入口（向后兼容）：
        svc.query("Fe2O3")
        svc.query("mp-126")
        svc.query("Fe-O")
    """

    def __init__(
        self,
        api_key:        str,
        max_results:    int  = 20,
        cache_ttl:      int  = 300,
        include_angles: bool = False,
    ):
        self.api_key        = api_key
        self.max_results    = max_results
        self.include_angles = include_angles
        self._cache         = _TTLCache(ttl=cache_ttl)

    @_retry(max_attempts=3, backoff=1.0)
    def _fetch(self, **kwargs) -> List[Any]:
        clean = {k: v for k, v in kwargs.items() if v is not None}
        logger.info("[MP API] search(%s)", clean)
        with MPRester(self.api_key) as mpr:
            return list(mpr.materials.summary.search(fields=_MP_FIELDS, **clean))

    def _post_process(self, docs: List[Any]) -> List[Dict[str, Any]]:
        out = []
        for doc in docs[:self.max_results]:
            item = _build_result(doc, include_angles=self.include_angles)
            if item:
                out.append(item)
        return out

    def _cached_query(self, cache_key: str, **kwargs) -> List[Dict[str, Any]]:
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.info("[cache] %s", cache_key)
            return cached
        docs    = self._fetch(**kwargs)
        results = self._post_process(docs)
        self._cache.set(cache_key, results)
        return results

    def query_by_formula(
        self,
        formula:     Union[str, List[str]],
        only_stable: bool = False,
    ) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {"formula": formula}
        if only_stable:
            kwargs["energy_above_hull"] = (0, 0)
        return self._cached_query(f"formula::{formula}::{only_stable}", **kwargs)

    def query_by_material_id(
        self,
        material_ids: Union[str, Sequence[str]],
    ) -> List[Dict[str, Any]]:
        ids = [material_ids] if isinstance(material_ids, str) else list(material_ids)
        ids = [m.lower() for m in ids]
        return self._cached_query(f"mid::{','.join(ids)}", material_ids=ids)

    def query_by_elements(
        self,
        elements:     Sequence[str],
        num_elements: Optional[Union[int, Range]] = None,
        only_stable:  bool = False,
    ) -> List[Dict[str, Any]]:
        els    = [e.capitalize() for e in elements]
        kwargs: Dict[str, Any] = {"elements": els}
        if num_elements is not None:
            kwargs["num_elements"] = num_elements
        if only_stable:
            kwargs["energy_above_hull"] = (0, 0)
        key = f"els::{'-'.join(els)}::{num_elements}::{only_stable}"
        return self._cached_query(key, **kwargs)

    def query_by_criteria(self, **criteria) -> List[Dict[str, Any]]:
        if not criteria:
            raise ValueError("query_by_criteria 至少需要一个过滤条件")
        key = "crit::" + "::".join(f"{k}={v}" for k, v in sorted(criteria.items()))
        return self._cached_query(key, **criteria)

    def query(
        self,
        raw_input:   Optional[str] = None,
        *,
        only_stable: bool = False,
        **criteria,
    ) -> List[Dict[str, Any]]:
        if raw_input is None and not criteria:
            raise ValueError("必须提供 raw_input 或至少一个 criteria 关键字")

        if raw_input:
            q = raw_input.strip()
            if re.match(r'^mp-\d+$', q, re.IGNORECASE):
                if criteria:
                    logger.warning("material_id 查询忽略额外 criteria：%s", criteria)
                return self.query_by_material_id(q)
            if "-" in q and all(
                re.match(r'^[A-Z][a-z]?$', p.strip().capitalize())
                for p in q.split("-")
            ):
                criteria.setdefault(
                    "chemsys",
                    "-".join(p.strip().capitalize() for p in q.split("-"))
                )
            else:
                criteria.setdefault("formula", q)

        if only_stable:
            criteria.setdefault("energy_above_hull", (0, 0))

        return self.query_by_criteria(**criteria)

    def get_structure(self, material_id: str) -> Optional[Structure]:
        results = self.query_by_material_id(material_id)
        return results[0].get("_structure") if results else None

    def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("缓存已清空")