# -*- coding: utf-8 -*-
"""
manifest.py — Manifest lifecycle: structure scanning, task expansion, persistence.
manifest 生命周期管理：结构扫描、任务展开、持久化。

This module owns the full read-modify-write cycle of manifest.json and all
task-graph expansion logic (bulk → slab → adsorption downstream).
本模块负责 manifest.json 的完整读-改-写周期，以及所有任务图展开逻辑
（块材 → 板坯 → 吸附下游）。

Public API
----------
  expand_manifest(cfg)     – Acquire global lock, expand, persist, return manifest dict.
  _manifest_path(cfg)      – Return the path to manifest.json (used by hook CLI to print it).
  _deps_satisfied(m, task) – Return True iff all deps of task are done on disk.
  _is_stale_submission(wd) – Return True iff submitted.json exists but PBS job is gone.
  _submission_age_seconds(wd) – Seconds since submitted.json was written.
  _STALE_GRACE_PERIOD_SECONDS, MAX_RETRIES – tuneable constants.
"""
from __future__ import annotations

import logging
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

from flow.workflow._io import _dump_json, _ensure_dir, _load_json, _now_ts
from flow.workflow.markers import is_done, submitted_marker
from flow.workflow.path_ids import (
    _ads_freq_tid, _ads_lobster_tid, _ads_nbo_tid, _ads_tid,
    _ads_workdir,
    _best_structure_path,
    _bulk_dos_tid, _bulk_lobster_tid, _bulk_nbo_tid, _bulk_relax_tid,
    _bulk_workdir,
    _extract_bulk_id,
    _hkl_str,
    _resolve_bulk_source_for_slab,
    _run_root,
    _sanitize_id,
    _slab_dos_tid, _slab_lobster_tid, _slab_nbo_tid, _slab_relax_tid,
    _slab_workdir,
)
from flow.workflow.pbs import DirLock
from flow.workflow.stages import Stage, enabled_stages, STAGE_ORDER

logger = logging.getLogger(__name__)


def _die(msg: str, code: int = 2) -> None:
    print(f"[hook] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STALE_GRACE_PERIOD_SECONDS = 300
MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Bulk-source scanning
# 块材源扫描
# ---------------------------------------------------------------------------

def _get_bulk_sources(cfg: "WorkflowConfig") -> List[Dict[str, str]]:
    """Scan the configured structure path and return one entry per bulk file.

    Accepts either a single file or a directory.  For directories, all files
    matching the patterns ``POSCAR_*``, ``CONTCAR_*``, ``POSCAR.*``, or
    ``CONTCAR.*`` are collected.  Duplicate bulk IDs are de-duplicated by
    appending a numeric suffix.

    扫描配置的结构路径，每个块材文件返回一个条目。
    """
    struct = cfg.structure
    if not struct:
        return []

    p = Path(struct).expanduser().resolve()
    if not p.exists():
        _die(f"structure path does not exist: {p}")

    files: List[Path] = []
    if p.is_file():
        files = [p]
    else:
        cands: List[Path] = []
        for pat in ("POSCAR_*", "CONTCAR_*", "POSCAR.*", "CONTCAR.*"):
            cands += sorted(p.glob(pat))
        files = [x for x in cands if x.is_file() and x.stat().st_size > 0]
        if not files:
            _die(
                f"No structure files found under {p}. "
                "Expected files like POSCAR_PtSnCu or POSCAR.Fe3O4."
            )

    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    for f in files:
        bid = _sanitize_id(_extract_bulk_id(f.name))
        if bid in seen:
            k = 2
            while f"{bid}_{k}" in seen:
                k += 1
            bid = f"{bid}_{k}"
        seen.add(bid)
        out.append({"id": bid, "path": str(f)})
    return out


# ---------------------------------------------------------------------------
# Direct-source scanners (slab-only and adsorption-only entry points)
# 直接源扫描器（仅板坯和仅吸附入口点）
# ---------------------------------------------------------------------------

def _scan_structure_files(path_str: str, label: str) -> List[Path]:
    """Scan a path (file or directory) for POSCAR/CONTCAR files.

    A lower-level helper used by both ``_get_direct_slab_sources`` and
    ``_get_direct_adsorption_sources``.

    扫描路径（文件或目录）以查找 POSCAR/CONTCAR 文件。
    """
    p = Path(path_str).expanduser().resolve()
    if not p.exists():
        _die(f"{label} path does not exist: {p}")
    if p.is_file():
        return [p]
    cands: List[Path] = []
    for pat in ("POSCAR_*", "CONTCAR_*", "POSCAR.*", "CONTCAR.*"):
        cands += sorted(p.glob(pat))
    files = [x for x in cands if x.is_file() and x.stat().st_size > 0]
    if not files:
        _die(f"No structure files found under {label}: {p}")
    return files


def _get_direct_slab_sources(cfg: "WorkflowConfig") -> List[Dict[str, Any]]:
    """Return [{id, path, term}] from cfg.slab_source, one entry per file.

    Groups files by sanitised bulk ID so that multiple files with the same
    base ID receive distinct termination indices (``term`` starting at 0).

    从 cfg.slab_source 返回 [{id, path, term}]，每个文件一个条目。
    """
    files = _scan_structure_files(cfg.slab_source, "slab_source")
    groups: Dict[str, List[Path]] = defaultdict(list)
    for f in files:
        bid = _sanitize_id(_extract_bulk_id(f.name))
        groups[bid].append(f)
    out: List[Dict[str, Any]] = []
    for bid, flist in sorted(groups.items()):
        for term, fpath in enumerate(flist):
            out.append({"id": bid, "path": str(fpath), "term": term})
    return out


def _get_direct_adsorption_sources(cfg: "WorkflowConfig") -> List[Dict[str, Any]]:
    """Return [{id, path, index}] from cfg.adsorption_source, one entry per file.

    Groups files by sanitised bulk ID so that multiple files with the same
    base ID receive distinct site indices (``index`` starting at 0).

    从 cfg.adsorption_source 返回 [{id, path, index}]，每个文件一个条目。
    """
    files = _scan_structure_files(cfg.adsorption_source, "adsorption_source")
    groups: Dict[str, List[Path]] = defaultdict(list)
    for f in files:
        bid = _sanitize_id(_extract_bulk_id(f.name))
        groups[bid].append(f)
    out: List[Dict[str, Any]] = []
    for bid, flist in sorted(groups.items()):
        for idx, fpath in enumerate(flist):
            out.append({"id": bid, "path": str(fpath), "index": idx})
    return out


# ---------------------------------------------------------------------------
# Manifest management
# Manifest 管理
# ---------------------------------------------------------------------------

def _manifest_path(cfg: "WorkflowConfig") -> Path:
    """Return the canonical path to manifest.json for the given config.

    返回给定配置的 manifest.json 的规范路径。
    """
    return _run_root(cfg) / "manifest.json"


def _ensure_manifest(cfg: "WorkflowConfig") -> Dict[str, Any]:
    """Load manifest.json if it exists, otherwise initialise a fresh skeleton.

    The returned dict always has a ``"tasks"`` key.

    若 manifest.json 存在则加载，否则初始化一个新的骨架结构。
    """
    mp = _manifest_path(cfg)
    m = _load_json(mp) if mp.exists() else {}
    if not m:
        m = {
            "schema_version": 1,
            "created_at": _now_ts(),
            "params_file": cfg.params_file,
            "tasks": {},
        }
    m.setdefault("tasks", {})
    return m


def _save_manifest(cfg: "WorkflowConfig", m: Dict[str, Any]) -> None:
    """Persist the manifest dict to disk as JSON.

    将 manifest 字典以 JSON 格式持久化到磁盘。
    """
    _dump_json(_manifest_path(cfg), m)


# ---------------------------------------------------------------------------
# Dependency and staleness checking
# 依赖项与陈旧提交检查
# ---------------------------------------------------------------------------

def _deps_satisfied(m: Dict[str, Any], task: Dict[str, Any]) -> bool:
    """Return True if every dependency of *task* is marked done on disk.

    若 *task* 的每个依赖项在磁盘上均被标记为完成则返回 True。
    """
    for dep_id in task.get("deps", []):
        dep = m["tasks"].get(dep_id)
        if not dep or not is_done(Path(dep["workdir"])):
            return False
    return True


def _submission_age_seconds(workdir: Path) -> float:
    """Return seconds elapsed since submitted.json was written, or inf if unparseable.

    submitted.json 写入后经过的秒数；若无法解析则返回 inf。
    """
    meta = _load_json(submitted_marker(workdir))
    ts_str = meta.get("time", "")
    if not ts_str:
        return float("inf")
    try:
        ts = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
        return time.time() - ts
    except Exception:
        return float("inf")


def _is_stale_submission(workdir: Path) -> bool:
    """Return True if submitted.json exists but its PBS job is no longer queued.

    Uses ``qstat <job_id>`` directly: a non-zero exit code reliably means the
    job is unknown to the scheduler (finished, deleted, or expired).
    Returns False conservatively when qstat is unavailable or the job_id
    field is missing (assume still running).

    若 submitted.json 存在但其 PBS 作业已不在队列中则返回 True。
    """
    sj = submitted_marker(workdir)
    if not sj.exists():
        return False
    meta = _load_json(sj)
    job_id = meta.get("job_id", "")
    if not job_id:
        return False
    try:
        import subprocess
        result = subprocess.run(
            ["qstat", job_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return result.returncode != 0
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        logger.warning("qstat timed out for job %s; treating as still running.", job_id)
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Manifest expansion
# Manifest 展开
# ---------------------------------------------------------------------------

def expand_manifest(cfg: "WorkflowConfig") -> Dict[str, Any]:
    """Acquire a global manifest lock then delegate to ``_expand_manifest_inner``.

    The lock prevents concurrent hook processes from performing a
    read-modify-write race on manifest.json (lost-update problem).

    获取全局 manifest 锁后委托给 ``_expand_manifest_inner``。
    锁防止并发 hook 进程在 manifest.json 上产生读-改-写竞态（丢更新问题）。
    """
    _ensure_dir(_run_root(cfg))
    lock = DirLock(_run_root(cfg) / ".manifest.lock")
    if not lock.acquire():
        _die(
            "manifest.json is locked by another hook process. "
            "If stale, remove the .manifest.lock directory manually."
        )
    try:
        return _expand_manifest_inner(cfg)
    finally:
        lock.release()


def _expand_bulk_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
    bulks: List[Dict[str, Any]],
) -> None:
    """Register bulk_relax, bulk_dos, bulk_lobster, bulk_nbo tasks (section 1).

    为每个已启用的块材阶段为每个块材文件注册一个任务（第 1 节）。
    """
    tasks = m["tasks"]
    for b in bulks:
        bid, bfile = b["id"], b["path"]

        if Stage.BULK_RELAX in stages_on:
            tid = _bulk_relax_tid(bid)
            if tid not in tasks:
                w = _bulk_workdir(cfg, Stage.BULK_RELAX, bid)
                tasks[tid] = {
                    "id": tid, "stage": Stage.BULK_RELAX, "workdir": str(w),
                    "deps": [],
                    "meta": {"bulk_id": bid, "structure": bfile},
                }

        relax_tid = _bulk_relax_tid(bid)
        relax_dir = str(_bulk_workdir(cfg, Stage.BULK_RELAX, bid))
        for stage, tid_fn in [
            (Stage.BULK_DOS,     _bulk_dos_tid),
            (Stage.BULK_LOBSTER, _bulk_lobster_tid),
            (Stage.BULK_NBO,     _bulk_nbo_tid),
        ]:
            if stage not in stages_on:
                continue
            tid = tid_fn(bid)
            if tid not in tasks:
                w = _bulk_workdir(cfg, stage, bid)
                tasks[tid] = {
                    "id": tid, "stage": stage, "workdir": str(w),
                    "deps": [relax_tid],
                    "meta": {"bulk_id": bid, "prev": relax_dir},
                }


def _expand_generated_slab_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
    bulks: List[Dict[str, Any]],
) -> None:
    """Generate slab_relax tasks from bulk via BulkToSlabGenerator (section 2a).

    通过 BulkToSlabGenerator 从块材生成 slab_relax 任务（第 2a 节）。
    """
    if Stage.SLAB_RELAX not in stages_on:
        return
    if not cfg.slab or not cfg.slab.miller_list:
        return

    tasks = m["tasks"]
    slabgen_cfg = cfg.slab.slabgen
    layers = slabgen_cfg.target_layers
    miller_list = cfg.slab.miller_list

    from pymatgen.io.vasp import Poscar
    from flow.workflow.structure import BulkToSlabGenerator

    for b in bulks:
        bid, bfile = b["id"], b["path"]
        br_task = tasks.get(_bulk_relax_tid(bid))
        if not br_task or not is_done(Path(br_task["workdir"])):
            continue

        bulk_source = _resolve_bulk_source_for_slab(cfg, bid, bfile)

        for miller in miller_list:
            hkl = [int(x) for x in miller]
            prefix = f"slab_relax:{bid}:{_hkl_str(hkl)}:{layers}L:"
            if any(t.startswith(prefix) for t in tasks):
                continue

            save_dir = _run_root(cfg) / "_generated_slabs" / bid / _hkl_str(hkl) / f"{layers}L"
            _ensure_dir(save_dir)

            gen_lock = DirLock(save_dir / ".slabgen.lock")
            if not gen_lock.acquire():
                continue
            try:
                if any(t.startswith(prefix) for t in tasks):
                    continue

                gen_params: Dict[str, Any] = {
                    "miller_indices": hkl,
                    "target_layers": layers,
                    "vacuum_thickness": float(slabgen_cfg.vacuum_thickness),
                    "supercell_matrix": slabgen_cfg.supercell_matrix,
                    "fix_bottom_layers": int(slabgen_cfg.fix_bottom_layers),
                    "fix_top_layers": int(slabgen_cfg.fix_top_layers),
                    "all_fix": bool(slabgen_cfg.all_fix),
                    "symmetric": bool(slabgen_cfg.symmetric),
                    "center": bool(slabgen_cfg.center),
                    "primitive": bool(slabgen_cfg.primitive),
                    "lll_reduce": bool(slabgen_cfg.lll_reduce),
                    "hcluster_cutoff": float(slabgen_cfg.hcluster_cutoff),
                }
                slabs = BulkToSlabGenerator.run_from_dict({
                    "structure_source": bulk_source,
                    "save_dir": str(save_dir),
                    "standardize_bulk": bool(slabgen_cfg.standardize_bulk),
                    "generate_params": gen_params,
                    "save_options": {"save": True, "filename_prefix": "POSCAR"},
                })
                if not slabs:
                    continue

                for term, slab in enumerate(slabs):
                    tid = _slab_relax_tid(bid, hkl, layers, term)
                    if tid in tasks:
                        continue
                    w = _slab_workdir(cfg, Stage.SLAB_RELAX, bid, hkl, layers, term)
                    _ensure_dir(w)
                    Poscar(slab).write_file(str(w / "POSCAR"))
                    tasks[tid] = {
                        "id": tid, "stage": Stage.SLAB_RELAX, "workdir": str(w),
                        "deps": [_bulk_relax_tid(bid)],
                        "meta": {"bulk_id": bid, "hkl": hkl,
                                 "layers": layers, "term": term},
                    }
            except Exception:
                logger.exception("Slab generation failed for bid=%s hkl=%s", bid, hkl)
            finally:
                gen_lock.release()


def _expand_direct_slab_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
) -> None:
    """Register slab_relax tasks from pre-existing POSCARs (section 2b).

    从预存 POSCAR 注册 slab_relax 任务（第 2b 节）。
    """
    if not cfg.slab_source or Stage.SLAB_RELAX not in stages_on:
        return
    tasks = m["tasks"]
    for entry in _get_direct_slab_sources(cfg):
        bid  = entry["id"]
        term = entry["term"]
        hkl    = [0, 0, 0]
        layers = 0
        tid = _slab_relax_tid(bid, hkl, layers, term)
        if tid in tasks:
            continue
        w = _slab_workdir(cfg, Stage.SLAB_RELAX, bid, hkl, layers, term)
        _ensure_dir(w)
        shutil.copy2(entry["path"], str(w / "POSCAR"))
        tasks[tid] = {
            "id": tid, "stage": Stage.SLAB_RELAX, "workdir": str(w),
            "deps": [],
            "meta": {"bulk_id": bid, "hkl": hkl, "layers": layers, "term": term},
        }


def _expand_slab_downstream_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
) -> None:
    """Register slab_dos, slab_lobster, slab_nbo tasks gated on slab_relax done (section 3).

    注册以 slab_relax 完成为门控的 slab_dos、slab_lobster、slab_nbo 任务（第 3 节）。
    """
    need = (
        Stage.SLAB_DOS in stages_on
        or Stage.SLAB_LOBSTER in stages_on
        or Stage.SLAB_NBO in stages_on
    )
    if not need:
        return
    tasks = m["tasks"]
    for tid, t in list(tasks.items()):
        if t.get("stage") != Stage.SLAB_RELAX:
            continue
        slab_dir = Path(t["workdir"])
        if not is_done(slab_dir):
            continue

        bid    = t["meta"]["bulk_id"]
        hkl    = t["meta"]["hkl"]
        layers = int(t["meta"]["layers"])
        term   = int(t["meta"]["term"])

        shared_meta = {"bulk_id": bid, "prev": str(slab_dir),
                       "hkl": hkl, "layers": layers, "term": term}
        for stage, dtid_fn in [
            (Stage.SLAB_DOS,     _slab_dos_tid),
            (Stage.SLAB_LOBSTER, _slab_lobster_tid),
            (Stage.SLAB_NBO,     _slab_nbo_tid),
        ]:
            if stage not in stages_on:
                continue
            dtid = dtid_fn(bid, hkl, layers, term)
            if dtid not in tasks:
                w = _slab_workdir(cfg, stage, bid, hkl, layers, term)
                _ensure_dir(w)
                tasks[dtid] = {
                    "id": dtid, "stage": stage, "workdir": str(w),
                    "deps": [tid],
                    "meta": shared_meta,
                }


def _expand_generated_adsorption_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
) -> None:
    """Auto-generate adsorption tasks from completed slab_relax tasks (section 3, adsorption branch).

    从已完成的 slab_relax 任务自动生成吸附任务（第 3 节，吸附分支）。
    """
    if Stage.ADSORPTION not in stages_on:
        return
    if not cfg.adsorption:
        _die("adsorption is enabled but adsorption config is missing.")
    if cfg.adsorption.build.mode != "site":
        logger.warning(
            "adsorption.build.mode=%r is not 'site'; adsorption tasks will not be "
            "auto-generated. Use adsorption_source for direct import.",
            cfg.adsorption.build.mode,
        )
        return

    tasks = m["tasks"]
    build = cfg.adsorption.build
    mol = build.molecule_formula
    if not mol:
        _die("adsorption.build.molecule_formula is required.")

    enum = build.enumerate
    site_types = enum.get("site_types", [build.site_type.lower()])
    max_per_type = int(enum.get("max_per_type", 10))
    start_index = int(enum.get("start_index", 0))

    from pymatgen.core import Molecule
    from pymatgen.io.vasp import Poscar
    from flow.workflow.structure import AdsorptionModify

    for tid, t in list(tasks.items()):
        if t.get("stage") != Stage.SLAB_RELAX:
            continue
        slab_dir = Path(t["workdir"])
        if not is_done(slab_dir):
            continue

        bid    = t["meta"]["bulk_id"]
        hkl    = t["meta"]["hkl"]
        layers = int(t["meta"]["layers"])
        term   = int(t["meta"]["term"])

        ads_prefix = f"adsorption:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}:"
        if any(x.startswith(ads_prefix) for x in tasks):
            continue

        ads_save_dir = (
            _run_root(cfg) / "_generated_ads" / bid / _hkl_str(hkl)
            / f"{layers}L" / f"term{term}"
        )
        _ensure_dir(ads_save_dir)

        ads_lock = DirLock(ads_save_dir / ".adsgen.lock")
        if not ads_lock.acquire():
            continue
        try:
            if any(x.startswith(ads_prefix) for x in tasks):
                continue

            modifier = AdsorptionModify(
                slab_source=str(slab_dir),
                selective_dynamics=bool(build.selective_dynamics),
                height=float(build.height),
                save_dir=str(ads_save_dir),
                log_to_file=True,
            )
            find_args = dict(build.find_args or {})
            sites = modifier.find_adsorption_sites(**find_args)

            try:
                molecule = AdsorptionModify.ase2pmg(str(mol))
            except Exception:
                mp = Path(str(mol))
                if mp.exists():
                    molecule = Molecule.from_file(str(mp))
                else:
                    _die(f"Cannot resolve molecule_formula='{mol}'.")

            for stype in site_types:
                stype = str(stype).lower()
                coords_list = sites.get(stype, [])
                if not coords_list:
                    continue
                end = min(len(coords_list), start_index + max_per_type)
                for idx in range(start_index, end):
                    aid = _ads_tid(bid, hkl, layers, term, stype, idx)
                    if aid in tasks:
                        continue
                    w = _ads_workdir(cfg, Stage.ADSORPTION, bid, hkl, layers, term, stype, idx)
                    _ensure_dir(w)
                    reorient = bool(build.reorient)
                    struct = modifier.add_adsorbate(molecule, coords_list[idx], reorient=reorient)
                    Poscar(struct).write_file(str(w / "POSCAR"))
                    tasks[aid] = {
                        "id": aid, "stage": Stage.ADSORPTION, "workdir": str(w),
                        "deps": [tid],
                        "meta": {
                            "bulk_id": bid, "prev": str(slab_dir),
                            "hkl": hkl, "layers": layers, "term": term,
                            "site_type": stype, "site_index": idx,
                        },
                    }
        except Exception:
            logger.exception(
                "Adsorption generation failed bid=%s hkl=%s term=%d", bid, hkl, term
            )
        finally:
            ads_lock.release()


def _expand_direct_adsorption_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
) -> None:
    """Register adsorption tasks from pre-existing POSCARs (section 3b).

    从预存 POSCAR 注册吸附任务（第 3b 节）。
    """
    if not cfg.adsorption_source or Stage.ADSORPTION not in stages_on:
        return
    tasks = m["tasks"]
    for entry in _get_direct_adsorption_sources(cfg):
        bid = entry["id"]
        idx = entry["index"]
        hkl    = [0, 0, 0]
        layers = 0
        term   = 0
        stype = "direct"
        aid = _ads_tid(bid, hkl, layers, term, stype, idx)
        if aid in tasks:
            continue
        w = _ads_workdir(cfg, Stage.ADSORPTION, bid, hkl, layers, term, stype, idx)
        _ensure_dir(w)
        shutil.copy2(entry["path"], str(w / "POSCAR"))
        tasks[aid] = {
            "id": aid, "stage": Stage.ADSORPTION, "workdir": str(w),
            "deps": [],
            "meta": {
                "bulk_id": bid, "hkl": hkl, "layers": layers, "term": term,
                "site_type": stype, "site_index": idx,
            },
        }


def _expand_adsorption_downstream_tasks(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    stages_on: set,
) -> None:
    """Register adsorption_freq, adsorption_lobster, adsorption_nbo tasks (sections 4–6).

    注册 adsorption_freq、adsorption_lobster、adsorption_nbo 任务（第 4–6 节）。
    """
    need = (
        Stage.ADSORPTION_FREQ in stages_on
        or Stage.ADSORPTION_LOBSTER in stages_on
        or Stage.ADSORPTION_NBO in stages_on
    )
    if not need:
        return
    tasks = m["tasks"]
    for tid, t in list(tasks.items()):
        if t.get("stage") != Stage.ADSORPTION:
            continue
        ads_dir = Path(t["workdir"])
        if not is_done(ads_dir):
            continue

        bid    = t["meta"]["bulk_id"]
        hkl    = t["meta"]["hkl"]
        layers = int(t["meta"]["layers"])
        term   = int(t["meta"]["term"])
        stype  = t["meta"]["site_type"]
        sidx   = int(t["meta"]["site_index"])

        if Stage.ADSORPTION_FREQ in stages_on:
            fid = _ads_freq_tid(bid, hkl, layers, term, stype, sidx)
            if fid not in tasks:
                mol = cfg.adsorption.build.molecule_formula if cfg.adsorption else None
                w = _ads_workdir(cfg, Stage.ADSORPTION_FREQ, bid, hkl, layers, term, stype, sidx)
                _ensure_dir(w)
                tasks[fid] = {
                    "id": fid, "stage": Stage.ADSORPTION_FREQ, "workdir": str(w),
                    "deps": [t["id"]],
                    "meta": {
                        "bulk_id": bid, "prev": str(ads_dir),
                        "hkl": hkl, "layers": layers, "term": term,
                        "site_type": stype, "site_index": sidx,
                        "adsorbate_formula": mol,
                    },
                }

        shared_ads_meta = {
            "bulk_id": bid, "prev": str(ads_dir),
            "hkl": hkl, "layers": layers, "term": term,
            "site_type": stype, "site_index": sidx,
        }
        for stage, atid_fn in [
            (Stage.ADSORPTION_LOBSTER, _ads_lobster_tid),
            (Stage.ADSORPTION_NBO,     _ads_nbo_tid),
        ]:
            if stage not in stages_on:
                continue
            atid = atid_fn(bid, hkl, layers, term, stype, sidx)
            if atid not in tasks:
                w = _ads_workdir(cfg, stage, bid, hkl, layers, term, stype, sidx)
                _ensure_dir(w)
                tasks[atid] = {
                    "id": atid, "stage": stage, "workdir": str(w),
                    "deps": [t["id"]],
                    "meta": shared_ads_meta,
                }


def _validate_stage_dependencies(cfg: "WorkflowConfig", stages_on: set) -> None:
    """Abort with a clear error if a required upstream stage is not enabled.

    Checks every enabled downstream stage against its known prerequisites.
    Exemptions apply when the direct-import bypasses (slab_source /
    adsorption_source) are configured.

    若启用的下游阶段缺少必要的上游阶段则中止并给出明确错误信息。
    """
    from flow.workflow.config import _REQUIRED_STAGE_DEPS
    for stage, deps in _REQUIRED_STAGE_DEPS.items():
        if stage not in stages_on:
            continue
        for dep in deps:
            if dep not in stages_on:
                if dep == "bulk_relax" and cfg.slab_source:
                    continue
                if dep == "slab_relax" and cfg.adsorption_source:
                    continue
                _die(
                    f"Stage '{stage}' requires '{dep}' to be enabled in workflow.stages. "
                    f"Add '{dep}' to your params.yaml, or set the appropriate source bypass."
                )


def _expand_manifest_inner(cfg: "WorkflowConfig") -> Dict[str, Any]:
    """Create or refresh manifest.json with all tasks derivable from current state.

    This is the central fan-out function.  It walks the enabled stages in
    dependency order and adds new task entries whenever their prerequisite
    conditions are met.

    创建或刷新 manifest.json，包含当前状态可推导出的所有任务。
    这是核心扇出函数，按依赖顺序遍历已启用阶段，在满足先决条件时添加新任务条目。
    """
    _ensure_dir(_run_root(cfg))
    stages_on = set(enabled_stages(cfg))
    if not stages_on:
        _die("No stages enabled in workflow.stages.")
    _validate_stage_dependencies(cfg, stages_on)
    bulks = _get_bulk_sources(cfg)
    m = _ensure_manifest(cfg)

    _expand_bulk_tasks(cfg, m, stages_on, bulks)
    _expand_generated_slab_tasks(cfg, m, stages_on, bulks)
    _expand_direct_slab_tasks(cfg, m, stages_on)
    _expand_slab_downstream_tasks(cfg, m, stages_on)
    _expand_generated_adsorption_tasks(cfg, m, stages_on)
    _expand_direct_adsorption_tasks(cfg, m, stages_on)
    _expand_adsorption_downstream_tasks(cfg, m, stages_on)

    _save_manifest(cfg, m)
    return m
