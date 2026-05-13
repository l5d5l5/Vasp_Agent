"""
pbs.py
======
Low-level PBS/Torque helpers.

  DirLock          – mkdir-based atomic directory lock (safe on shared FS)
  render_template  – Jinja2 template rendering with StrictUndefined
  submit_job       – submit a PBS script via qsub, return job_id
  poll_job         – query job status via qstat, return status string
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, StrictUndefined

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Directory lock
# ---------------------------------------------------------------------------

class DirLock:
    """Atomic lock implemented via ``mkdir`` – safe on most shared filesystems.

    Usage::

        lock = DirLock(some_dir / ".lock")
        if not lock.acquire():
            sys.exit(0)          # another process holds it
        try:
            ...do work...
        finally:
            lock.release()
    """

    def __init__(self, lock_dir: Path) -> None:
        self.lock_dir = lock_dir
        self.acquired = False

    def acquire(self) -> bool:
        """Try to acquire the lock.  Returns True on success, False if already held."""
        try:
            self.lock_dir.mkdir(parents=False, exist_ok=False)
            self.acquired = True
            (self.lock_dir / "meta.json").write_text(
                json.dumps({"pid": os.getpid(), "time": _now_ts()}, indent=2),
                encoding="utf-8",
            )
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        """Release the lock by removing the lock directory."""
        if not self.acquired:
            return
        try:
            for child in self.lock_dir.glob("*"):
                try:
                    child.unlink()
                except Exception:
                    pass
            self.lock_dir.rmdir()
        except Exception:
            pass
        self.acquired = False

    def __enter__(self) -> "DirLock":
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def render_template(tpl_path: Path, ctx: Dict[str, Any]) -> str:
    """Render a Jinja2 template file with StrictUndefined (fails on missing vars).

    Args:
        tpl_path: Absolute path to the ``.tpl`` file.
        ctx:      Template context dict.

    Returns:
        Rendered string.

    Raises:
        jinja2.UndefinedError: if any template variable is not present in *ctx*.
        FileNotFoundError:     if *tpl_path* does not exist.
    """
    if not tpl_path.exists():
        raise FileNotFoundError(f"PBS template not found: {tpl_path}")
    text = tpl_path.read_text(encoding="utf-8")
    env = Environment(undefined=StrictUndefined)
    return env.from_string(text).render(**ctx)


# ---------------------------------------------------------------------------
# Job submission
# ---------------------------------------------------------------------------

def submit_job(script_path: Path, workdir: Path) -> str:
    """Submit a PBS script via ``qsub`` and return the job_id string.

    Args:
        script_path: Path to the ``.pbs`` script file.
        workdir:     Working directory passed to qsub (``-cwd``-equivalent via CWD).

    Returns:
        Job ID string as printed by qsub (e.g. ``"12345.pbs-server"``).

    Raises:
        RuntimeError: if qsub exits with a non-zero return code.
    """
    rc, out, err = _run_cmd(["qsub", str(script_path)], cwd=workdir)
    if rc != 0:
        raise RuntimeError(
            f"qsub failed (rc={rc}). stdout={out!r} stderr={err!r}"
        )
    return out.strip()


# ---------------------------------------------------------------------------
# Job status polling
# ---------------------------------------------------------------------------

def poll_job(job_id: str) -> str:
    """Query the status of a job via ``qstat``.

    Returns:
        A single status character (``"R"``, ``"Q"``, ``"C"``, …) extracted
        from qstat output, or ``"UNKNOWN"`` if the job is not found.
    """
    rc, out, err = _run_cmd(["qstat", job_id])
    if rc != 0:
        logger.debug("qstat for job %s returned rc=%d: %s", job_id, rc, err)
        return "UNKNOWN"

    # qstat output format:  Job id  Name  User  Time Use  S  Queue
    for line in out.splitlines():
        parts = line.split()
        if parts and job_id in parts[0]:
            return parts[4] if len(parts) > 4 else "UNKNOWN"

    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _run_cmd(
    cmd: List[str],
    cwd: Optional[Path] = None,
) -> Tuple[int, str, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = proc.communicate()
    return proc.returncode, (out or "").strip(), (err or "").strip()


def _now_ts() -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
