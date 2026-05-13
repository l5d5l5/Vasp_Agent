"""
stages/__init__.py
==================
Stage registry: STAGE_ORDER, enabled_stages(), get_stage().

This module aggregates all stage classes into a single registry and
provides helper functions for looking up and filtering stages.

阶段注册表：STAGE_ORDER、enabled_stages()、get_stage()。

本模块将所有阶段类汇聚到统一的注册表中，并提供用于查找和筛选阶段的辅助函数。
"""
from __future__ import annotations

from typing import Dict, List, Union, TYPE_CHECKING

from .base import BaseStage, Stage
from .bulk import (
    BulkRelaxStage,
    BulkDosStage,
    BulkLobsterStage,
    BulkNboStage,
)
from .slab import (
    SlabRelaxStage,
    SlabDosStage,
    SlabLobsterStage,
    SlabNboStage,
)
from .adsorption import (
    AdsorptionStage,
    AdsorptionFreqStage,
    AdsLobsterStage,
    AdsNboStage,
)

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig


# Canonical execution order (must match manifest dependency graph).
# 规范的执行顺序（必须与清单依赖图保持一致）。
STAGE_ORDER: List[Stage] = [
    Stage.BULK_RELAX,
    Stage.BULK_DOS,
    Stage.BULK_LOBSTER,
    Stage.BULK_NBO,

    Stage.SLAB_RELAX,
    Stage.SLAB_DOS,
    Stage.SLAB_LOBSTER,
    Stage.SLAB_NBO,

    Stage.ADSORPTION,
    Stage.ADSORPTION_FREQ,
    Stage.ADSORPTION_LOBSTER,
    Stage.ADSORPTION_NBO,
]


# Internal registry mapping stage name → stage instance.
# 内部注册表，将阶段名称映射到阶段实例。
_REGISTRY: dict[Stage, BaseStage] = {
    Stage.BULK_RELAX:         BulkRelaxStage(),
    Stage.BULK_DOS:           BulkDosStage(),
    Stage.BULK_LOBSTER:       BulkLobsterStage(),
    Stage.BULK_NBO:           BulkNboStage(),

    Stage.SLAB_RELAX:         SlabRelaxStage(),
    Stage.SLAB_DOS:           SlabDosStage(),
    Stage.SLAB_LOBSTER:       SlabLobsterStage(),
    Stage.SLAB_NBO:           SlabNboStage(),

    Stage.ADSORPTION:         AdsorptionStage(),
    Stage.ADSORPTION_FREQ:    AdsorptionFreqStage(),
    Stage.ADSORPTION_LOBSTER: AdsLobsterStage(),
    Stage.ADSORPTION_NBO:     AdsNboStage(),
}


def stage_sort_key(stage: "Union[str, Stage]") -> int:
    """Return the execution-order index of *stage* in STAGE_ORDER.

    Lower index = higher scheduling priority.  Returns 999 for unknown stages
    so they sort last without raising.

    返回 *stage* 在 STAGE_ORDER 中的执行顺序索引（越小优先级越高）。
    未知阶段返回 999，排在最后，不抛异常。
    """
    try:
        return STAGE_ORDER.index(stage)
    except ValueError:
        return 999


def get_stage(stage_name: "str | Stage") -> BaseStage:
    """Return the stage instance for *stage_name*.

    Looks up the stage in the module-level ``_REGISTRY`` dict.

    Args:
        stage_name: Key matching an entry in ``STAGE_ORDER``.

    Returns:
        The singleton ``BaseStage`` instance registered under *stage_name*.

    Raises:
        ValueError: if *stage_name* is not in the registry.

    根据阶段名称返回对应的阶段实例。

    在模块级 ``_REGISTRY`` 字典中查找阶段。

    Args:
        stage_name: 与 ``STAGE_ORDER`` 中某条目匹配的键。

    Returns:
        注册在 *stage_name* 下的单例 ``BaseStage`` 实例。

    Raises:
        ValueError: 若 *stage_name* 不在注册表中。
    """
    try:
        return _REGISTRY[stage_name]
    except KeyError:
        raise ValueError(
            f"Unknown stage {stage_name!r}. Valid stages: {STAGE_ORDER}"
        ) from None


def enabled_stages(cfg: "WorkflowConfig") -> List[str]:
    """Return the ordered list of stages that are enabled in *cfg*.

    Iterates ``STAGE_ORDER`` and keeps only those stages whose
    corresponding boolean flag on ``cfg.workflow`` is truthy.

    Args:
        cfg: Full typed workflow configuration object.

    Returns:
        Ordered list of stage-name strings that are switched on.

    返回在 *cfg* 中已启用的阶段的有序列表。

    遍历 ``STAGE_ORDER``，仅保留 ``cfg.workflow`` 上对应布尔标志为真的阶段。

    Args:
        cfg: 完整的带类型工作流配置对象。

    Returns:
        已开启的阶段名称字符串的有序列表。
    """
    flags = cfg.workflow

    # Keep only stages whose flag attribute evaluates to True.
    # 仅保留标志属性值为 True 的阶段。
    return [
        s for s in STAGE_ORDER
        if getattr(flags, s, False)
    ]


__all__ = [
    "STAGE_ORDER",
    "Stage",
    "get_stage",
    "enabled_stages",
    "stage_sort_key",

    "BaseStage",

    "BulkRelaxStage",
    "BulkDosStage",
    "BulkLobsterStage",
    "BulkNboStage",

    "SlabRelaxStage",
    "SlabDosStage",
    "SlabLobsterStage",
    "SlabNboStage",

    "AdsorptionStage",
    "AdsorptionFreqStage",
    "AdsLobsterStage",
    "AdsNboStage",
]
