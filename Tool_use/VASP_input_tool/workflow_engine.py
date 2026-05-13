# -*- coding: utf-8 -*-
"""
flow.workflow_engine — VASP input-file dispatch engine
=======================================================

Position in the write pipeline
-------------------------------
::

    FrontendAdapter.from_frontend_dict()    (flow/api.py)
        └─ VaspWorkflowParams.to_workflow_config()
                 └─ WorkflowEngine.run(config)           ← THIS FILE
                          ├─ _get_incar_params()  ← CALC_TYPE_REGISTRY lookup
                          └─ _write_*(config, incar_params, output_dir)  ← module-level
                                   └─ InputSet.write_input()  (flow/input_sets/)
                                            └─ POSCAR / INCAR / KPOINTS / POTCAR (disk)

Responsibilities
----------------
1. ``CalcType`` enum — the single canonical name for each calculation type.
2. ``CALC_TYPE_REGISTRY`` — maps each ``CalcType`` to its INCAR template, WAVECAR
   retention flag, VTST requirement, and script category.  This is the single
   source of truth for per-type defaults.
3. ``WorkflowConfig`` dataclass — all parameters consumed by ``WorkflowEngine``.
4. ``WorkflowEngine.run()`` — selects the correct ``_write_*()`` module-level
   function via a ``match`` statement and calls the InputSet directly.

Extension points — where to touch this file when adding a new stage
--------------------------------------------------------------------
1. Add a value to the ``CalcType`` enum.
2. Add a ``CalcTypeConfig(...)`` entry to ``CALC_TYPE_REGISTRY`` referencing the
   correct ``DEFAULT_INCAR_*`` template from ``flow/constants.py``.
3. If the new type needs extra parameters (e.g. ``nbo_config``), add a field to
   ``WorkflowConfig``.
4. Add a ``_write_new_type()`` module-level function below and a matching
   ``case CalcType.NEW_TYPE:`` arm in ``WorkflowEngine.run()``.
5. Add a matching ``FrontendAdapter`` extraction in ``flow/api.py``.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pymatgen.core import Structure

from .constants import FUNCTIONAL_INCAR_PATCHES
from .calc_registry import CalcType
from .calc_registry import (
    CalcTypeEntry as CalcTypeConfig,   # backward-compat alias (tests import CalcTypeConfig)
    CALC_REGISTRY as CALC_TYPE_REGISTRY,
    VDW_FUNCTIONALS as _VDW_NEEDED,    # backward-compat name used in this file
    calc_type_from_str as _calc_type_from_str,
)
from .input_sets import (
    BulkRelaxSetEcat,
    DimerSetEcat,
    FreqSetEcat,
    LobsterSetEcat,
    MDSetEcat,
    MPStaticSetEcat,
    NBOSetEcat,
    NEBSetEcat,
    NMRSetEcat,
    SlabSetEcat,
)
from .script import CalcCategory, Script
from .utils import load_structure, pick_adsorbate_indices_by_formula_strict
from .validator import validate as _validator_validate, ValidationError

logger = logging.getLogger(__name__)



# CalcTypeConfig, CALC_TYPE_REGISTRY, _CALC_TYPE_STR_MAP, _VDW_NEEDED have been
# moved to flow/calc_registry.py and are imported above as backward-compat aliases.
# CalcTypeConfig、CALC_TYPE_REGISTRY、_CALC_TYPE_STR_MAP、_VDW_NEEDED 已移至
# flow/calc_registry.py，在上方以向后兼容别名导入。


@dataclass
class WorkflowConfig:
    """
    工作流配置 - 用户友好接口
    
    相比直接构建 InputSet，用户只需：
    1. 指定 calc_type：计算类型（必选）
    2. 指定 structure：输入结构（必选）
    3. 指定 prev_dir：前序目录（可选，系统会自动推断）
    
    ================================================================================
    参数分类
    ================================================================================
    
    【前端可配置参数】
      calc_type          - 计算类型（CalcType枚举）
      structure          - 输入结构（文件路径或pymatgen Structure对象）
      functional         - 泛函，默认 PBE
      kpoints_density    - K点密度，默认 50.0
      output_dir         - 输出目录，默认自动生成
      prev_dir           - 前序计算目录（可选）
      
      MD参数: ensemble, start_temp, end_temp, nsteps, time_step
      NEB参数: n_images, use_idpp, start_structure, end_structure
      频率参数: vibrate_indices, calc_ir
      NMR参数: isotopes
      NBO参数: nbo_config
      
    【高级参数】（谨慎使用）
      user_incar_overrides - 直接覆盖INCAR参数
      
    ================================================================================
    """
    # === 核心配置 ===
    calc_type: CalcType                                    # 计算类型（必选）
    structure: Optional[Union[str, Path, Structure]] = None  # 输入结构（neb/dimer 可为 None）
    
    # === 功能参数（前端暴露）===
    functional: str = "PBE"                                # 泛函，默认 PBE
    kpoints_density: float = 50.0                           # K点密度
    output_dir: Optional[Union[str, Path]] = None          # 输出目录
    
    # === 前序依赖（可选，系统可自动推断）===
    prev_dir: Optional[Union[str, Path]] = None
    
    # === MD 专用参数 ===
    ensemble: str = "nvt"
    start_temp: float = 300.0
    end_temp: float = 300.0
    nsteps: int = 1000
    time_step: Optional[float] = None
    
    # === NEB 专用参数 ===
    n_images: int = 6
    use_idpp: bool = True
    start_structure: Optional[Union[str, Path, Structure]] = None
    end_structure: Optional[Union[str, Path, Structure]] = None
    
    # === 频率计算专用 ===
    vibrate_indices: Optional[List[int]] = None
    calc_ir: bool = False
    
    # === NMR 专用 ===
    isotopes: Optional[List[str]] = None
    
    # === NBO 专用 ===
    nbo_config: Optional[Dict[str, Any]] = None

    # === Lobster 专用 ===
    lobster_overwritedict: Optional[Dict[str, Any]] = None
    lobster_custom_lines: Optional[List[str]] = None

    # === 高级覆盖 ===
    user_incar_overrides: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        # ── calc_type：接受字符串，自动转换为 CalcType 枚举 ──────────────────
        if isinstance(self.calc_type, str):
            key = self.calc_type.lower().strip()
            try:
                self.calc_type = _calc_type_from_str(key)
            except KeyError:
                from .calc_registry import _STR_TO_CALC_TYPE
                valid = ", ".join(f'"{k}"' for k in sorted(_STR_TO_CALC_TYPE))
                raise ValueError(
                    f"Unknown calc_type string '{self.calc_type}'. "
                    f"Valid options: {valid}"
                ) from None

        # ── functional：统一大写 ─────────────────────────────────────────────
        self.functional = self.functional.upper()

        # ── output_dir：统一转为 Path ────────────────────────────────────────
        self.output_dir = Path(self.output_dir) if self.output_dir else None

        # ── user_incar_overrides：确保不为 None ──────────────────────────────
        if self.user_incar_overrides is None:
            self.user_incar_overrides = {}
    
    def auto_detect_prev_dir(self) -> Optional[Path]:
        """
        自动检测前序目录
        
        策略：
        1. 如果已指定 prev_dir，直接返回
        2. 尝试从 output_dir 的兄弟目录推断（假设命名规范）
        3. 尝试从当前工作目录推断
        """
        if self.prev_dir:
            return Path(self.prev_dir).resolve()
        
        # 策略2：从 output_dir 推断
        if self.output_dir:
            parent = self.output_dir.parent
            # 尝试常见的命名模式
            patterns = ["00-relax", "01-relax", "opt", "optimization", "relax"]
            for pattern in patterns:
                candidate = parent / pattern
                if candidate.exists() and (candidate / "CONTCAR").exists():
                    logger.info(f"自动检测到前序目录: {candidate}")
                    return candidate
        
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Module-level write helpers — called directly from WorkflowEngine.run().
# These replace VaspInputMaker as the indirection layer between WorkflowEngine
# and the InputSet classes.  Each function receives already-merged incar_params
# and a pre-created output_dir; per-type logic (prev_dir handling, special
# constructor args) lives here rather than in a separate class.
# ──────────────────────────────────────────────────────────────────────────────

_POTCAR_FUNCTIONAL = "PBE_54"


def _ensure_dir(path: Union[str, Path]) -> Path:
    """Resolve *path* to an absolute Path and create it (and parents) if absent."""
    out = Path(path).resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _apply_magmom_compat(
    structure: Optional[Structure],
    incar_params: Dict[str, Any],
) -> Optional[Structure]:
    """Normalize MAGMOM in *incar_params* to the per-element dict pymatgen expects.

    Converts VASP-style strings (``"3*0.6 1*5.0"``) and flat lists/tuples to a
    ``{element: avg_moment}`` dict.  When the per-atom list length matches the
    site count, values are also attached as the ``"magmom"`` site property.

    Modifies *incar_params* in-place.  Returns the (possibly copied) structure.
    """
    if structure is None or "MAGMOM" not in incar_params:
        return structure

    raw_magmom = incar_params["MAGMOM"]
    mag_list: List[float] = []

    if isinstance(raw_magmom, dict):
        return structure
    elif isinstance(raw_magmom, str):
        for token in raw_magmom.split():
            if "*" in token:
                try:
                    count, val = token.split("*", 1)
                    mag_list.extend([float(val)] * int(count))
                except ValueError:
                    logger.warning("MAGMOM string parse failed, keeping original: %s", raw_magmom)
                    mag_list = []
                    break
            else:
                mag_list.append(float(token))
    elif isinstance(raw_magmom, (list, tuple)):
        mag_list = [float(v) for v in raw_magmom]
    else:
        return structure

    if not mag_list:
        incar_params["MAGMOM"] = {}
        return structure

    if len(mag_list) == len(structure):
        try:
            structure = structure.copy()
            structure.add_site_property("magmom", mag_list)
        except Exception as exc:
            logger.warning("Failed to attach per-atom MAGMOM to structure: %s", exc)

    per_element: Dict[str, List[float]] = {}
    for idx, site in enumerate(structure):
        val = mag_list[idx] if idx < len(mag_list) else mag_list[-1]
        per_element.setdefault(site.species_string, []).append(val)
    incar_params["MAGMOM"] = {k: sum(v) / len(v) for k, v in per_element.items()}
    return structure


def _write_bulk(struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig") -> None:
    struct_obj = load_structure(struct)
    struct_obj = _apply_magmom_compat(struct_obj, incar) or struct_obj
    BulkRelaxSetEcat(
        structure=struct_obj,
        functional=config.functional,
        kpoints_density=config.kpoints_density,
        use_default_incar=True,
        use_default_kpoints=True,
        user_incar_settings=incar,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    ).write_input(output_dir)


def _write_slab(struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig") -> None:
    struct_obj = load_structure(struct)
    struct_obj = _apply_magmom_compat(struct_obj, incar) or struct_obj
    SlabSetEcat(
        structure=struct_obj,
        functional=config.functional,
        kpoints_density=config.kpoints_density,
        use_default_incar=True,
        use_default_kpoints=True,
        user_incar_settings=incar,
        auto_dipole=True,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    ).write_input(output_dir)


def _write_noscf(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path],
) -> None:
    structure_obj: Optional[Structure] = None
    if prev is not None:
        try:
            structure_obj = load_structure(prev)
        except Exception:
            pass
    elif struct is not None:
        structure_obj = load_structure(struct)
    structure_obj = _apply_magmom_compat(structure_obj, incar) or structure_obj

    if prev is not None:
        MPStaticSetEcat.from_prev_calc_ecat(
            prev_dir=prev,
            kpoints_density=config.kpoints_density,
            user_incar_settings=incar,
            user_kpoints_settings=None,
        ).write_input(output_dir)
    else:
        if structure_obj is None:
            raise ValueError("Must provide structure or prev_dir for static calculation.")
        MPStaticSetEcat(
            structure=structure_obj,
            functional=config.functional,
            kpoints_density=config.kpoints_density,
            use_default_incar=True,
            use_default_kpoints=True,
            user_incar_settings=incar,
            user_potcar_functional=_POTCAR_FUNCTIONAL,
        ).write_input(output_dir)


def _write_neb(incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig") -> None:
    structure_for_mag: Optional[Structure] = None
    try:
        structure_for_mag = load_structure(config.start_structure)
    except Exception:
        try:
            structure_for_mag = load_structure(config.end_structure)
        except Exception:
            pass
    _apply_magmom_compat(structure_for_mag, incar)

    is_start_dir = isinstance(config.start_structure, (str, Path)) and Path(config.start_structure).is_dir()
    is_end_dir = isinstance(config.end_structure, (str, Path)) and Path(config.end_structure).is_dir()

    common = dict(
        use_default_incar=True,
        user_incar_settings=incar,
        user_kpoints_settings=None,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    )
    if is_start_dir or is_end_dir:
        prev_dir = config.start_structure if is_start_dir else config.end_structure
        NEBSetEcat.from_prev_calc(
            prev_dir=prev_dir,
            start_structure=config.start_structure,
            end_structure=config.end_structure,
            n_images=config.n_images,
            use_idpp=config.use_idpp,
            **common,
        ).write_input(output_dir)
    else:
        NEBSetEcat(
            start_structure=config.start_structure,
            end_structure=config.end_structure,
            n_images=config.n_images,
            use_idpp=config.use_idpp,
            **common,
        ).write_input(output_dir)


def _write_lobster(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path],
) -> None:
    structure_obj: Optional[Structure] = None
    if prev is not None:
        try:
            structure_obj = load_structure(prev)
        except Exception:
            pass
    elif struct is not None:
        structure_obj = load_structure(struct)
    structure_obj = _apply_magmom_compat(structure_obj, incar) or structure_obj

    common = dict(
        use_default_incar=True,
        user_incar_settings=incar,
        user_kpoints_settings=None,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    )
    write_kwargs = dict(
        overwritedict=config.lobster_overwritedict,
        custom_lobsterin_lines=config.lobster_custom_lines,
    )
    if prev is not None:
        LobsterSetEcat.from_prev_calc_ecat(
            prev_dir=prev,
            kpoints_density=config.kpoints_density,
            isym=0,
            ismear=-5,
            reciprocal_density=None,
            user_supplied_basis=None,
            **common,
        ).write_input(output_dir, **write_kwargs)
    else:
        if structure_obj is None:
            raise ValueError("Must provide structure or prev_dir for Lobster.")
        LobsterSetEcat(
            structure=structure_obj,
            isym=0,
            ismear=-5,
            reciprocal_density=None,
            user_supplied_basis=None,
            **common,
        ).write_input(output_dir, **write_kwargs)


def _write_freq(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path], calc_ir: bool,
) -> None:
    if isinstance(struct, Structure):
        final_structure = struct.copy()
    elif struct is not None:
        final_structure = load_structure(struct)
    elif prev is not None:
        contcar_path = prev / "CONTCAR"
        if not contcar_path.exists():
            raise FileNotFoundError(f"CONTCAR not found in {prev}")
        final_structure = Structure.from_file(contcar_path)
    else:
        raise ValueError("Either structure or prev_dir must be provided for freq calculation.")

    final_structure = _apply_magmom_compat(final_structure, incar) or final_structure
    vibrate_indices = config.vibrate_indices

    common = dict(
        use_default_incar=True,
        user_incar_settings=incar,
        user_kpoints_settings=None,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    )
    if prev is not None:
        FreqSetEcat.from_prev_calc_ecat(
            prev_dir=prev,
            structure=final_structure,
            vibrate_indices=vibrate_indices,
            calc_ir=calc_ir,
            **common,
        ).write_input(output_dir)
    else:
        if vibrate_indices is not None:
            final_structure = FreqSetEcat._apply_vibrate_indices(final_structure, vibrate_indices)
        FreqSetEcat(
            structure=final_structure,
            functional=config.functional,
            calc_ir=calc_ir,
            **common,
        ).write_input(output_dir)


def _write_dimer(incar: Dict[str, Any], output_dir: Path, prev: Optional[Path]) -> None:
    structure_obj: Optional[Structure] = None
    if prev is not None:
        try:
            structure_obj = load_structure(prev)
        except Exception:
            pass
    _apply_magmom_compat(structure_obj, incar)

    if prev is None:
        raise ValueError("Dimer calculation requires a completed NEB directory as prev_dir.")
    logger.info("Generating Dimer input from NEB directory: %s", prev)
    DimerSetEcat.from_neb_calc(
        neb_dir=prev,
        num_images=None,
        use_default_incar=True,
        user_incar_settings=incar,
        user_kpoints_settings=None,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    ).write_input(output_dir)


def _write_nbo(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path],
) -> None:
    if struct is not None:
        if isinstance(struct, Structure):
            final_structure = struct.copy()
        else:
            final_structure = Structure.from_file(struct)
    elif prev is not None:
        contcar_path = prev / "CONTCAR"
        if not contcar_path.exists():
            raise FileNotFoundError(f"CONTCAR not found in {prev}")
        final_structure = Structure.from_file(contcar_path)
    else:
        raise ValueError("Must provide structure or prev_dir for NBO calculation.")

    final_structure = _apply_magmom_compat(final_structure, incar) or final_structure
    nbo_config_dict = dict(config.nbo_config) if config.nbo_config else {}
    basis_source = nbo_config_dict.pop("basis_source", None)

    if prev is not None:
        NBOSetEcat.from_prev_calc(
            prev_dir=prev,
            basis_source=basis_source,
            nbo_config=nbo_config_dict or None,
            user_incar_settings=incar,
            user_kpoints_settings=None,
            structure=final_structure,
        ).write_input(output_dir)
    else:
        NBOSetEcat(
            structure=final_structure,
            basis_source=basis_source,
            nbo_config=nbo_config_dict or None,
            use_default_incar=True,
            user_incar_settings=incar,
            user_kpoints_settings=None,
            user_potcar_functional=_POTCAR_FUNCTIONAL,
        ).write_input(output_dir)


def _write_nmr(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path], mode: str,
) -> None:
    nmr_kd = max(int(config.kpoints_density), 100)

    structure_obj: Optional[Structure] = None
    if prev is not None:
        try:
            structure_obj = load_structure(prev)
        except Exception:
            pass
    elif struct is not None:
        structure_obj = load_structure(struct)
    structure_obj = _apply_magmom_compat(structure_obj, incar) or structure_obj

    if prev is not None:
        NMRSetEcat.from_prev_calc_ecat(
            prev_dir=prev,
            mode=mode,
            isotopes=config.isotopes,
            kpoints_density=nmr_kd,
            user_incar_settings=incar,
            user_kpoints_settings=None,
        ).write_input(output_dir)
    else:
        if structure_obj is None:
            raise ValueError("Must provide structure or prev_dir for NMR calculation.")
        NMRSetEcat(
            structure=structure_obj,
            mode=mode,
            isotopes=config.isotopes,
            functional=config.functional,
            kpoints_density=nmr_kd,
            use_default_incar=True,
            user_incar_settings=incar,
            user_kpoints_settings=None,
            user_potcar_functional=_POTCAR_FUNCTIONAL,
        ).write_input(output_dir)


def _write_md(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
    prev: Optional[Path], ensemble: str,
) -> None:
    structure_obj: Optional[Structure] = None
    if prev is not None:
        try:
            structure_obj = load_structure(prev)
        except Exception:
            pass
    elif struct is not None:
        structure_obj = load_structure(struct)
    structure_obj = _apply_magmom_compat(structure_obj, incar) or structure_obj

    md_params = dict(
        ensemble=ensemble,
        start_temp=config.start_temp,
        end_temp=config.end_temp,
        nsteps=config.nsteps,
        time_step=config.time_step,
    )

    if prev is not None:
        MDSetEcat.from_prev_calc_ecat(
            prev_dir=prev,
            user_incar_settings=incar,
            user_kpoints_settings=None,
            **md_params,
        ).write_input(output_dir)
    else:
        if structure_obj is None:
            raise ValueError("Must provide structure or prev_dir for MD calculation.")
        MDSetEcat(
            structure=structure_obj,
            functional=config.functional,
            use_default_incar=True,
            user_incar_settings=incar,
            user_kpoints_settings=None,
            user_potcar_functional=_POTCAR_FUNCTIONAL,
            **md_params,
        ).write_input(output_dir)


class WorkflowEngine:
    """
    工作流引擎 - 执行标准化工作流
    
    用法示例：
    
    ```python
    # 简单用法
    engine = WorkflowEngine()
    engine.run(
        calc_type=CalcType.STATIC_SP,
        structure="POSCAR",
        functional="PBE",
        output_dir="calc/static"
    )
    
    # 续接前序计算
    engine.run(
        calc_type=CalcType.DOS_SP,
        structure="calc/static",
        prev_dir="calc/static"  # 可省略，会自动检测
    )
    ```
    
    对于脚本生成：
    ```python
    engine.generate_script(
        calc_type=CalcType.NEB,
        ...
    )
    ```
    """
    
    def __init__(
        self,
        maker=None,  # deprecated: kept for backward compatibility, no longer used
        script_maker: Optional[Script] = None,
    ):
        self.script_maker = script_maker or Script()
    
    def _get_incar_params(self, config: WorkflowConfig) -> Dict[str, Any]:
        """Merge INCAR parameters in priority order (lowest → highest):

        1. ``CALC_TYPE_REGISTRY[calc_type].incar_base``  — type-specific defaults
        2. ``CALC_TYPE_REGISTRY[calc_type].incar_delta`` — static increments
        3. ``FUNCTIONAL_INCAR_PATCHES[functional]``      — functional-specific tags
           (e.g. GGA/LUSE_VDW/AGGAC/LASPH for BEEF, METAGGA/ADDGRID for SCAN,
           LHFCALC/AEXX/HFSCREEN for HSE)
        4. ``config.user_incar_overrides``               — user-supplied overrides
           (always wins; user can still override any functional-level default)

        Note: when ``prev_dir`` is set, INCAR/KPOINTS inheritance from the
        previous calculation is handled inside the relevant ``InputSet``
        ``from_prev_calc_ecat()`` class methods (``MPStaticSetEcat``,
        ``FreqSetEcat``, ``LobsterSetEcat``, …) in ``flow/input_sets/``.
        Those methods merge the inherited INCAR with calc-type-specific deltas
        (e.g. ``DEFAULT_INCAR_STATIC`` on top of the relax INCAR), then apply
        ``user_incar_overrides`` as the final layer.  This function therefore
        does NOT additionally read ``prev_dir/INCAR`` — doing so would put the
        full relax INCAR into ``user_incar_settings``, overriding the static
        defaults (IBRION, NSW, …) that ``from_prev_calc_ecat`` correctly sets.

        Side effect: when MAGMOM is present in the merged result, ISPIN=2 is
        injected automatically unless the user already supplied ISPIN explicitly.

        The result is passed as ``user_incar_settings`` to the ``_write_*()``
        helper, which forwards it to the pymatgen ``InputSet`` as the final INCAR overlay.

        按优先级（从低到高）合并 INCAR 参数：

        1. ``CALC_TYPE_REGISTRY[calc_type].incar_base``  — 计算类型专属默认值
        2. ``CALC_TYPE_REGISTRY[calc_type].incar_delta`` — 静态增量覆盖
        3. ``FUNCTIONAL_INCAR_PATCHES[functional]``      — 泛函专属标记
        4. ``config.user_incar_overrides``               — 用户覆盖（始终最高优先级）

        注意：设置了 ``prev_dir`` 时，INCAR/KPOINTS 继承由各 ``InputSet`` 的
        ``from_prev_calc_ecat()`` 类方法在 ``flow/input_sets/`` 内部处理，
        本函数不额外读取 ``prev_dir/INCAR``。

        副作用：若合并结果中存在 MAGMOM，且用户未显式设置 ISPIN，则自动注入 ISPIN=2。
        """
        ct_cfg = CALC_TYPE_REGISTRY.get(config.calc_type)
        base = ct_cfg.get_merged_incar({}) if ct_cfg is not None else {}
        func_patch = FUNCTIONAL_INCAR_PATCHES.get(config.functional, {})
        merged: Dict[str, Any] = {**base, **func_patch, **config.user_incar_overrides}
        # Auto-inject ISPIN=2 when MAGMOM is present and the user has not
        # explicitly set ISPIN.  VASP silently ignores MAGMOM when ISPIN=1.
        # 当 MAGMOM 存在且用户未显式设置 ISPIN 时自动注入 ISPIN=2。
        if "MAGMOM" in merged and "ISPIN" not in config.user_incar_overrides:
            merged.setdefault("ISPIN", 2)
        return merged

    def _get_script_context(self, config: WorkflowConfig) -> Dict[str, Any]:
        """生成脚本渲染上下文。"""
        ct_cfg = CALC_TYPE_REGISTRY[config.calc_type]
        need_wavecharge = ct_cfg.need_wavecharge
        cleanup_cmd = (
            ""
            if need_wavecharge
            else "rm REPORT CHG* DOSCAR EIGENVAL IBZKPT PCDAT PROCAR WAVECAR XDATCAR vasprun.xml FORCECAR"
        )
        return {
            "functional": config.functional,
            "cleanup_cmd": cleanup_cmd,
            "need_vdw": any(v in config.functional for v in _VDW_NEEDED),
        }
    
    def _copy_vdw_kernel(self, output_dir: Path) -> None:
        """Copy ``vdw_kernel.bindat`` into *output_dir* for vdW functionals.

        The source path is read from the ``FLOW_VDW_KERNEL`` environment
        variable.  Raises ``FileNotFoundError`` with a clear message when the
        variable is unset or points to a non-existent file — so the user knows
        exactly what to fix before the VASP job is submitted.

        将 ``vdw_kernel.bindat`` 复制到 *output_dir*（用于需要 vdW 核文件的泛函）。

        源路径从环境变量 ``FLOW_VDW_KERNEL`` 读取。若该变量未设置或指向不存在的
        文件，抛出 ``FileNotFoundError`` 并给出明确的错误说明。
        """
        vdw_env = os.environ.get("FLOW_VDW_KERNEL", "").strip()
        if not vdw_env:
            raise FileNotFoundError(
                "BEEF/BEEFVTST functional requires vdw_kernel.bindat in the "
                "output directory, but the FLOW_VDW_KERNEL environment variable "
                "is not set.  Please run:\n"
                "  export FLOW_VDW_KERNEL=/absolute/path/to/vdw_kernel.bindat\n"
                "BEEF/BEEFVTST 泛函需要 vdw_kernel.bindat，但环境变量 "
                "FLOW_VDW_KERNEL 未设置。请执行上述 export 命令后重试。"
            )
        src = Path(vdw_env)
        if not src.is_file():
            raise FileNotFoundError(
                f"vdw_kernel.bindat not found at '{src}' "
                f"(FLOW_VDW_KERNEL={vdw_env}).\n"
                f"vdw_kernel.bindat 在 '{src}' 处不存在，请检查 FLOW_VDW_KERNEL 路径。"
            )
        dest = output_dir / "vdw_kernel.bindat"
        shutil.copy2(src, dest)
        logger.info("Copied vdw_kernel.bindat → %s", dest)

    def _copy_prev_wavecharge(
        self,
        prev_dir: Path,
        output_dir: Path,
        user_incar_overrides: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Copy WAVECAR and/or CHGCAR from *prev_dir* into *output_dir*.

        Files are only copied when they exist and are non-empty.  Missing or
        empty files are silently skipped — the workflow proceeds normally.

        Returns a dict of INCAR tags to add (``ICHARG=1`` when CHGCAR is
        copied, ``ISTART=1`` when only WAVECAR is copied).  Tags already
        present in *user_incar_overrides* are **not** included in the return
        value so the user's explicit settings always take highest priority.

        将 WAVECAR 和/或 CHGCAR 从 *prev_dir* 复制到 *output_dir*。

        仅在文件存在且非空时复制；缺失或空文件静默跳过，工作流继续正常运行。

        返回需追加的 INCAR 标记字典：复制了 CHGCAR 时返回 ``ICHARG=1``，
        仅复制了 WAVECAR 时返回 ``ISTART=1``。若用户在 *user_incar_overrides*
        中已显式设置这些标记，则不覆盖（用户值始终优先）。
        """
        incar_additions: Dict[str, Any] = {}

        chgcar = prev_dir / "CHGCAR"
        wavecar = prev_dir / "WAVECAR"

        chgcar_copied = False
        wavecar_copied = False

        if chgcar.is_file() and chgcar.stat().st_size > 0:
            shutil.copy2(chgcar, output_dir / "CHGCAR")
            chgcar_copied = True
            logger.info("Copied CHGCAR from %s → %s", prev_dir, output_dir)

        if wavecar.is_file() and wavecar.stat().st_size > 0:
            shutil.copy2(wavecar, output_dir / "WAVECAR")
            wavecar_copied = True
            logger.info("Copied WAVECAR from %s → %s", prev_dir, output_dir)

        if chgcar_copied and "ICHARG" not in user_incar_overrides:
            incar_additions["ICHARG"] = 1
        elif wavecar_copied and "ISTART" not in user_incar_overrides:
            incar_additions["ISTART"] = 1

        return incar_additions

    def run(
        self,
        config: WorkflowConfig,
        generate_script: bool = True,
        cores: Optional[int] = None,
        walltime: Optional[int] = None,
    ) -> str:
        """Write VASP input files for *config* to ``config.output_dir``.

        Steps
        -----
        1. Auto-detect ``prev_dir`` if not supplied.
        2. Validate ``config`` (raises ``ValueError`` on bad params).
        3. Resolve structure from ``prev_dir`` when the explicit path is absent.
        4. Pre-check ``prev_dir`` for WAVECAR/CHGCAR; append ICHARG/ISTART tags.
        5. Build merged INCAR params via ``_get_incar_params()``.
        6. Dispatch to the correct ``_write_*()`` module-level helper via a ``match`` statement.
        7. Copy WAVECAR/CHGCAR from ``prev_dir`` into the output directory.
        8. Copy ``vdw_kernel.bindat`` if a vdW functional is used.
        9. Optionally generate a PBS/SLURM job submission script.

        Args:
            config:          Workflow configuration.
            generate_script: If ``True``, write a job submission script after
                             generating VASP inputs.  Failures are logged as
                             warnings; VASP inputs are never affected.
            cores:           CPU core count passed to the script generator.
            walltime:        Wall-time limit in hours passed to the script generator.

        To add a new calc type, add a ``case CalcType.NEW_TYPE:`` arm here that
        calls the appropriate ``_write_*()`` function with any required
        ``WorkflowConfig`` fields.

        Returns:
            Absolute path to the output directory as a string.
        """
        # 1. 自动检测 prev_dir
        if config.prev_dir is None:
            config.prev_dir = config.auto_detect_prev_dir()

        prev = Path(config.prev_dir).resolve() if config.prev_dir else None

        # 2. 验证配置
        try:
            _validator_validate(
                calc_type=config.calc_type.value,
                structure=config.structure,
                functional=config.functional,
                kpoints_density=config.kpoints_density,
                output_dir=config.output_dir,
                prev_dir=config.prev_dir,
                incar=config.user_incar_overrides or None,
                # NEB 专用字段通过 **extra 传入
                start_structure=config.start_structure,
                end_structure=config.end_structure,
                neb_images=None,  # WorkflowConfig 不直接暴露 neb_images 列表
            )
        except ValidationError as exc:
            # 将 ValidationError 转为 ValueError 保持 run() 原有异常类型契约
            raise ValueError("配置验证失败:\n" + "\n".join(f"  - {e}" for e in exc.errors)) from exc
        
        # 3. 解析 structure 为具体的文件路径
        #
        # 优先级：
        #   a) structure 是存在的文件            → 直接使用
        #   b) structure 是目录                  → 从目录取 CONTCAR（非空）或 POSCAR
        #   c) structure 文件不存在 / 为 None     → 从 prev_dir 取 CONTCAR（非空）或 POSCAR
        struct = config.structure

        if isinstance(struct, (str, Path)):
            struct_path = Path(struct)

            if struct_path.is_file():
                # 文件存在，直接使用，无需任何处理
                pass

            elif struct_path.is_dir():
                # structure 本身是目录，从中解析 CONTCAR/POSCAR
                contcar = struct_path / "CONTCAR"
                poscar  = struct_path / "POSCAR"
                if contcar.is_file() and contcar.stat().st_size > 0:
                    struct = contcar
                    logger.info(
                        "Structure '%s' is a directory; using CONTCAR: %s",
                        config.structure, contcar,
                    )
                elif poscar.is_file():
                    struct = poscar
                    logger.info(
                        "Structure '%s' is a directory; using POSCAR: %s",
                        config.structure, poscar,
                    )
                else:
                    raise ValueError(
                        f"Structure path '{config.structure}' is a directory but "
                        "contains neither CONTCAR nor POSCAR."
                    )

            else:
                # 路径不存在，尝试从 prev_dir 取
                if prev is not None:
                    contcar = prev / "CONTCAR"
                    poscar_fallback = prev / "POSCAR"
                    if contcar.is_file() and contcar.stat().st_size > 0:
                        struct = contcar
                        logger.info(
                            "Structure '%s' not found; using CONTCAR from prev_dir: %s",
                            config.structure, contcar,
                        )
                    elif poscar_fallback.is_file():
                        struct = poscar_fallback
                        logger.info(
                            "Structure '%s' not found; using POSCAR from prev_dir: %s",
                            config.structure, poscar_fallback,
                        )
                    else:
                        raise ValueError(
                            f"Structure file '{config.structure}' not found and "
                            f"prev_dir '{prev}' contains neither CONTCAR nor POSCAR."
                        )
                # else: structure 不存在且无 prev_dir → validator 已拦截，不会到达此处

        elif struct is None:
            # structure=None，完全依赖 prev_dir
            if prev is not None:
                contcar = prev / "CONTCAR"
                poscar_fallback = prev / "POSCAR"
                if contcar.is_file() and contcar.stat().st_size > 0:
                    struct = contcar
                    logger.info("structure=None; using CONTCAR from prev_dir: %s", contcar)
                elif poscar_fallback.is_file():
                    struct = poscar_fallback
                    logger.info("structure=None; using POSCAR from prev_dir: %s", poscar_fallback)
                else:
                    raise ValueError(
                        f"structure is None and prev_dir '{prev}' contains "
                        "neither CONTCAR nor POSCAR."
                    )

        # 4. 确定并创建输出目录
        raw_out = config.output_dir if config.output_dir is not None else Path.cwd() / f"calc_{config.calc_type.value}"
        output_dir = _ensure_dir(raw_out)

        # 5. Pre-check prev_dir for WAVECAR/CHGCAR; add ICHARG/ISTART to INCAR.
        wavecharge_incar: Dict[str, Any] = {}
        if prev is not None:
            chgcar = prev / "CHGCAR"
            wavecar = prev / "WAVECAR"
            if chgcar.is_file() and chgcar.stat().st_size > 0 and "ICHARG" not in config.user_incar_overrides:
                wavecharge_incar["ICHARG"] = 1
            elif wavecar.is_file() and wavecar.stat().st_size > 0 and "ISTART" not in config.user_incar_overrides:
                wavecharge_incar["ISTART"] = 1

        # 6. Build merged INCAR and dispatch directly to the InputSet.
        incar_params = {**self._get_incar_params(config), **wavecharge_incar}

        match config.calc_type:
            case CalcType.BULK_RELAX:
                _write_bulk(struct, incar_params, output_dir, config)

            case CalcType.SLAB_RELAX:
                _write_slab(struct, incar_params, output_dir, config)

            case CalcType.STATIC_SP | CalcType.DOS_SP | CalcType.CHG_SP | CalcType.ELF_SP:
                _write_noscf(struct if prev is None else None, incar_params, output_dir, config, prev)

            case CalcType.NEB:
                _write_neb(incar_params, output_dir, config)

            case CalcType.DIMER:
                _write_dimer(incar_params, output_dir, prev)

            case CalcType.FREQ:
                _write_freq(struct, incar_params, output_dir, config, prev, calc_ir=False)

            case CalcType.FREQ_IR:
                _write_freq(struct, incar_params, output_dir, config, prev, calc_ir=True)

            case CalcType.LOBSTER:
                _write_lobster(struct if prev is None else None, incar_params, output_dir, config, prev)

            case CalcType.NMR_CS:
                _write_nmr(struct if prev is None else None, incar_params, output_dir, config, prev, mode="cs")

            case CalcType.NMR_EFG:
                _write_nmr(struct if prev is None else None, incar_params, output_dir, config, prev, mode="efg")

            case CalcType.NBO:
                _write_nbo(struct if prev is None else None, incar_params, output_dir, config, prev)

            case CalcType.MD_NVT | CalcType.MD_NPT:
                ensemble = "nvt" if config.calc_type == CalcType.MD_NVT else "npt"
                _write_md(struct if prev is None else None, incar_params, output_dir, config, prev, ensemble)

            case _:
                raise ValueError(f"不支持的计算类型: {config.calc_type}")

        # 7. Copy WAVECAR/CHGCAR from prev_dir (silent no-op if absent/empty).
        # 将 WAVECAR/CHGCAR 从 prev_dir 复制到输出目录（不存在或为空时静默跳过）。
        if prev is not None:
            self._copy_prev_wavecharge(prev, output_dir, config.user_incar_overrides)

        # 8. Copy vdW kernel file for functionals that require it (BEEF, BEEFVTST).
        # 为需要 vdW 核文件的泛函（BEEF、BEEFVTST）复制 vdw_kernel.bindat。
        if any(v in config.functional for v in _VDW_NEEDED):
            self._copy_vdw_kernel(output_dir)

        # 9. Generate PBS/SLURM job submission script.
        # 生成 PBS/SLURM 作业提交脚本（失败只记录警告，不影响 VASP 输入文件）。
        if generate_script:
            try:
                self.generate_script(
                    config=config,
                    output_dir=output_dir,
                    cores=cores,
                    walltime=walltime,
                )
            except Exception as e:
                logger.warning("Script generation failed (VASP inputs are unaffected): %s", e)

        logger.info(f"工作流完成，输入文件已生成至: {output_dir}")
        return str(output_dir)
    
    def generate_script(
        self,
        config: WorkflowConfig,
        output_dir: Optional[Union[str, Path]] = None,
        calc_category: Optional[CalcCategory] = None,
        cores: Optional[int] = None,
        walltime: Optional[int] = None,
        queue: Optional[str] = None,
        **script_kwargs,
    ) -> List[str]:
        """
        生成 PBS/SLURM 作业脚本。

        Args:
            config:        工作流配置
            output_dir:    脚本生成目录（默认使用 config.output_dir）
            calc_category: 计算类别，None 时由系统从 calc_type 自动推断
            cores:         核数（None 则使用类别默认值）
            walltime:      计算时间，小时（None 则使用类别默认值）
            queue:         队列名（None 则使用集群默认值）
            **script_kwargs: 额外模板变量（最高优先级）
        """
        # 1. 确保输出目录存在
        if output_dir is None:
            output_dir = config.output_dir
        if output_dir is None:
            output_dir = self.run(config)

        # 2. 若调用方未传 calc_category，从注册表直接读取
        if calc_category is None:
            calc_category = self._infer_calc_category_from_config(config)

        # 3. 渲染脚本
        return self.script_maker.render_script(
            folders=[output_dir],
            functional=config.functional,
            calc_category=calc_category,
            cores=cores,
            walltime=walltime,
            queue=queue,
            custom_context=script_kwargs if script_kwargs else None,
        )

    def _infer_calc_category_from_config(self, config: WorkflowConfig) -> CalcCategory:
        """从 CALC_TYPE_REGISTRY 直接读取 script_category，无需本地映射表。"""
        return CALC_TYPE_REGISTRY[config.calc_type].script_category


