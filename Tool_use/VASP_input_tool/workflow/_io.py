# -*- coding: utf-8 -*-
"""
_io.py — Tiny I/O primitives shared by workflow modules.
workflow 模块共享的小型 I/O 原语。

Kept here (rather than inlined) to avoid duplicating 4 identical helpers
across manifest.py / submitter.py / path_ids.py.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict


def _now_ts() -> str:
    """Return current local time as ``YYYY-MM-DD HH:MM:SS``."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _ensure_dir(p: Path) -> None:
    """Create directory *p* and all parents if they do not exist."""
    p.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file as dict; return ``{}`` when the file does not exist."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, obj: Dict[str, Any]) -> None:
    """Atomically write *obj* as JSON to *path* via a ``.tmp`` sibling."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
