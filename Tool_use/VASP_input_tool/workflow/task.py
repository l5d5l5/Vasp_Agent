"""
task.py
=======
Typed structure for manifest task entries.

manifest 任务条目的类型化结构。
"""
from __future__ import annotations

from typing import Any, Dict, List

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # type: ignore[assignment]


class WorkflowTask(TypedDict):
    """Typed structure for a single manifest task entry.

    ``stage`` is stored as a plain string for JSON round-trip compatibility;
    its values correspond to ``Stage`` enum members.

    manifest 中单个任务条目的类型化结构。

    ``stage`` 以普通字符串存储，保证 JSON 读写兼容；
    其值对应 ``Stage`` 枚举的成员值。
    """

    id:      str
    stage:   str
    workdir: str
    deps:    List[str]
    meta:    Dict[str, Any]
