# -*- coding: utf-8 -*-
"""
flow.calc_registry — CalcType enum + single source of truth for all CalcType-level mappings.
=============================================================================================

All per-CalcType properties live here; other modules import from here
instead of maintaining their own local dicts.  CalcType itself is also
defined here so that calc_type.py can be a thin re-export shim.

Replaces / consolidates the following scattered dicts:
  workflow_engine.py  CalcTypeConfig, CALC_TYPE_REGISTRY,
                      _CALC_TYPE_STR_MAP, CALC_TYPE_FRONTEND_NAME, _VDW_NEEDED
  script.py           CALC_TYPE_TO_CATEGORY
  script_writer.py    _CALC_TYPE_TEMPLATE_MAP, _VDW_FUNCTIONALS

Import chain (no circular deps):
  constants.py  ──┐
  script.py     ──┤──► calc_registry.py
                     then imported by:
                     workflow_engine.py, api.py, script.py, script_writer.py

所有 CalcType 级别属性集中于此；其他模块从此处导入，不再维护本地副本。
CalcType 枚举也定义于此，calc_type.py 成为单行 re-export shim。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Optional, Tuple

from .script import CalcCategory
from .constants import (
    DEFAULT_INCAR_BULK, DEFAULT_INCAR_SLAB,
    DEFAULT_INCAR_NEB, DEFAULT_INCAR_DIMER,
    DEFAULT_INCAR_LOBSTER, DEFAULT_INCAR_NMR_CS, DEFAULT_INCAR_NMR_EFG,
    DEFAULT_INCAR_NBO, DEFAULT_INCAR_MD, DEFAULT_INCAR_MD_NPT,
    DEFAULT_INCAR_FREQ, DEFAULT_INCAR_FREQ_IR,
    INCAR_DELTA_STATIC_SP, INCAR_DELTA_STATIC_DOS,
    INCAR_DELTA_STATIC_CHG, INCAR_DELTA_STATIC_ELF,
)


# ── CalcType enum ─────────────────────────────────────────────────────────────

class CalcType(Enum):
    """标准化计算类型枚举 — 每种计算的规范标识符。"""
    # === 结构优化类 ===
    BULK_RELAX = "bulk_relax"
    SLAB_RELAX = "slab_relax"

    # === 电子结构计算类 ===
    STATIC_SP = "static_sp"
    DOS_SP = "static_dos"
    CHG_SP = "static_charge_density"
    ELF_SP = "static_elf"

    # === 过渡态搜索类 ===
    NEB = "neb"
    DIMER = "dimer"

    # === 频率计算类 ===
    FREQ = "freq"
    FREQ_IR = "freq_ir"

    # === 性质分析类 ===
    LOBSTER = "lobster"
    NMR_CS = "nmr_cs"
    NMR_EFG = "nmr_efg"
    NBO = "nbo"

    # === 分子动力学类 ===
    MD_NVT = "md_nvt"
    MD_NPT = "md_npt"
from .constants import (
    DEFAULT_INCAR_BULK, DEFAULT_INCAR_SLAB,
    DEFAULT_INCAR_NEB, DEFAULT_INCAR_DIMER,
    DEFAULT_INCAR_LOBSTER, DEFAULT_INCAR_NMR_CS, DEFAULT_INCAR_NMR_EFG,
    DEFAULT_INCAR_NBO, DEFAULT_INCAR_MD, DEFAULT_INCAR_MD_NPT,
    DEFAULT_INCAR_FREQ, DEFAULT_INCAR_FREQ_IR,
    INCAR_DELTA_STATIC_SP, INCAR_DELTA_STATIC_DOS,
    INCAR_DELTA_STATIC_CHG, INCAR_DELTA_STATIC_ELF,
)


# ── CalcTypeEntry dataclass ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CalcTypeEntry:
    """All per-CalcType static properties bundled in one object.

    Extends the former CalcTypeConfig with PBS script fields so that every
    module can import from a single registry rather than maintaining local dicts.

    Attributes:
        incar_base:      Base INCAR dict (DEFAULT_INCAR_* from constants.py).
        script_category: CalcCategory used for PBS script template selection.
        frontend_name:   Canonical user-facing string (e.g. ``"bulk_relax"``).
        template_name:   PBS template filename inside ``flow/script/``.
        incar_delta:     Incremental INCAR overrides applied on top of incar_base.
        need_wavecharge: Retain WAVECAR/CHGCAR after the job.
        need_vtst:       Require VTST-patched VASP binary (NEB, DIMER).
        beef_compatible: False for calc types incompatible with BEEF functional.
        str_aliases:     Additional string lookup aliases for this calc type.

    所有 CalcType 级别静态属性汇聚于此。
    """
    incar_base:      Dict[str, Any]
    script_category: CalcCategory
    frontend_name:   str
    template_name:   str = "script.txt"
    incar_delta:     Dict[str, Any] = field(default_factory=dict)
    need_wavecharge: bool = False
    need_vtst:       bool = False
    beef_compatible: bool = True
    str_aliases:     Tuple[str, ...] = ()

    def get_merged_incar(
        self, user_overrides: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Return incar_base merged with incar_delta, then user_overrides on top."""
        merged = {**self.incar_base, **self.incar_delta}
        if user_overrides:
            merged.update(user_overrides)
        return merged


# ── CALC_REGISTRY — single source of truth ───────────────────────────────────
# Maps every CalcType to a CalcTypeEntry that encodes all per-type properties.
# To add a new calc type:
#   1. Add a member to the CalcType enum above.
#   2. Add a DEFAULT_INCAR_* template in constants.py.
#   3. Add a CalcTypeEntry row here.
#   4. Add a case arm in WorkflowEngine.run() (workflow_engine.py).
# ─────────────────────────────────────────────────────────────────────────────
CALC_REGISTRY: Dict[CalcType, CalcTypeEntry] = {
    # ── 结构优化 ─────────────────────────────────────────────────────────────
    CalcType.BULK_RELAX: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_BULK,
        script_category=CalcCategory.RELAX,
        frontend_name="bulk_relax",
    ),
    CalcType.SLAB_RELAX: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_SLAB,
        script_category=CalcCategory.RELAX,
        frontend_name="slab_relax",
        str_aliases=("relax",),
    ),
    # ── 静态/电子结构（MPStaticSetEcat 处理 DEFAULT_INCAR_STATIC，此处仅存增量）─
    CalcType.STATIC_SP: CalcTypeEntry(
        incar_base={},
        incar_delta=INCAR_DELTA_STATIC_SP,
        script_category=CalcCategory.STATIC,
        frontend_name="static_sp",
    ),
    CalcType.DOS_SP: CalcTypeEntry(
        incar_base={},
        incar_delta=INCAR_DELTA_STATIC_DOS,
        need_wavecharge=True,
        script_category=CalcCategory.STATIC,
        frontend_name="static_dos",
        str_aliases=("dos",),          # "dos" is also accepted by generate_inputs()
    ),
    CalcType.CHG_SP: CalcTypeEntry(
        incar_base={},
        incar_delta=INCAR_DELTA_STATIC_CHG,
        need_wavecharge=True,
        script_category=CalcCategory.STATIC,
        frontend_name="static_charge",
        str_aliases=("static_charge_density",),  # CalcType.CHG_SP.value
    ),
    CalcType.ELF_SP: CalcTypeEntry(
        incar_base={},
        incar_delta=INCAR_DELTA_STATIC_ELF,
        need_wavecharge=True,
        script_category=CalcCategory.STATIC,
        frontend_name="static_elf",
    ),
    # ── 过渡态 ───────────────────────────────────────────────────────────────
    CalcType.NEB: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_NEB,
        need_vtst=True,
        script_category=CalcCategory.NEB,
        frontend_name="neb",
    ),
    CalcType.DIMER: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_DIMER,
        need_vtst=True,
        script_category=CalcCategory.DIMER,
        frontend_name="dimer",
    ),
    # ── 频率 ─────────────────────────────────────────────────────────────────
    CalcType.FREQ: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_FREQ,
        script_category=CalcCategory.FREQ,
        frontend_name="freq",
    ),
    CalcType.FREQ_IR: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_FREQ_IR,
        script_category=CalcCategory.FREQ,
        frontend_name="freq_ir",
    ),
    # ── 性质分析 ─────────────────────────────────────────────────────────────
    CalcType.LOBSTER: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_LOBSTER,
        need_wavecharge=True,
        script_category=CalcCategory.LOBSTER,
        frontend_name="lobster",
    ),
    CalcType.NMR_CS: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_NMR_CS,
        script_category=CalcCategory.NMR,
        frontend_name="nmr_cs",
    ),
    CalcType.NMR_EFG: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_NMR_EFG,
        script_category=CalcCategory.NMR,
        frontend_name="nmr_efg",
    ),
    CalcType.NBO: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_NBO,
        need_wavecharge=True,
        script_category=CalcCategory.NBO,
        frontend_name="nbo",
    ),
    # ── 分子动力学 ───────────────────────────────────────────────────────────
    CalcType.MD_NVT: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_MD,
        need_wavecharge=True,
        script_category=CalcCategory.MD,
        frontend_name="md_nvt",
    ),
    CalcType.MD_NPT: CalcTypeEntry(
        incar_base=DEFAULT_INCAR_MD_NPT,
        need_wavecharge=True,
        script_category=CalcCategory.MD,
        frontend_name="md_npt",
    ),
}


# ── VDW_FUNCTIONALS ───────────────────────────────────────────────────────────
# Consolidates _VDW_NEEDED (workflow_engine.py) and _VDW_FUNCTIONALS (script_writer.py).
# 合并原来分散在两处的 VDW 泛函集合。
VDW_FUNCTIONALS: FrozenSet[str] = frozenset({"BEEF", "BEEFVTST"})


# ── Derived lookup tables (built once at module load) ─────────────────────────

# String → CalcType: covers frontend_name, CalcType.value, and str_aliases.
# 字符串 → CalcType：覆盖 frontend_name、CalcType.value 及 str_aliases。
_STR_TO_CALC_TYPE: Dict[str, CalcType] = {}
for _ct, _entry in CALC_REGISTRY.items():
    _STR_TO_CALC_TYPE[_entry.frontend_name] = _ct
    _STR_TO_CALC_TYPE[_ct.value] = _ct           # CalcType.value (may equal frontend_name)
    for _alias in _entry.str_aliases:
        _STR_TO_CALC_TYPE[_alias] = _ct

# CalcType value / frontend_name → CalcCategory.
# Replaces CALC_TYPE_TO_CATEGORY dict in script.py; keyed by all known strings.
# 替代 script.py 中的 CALC_TYPE_TO_CATEGORY，以所有已知字符串为键。
CALC_TYPE_TO_CATEGORY: Dict[str, CalcCategory] = {
    s: CALC_REGISTRY[ct].script_category
    for s, ct in _STR_TO_CALC_TYPE.items()
}


# ── Public helper functions ───────────────────────────────────────────────────

def calc_type_from_str(s: str) -> CalcType:
    """Convert a string to CalcType.  Replaces _CALC_TYPE_STR_MAP lookup.

    Args:
        s: A calc_type string such as ``"bulk_relax"``, ``"dos"``, etc.

    Returns:
        The matching ``CalcType`` enum member.

    Raises:
        KeyError: if *s* is not a known calc_type string.

    将字符串转换为 CalcType 枚举值。替代 _CALC_TYPE_STR_MAP 查找。
    """
    return _STR_TO_CALC_TYPE[s]


def get_template_name(calc_type_str: str) -> str:
    """Return the PBS template filename for *calc_type_str*.

    Replaces _CALC_TYPE_TEMPLATE_MAP lookup in script_writer.py.
    Falls back to ``"script.txt"`` for unknown strings.

    返回给定计算类型的 PBS 模板文件名，替代 _CALC_TYPE_TEMPLATE_MAP。
    """
    ct = _STR_TO_CALC_TYPE.get(calc_type_str)
    return CALC_REGISTRY[ct].template_name if ct is not None else "script.txt"
