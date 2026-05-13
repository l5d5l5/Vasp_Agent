# -*- coding: utf-8 -*-
"""
submitter.py — PBS job submission and workflow-level drivers.
PBS 作业提交与工作流级别驱动函数。

This module owns the full task-submission pipeline (script build → qsub →
submitted.json) and the three public workflow drivers that callers use
(auto_submit_workflow, submit_all_ready, mark_done_by_workdir).
本模块负责完整的任务提交流程（脚本构建 → qsub → submitted.json）
以及调用方使用的三个公共工作流驱动函数。
"""
from __future__ import annotations

import hashlib as _hashlib
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

from flow.workflow._io import _dump_json, _ensure_dir, _load_json, _now_ts
from flow.workflow.manifest import (
    MAX_RETRIES,
    _STALE_GRACE_PERIOD_SECONDS,
    _deps_satisfied,
    _is_stale_submission,
    _submission_age_seconds,
    expand_manifest,
)
from flow.workflow.markers import (
    is_done,
    is_failed,
    is_submitted,
    lobster_ok,
    outcar_ok,
    submitted_marker,
    write_done,
    write_failed,
)
from flow.workflow.path_ids import _detect_stage
from flow.workflow.pbs import DirLock, render_template, submit_job
from flow.workflow.stages import STAGE_ORDER, Stage, get_stage, stage_sort_key
from flow.workflow.task import WorkflowTask

logger = logging.getLogger(__name__)


def _die(msg: str, code: int = 2) -> None:
    print(f"[hook] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


# ---------------------------------------------------------------------------
# PBS script construction
# PBS 脚本构建
# ---------------------------------------------------------------------------

def _short_hash(text: str, n: int = 6) -> str:
    """Return the first *n* hex characters of the SHA-1 hash of *text*.

    返回 *text* 的 SHA-1 哈希的前 *n* 个十六进制字符，用于生成唯一 PBS 作业名后缀。
    """
    return _hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def _build_pbs_ctx(
    cfg: "WorkflowConfig",
    stage: str,
    workdir: Path,
    task: WorkflowTask,
) -> Dict[str, Any]:
    """Build the template context dict used to render the PBS job script.

    构建用于渲染 PBS 作业脚本的模板上下文字典。
    """
    pbs = cfg.pbs
    proj = cfg.project
    pr = cfg.python_runtime
    bulk_id = (task.get("meta") or {}).get("bulk_id", "")

    base = f"{pbs.job_name_prefix}_{stage}"
    if bulk_id:
        base = f"{base}_{bulk_id}"
    job_name = f"{base[:8]}_{_short_hash(task['id'])}"

    hook_script = proj.project_root / "workflow" / "hook.py"

    try:
        functional = cfg.get_stage_vasp(stage).functional.upper()
        type1 = "beef" if functional == "BEEF" else "org"
    except (ValueError, AttributeError):
        type1 = "org"

    return {
        "project_root":  str(proj.project_root),
        "run_root":      str(proj.run_root),
        "stage":         stage,
        "workdir":       str(workdir),
        "task_id":       str(task.get("id", "")),
        "bulk_id":       str(bulk_id),
        "params_file":   cfg._params_file,
        "queue":         pbs.queue,
        "ppn":           int(pbs.ppn),
        "walltime":      str(pbs.walltime),
        "job_name":      job_name,
        "hook_script":   str(hook_script),
        "TYPE1":         type1,
        "conda_sh":      pr.conda_sh,
        "conda_env":     pr.conda_env,
        "python_bin":    pr.python_bin,
    }


def _write_pbs_script(
    cfg: "WorkflowConfig",
    stage: str,
    workdir: Path,
    task: Dict[str, Any],
) -> Path:
    """Render the PBS template and write ``job.pbs`` into *workdir*.

    渲染 PBS 模板并将 ``job.pbs`` 写入 *workdir*。
    """
    tpl = cfg.pbs.template_file
    ctx = _build_pbs_ctx(cfg, stage, workdir, task)
    script_text = render_template(tpl, ctx)
    script_path = workdir / "job.pbs"
    script_path.write_text(script_text, encoding="utf-8")
    return script_path


# ---------------------------------------------------------------------------
# Input generation (delegates to stage classes)
# 输入生成（委托给阶段类）
# ---------------------------------------------------------------------------

def _generate_inputs(cfg: "WorkflowConfig", task: WorkflowTask) -> None:
    """Call the appropriate stage's prepare() to write VASP inputs.

    调用相应阶段的 prepare() 以写入 VASP 输入文件。
    """
    stage = task["stage"]
    workdir = Path(task["workdir"]).expanduser().resolve()
    _ensure_dir(workdir)

    meta = task.get("meta") or {}
    prev_raw = meta.get("prev", "")
    prev_dir: Optional[Path] = (
        Path(prev_raw).expanduser().resolve()
        if prev_raw
        else None
    )

    stage_obj = get_stage(stage)

    if stage in (Stage.BULK_DOS, Stage.BULK_LOBSTER, Stage.BULK_NBO,
                 Stage.SLAB_DOS, Stage.SLAB_LOBSTER, Stage.SLAB_NBO,
                 Stage.ADSORPTION_FREQ, Stage.ADSORPTION_LOBSTER, Stage.ADSORPTION_NBO):
        if not prev_dir or not prev_dir.exists():
            _die(
                f"Task {task['id']}: prev_dir required and must exist, "
                f"but got: {prev_dir}"
            )
        if not is_done(prev_dir):
            _die(
                f"Task {task['id']}: prev_dir is not done yet: {prev_dir}"
            )

    stage_obj.prepare(
        workdir=workdir,
        prev_dir=prev_dir,
        cfg=cfg,
        task_meta=meta,
    )


# ---------------------------------------------------------------------------
# Task submission
# 任务提交
# ---------------------------------------------------------------------------

def _submit_task(
    cfg: "WorkflowConfig",
    m: Dict[str, Any],
    task: WorkflowTask,
    resubmit: bool = False,
    rerun_done: bool = False,
    ignore_deps: bool = False,
) -> bool:
    """Submit a single task. Returns True if actually submitted.

    Acquires a per-directory lock, checks guard conditions (done, submitted,
    deps), generates VASP inputs, renders the PBS script, calls qsub, and
    writes ``submitted.json``.

    提交单个任务，若实际提交则返回 True。
    """
    stage       = task["stage"]
    workdir     = Path(task["workdir"]).expanduser().resolve()
    retry_count = 0
    _ensure_dir(workdir)

    lock = DirLock(workdir / ".lock")
    if not lock.acquire():
        print(f"[hook] task locked, skip: id={task['id']}")
        return False

    try:
        if is_done(workdir) and not rerun_done:
            print(f"[hook] task done, skip: id={task['id']}")
            return False
        if is_submitted(workdir) and not resubmit:
            if not _is_stale_submission(workdir):
                print(f"[hook] task submitted, skip: id={task['id']}")
                return False
            age = _submission_age_seconds(workdir)
            if age < _STALE_GRACE_PERIOD_SECONDS:
                print(
                    f"[hook] stale within grace period "
                    f"({age:.0f}s < {_STALE_GRACE_PERIOD_SECONDS}s), skip: id={task['id']}"
                )
                return False
            try:
                if get_stage(stage).check_success(workdir, cfg):
                    write_done(workdir, {
                        "task_id": task["id"],
                        "stage":   stage,
                        "workdir": str(workdir),
                        "time":    _now_ts(),
                        "note":    "written by stale-detection success check",
                    })
                    print(f"[hook] stale job already succeeded, wrote done.ok: id={task['id']}")
                    return False
            except Exception:
                logger.debug("check_success failed for %s; will resubmit.", task["id"])
            old_meta = _load_json(submitted_marker(workdir))
            retry_count = old_meta.get("retry_count", 0) + 1
            if retry_count > MAX_RETRIES:
                logger.warning(
                    "Task %s exceeded MAX_RETRIES (%d); writing failed.json.",
                    task["id"], MAX_RETRIES,
                )
                write_failed(workdir, {
                    "task_id":     task["id"],
                    "stage":       stage,
                    "workdir":     str(workdir),
                    "time":        _now_ts(),
                    "retry_count": retry_count,
                    "reason":      "exceeded MAX_RETRIES",
                })
                return False
            logger.warning(
                "Stale submission for task %s (%s); clearing submitted.json for resubmission "
                "(retry %d/%d).",
                task["id"], workdir, retry_count, MAX_RETRIES,
            )
            submitted_marker(workdir).unlink(missing_ok=True)
        if not ignore_deps and not _deps_satisfied(m, task):
            print(f"[hook] deps not satisfied, skip: id={task['id']}")
            return False

        _generate_inputs(cfg, task)
        script = _write_pbs_script(cfg, stage, workdir, task)
        job_id = submit_job(script, workdir)

        sub_meta = {
            "task_id":     task["id"],
            "stage":       stage,
            "workdir":     str(workdir),
            "job_id":      job_id,
            "time":        _now_ts(),
            "retry_count": retry_count,
        }
        _dump_json(submitted_marker(workdir), sub_meta)
        print(
            f"[hook] submitted: task_id={task['id']} "
            f"stage={stage} job_id={job_id} workdir={workdir}"
        )
        return True

    except Exception:
        logger.exception("Error submitting task %s", task["id"])
        return False
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# Workflow drivers (public API)
# 工作流驱动函数（公共 API）
# ---------------------------------------------------------------------------

def auto_submit_workflow(
    cfg: "WorkflowConfig",
    resubmit: bool = False,
    rerun_done: bool = False,
    ignore_deps: bool = False,
    stage_filter: str = "",
) -> None:
    """Expand manifest and submit the first eligible task.

    Tasks are sorted by stage order then by task ID for determinism.
    The loop exits after the first successful submission.

    展开 manifest 并提交第一个符合条件的任务。
    """
    m = expand_manifest(cfg)
    tasks = m["tasks"]

    def _key(t: Dict[str, Any]) -> Tuple[int, str]:
        return (stage_sort_key(t["stage"]), t["id"])

    for t in sorted(tasks.values(), key=_key):
        if stage_filter and t["stage"] != stage_filter:
            continue
        w = Path(t["workdir"])
        if is_failed(w):
            continue
        if is_done(w) and not rerun_done:
            continue
        if is_submitted(w) and not resubmit:
            if not _is_stale_submission(w):
                continue
        if not ignore_deps and not _deps_satisfied(m, t):
            continue
        _submit_task(cfg, m, t, resubmit=resubmit, rerun_done=rerun_done, ignore_deps=ignore_deps)
        return

    print("[hook] No eligible tasks: all done/submitted or deps not met.")


def submit_all_ready(
    cfg: "WorkflowConfig",
    resubmit: bool = False,
    rerun_done: bool = False,
    ignore_deps: bool = False,
    stage_filter: str = "",
    limit: int = 0,
) -> int:
    """Expand manifest and submit ALL currently eligible tasks.

    Unlike ``auto_submit_workflow``, this function does not stop after the
    first submission.  A ``limit`` of 0 means unlimited.

    展开 manifest 并提交所有当前符合条件的任务。
    """
    m = expand_manifest(cfg)
    tasks = m["tasks"]

    def _key(t: Dict[str, Any]) -> Tuple[int, str]:
        return (stage_sort_key(t["stage"]), t["id"])

    submitted = skipped = 0
    for t in sorted(tasks.values(), key=_key):
        if stage_filter and t["stage"] != stage_filter:
            continue
        w = Path(t["workdir"])
        if is_failed(w):
            skipped += 1
            continue
        if is_done(w) and not rerun_done:
            skipped += 1
            continue
        if is_submitted(w) and not resubmit:
            if not _is_stale_submission(w):
                skipped += 1
                continue
        if not ignore_deps and not _deps_satisfied(m, t):
            skipped += 1
            continue
        ok = _submit_task(cfg, m, t, resubmit=resubmit, rerun_done=rerun_done, ignore_deps=ignore_deps)
        if ok:
            submitted += 1
            if limit and submitted >= limit:
                break
        else:
            skipped += 1

    print(
        f"[hook] submit-all finished: "
        f"submitted={submitted}, skipped={skipped}, limit={limit}"
    )
    return submitted


# ---------------------------------------------------------------------------
# Mark-done
# 标记完成
# ---------------------------------------------------------------------------

def mark_done_by_workdir(workdir: Path, cfg: "WorkflowConfig") -> None:
    """Check OUTCAR (and optionally LOBSTER or NBO), then write done.ok.

    Detects the stage from ``submitted.json`` or the directory path, then
    applies the appropriate success check.

    检查 OUTCAR（以及可选的 LOBSTER 或 NBO），然后写入 done.ok。
    """
    stage = _detect_stage(workdir)
    if not stage:
        _die(f"Cannot infer stage from workdir: {workdir}")

    if stage in (Stage.BULK_LOBSTER, Stage.SLAB_LOBSTER, Stage.ADSORPTION_LOBSTER):
        if lobster_ok(workdir, cfg):
            write_done(workdir, {
                "workdir": str(workdir),
                "time": _now_ts(),
                "success_check": "OUTCAR+LOBSTER",
                "stage": stage,
            })
            print(f"[hook] marked done: {workdir} ({stage})")
            return
        _die(f"LOBSTER stage did not pass success check: {workdir}")

    if stage in (Stage.BULK_NBO, Stage.SLAB_NBO, Stage.ADSORPTION_NBO):
        if get_stage(stage).check_success(workdir, cfg):
            write_done(workdir, {
                "workdir": str(workdir),
                "time": _now_ts(),
                "success_check": "stage.check_success",
                "stage": stage,
            })
            print(f"[hook] marked done: {workdir} ({stage})")
            return
        _die(f"NBO stage did not pass success check: {workdir}")

    if outcar_ok(workdir / "OUTCAR"):
        write_done(workdir, {
            "workdir": str(workdir),
            "time": _now_ts(),
            "success_check": "OUTCAR",
            "stage": stage,
        })
        print(f"[hook] marked done: {workdir}")
    else:
        _die(f"OUTCAR does not show normal termination: {workdir / 'OUTCAR'}")
