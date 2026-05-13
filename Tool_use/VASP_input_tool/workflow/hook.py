#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hook.py — PBS epilogue entry point and workflow orchestrator (CLI shell).
PBS 结束钩子入口点与工作流总调度器（CLI 外壳）。

This file is now a thin CLI wrapper.  All business logic has been moved to:
  manifest.py   – manifest lifecycle and task-graph expansion
  submitter.py  – PBS script building, job submission, workflow drivers
  path_ids.py   – path construction and task-ID generation
  markers.py    – done.ok / submitted.json / failed.json + OUTCAR/LOBSTER checks
  _io.py        – tiny JSON / filesystem primitives

此文件现为薄 CLI 包装层，所有业务逻辑已迁移到上述模块。

CLI subcommands / CLI 子命令
-----------------------------
  expand        Expand / refresh manifest.json (create task entries).
  auto          Expand manifest and submit the first eligible task.
  submit-all    Expand manifest and submit ALL eligible tasks.
  mark-done     Check OUTCAR/LOBSTER for a workdir and write done.ok.
  extract       Parse completed calculations and report energies.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict

from flow.workflow.config import WorkflowConfig, load_config
from flow.workflow.manifest import expand_manifest, _manifest_path
from flow.workflow.stages import STAGE_ORDER
from flow.workflow.submitter import (
    auto_submit_workflow,
    mark_done_by_workdir,
    submit_all_ready,
)

# Re-export public API so existing callers (workflow/__init__.py, tests) keep working.
# 重导出公共 API，确保现有调用方（workflow/__init__.py、测试）无需修改。
__all__ = [
    "expand_manifest",
    "auto_submit_workflow",
    "submit_all_ready",
    "mark_done_by_workdir",
]

logger = logging.getLogger(__name__)


def _die(msg: str, code: int = 2) -> None:
    """Print an error message to stderr and exit with the given code.

    打印错误消息到 stderr，然后以指定退出码终止进程。
    """
    print(f"[hook] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _setup_logging() -> None:
    """Configure the root logger with WARNING level and a simple format.

    以 WARNING 级别和简单格式配置根 logger。
    """
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate workflow action.

    Subcommands and their behaviour:

    expand
        Calls ``expand_manifest`` and prints the manifest path.  No jobs are
        submitted.

    auto
        Calls ``auto_submit_workflow``.  Submits at most one eligible job.
        Accepts ``--resubmit``, ``--rerun-done``, ``--ignore-deps``, ``--stage``.

    submit-all
        Calls ``submit_all_ready``.  Submits all eligible jobs up to
        ``--limit`` (default 0 = unlimited).

    mark-done
        Calls ``mark_done_by_workdir`` for the path given by ``--workdir``.

    extract
        Imports and runs ``flow.workflow.extract.run_extract``.

    解析 CLI 参数并分派到相应的工作流操作。
    """
    _setup_logging()

    ap = argparse.ArgumentParser(
        description="HT workflow hook – manifest expansion, PBS submission, done markers."
    )
    ap.add_argument("--params", required=True, help="Path to params.yaml")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("expand", help="Expand/refresh manifest.json only.")

    s_auto = sub.add_parser("auto", help="Expand and submit the first eligible task.")
    s_auto.add_argument("--resubmit",    action="store_true",
                        help="Re-submit even if submitted.json exists.")
    s_auto.add_argument("--rerun-done",  action="store_true",
                        help="Re-run even if done.ok exists (use with caution).")
    s_auto.add_argument("--ignore-deps", action="store_true",
                        help="Skip dependency gate checks (dangerous).")
    s_auto.add_argument("--stage", default="", help="Optional stage filter.")

    s_all = sub.add_parser("submit-all", help="Expand and submit ALL eligible tasks.")
    s_all.add_argument("--resubmit",    action="store_true",
                       help="Re-submit even if submitted.json exists.")
    s_all.add_argument("--rerun-done",  action="store_true",
                       help="Re-run even if done.ok exists (use with caution).")
    s_all.add_argument("--ignore-deps", action="store_true",
                       help="Skip dependency gate checks (dangerous).")
    s_all.add_argument("--stage", default="", help="Optional stage filter.")
    s_all.add_argument("--limit", type=int, default=0)

    s_done = sub.add_parser(
        "mark-done", help="Check OUTCAR/LOBSTER and write done.ok for a workdir."
    )
    s_done.add_argument("--workdir", required=True)

    s_ext = sub.add_parser("extract", help="Parse completed calculations and report energies.")
    s_ext.add_argument("--output", default=None, help="Output file path (omit for stdout).")
    s_ext.add_argument("--format", dest="fmt", choices=["table", "json", "csv"], default="table")
    s_ext.add_argument("--stages", default="", help="Comma-separated stage filter.")
    s_ext.add_argument(
        "--mol-ref", action="append", dest="mol_refs", metavar="FORMULA=eV",
        help="Molecule reference energy, e.g. CO=-14.78. Repeat for multiple.",
    )

    args = ap.parse_args()
    cfg = load_config(args.params)

    if args.cmd == "expand":
        expand_manifest(cfg)
        print(f"[hook] manifest updated: {_manifest_path(cfg)}")
        return

    if args.cmd == "auto":
        if args.stage and args.stage not in STAGE_ORDER:
            _die(f"--stage must be one of {STAGE_ORDER} (or empty).")
        auto_submit_workflow(
            cfg,
            resubmit=bool(args.resubmit),
            rerun_done=bool(args.rerun_done),
            ignore_deps=bool(args.ignore_deps),
            stage_filter=str(args.stage),
        )
        return

    if args.cmd == "submit-all":
        if args.stage and args.stage not in STAGE_ORDER:
            _die(f"--stage must be one of {STAGE_ORDER} (or empty).")
        submit_all_ready(
            cfg,
            resubmit=bool(args.resubmit),
            rerun_done=bool(args.rerun_done),
            ignore_deps=bool(args.ignore_deps),
            stage_filter=str(args.stage),
            limit=int(args.limit),
        )
        return

    if args.cmd == "mark-done":
        wd = Path(args.workdir).expanduser().resolve()
        if not wd.exists():
            _die(f"workdir does not exist: {wd}")
        mark_done_by_workdir(wd, cfg)
        return

    if args.cmd == "extract":
        from flow.workflow.extract import run_extract
        mol_refs: Dict[str, float] = {}
        for item in (args.mol_refs or []):
            key, _, val = item.partition("=")
            if not key or not val:
                _die(f"--mol-ref must be FORMULA=eV, got: {item!r}")
            mol_refs[key.strip()] = float(val)
        stages_filter = [s.strip() for s in args.stages.split(",") if s.strip()] or None
        run_extract(cfg, output=args.output, fmt=args.fmt, mol_refs=mol_refs or None,
                    stages=stages_filter)
        return

    _die(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
