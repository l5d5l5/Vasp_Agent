"""
markers.py
==========
Atomic marker-file helpers for tracking workflow state on disk.

Every workdir can hold two marker files:
  done.ok          – written after a successful stage completion
  submitted.json   – written immediately after qsub returns a job_id

These are the ONLY sources of truth for stage status; never check job
scheduler state directly from application code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig


# ---------------------------------------------------------------------------
# Path accessors
# ---------------------------------------------------------------------------

def done_marker(workdir: Path) -> Path:
    """Return the path of the ``done.ok`` marker for *workdir*."""
    return workdir / "done.ok"


def submitted_marker(workdir: Path) -> Path:
    """Return the path of the ``submitted.json`` marker for *workdir*."""
    return workdir / "submitted.json"


def failed_marker(workdir: Path) -> Path:
    """Return the path of the ``failed.json`` marker for *workdir*."""
    return workdir / "failed.json"


# ---------------------------------------------------------------------------
# State predicates
# ---------------------------------------------------------------------------

def is_done(workdir: Path) -> bool:
    """Return True if the stage in *workdir* has written ``done.ok``."""
    return done_marker(workdir).exists()


def is_submitted(workdir: Path) -> bool:
    """Return True if the stage in *workdir* has been submitted (``submitted.json`` exists)."""
    return submitted_marker(workdir).exists()


def is_failed(workdir: Path) -> bool:
    """Return True if the stage in *workdir* has written ``failed.json`` (retry limit exceeded)."""
    return failed_marker(workdir).exists()


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def write_done(workdir: Path, meta: Dict[str, Any]) -> None:
    """Write ``done.ok`` containing *meta* as JSON (atomic via temp-file replace)."""
    _write_json_atomic(done_marker(workdir), meta)


def write_submitted(workdir: Path, meta: Dict[str, Any]) -> None:
    """Write ``submitted.json`` containing *meta* as JSON (atomic)."""
    _write_json_atomic(submitted_marker(workdir), meta)


def write_failed(workdir: Path, meta: Dict[str, Any]) -> None:
    """Write ``failed.json`` containing *meta* as JSON (atomic)."""
    _write_json_atomic(failed_marker(workdir), meta)


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _write_json_atomic(path: Path, obj: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# OUTCAR / LOBSTER success checks
# OUTCAR / LOBSTER 成功检查
# ---------------------------------------------------------------------------

def outcar_ok(outcar: Path) -> bool:
    """Return True if the OUTCAR file contains a normal-termination marker.

    Reads the last 20 000 characters of the file to find any of three
    patterns that VASP writes on clean exit.

    Args:
        outcar: Path to the OUTCAR file.

    Returns:
        ``True`` if a termination marker is found; ``False`` otherwise.

    若 OUTCAR 文件包含正常终止标志则返回 True。
    读取文件末尾 20 000 个字符，查找 VASP 正常退出时写入的三种模式之一。

    Args:
        outcar: OUTCAR 文件路径。

    Returns:
        找到终止标志时返回 ``True``，否则返回 ``False``。
    """
    if not outcar.exists():
        return False
    try:
        # Binary seek to tail: avoids loading multi-GB OUTCAR files into memory.
        # 二进制尾部读取：避免先将整个数 GB OUTCAR 加载入内存再切片。
        with outcar.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 20_000, 0))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return False
    # Three distinct phrases that VASP prints at the end of a successful run.
    # VASP 成功运行结束时打印的三个不同短语。
    patterns = [
        r"total cpu time used",
        r"voluntary context switches",
        r"General timing and accounting informations",
    ]
    return any(re.search(p, tail, flags=re.IGNORECASE) for p in patterns)


def lobster_ok(workdir: Path, cfg: "WorkflowConfig") -> bool:
    """Return True if both VASP and LOBSTER finished successfully.

    Checks, in order:
    1. OUTCAR contains a normal-termination marker.
    2. ``lobsterout`` exists and is non-empty.
    3. Every file listed in ``LOBSTER_SUCCESS_FILES`` exists and is non-empty.

    Args:
        workdir: Directory containing OUTCAR, lobsterout, and LOBSTER outputs.
        cfg:     Workflow configuration (used indirectly via LOBSTER_SUCCESS_FILES).

    Returns:
        ``True`` only when all three checks pass.

    若 VASP 和 LOBSTER 均成功完成则返回 True。
    依次检查：
    1. OUTCAR 包含正常终止标志。
    2. ``lobsterout`` 存在且非空。
    3. ``LOBSTER_SUCCESS_FILES`` 中列出的每个文件均存在且非空。

    Args:
        workdir: 包含 OUTCAR、lobsterout 及 LOBSTER 输出的目录。
        cfg:     工作流配置（通过 LOBSTER_SUCCESS_FILES 间接使用）。

    Returns:
        仅当三项检查全部通过时返回 ``True``。
    """
    from flow.workflow.config import LOBSTER_SUCCESS_FILES
    # Gate 1: VASP must have terminated normally.
    # 门控 1：VASP 必须正常终止。
    if not outcar_ok(workdir / "OUTCAR"):
        return False
    # Gate 2: LOBSTER must have produced a non-empty lobsterout.
    # 门控 2：LOBSTER 必须产生非空的 lobsterout 文件。
    lobsterout = workdir / "lobsterout"
    if not lobsterout.exists() or lobsterout.stat().st_size == 0:
        return False
    # Gate 3: All mandatory LOBSTER output files must be present and non-empty.
    # 门控 3：所有必须的 LOBSTER 输出文件必须存在且非空。
    for fn in LOBSTER_SUCCESS_FILES:
        p = workdir / str(fn)
        if not p.exists() or p.stat().st_size == 0:
            return False
    # Gate 4: lobsterout must end with LOBSTER's timing summary line.
    # 门控 4：lobsterout 末尾必须包含 LOBSTER 的耗时汇总行。
    try:
        with lobsterout.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 4_000, 0))
            tail = f.read().decode("utf-8", errors="ignore")
        if not re.search(r"finished in\s+\d+", tail):
            return False
    except OSError:
        return False
    return True
