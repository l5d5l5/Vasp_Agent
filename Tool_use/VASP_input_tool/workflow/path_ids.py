# -*- coding: utf-8 -*-
"""
path_ids.py — Path construction and task-ID generation helpers.
路径构造与任务 ID 生成辅助函数。

Pure-computation functions: given configuration / parameters → return Path or str.
No filesystem side-effects except where noted (_resolve_bulk_source_for_slab reads
marker files via is_done).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

from flow.workflow.markers import is_done, submitted_marker
from flow.workflow.stages import STAGE_ORDER, Stage

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> Dict[str, Any]:
    """Load and return a JSON file as a dict.

    Returns an empty dict if the file does not exist.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON object, or ``{}`` when the file is absent.

    将 JSON 文件加载并以字典形式返回。
    若文件不存在则返回空字典。

    Args:
        path: JSON 文件路径。

    Returns:
        解析后的 JSON 对象；文件不存在时返回 ``{}``。
    """
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _detect_stage(workdir: Path) -> str:
    """Infer stage name from submitted.json or directory structure.

    First attempts to read the ``stage`` field from ``submitted.json``
    inside *workdir*.  If that is absent or unreadable, falls back to
    testing whether any known stage name appears as a path component.

    Args:
        workdir: Calculation working directory.

    Returns:
        Stage name string (e.g. ``"bulk_relax"``), or ``""`` if unknown.

    从 submitted.json 或目录结构推断阶段名称。
    首先尝试从 *workdir* 内的 ``submitted.json`` 读取 ``stage`` 字段；
    若不存在或无法读取，则退回到检查路径组件中是否包含已知阶段名。

    Args:
        workdir: 计算工作目录。

    Returns:
        阶段名称字符串（如 ``"bulk_relax"``），未知时返回 ``""``。
    """
    sj = submitted_marker(workdir)
    if sj.exists():
        try:
            meta = _load_json(sj)
            st = str(meta.get("stage", "")).strip()
            if st:
                return st
        except Exception:
            logger.exception("Failed to read submitted.json in %s", workdir)
    # Fallback: scan path components against the ordered stage list.
    # 回退方案：将路径组件与有序阶段列表逐一比对。
    for s in STAGE_ORDER:
        if s in workdir.parts:
            return s
    return ""


# ---------------------------------------------------------------------------
# Path helpers
# 路径辅助函数
# ---------------------------------------------------------------------------

def _run_root(cfg: "WorkflowConfig") -> Path:
    """Return the run root directory from the config.

    返回配置中的运行根目录。
    """
    return cfg.project.run_root


def _project_root(cfg: "WorkflowConfig") -> Path:
    """Return the project root directory from the config.

    返回配置中的项目根目录。
    """
    return cfg.project.project_root


def _hkl_str(hkl: List[int]) -> str:
    """Format a Miller-index triplet as a directory-safe string.

    Args:
        hkl: Three-element list of Miller indices.

    Returns:
        String of the form ``"hkl_HKL"`` (e.g. ``"hkl_110"``).

    将 Miller 指数三元组格式化为目录安全字符串。

    Args:
        hkl: 包含三个 Miller 指数的列表。

    Returns:
        形如 ``"hkl_HKL"`` 的字符串（如 ``"hkl_110"``）。
    """
    return f"hkl_{hkl[0]}{hkl[1]}{hkl[2]}"


def _sanitize_id(s: str) -> str:
    """Normalise an arbitrary string into a safe identifier for task IDs and directory names.

    Replaces whitespace with underscores, strips non-alphanumeric characters
    (except ``_``, ``.``, ``-``), and falls back to ``"bulk"`` for empty input.

    Args:
        s: Raw identifier string.

    Returns:
        Sanitised identifier string.

    将任意字符串规范化为任务 ID 和目录名的安全标识符。
    以下划线替换空白，去除非字母数字字符（除 ``_``、``.``、``-`` 外），
    空字符串时回退为 ``"bulk"``。

    Args:
        s: 原始标识符字符串。

    Returns:
        已净化的标识符字符串。
    """
    s = re.sub(r"\s+", "_", (s or "").strip())
    s = re.sub(r"[^A-Za-z0-9_.\-]+", "_", s)
    return s.strip("_") or "bulk"


def _extract_bulk_id(name: str) -> str:
    """Strip a recognised POSCAR/CONTCAR prefix to obtain the bulk material ID.

    Handles the naming patterns ``POSCAR_ID``, ``CONTCAR_ID``,
    ``POSCAR.ID``, and ``CONTCAR.ID``.  Falls back to the file stem.

    Args:
        name: Filename (not a full path).

    Returns:
        Extracted bulk material identifier string.

    去除已知的 POSCAR/CONTCAR 前缀以获取块材 ID。
    支持命名模式 ``POSCAR_ID``、``CONTCAR_ID``、``POSCAR.ID``、``CONTCAR.ID``，
    无匹配时退回文件名主干。

    Args:
        name: 文件名（非完整路径）。

    Returns:
        提取的块材标识符字符串。
    """
    for prefix in ("POSCAR_", "CONTCAR_"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    for prefix in ("POSCAR.", "CONTCAR."):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return Path(name).stem


def _bulk_workdir(cfg: "WorkflowConfig", stage: str, bulk_id: str) -> Path:
    """Return the working directory for a bulk-level stage task.

    Args:
        cfg:     Workflow configuration.
        stage:   Stage name (e.g. ``"bulk_relax"``).
        bulk_id: Sanitised bulk material identifier.

    Returns:
        Absolute path: ``<run_root>/<stage>/<bulk_id>``.

    返回块材级阶段任务的工作目录。

    Args:
        cfg:     工作流配置。
        stage:   阶段名称（如 ``"bulk_relax"``）。
        bulk_id: 经净化的块材标识符。

    Returns:
        绝对路径：``<run_root>/<stage>/<bulk_id>``。
    """
    return _run_root(cfg) / stage / bulk_id


def _slab_workdir(cfg: "WorkflowConfig", stage: str, bulk_id: str,
                  hkl: List[int], layers: int, term: int) -> Path:
    """Return the working directory for a slab-level stage task.

    Args:
        cfg:     Workflow configuration.
        stage:   Stage name (e.g. ``"slab_relax"``).
        bulk_id: Sanitised bulk material identifier.
        hkl:     Miller index triplet.
        layers:  Number of atomic layers in the slab.
        term:    Termination index (0-based).

    Returns:
        Absolute path: ``<run_root>/<stage>/<bulk_id>/hkl_HKL/<layers>L/term<term>``.

    返回板坯级阶段任务的工作目录。

    Args:
        cfg:     工作流配置。
        stage:   阶段名称（如 ``"slab_relax"``）。
        bulk_id: 经净化的块材标识符。
        hkl:     Miller 指数三元组。
        layers:  板坯的原子层数。
        term:    终止面索引（从 0 开始）。

    Returns:
        绝对路径：``<run_root>/<stage>/<bulk_id>/hkl_HKL/<layers>L/term<term>``。
    """
    return _run_root(cfg) / stage / bulk_id / _hkl_str(hkl) / f"{layers}L" / f"term{term}"


def _ads_workdir(cfg: "WorkflowConfig", stage: str, bulk_id: str,
                 hkl: List[int], layers: int, term: int,
                 site_type: str, site_index: int) -> Path:
    """Return the working directory for an adsorption-level stage task.

    Args:
        cfg:        Workflow configuration.
        stage:      Stage name (e.g. ``"adsorption"``).
        bulk_id:    Sanitised bulk material identifier.
        hkl:        Miller index triplet.
        layers:     Number of atomic layers in the slab.
        term:       Termination index (0-based).
        site_type:  Adsorption site type string (e.g. ``"ontop"``).
        site_index: Zero-based index of the specific site, zero-padded to 3 digits.

    Returns:
        Absolute path under ``<run_root>/<stage>/.../<site_type>/<NNN>``.

    返回吸附级阶段任务的工作目录。

    Args:
        cfg:        工作流配置。
        stage:      阶段名称（如 ``"adsorption"``）。
        bulk_id:    经净化的块材标识符。
        hkl:        Miller 指数三元组。
        layers:     板坯的原子层数。
        term:       终止面索引（从 0 开始）。
        site_type:  吸附位点类型字符串（如 ``"ontop"``）。
        site_index: 特定位点的从零开始索引，补零至 3 位数字。

    Returns:
        位于 ``<run_root>/<stage>/.../<site_type>/<NNN>`` 下的绝对路径。
    """
    return (
        _run_root(cfg) / stage / bulk_id / _hkl_str(hkl)
        / f"{layers}L" / f"term{term}" / site_type / f"{site_index:03d}"
    )


# ---------------------------------------------------------------------------
# Task ID constructors
# 任务 ID 构造函数
# ---------------------------------------------------------------------------

def _bulk_relax_tid(bid: str) -> str:
    """Return the task ID for a bulk relaxation task.
    返回块材弛豫任务的任务 ID。
    """
    return f"bulk_relax:{bid}"


def _bulk_dos_tid(bid: str) -> str:
    """Return the task ID for a bulk DOS task.
    返回块材 DOS 任务的任务 ID。
    """
    return f"bulk_dos:{bid}"


def _bulk_lobster_tid(bid: str) -> str:
    """Return the task ID for a bulk LOBSTER task.
    返回块材 LOBSTER 任务的任务 ID。
    """
    return f"bulk_lobster:{bid}"


def _bulk_nbo_tid(bid: str) -> str:
    """Return the task ID for a bulk NBO task.
    返回块材 NBO 任务的任务 ID。
    """
    return f"bulk_nbo:{bid}"


def _slab_relax_tid(bid: str, hkl: List[int], layers: int, term: int) -> str:
    """Return the task ID for a slab relaxation task.
    返回板坯弛豫任务的任务 ID。
    """
    return f"slab_relax:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}"


def _slab_dos_tid(bid: str, hkl: List[int], layers: int, term: int) -> str:
    """Return the task ID for a slab DOS task.
    返回板坯 DOS 任务的任务 ID。
    """
    return f"slab_dos:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}"


def _slab_lobster_tid(bid: str, hkl: List[int], layers: int, term: int) -> str:
    """Return the task ID for a slab LOBSTER task.
    返回板坯 LOBSTER 任务的任务 ID。
    """
    return f"slab_lobster:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}"


def _slab_nbo_tid(bid: str, hkl: List[int], layers: int, term: int) -> str:
    """Return the task ID for a slab NBO task.
    返回板坯 NBO 任务的任务 ID。
    """
    return f"slab_nbo:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}"


def _ads_tid(bid: str, hkl: List[int], layers: int, term: int, stype: str, sidx: int) -> str:
    """Return the task ID for an adsorption relaxation task.
    返回吸附弛豫任务的任务 ID。
    """
    return f"adsorption:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}:{stype}:{sidx:03d}"


def _ads_freq_tid(bid: str, hkl: List[int], layers: int, term: int, stype: str, sidx: int) -> str:
    """Return the task ID for an adsorption frequency task.
    返回吸附频率计算任务的任务 ID。
    """
    return f"adsorption_freq:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}:{stype}:{sidx:03d}"


def _ads_lobster_tid(bid: str, hkl: List[int], layers: int, term: int, stype: str, sidx: int) -> str:
    """Return the task ID for an adsorption LOBSTER task.
    返回吸附 LOBSTER 任务的任务 ID。
    """
    return f"adsorption_lobster:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}:{stype}:{sidx:03d}"


def _ads_nbo_tid(bid: str, hkl: List[int], layers: int, term: int, stype: str, sidx: int) -> str:
    """Return the task ID for an adsorption NBO task.
    返回吸附 NBO 任务的任务 ID。
    """
    return f"adsorption_nbo:{bid}:{_hkl_str(hkl)}:{layers}L:term{term}:{stype}:{sidx:03d}"


def _best_structure_path(d: Path) -> Optional[Path]:
    """Return the best available structure file (CONTCAR preferred over POSCAR) in *d*.

    Returns ``None`` when neither file exists or both are empty.

    Args:
        d: Directory to search.

    Returns:
        Path to the first non-empty CONTCAR or POSCAR found, or ``None``.

    返回目录 *d* 中最佳可用结构文件（CONTCAR 优先于 POSCAR）。
    两者均不存在或均为空时返回 ``None``。

    Args:
        d: 要搜索的目录。

    Returns:
        第一个找到的非空 CONTCAR 或 POSCAR 的路径，或 ``None``。
    """
    for name in ("CONTCAR", "POSCAR"):
        p = d / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _resolve_bulk_source_for_slab(
    cfg: "WorkflowConfig", bulk_id: str, fallback: str
) -> str:
    """Prefer CONTCAR/POSCAR from bulk_relax if done, else fallback.

    When the bulk relaxation task for *bulk_id* is marked done, the relaxed
    structure (CONTCAR or POSCAR) is returned so that slab generation uses
    the optimised geometry.  Otherwise the original input file is returned.

    Args:
        cfg:      Workflow configuration.
        bulk_id:  Sanitised bulk material identifier.
        fallback: Path string to use when bulk_relax is not yet done.

    Returns:
        Absolute path string to the structure file to use for slab generation.

    Side effects:
        Raises ``SystemExit`` if bulk_relax is done but no structure file is found.

    若 bulk_relax 已完成则优先使用其中的 CONTCAR/POSCAR，否则使用 fallback。
    当 *bulk_id* 的块材弛豫任务被标记为完成时，返回已弛豫的结构（CONTCAR 或 POSCAR），
    以便板坯生成使用优化后的几何结构；否则返回原始输入文件。

    Args:
        cfg:      工作流配置。
        bulk_id:  经净化的块材标识符。
        fallback: bulk_relax 尚未完成时使用的路径字符串。

    Returns:
        用于板坯生成的结构文件的绝对路径字符串。

    副作用：
        若 bulk_relax 已完成但未找到结构文件，则抛出 ``SystemExit``。
    """
    br = _bulk_workdir(cfg, Stage.BULK_RELAX, bulk_id)
    if is_done(br):
        p = _best_structure_path(br)
        if p:
            return str(p)
        raise SystemExit(f"[hook] ERROR: {br} marked done but no CONTCAR/POSCAR found")
    return fallback
