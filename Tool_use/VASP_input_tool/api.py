# -*- coding: utf-8 -*-
"""
flow.api — Frontend-to-engine adapter layer
============================================

Position in the write pipeline
-------------------------------
::

    Stage.prepare()                     (flow/workflow/stages/*.py)
        └─ BaseStage._write_vasp_inputs()
               └─ FrontendAdapter.from_frontend_dict()   ← THIS FILE
                        └─ VaspWorkflowParams.to_workflow_config()
                                 └─ WorkflowEngine.run()  (flow/workflow_engine.py)
                                          └─ _write_*(config, incar_params, output_dir)
                                                   └─ InputSet.write_input()  (flow/input_sets/)
                                                            └─ POSCAR / INCAR / KPOINTS / POTCAR  (disk)

Responsibilities
----------------
1. Accept a simple ``frontend_dict`` (calc_type string, xc, kpoints density,
   user_incar_settings, prev_dir, lobsterin, …) and validate/normalise it into
   a typed ``VaspWorkflowParams`` object.
2. Convert ``VaspWorkflowParams`` to the engine's ``WorkflowConfig`` via
   ``to_workflow_config()``, mapping frontend names to ``CalcType`` enum values
   and fanning out sub-module parameters (frequency, lobster, NBO, …).

Extension points — where to touch this file
-------------------------------------------
- **New calc type**: add a member to ``CalcType`` and a ``CalcTypeEntry`` row in
  ``calc_registry.py``; add a case arm in ``WorkflowEngine.run()``.
  No changes needed here — ``calc_type_from_str()`` picks it up automatically.
- **New param group**: add a new ``XxxParams`` dataclass in ``frontend_params.py``,
  extract it in ``from_frontend_dict()``, and transfer it in ``to_workflow_config()``.
- **New lobsterin/NBO field**: extend ``LobsterParams`` / ``NBOParams`` in
  ``frontend_params.py``, extract from ``data`` in ``from_frontend_dict()``,
  and set the matching ``WorkflowConfig`` field in ``to_workflow_config()``.

本模块是前端数据字典到引擎工作流配置的适配层。

职责
----
1. 接受前端传入的简单字典（包含 calc_type 字符串、交换关联泛函、K 点密度、
   用户 INCAR 设置、前序目录、lobsterin 等），将其验证并规范化为带类型的
   ``VaspWorkflowParams`` 对象。
2. 通过 ``to_workflow_config()`` 将 ``VaspWorkflowParams`` 转换为引擎所需的
   ``WorkflowConfig``，把 calc_type 字符串通过 ``calc_type_from_str()`` 解析为
   ``CalcType`` 枚举值，并展开各子模块参数（频率、Lobster、NBO 等）。

扩展点
------
- **新计算类型**：在 ``calc_registry.py`` 的 ``CalcType`` 枚举及 ``CALC_REGISTRY``
  中添加条目，并在 ``WorkflowEngine.run()`` 中添加对应 case 分支。
  本文件无需修改，``calc_type_from_str()`` 会自动识别新类型。
- **新参数组**：在 ``frontend_params.py`` 中新增 ``XxxParams`` 数据类，在
  ``from_frontend_dict()`` 中提取，并在 ``to_workflow_config()`` 中传递。
- **新 lobsterin/NBO 字段**：在 ``frontend_params.py`` 中扩展 ``LobsterParams`` /
  ``NBOParams``，从 ``from_frontend_dict()`` 的 ``data`` 中提取，并在
  ``to_workflow_config()`` 中设置 ``WorkflowConfig`` 的对应字段。
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pymatgen.core import Structure

from .calc_registry import CalcType, calc_type_from_str, CALC_TYPE_TO_CATEGORY
from .workflow_engine import WorkflowConfig, WorkflowEngine
from .script import Script, CalcCategory
from .validator import validate as _validator_validate, ValidationError
from .frontend_params import (
    FRONTEND_XC_MAP, FRONTEND_VDW_MAP,
    StructureInput, PrecisionParams, KpointParams, MagmomParams,
    DFTPlusUParams, VdwParams, DipoleParams, FrequencyParams,
    LobsterParams, NBOParams, MDParams, NEBParams, ResourceParams,
    _parse_int, _parse_float, _parse_number, _parse_number_list, _parse_magmom_list,
)

logger = logging.getLogger(__name__)

# All FrontendXxxParams dataclasses, XC/vdW maps, and parse helpers live in
# frontend_params.py; re-exported above so existing `from flow.api import X`
# callers continue to work without modification.
# 所有 FrontendXxxParams 数据类、XC/vdW 映射及解析辅助函数均位于 frontend_params.py；
# 上方已重导出，现有的 `from flow.api import X` 调用无需修改。


# ============================================================================
# 统一API参数类
# ============================================================================

@dataclass
class VaspWorkflowParams:
    """Unified VASP workflow parameters — the complete frontend-supplied configuration.

    This dataclass is the canonical intermediate representation between the raw
    frontend dict and the engine's ``WorkflowConfig``.  All frontend parameter
    groups are collected here as typed sub-objects; ``to_workflow_config()``
    converts them to the engine format.

    Core attributes:
        calc_type:       Frontend calculation type string (resolved to
            ``CalcType`` by ``to_workflow_config()``).
        structure:       Input structure — file path, pymatgen ``Structure``,
            or ``StructureInput``.

    Optional sub-module attributes:
        precision, kpoints, magmom, dft_u, vdw, dipole, frequency,
        lobster, nbo, md, neb — each holds a typed params dataclass or ``None``.

    统一的 VASP 工作流参数——前端传入的完整配置。

    本数据类是原始前端字典与引擎 ``WorkflowConfig`` 之间的规范中间表示。
    所有前端参数组以类型化子对象形式汇聚于此；``to_workflow_config()`` 负责将其
    转换为引擎格式。

    核心属性：
        calc_type:  前端计算类型字符串（由 ``to_workflow_config()`` 解析为
            ``CalcType``）。
        structure:  输入结构——文件路径、pymatgen ``Structure`` 对象或
            ``StructureInput``。

    可选子模块属性：
        precision、kpoints、magmom、dft_u、vdw、dipole、frequency、
        lobster、nbo、md、neb——每项持有一个类型化参数数据类或 ``None``。
    """

    # === 核心参数 ===
    calc_type: str
    structure: Union[str, Path, Structure, StructureInput]

    # === 功能参数 ===
    functional: str = "PBE"
    kpoints_density: float = 50.0

    # === 可选参数 ===
    prev_dir: Optional[Union[str, Path]] = None
    output_dir: Optional[Union[str, Path]] = None

    # === 子模块参数 ===
    precision: Optional[PrecisionParams] = None
    kpoints: Optional[KpointParams] = None
    magmom: Optional[MagmomParams] = None
    dft_u: Optional[DFTPlusUParams] = None
    vdw: Optional[VdwParams] = None
    dipole: Optional[DipoleParams] = None
    frequency: Optional[FrequencyParams] = None
    lobster: Optional[LobsterParams] = None
    nbo: Optional[NBOParams] = None
    nbo_config: Optional[Dict[str, Any]] = None
    md: Optional[MDParams] = None
    neb: Optional[NEBParams] = None

    # === 资源配置 ===
    resources: Optional[ResourceParams] = None

    # === 自定义INCAR ===
    custom_incar: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        # Normalise functional to uppercase and supply default sub-objects.
        # 将泛函规范化为大写，并提供默认子对象。
        self.functional = self.functional.upper()
        if self.precision is None:
            self.precision = PrecisionParams()
        if self.kpoints is None:
            self.kpoints = KpointParams()
        if self.resources is None:
            self.resources = ResourceParams()

    def to_workflow_config(self) -> WorkflowConfig:
        """Convert this adapter object to the engine's ``WorkflowConfig``.

        Mapping rules:
        - ``calc_type`` string → ``CalcType`` enum via ``calc_type_map``
        - ``custom_incar`` + precision overrides → ``user_incar_overrides``
        - Sub-module params (frequency, lobster, NBO) set dedicated fields on
          ``WorkflowConfig`` (e.g. ``vibrate_indices``, ``lobster_overwritedict``)

        Extension: when you add a new ``FrontendXxxParams`` group, add a matching
        ``if self.xxx: config.xxx_field = ...`` block at the end of this method,
        and add the corresponding field to ``workflow_engine.WorkflowConfig``.

        将本适配器对象转换为引擎所需的 ``WorkflowConfig``。

        映射规则：
        - ``calc_type`` 字符串通过 ``calc_type_map`` 映射为 ``CalcType`` 枚举值。
        - ``custom_incar`` + 精度覆盖参数合并为 ``user_incar_overrides``。
        - 子模块参数（frequency、lobster、NBO）设置 ``WorkflowConfig`` 的专用字段
          （如 ``vibrate_indices``、``lobster_overwritedict``）。

        扩展：新增 ``FrontendXxxParams`` 参数组时，在本方法末尾添加对应的
        ``if self.xxx: config.xxx_field = ...`` 代码块，并在
        ``workflow_engine.WorkflowConfig`` 中添加相应字段。
        """

        try:
            backend_calc_type = calc_type_from_str(self.calc_type)
        except KeyError:
            raise ValueError(f"未知的计算类型: {self.calc_type}")

        # ── 构建 INCAR 覆盖参数 ────────────────────────────────────────────
        user_incar_overrides: Dict[str, Any] = {}
        if self.custom_incar:
            user_incar_overrides.update(self.custom_incar)

        if self.precision:
            prec = self.precision
            if prec.encut:  user_incar_overrides["ENCUT"]  = prec.encut
            if prec.ediff:  user_incar_overrides["EDIFF"]  = prec.ediff
            if prec.ediffg: user_incar_overrides["EDIFFG"] = prec.ediffg
            if prec.nedos:  user_incar_overrides["NEDOS"]  = prec.nedos

        # frequency
        if self.frequency and backend_calc_type in (CalcType.FREQ, CalcType.FREQ_IR):
            freq = self.frequency
            user_incar_overrides.update({
                "IBRION": freq.ibrion,
                "POTIM":  freq.potim,
                "NFREE":  freq.nfree,
            })
            if freq.calc_ir:
                user_incar_overrides["LEPSILON"] = True
                user_incar_overrides["IBRION"]   = 7

        # ── MAGMOM ────────────────────────────────────────────────────────
        if self.magmom and self.magmom.enabled:
            if self.magmom.per_atom:
                # 直接传 per-site 列表，pymatgen 原样写入 INCAR
                # Pass per-site list directly; pymatgen writes it verbatim to INCAR.
                user_incar_overrides["MAGMOM"] = [float(v) for v in self.magmom.per_atom]
            elif self.magmom.per_element:
                # 传 per-element dict，pymatgen 按结构中各元素出现顺序展开
                # Pass per-element dict; pymatgen expands by element order in the structure.
                user_incar_overrides["MAGMOM"] = {
                    k: float(v) for k, v in self.magmom.per_element.items()
                }

        # dipole
        if self.dipole and self.dipole.enabled:
            user_incar_overrides.update({
                "IDIPOL": self.dipole.direction,
                "LDIPOL": True,
            })

        # ── DFT+U ─────────────────────────────────────────────────────────
        if self.dft_u and self.dft_u.enabled:
            dft_u_fmt = self.dft_u.to_pymatgen_format()
            if dft_u_fmt:
                user_incar_overrides["LDAUU"] = dft_u_fmt["LDAUU"]
                user_incar_overrides["LDAUL"] = dft_u_fmt["LDAUL"]
                user_incar_overrides["LDAUJ"] = dft_u_fmt["LDAUJ"]
                user_incar_overrides["LDAU"]  = True

        # MD
        if self.md and backend_calc_type in (CalcType.MD_NVT, CalcType.MD_NPT):
            user_incar_overrides.update({
                "TEBEG": self.md.start_temp,
                "TEEND": self.md.end_temp,
                "NSW":   self.md.nsteps,
            })
            if self.md.time_step:
                user_incar_overrides["POTIM"] = self.md.time_step

        # ── 构建 WorkflowConfig ───────────────────────────────────────────
        config = WorkflowConfig(
            calc_type=backend_calc_type,
            structure=self.structure,
            functional=self.functional,
            kpoints_density=self.kpoints_density,
            output_dir=self.output_dir,
            prev_dir=self.prev_dir,
            user_incar_overrides=user_incar_overrides,
        )

        if self.md:
            config.ensemble   = self.md.ensemble
            config.start_temp = self.md.start_temp
            config.end_temp   = self.md.end_temp
            config.nsteps     = self.md.nsteps
            config.time_step  = self.md.time_step

        if self.neb:
            config.n_images  = self.neb.n_images
            config.use_idpp  = self.neb.use_idpp

        if self.frequency:
            config.vibrate_indices = self.frequency.vibrate_indices
            config.calc_ir         = self.frequency.calc_ir

        if self.lobster:
            config.lobster_overwritedict   = self.lobster.overwritedict
            config.lobster_custom_lines    = self.lobster.custom_lobsterin_lines

        if self.nbo_config is not None:
            config.nbo_config = self.nbo_config

        return config

    def get_script_context(self) -> Dict[str, Any]:
        """Build the template rendering context required by the script generator.

        Returns:
            Dict with keys ``functional``, ``calc_category``, ``cores``,
            ``walltime``, ``queue``, and optionally ``need_vdw``.

        构建脚本生成器所需的模板渲染上下文。

        返回：
            包含 ``functional``、``calc_category``、``cores``、``walltime``、
            ``queue`` 以及可选 ``need_vdw`` 键的字典。
        """
        calc_category = CALC_TYPE_TO_CATEGORY.get(self.calc_type, CalcCategory.STATIC)

        res = self.resources
        context: Dict[str, Any] = {
            "functional":    self.functional,
            "calc_category": calc_category,
            "cores":         res.cores   if res else None,
            "walltime":      res.runtime if res else None,
            "queue":         res.queue   if res else None,
        }

        if self.vdw and self.vdw.method != "None":
            context["need_vdw"] = True
        return context


# ============================================================================
# API 类
# ============================================================================

class VaspAPI:
    """Unified VASP workflow API.

    Wraps ``WorkflowEngine`` and ``Script`` to provide a single entry point
    for executing a complete VASP workflow (input generation + job script
    creation) from a ``VaspWorkflowParams`` object.

    VASP 工作流统一 API。

    封装 ``WorkflowEngine`` 与 ``Script``，提供单一入口点，用于从
    ``VaspWorkflowParams`` 对象执行完整的 VASP 工作流（输入文件生成 + 作业
    脚本创建）。
    """

    def __init__(
        self,
        engine: Optional[WorkflowEngine] = None,
        script_maker: Optional[Script] = None,
    ):
        self.engine = engine or WorkflowEngine()
        self.script_maker = script_maker or Script()

    def run_workflow(
        self,
        params: VaspWorkflowParams,
        generate_script: bool = True,
    ) -> Dict[str, Any]:
        """Execute a full VASP workflow from a ``VaspWorkflowParams`` object.

        Steps:
        1. Convert *params* to ``WorkflowConfig`` and validate.
        2. Call ``WorkflowEngine.run()`` to write VASP input files.
        3. Optionally generate a PBS/SLURM job script.

        Args:
            params:          Typed workflow parameters.
            generate_script: If ``True``, also write a job submission script.

        Returns:
            Dict with keys ``success``, ``output_dir``, ``calc_type``, and
            optionally ``script_paths``.

        Raises:
            ValueError: if ``config.validate()`` returns any errors.

        从 ``VaspWorkflowParams`` 对象执行完整的 VASP 工作流。

        步骤：
        1. 将 *params* 转换为 ``WorkflowConfig`` 并验证。
        2. 调用 ``WorkflowEngine.run()`` 写出 VASP 输入文件。
        3. 可选地生成 PBS/SLURM 作业脚本。

        参数：
            params:          类型化工作流参数。
            generate_script: 若为 ``True``，同时写出作业提交脚本。

        返回：
            包含 ``success``、``output_dir``、``calc_type`` 以及可选
            ``script_paths`` 键的字典。

        抛出：
            ValueError: 若 ``config.validate()`` 返回任何错误。
        """
        logger.info(f"开始执行工作流: calc_type={params.calc_type}")

        config = params.to_workflow_config()
        output_dir = self.engine.run(config, generate_script=generate_script)
        result = {
            "success":    True,
            "output_dir": output_dir,
            "calc_type":  params.calc_type,
        }

        logger.info(f"工作流执行完成: {output_dir}")
        return result

    def validate_params(self, params: VaspWorkflowParams) -> List[str]:
        """Validate a ``VaspWorkflowParams`` object without executing the workflow.

        Delegates all checks to ``validator.validate()``.  Returns the error list
        rather than raising, preserving the ``List[str]`` contract for callers.

        Args:
            params: Workflow parameters to validate.

        Returns:
            List of human-readable error strings (empty if valid).

        将所有检查委托给 ``validator.validate()``，以 ``List[str]`` 形式返回错误，
        而非抛出异常，保持调用方兼容性。
        """
        if params is None:
            return ["VaspWorkflowParams object is None"]

        errors: List[str] = []
        try:
            _validator_validate(
                calc_type=params.calc_type,
                structure=params.structure,
                functional=params.functional,
                kpoints_density=params.kpoints_density,
                output_dir=params.output_dir,
                prev_dir=params.prev_dir,
            )
        except ValidationError as exc:
            errors.extend(exc.errors)
        return errors

    @staticmethod
    def from_json(json_str: str) -> VaspWorkflowParams:
        """Deserialise a JSON string to ``VaspWorkflowParams``.

        Delegates to ``from_dict`` after parsing.

        Args:
            json_str: JSON-encoded workflow parameter dict.

        Returns:
            Parsed ``VaspWorkflowParams`` instance.

        将 JSON 字符串反序列化为 ``VaspWorkflowParams``。

        解析后委托给 ``from_dict``。

        参数：
            json_str: JSON 编码的工作流参数字典。

        返回：
            解析后的 ``VaspWorkflowParams`` 实例。
        """
        import json
        data = json.loads(json_str)
        return VaspAPI.from_dict(data)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> VaspWorkflowParams:
        """Build a ``VaspWorkflowParams`` from a plain dict.

        If *data* contains ``"type"`` and ``"settings"`` keys it is treated as
        a frontend dict and forwarded to ``FrontendAdapter.from_frontend_dict``.
        Otherwise the direct-mapping path is used.

        Args:
            data: Workflow parameter dict (direct or frontend format).

        Returns:
            Constructed ``VaspWorkflowParams`` instance.

        从普通字典构建 ``VaspWorkflowParams``。

        若 *data* 包含 ``"type"`` 和 ``"settings"`` 键，则视为前端格式，
        转发给 ``FrontendAdapter.from_frontend_dict`` 处理；否则使用直接映射路径。

        参数：
            data: 工作流参数字典（直接格式或前端格式）。

        返回：
            构建的 ``VaspWorkflowParams`` 实例。
        """
        if "type" in data and "settings" in data:
            return FrontendAdapter.from_frontend_dict(data)

        precision = None
        if "precision" in data and data["precision"]:
            precision_data = data["precision"]
            precision = PrecisionParams(
                encut=precision_data.get("encut"), ediff=precision_data.get("ediff"),
                ediffg=precision_data.get("ediffg"), nedos=precision_data.get("nedos"),
            )

        kpoints = None
        if "kpoints" in data and data["kpoints"]:
            kpoints_data = data["kpoints"]
            kpoints = KpointParams(
                density=kpoints_data.get("density"),
                gamma_centered=kpoints_data.get("gammaCentered", True),
            )

        resources = None
        if "resource" in data and data["resource"]:
            resource_data = data["resource"]
            # Strip a trailing "h" or "H" from runtime strings like "72h".
            # 从 "72h" 等格式中去除尾部的 "h" 或 "H"。
            runtime_str = str(resource_data.get("runtime", "72"))
            runtime = int(runtime_str.rstrip("hH"))
            resources = ResourceParams(runtime=runtime, cores=resource_data.get("cores", 72))

        structure_input = None
        if "structure" in data and isinstance(data["structure"], dict):
            structure_data = data["structure"]
            structure_input = StructureInput(
                source=structure_data.get("source", "file"),
                id=structure_data.get("id", ""),
                content=structure_data.get("content", ""),
            )

        md = None
        if "md" in data and data["md"]:
            md_data = data["md"]
            md = MDParams(
                ensemble=md_data.get("ensemble", "nvt"),
                start_temp=md_data.get("TEBEG", 300),
                end_temp=md_data.get("TEEND", 300),
                nsteps=md_data.get("NSW", 1000),
                time_step=md_data.get("POTIM"),
            )

        frequency = None
        if "frequency" in data and data["frequency"]:
            freq_data = data["frequency"]
            frequency = FrequencyParams(
                ibrion=freq_data.get("IBRION", 5),
                potim=freq_data.get("POTIM", 0.015),
                nfree=freq_data.get("NFREE", 2),
                vibrate_mode=freq_data.get("vibrate_mode", "inherit"),
                adsorbate_formula=freq_data.get("adsorbate_formula"),
                calc_ir=freq_data.get("calc_ir", False),
            )

        prev_dir = None
        if "prev_dir" in data and data["prev_dir"]:
            prev_dir = data["prev_dir"]
        elif "from_prev_calc" in data and data["from_prev_calc"]:
            prev_dir = data["from_prev_calc"]

        custom_incar = data.get("custom_incar") or None

        return VaspWorkflowParams(
            calc_type=data.get("calc_type", "static_sp"),
            structure=data.get("structure", data.get("structure_id", "")),
            functional=data.get("functional", data.get("xc", "PBE")),
            kpoints_density=data.get("kpoints_density", data.get("kpoints", {}).get("density", 50)),
            prev_dir=prev_dir,
            output_dir=data.get("output_dir"),
            precision=precision,
            kpoints=kpoints,
            resources=resources,
            md=md,
            frequency=frequency,
            custom_incar=custom_incar,
        )


# ============================================================================
# 前端兼容层
# ============================================================================

class FrontendAdapter:
    """Convert a plain frontend dict into a fully typed ``VaspWorkflowParams``.

    This is the sole public entry point used by ``BaseStage._write_vasp_inputs()``.
    It normalises string calc-type names, resolves XC functional aliases, and
    unpacks every sub-module parameter group (precision, lobster, NBO, frequency,
    MAGMOM, DFT+U, …) from the flat ``settings`` dict.

    To add a new frontend parameter:
      1. Add the key to ``known_keys`` inside ``from_frontend_dict`` so it is
         excluded from ``custom_incar``.
      2. Build the matching ``FrontendXxxParams`` object and attach it to the
         returned ``VaspWorkflowParams``.
      3. Transfer it to ``WorkflowConfig`` in ``to_workflow_config()``.

    将普通前端字典转换为完全类型化的 ``VaspWorkflowParams``。

    这是 ``BaseStage._write_vasp_inputs()`` 唯一使用的公共入口点。
    它规范化 calc_type 字符串名称，解析 XC 泛函别名，并从扁平的 ``settings``
    字典中解包每个子模块参数组（precision、lobster、NBO、frequency、MAGMOM、
    DFT+U 等）。

    新增前端参数的步骤：
      1. 在 ``from_frontend_dict`` 内的 ``known_keys`` 中添加该键，使其不进入
         ``custom_incar``。
      2. 构建对应的 ``FrontendXxxParams`` 对象并附加到返回的
         ``VaspWorkflowParams`` 上。
      3. 在 ``to_workflow_config()`` 中将其传递给 ``WorkflowConfig``。
    """

    @staticmethod
    def from_frontend_dict(data: Dict[str, Any]) -> VaspWorkflowParams:
        """Build a ``VaspWorkflowParams`` from a flat frontend dict.

        Expected keys in *data*:
            calc_type   – string name, resolved via ``FRONTEND_CALC_TYPE_MAP``
            xc / functional – functional alias, resolved via ``FRONTEND_XC_MAP``
            kpoints     – ``{"density": float}``
            settings    – flat INCAR + sub-module params (NEDOS, IBRION, lobsterin_mode, …)
            structure   – ``{"source": "file", "id": "<path>"}``
            prev_dir    – predecessor calculation directory
            lobsterin   – ``Dict[str, Any]`` written to lobsterin (overwritedict)
            lobsterin_custom_lines – ``List[str]`` appended verbatim to lobsterin

        从扁平的前端字典构建 ``VaspWorkflowParams``。

        *data* 中的预期键：
            calc_type              — 字符串名称，通过 ``FRONTEND_CALC_TYPE_MAP`` 解析
            xc / functional        — 泛函别名，通过 ``FRONTEND_XC_MAP`` 解析
            kpoints                — ``{"density": float}``
            settings               — 扁平 INCAR + 子模块参数（NEDOS、IBRION、
                                     lobsterin_mode 等）
            structure              — ``{"source": "file", "id": "<path>"}``
            prev_dir               — 前序计算目录
            lobsterin              — ``Dict[str, Any]``，写入 lobsterin（overwritedict）
            lobsterin_custom_lines — ``List[str]``，逐字追加到 lobsterin
        """
        # 1. calc_type — stored as-is; resolved to CalcType enum in to_workflow_config().
        # Aliases ("relax", "dos", …) are handled by calc_type_from_str() via str_aliases.
        # calc_type 原样存储；to_workflow_config() 中通过 calc_type_from_str() 解析。
        calc_type_str = data.get("calc_type", "static_dos")

        # 2. 结构
        # Parse the structure descriptor into a StructureInput.
        # 将结构描述符解析为 StructureInput。
        struct_data = data.get("structure", {})
        if isinstance(struct_data, dict):
            structure = StructureInput(
                source=struct_data.get("source", "file"),
                id=struct_data.get("id", ""),
                content=struct_data.get("content", ""),
            )
        else:
            # Non-dict values (e.g. raw path string) are passed through unchanged.
            # 非字典值（如原始路径字符串）直接透传。
            structure = struct_data

        # 3. 泛函
        # Resolve XC alias; fall back to uppercasing the raw string.
        # 解析 XC 别名；若无匹配则将原始字符串转为大写。
        xc = data.get("xc", data.get("functional", "PBE"))
        functional = FRONTEND_XC_MAP.get(xc, xc.upper())

        # 4. settings
        settings = data.get("settings", {})

        # 4.1 精度参数
        precision = PrecisionParams(
            nedos=_parse_int(settings.get("NEDOS")),
            encut=_parse_int(settings.get("ENCUT")),
            ediff=_parse_float(settings.get("EDIFF")),
            ediffg=_parse_float(settings.get("EDIFFG")),
        )

        # 4.2 自定义 INCAR（非标准字段）
        # Collect all settings keys not in known_keys as raw INCAR overrides.
        # 将所有不在 known_keys 中的 settings 键收集为原始 INCAR 覆盖。
        custom_incar: Dict[str, Any] = {}
        known_keys = {
            "NEDOS", "ENCUT", "EDIFF", "EDIFFG",
            "ISMEAR", "SIGMA", "IBRION", "POTIM", "NFREE",
            "from_prev_calc", "lobsterin_mode", "calc_ir",
            "vibrate_mode", "adsorbate_formula", "adsorbate_formula_prefer",
            "vibrate_indices", "basis_source", "nbo_config",
            # MAGMOM / DFT+U 单独处理，不进 custom_incar
            # MAGMOM / DFT+U are handled separately and excluded from custom_incar.
            "MAGMOM", "LDAUU", "LDAUL", "LDAUJ",
        }
        for key, value in settings.items():
            if key not in known_keys and value not in (None, "", "—"):
                try:
                    # Attempt numeric parsing; fall back to raw string on failure.
                    # 尝试数值解析；失败时保留原始字符串。
                    custom_incar[key] = _parse_number(value)
                except (ValueError, TypeError):
                    custom_incar[key] = value

        # 4.3 ISMEAR / SIGMA
        # Apply smearing parameters only when explicitly provided and non-empty.
        # 仅在显式提供且非空时才应用展宽参数。
        if "ISMEAR" in settings and settings["ISMEAR"] not in (None, "", "—"):
            custom_incar["ISMEAR"] = _parse_int(settings["ISMEAR"])
        if "SIGMA" in settings and settings["SIGMA"] not in (None, "", "—"):
            custom_incar["SIGMA"] = _parse_float(settings["SIGMA"])

        # 5. kpoints
        kpt_data = data.get("kpoints", {})
        if isinstance(kpt_data, dict):
            kpoints = KpointParams(
                density=_parse_float(kpt_data.get("density")),
                gamma_centered=kpt_data.get("gammaCentered", True),
            )
        else:
            # Scalar value treated as density directly.
            # 标量值直接视为密度。
            kpoints = KpointParams(density=_parse_float(kpt_data))

        # 6. resource
        # Strip trailing "h"/"H" from runtime strings such as "72h".
        # 从 "72h" 等运行时字符串中去除尾部的 "h"/"H"。
        res_data = data.get("resource", {})
        if isinstance(res_data, dict):
            runtime_str = str(res_data.get("runtime", "72"))
            runtime = int(runtime_str.rstrip("hH"))
            resources = ResourceParams(runtime=runtime, cores=res_data.get("cores", 72))
        else:
            resources = ResourceParams()

        # 7. prev_dir
        # Prefer settings["from_prev_calc"] then top-level prev_dir / prevDir.
        # 优先使用 settings["from_prev_calc"]，其次是顶层的 prev_dir / prevDir。
        prev_dir = (
            settings.get("from_prev_calc")
            or data.get("prev_dir")
            or data.get("prevDir")
        )

        # 8. vdW
        vdw_method = data.get("vdw", "None")
        vdw = VdwParams(method=FRONTEND_VDW_MAP.get(vdw_method, vdw_method))

        # 9. 偶极校正
        dipole = DipoleParams(enabled=data.get("dipole", False))

        # 10. 频率参数
        # Frequency parameters are only constructed for frequency calc types.
        # 频率参数仅在计算类型为频率计算时构建。
        frequency = None
        if calc_type_str in ("freq", "freq_ir"):
            frequency = FrequencyParams(
                ibrion=_parse_int(settings.get("IBRION", 5)),
                potim=_parse_float(settings.get("POTIM", 0.015)),
                nfree=_parse_int(settings.get("NFREE", 2)),
                vibrate_mode=settings.get("vibrate_mode", "inherit"),
                adsorbate_formula=settings.get("adsorbate_formula"),
                adsorbate_formula_prefer=settings.get("adsorbate_formula_prefer", "tail"),
                calc_ir=settings.get("calc_ir", False),
            )
            if "vibrate_indices" in settings and settings["vibrate_indices"]:
                try:
                    # Parse comma-separated index string to integer list.
                    # 将逗号分隔的索引字符串解析为整数列表。
                    frequency.vibrate_indices = [
                        int(x.strip())
                        for x in str(settings["vibrate_indices"]).split(",")
                    ]
                except ValueError:
                    pass

        # 11. Lobster
        lobster = None
        if calc_type_str == "lobster":
            lobster = LobsterParams(
                lobsterin_mode=settings.get("lobsterin_mode", "template"),
                overwritedict=data.get("lobsterin") or None,
                custom_lobsterin_lines=data.get("lobsterin_custom_lines") or None,
            )

        # 12. NBO
        nbo = None
        if calc_type_str == "nbo":
            nbo_config = settings.get("nbo_config", {})
            nbo = NBOParams(
                basis_source="ANO-RCC-MB" if settings.get("basis_source") == "default" else "custom",
                custom_basis_path=settings.get("nboBasisPath"),
                occ_1c=_parse_float(nbo_config.get("occ_1c", 1.60)),
                occ_2c=_parse_float(nbo_config.get("occ_2c", 1.85)),
                print_cube=nbo_config.get("print_cube", "F"),
                density=nbo_config.get("density", "F"),
                vis_start=_parse_int(nbo_config.get("vis_start", 0)),
                vis_end=_parse_int(nbo_config.get("vis_end", -1)),
                mesh=nbo_config.get("mesh", [0, 0, 0]) if isinstance(nbo_config.get("mesh"), list) else [0, 0, 0],
                box_int=nbo_config.get("box_int", [1, 1, 1]) if isinstance(nbo_config.get("box_int"), list) else [1, 1, 1],
                origin_fact=_parse_float(nbo_config.get("origin_fact", 0.00)),
            )

        # ── 13. MAGMOM ────────────────────────────────────────────────────
        # 前端可通过两种方式传入：
        #   a) settings["MAGMOM"] = [5.0, 5.0, 3.0]     per-atom 列表
        #   b) settings["MAGMOM"] = "5.0 5.0 3.0"       空格分隔字符串
        #   c) settings["MAGMOM"] = {"Fe": 5.0, "Co": 3.0}  per-element dict
        # The frontend may supply MAGMOM in three forms:
        #   a) List[float]        — per-atom order
        #   b) space-delimited str — per-atom order
        #   c) Dict[str, float]   — per-element mapping
        magmom = None
        raw_magmom = settings.get("MAGMOM")
        if raw_magmom is not None:
            magmom = MagmomParams(enabled=True)
            if isinstance(raw_magmom, dict):
                # per-element dict
                magmom.per_element = {k: float(v) for k, v in raw_magmom.items()}
            else:
                # per-atom 列表或字符串
                # Per-atom list or space-delimited string.
                magmom.per_atom = _parse_magmom_list(raw_magmom)

        # ── 14. DFT+U ─────────────────────────────────────────────────────
        # 前端传入格式（推荐，按元素顺序）：
        #   settings["LDAUU"] = {"Fe": 4.0, "Co": 3.0}
        #   settings["LDAUL"] = {"Fe": 2,   "Co": 2}
        #   settings["LDAUJ"] = {"Fe": 0.0, "Co": 0.0}
        # 或旧格式（空格字符串，需配合元素列表）：
        #   settings["LDAUU"] = "4.0 3.0"  +  settings["elements"] = ["Fe", "Co"]
        # Recommended frontend format (per-element dicts):
        #   settings["LDAUU"] = {"Fe": 4.0, "Co": 3.0}
        #   settings["LDAUL"] = {"Fe": 2,   "Co": 2}
        #   settings["LDAUJ"] = {"Fe": 0.0, "Co": 0.0}
        # Legacy format (space-separated strings + elements list):
        #   settings["LDAUU"] = "4.0 3.0"  +  settings["elements"] = ["Fe", "Co"]
        dft_u = None
        raw_ldauu = settings.get("LDAUU")
        raw_ldaul = settings.get("LDAUL")
        raw_ldauj = settings.get("LDAUJ")

        if raw_ldauu is not None or raw_ldaul is not None:
            dft_u = DFTPlusUParams(enabled=True)

            if isinstance(raw_ldauu, dict):
                # ── 推荐格式：直接是 per-element dict ──────────────────────
                # Recommended format: LDAUU is already a per-element dict.
                # 推荐格式：LDAUU 已经是 per-element 字典。
                elements = list(raw_ldauu.keys())
                ldauu_dict = {k: float(v) for k, v in raw_ldauu.items()}
                ldaul_dict = (
                    {k: int(v) for k, v in raw_ldaul.items()}
                    if isinstance(raw_ldaul, dict)
                    else {e: 0 for e in elements}
                )
                ldauj_dict = (
                    {k: float(v) for k, v in raw_ldauj.items()}
                    if isinstance(raw_ldauj, dict)
                    else {e: 0.0 for e in elements}
                )
                dft_u.values = {
                    elem: {
                        "LDAUU": ldauu_dict.get(elem, 0.0),
                        "LDAUL": ldaul_dict.get(elem, 0),
                        "LDAUJ": ldauj_dict.get(elem, 0.0),
                    }
                    for elem in elements
                }

            else:
                # ── 兼容格式：空格字符串 + elements 列表 ──────────────────
                # Legacy format: space-separated string values require an explicit
                # elements list to pair with U values.
                # 兼容格式：空格分隔的字符串值需要显式 elements 列表与 U 值配对。
                elements = settings.get("elements", [])
                ldauu_vals = _parse_number_list(raw_ldauu)
                ldaul_vals = _parse_number_list(raw_ldaul)
                ldauj_vals = _parse_number_list(raw_ldauj)

                if elements and len(elements) == len(ldauu_vals):
                    dft_u.values = {
                        elem: {
                            "LDAUU": float(ldauu_vals[i]) if i < len(ldauu_vals) else 0.0,
                            "LDAUL": int(ldaul_vals[i])   if i < len(ldaul_vals)  else 0,
                            "LDAUJ": float(ldauj_vals[i]) if i < len(ldauj_vals)  else 0.0,
                        }
                        for i, elem in enumerate(elements)
                    }
                else:
                    # 无法匹配元素，禁用 DFT+U 并警告
                    # Cannot pair elements with U values; disable DFT+U and warn.
                    logger.warning(
                        "DFT+U: LDAUU 为字符串格式但未提供 settings['elements'] 列表，"
                        "或元素数量与 U 值数量不匹配，DFT+U 将被忽略。"
                        "推荐使用 dict 格式: settings['LDAUU'] = {'Fe': 4.0, 'Co': 3.0}"
                    )
                    dft_u = None

        return VaspWorkflowParams(
            calc_type=calc_type_str,
            structure=structure,
            functional=functional,
            kpoints_density=kpoints.density or 50.0,
            prev_dir=prev_dir,
            precision=precision,
            kpoints=kpoints,
            resources=resources,
            vdw=vdw,
            dipole=dipole,
            frequency=frequency,
            lobster=lobster,
            nbo=nbo,
            magmom=magmom,
            dft_u=dft_u,
            custom_incar=custom_incar if custom_incar else None,
        )


# ============================================================================
# 主入口 — generate_inputs()
# ============================================================================

def _normalise_dft_u(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Normalise user-facing DFT+U dict to the internal per-element format.

    Accepts short keys (``"U"``, ``"l"``, ``"J"``) or full VASP tag names
    (``"LDAUU"``, ``"LDAUL"``, ``"LDAUJ"``).  A plain scalar is treated as the
    U value with l=2 (d-shell) and J=0.

    Examples::

        {"Fe": {"U": 4.0, "l": 2, "J": 0.0}}   # short keys
        {"Fe": {"LDAUU": 4.0, "LDAUL": 2}}       # VASP tag names
        {"Fe": 4.0}                               # scalar shorthand
    """
    result: Dict[str, Dict[str, Any]] = {}
    for elem, spec in raw.items():
        if isinstance(spec, (int, float)):
            result[elem] = {"LDAUU": float(spec), "LDAUL": 2, "LDAUJ": 0.0}
        else:
            u = float(spec.get("U", spec.get("LDAUU", 0.0)))
            l = int(spec.get("l", spec.get("L", spec.get("LDAUL", 2))))
            j = float(spec.get("J", spec.get("LDAUJ", 0.0)))
            result[elem] = {"LDAUU": u, "LDAUL": l, "LDAUJ": j}
    return result


def generate_inputs(
    calc_type: str,
    structure: Union[str, Path] = "POSCAR",
    functional: str = "PBE",
    kpoints_density: float = 50.0,
    output_dir: Optional[Union[str, Path]] = None,
    prev_dir: Optional[Union[str, Path]] = None,
    *,
    incar: Optional[Dict[str, Any]] = None,
    magmom: Optional[Union[List[float], Dict[str, float]]] = None,
    dft_u: Optional[Dict[str, Any]] = None,
    cohp_generator: Optional[Union[str, List[str]]] = None,
    lobsterin: Optional[Dict[str, Any]] = None,
    nbo_config: Optional[Dict[str, Any]] = None,
    walltime: Optional[str] = None,
    ncores: Optional[int] = None,
    dry_run: bool = False,
) -> Union[str, Dict[str, Any]]:
    """Generate VASP input files for one calculation — the single user-facing entry point.
    为单次计算生成 VASP 输入文件——唯一面向用户的入口函数。

    All internal complexity (adapter layer, dataclasses, engine dispatch) is
    fully encapsulated.  Callers only need to supply their scientific parameters;
    no knowledge of the internal pipeline is required.
    所有内部复杂性（适配层、数据类、引擎调度）均被完全封装。
    调用方只需提供科学参数，无需了解内部流程。

    Args:
        calc_type (str): Calculation type string.  Controls which VASP input
            template and defaults are used.  Accepted values:
            ``"bulk_relax"`` — bulk structure relaxation (ISIF=3);
            ``"slab_relax"`` — surface slab relaxation (ISIF=2);
            ``"static_sp"``  — single-point energy;
            ``"static_dos"`` — single-point + projected DOS (writes CHGCAR);
            ``"static_charge"`` — single-point + full charge density;
            ``"static_elf"`` — single-point + electron localisation function;
            ``"freq"`` — vibrational frequencies (finite differences, IBRION=5);
            ``"freq_ir"`` — vibrational frequencies + IR intensities (DFPT, IBRION=7);
            ``"lobster"``    — COHP bonding analysis (writes WAVECAR);
            ``"nmr_cs"`` / ``"nmr_efg"`` — NMR chemical shift / EFG;
            ``"nbo"``        — Natural Bond Orbital analysis;
            ``"neb"``        — Nudged Elastic Band transition-state search;
            ``"dimer"``      — Dimer method saddle-point search;
            ``"md_nvt"`` / ``"md_npt"`` — molecular dynamics (NVT / NPT).
        calc_type (str): 计算类型字符串，决定使用哪套 VASP 输入模板和默认参数。
            ``"bulk_relax"`` — 体相结构弛豫（ISIF=3）；
            ``"slab_relax"`` — 表面 slab 弛豫（ISIF=2）；
            ``"static_sp"``  — 单点能；
            ``"static_dos"`` — 单点 + 投影态密度（输出 CHGCAR）；
            ``"static_charge"`` — 单点 + 全电荷密度；
            ``"static_elf"`` — 单点 + 电子局域函数；
            ``"freq"`` — 振动频率（有限差分，IBRION=5）；
            ``"freq_ir"`` — 振动频率 + 红外强度（DFPT，IBRION=7）；
            ``"lobster"``    — COHP 化学键分析（输出 WAVECAR）；
            ``"nmr_cs"`` / ``"nmr_efg"`` — NMR 化学位移 / 电场梯度；
            ``"nbo"``        — 自然键轨道分析；
            ``"neb"``        — NEB 过渡态搜索；
            ``"dimer"``      — Dimer 鞍点搜索；
            ``"md_nvt"`` / ``"md_npt"`` — 分子动力学（NVT / NPT）。

        structure (str | Path): Path to the input structure file (POSCAR, CIF,
            CONTCAR) or to a directory that contains a CONTCAR.
            Default: ``"POSCAR"`` (file in the current working directory).
        structure (str | Path): 输入结构文件（POSCAR、CIF、CONTCAR）的路径，
            或包含 CONTCAR 的目录路径。默认值：``"POSCAR"``（当前工作目录下的文件）。

        functional (str): Exchange-correlation functional label.  The functional
            controls both the pymatgen ``InputSet`` selection and the INCAR patches
            applied on top of the base settings.  Accepted values:
            ``"PBE"`` (default) — standard GGA;
            ``"RPBE"`` — revised PBE (better adsorption energies);
            ``"BEEF"`` — BEEF-vdW non-local van-der-Waals (requires
              vdw_kernel.bindat and a BEEF-patched VASP binary);
            ``"HSE"``  — HSE06 hybrid (accurate band gaps, expensive);
            ``"SCAN"`` — SCAN meta-GGA;
            ``"LDA"``  — local density approximation.
        functional (str): 交换关联泛函标签，同时控制 pymatgen ``InputSet`` 的选择
            和叠加在基础设置之上的 INCAR 补丁。接受的值：
            ``"PBE"``（默认）— 标准 GGA；
            ``"RPBE"`` — 修正 PBE（吸附能更准确）；
            ``"BEEF"`` — BEEF-vdW 非局域范德华（需要 vdw_kernel.bindat 和
              BEEF 补丁版 VASP 二进制）；
            ``"HSE"``  — HSE06 杂化泛函（能隙准确，计算代价高）；
            ``"SCAN"`` — SCAN meta-GGA；
            ``"LDA"``  — 局域密度近似。

        kpoints_density (float): Reciprocal-space k-point sampling density in
            units of Å⁻¹ (points per reciprocal-lattice length).  The actual
            k-mesh is generated automatically by pymatgen using this density.
            Default: ``50.0``.  Typical values: 50 for bulk, 25 for surfaces.
        kpoints_density (float): 倒空间 K 点采样密度（单位 Å⁻¹，即每倒格矢长度
            的网格点数）。pymatgen 据此自动生成 K 网格。默认值：``50.0``。
            典型值：体相 50，表面 25。

        output_dir (str | Path | None): Directory where the generated VASP input
            files (INCAR, KPOINTS, POSCAR, POTCAR, lobsterin, …) are written.
            When ``None`` the engine auto-generates a directory name under the
            current working directory based on the ``calc_type``.
        output_dir (str | Path | None): 生成的 VASP 输入文件（INCAR、KPOINTS、
            POSCAR、POTCAR、lobsterin 等）写入的目标目录。为 ``None`` 时，引擎
            根据 ``calc_type`` 在当前工作目录下自动生成目录名。

        prev_dir (str | Path | None): Directory of a preceding calculation.
            Enables three automatic behaviours:

            1. **Structure extraction** — when no ``structure`` file exists at
               the given path (or the default ``"POSCAR"`` is absent), the
               engine reads ``prev_dir/CONTCAR`` (if non-empty) or falls back
               to ``prev_dir/POSCAR``.

            2. **INCAR inheritance** — settings from ``prev_dir/INCAR`` become
               the base INCAR; workflow type-defaults are **not** applied on
               top so ENCUT, EDIFF, EDIFFG, … carry over automatically.
               The ``functional`` patch and any ``incar={}`` overrides are
               still applied above the inherited values.

            3. **WAVECAR/CHGCAR copy** — if ``prev_dir`` contains a non-empty
               CHGCAR the file is copied into the output directory and
               ``ICHARG=1`` is set automatically; if only a WAVECAR exists,
               it is copied and ``ISTART=1`` is set.  Both tags are
               overridable via ``incar={"ICHARG": X}``.

            Required (or auto-detected) for: ``"static_dos"``,
            ``"static_charge"``, ``"static_elf"``, ``"lobster"``, ``"nbo"``,
            ``"dimer"``.
            Example: ``prev_dir="./01-slab_relax/Fe110"``.
        prev_dir (str | Path | None): 前序计算目录。启用三项自动行为：

            1. **结构提取** — 若指定的 ``structure`` 路径（或默认 ``"POSCAR"``）
               不存在，引擎从 ``prev_dir/CONTCAR``（非空优先）或
               ``prev_dir/POSCAR`` 中读取结构。

            2. **INCAR 继承** — ``prev_dir/INCAR`` 的内容成为基础 INCAR；
               计算类型工作流默认值**不再**叠加覆盖，ENCUT、EDIFF、EDIFFG
               等参数自动延续。泛函补丁和 ``incar={}`` 覆盖项仍应用于继承值之上。

            3. **WAVECAR/CHGCAR 复制** — 若 ``prev_dir`` 包含非空 CHGCAR，
               将其复制到输出目录并自动设置 ``ICHARG=1``；若仅存在 WAVECAR，
               则复制并设置 ``ISTART=1``。两者均可通过 ``incar={"ICHARG": X}``
               覆盖。

            以下计算类型需要或可自动检测：``"static_dos"``、``"static_charge"``、
            ``"static_elf"``、``"lobster"``、``"nbo"``、``"dimer"``。
            示例：``prev_dir="./01-slab_relax/Fe110"``。

        incar (dict | None): **The single channel for all INCAR overrides.**
            Pass any VASP INCAR tag as a plain ``{"TAG": value}`` dict.
            These values are merged on top of *all* other settings
            (calc-type defaults, functional patches, DFT+U, MAGMOM) and
            therefore always win.  Any standard VASP tag is valid — there is
            no whitelist.  Default: ``None`` (use calc-type defaults only).

            Common examples::

                incar={"EDIFFG": -0.01}          # tighter force convergence
                incar={"EDIFF":  1e-7}            # tighter electronic convergence
                incar={"ENCUT":  600}             # raise plane-wave cutoff (eV)
                incar={"LREAL":  False}           # reciprocal-space projectors
                incar={"NPAR": 4, "KPAR": 2}     # parallelisation flags
                incar={"ISMEAR": 0, "SIGMA": 0.05}   # Gaussian smearing
                incar={"NSW": 300, "POTIM": 0.3}     # relax step count / size
                incar={"LORBIT": 11, "NEDOS": 3001}  # projected DOS density

        incar (dict | None): **所有 INCAR 覆盖项的唯一通道。**
            以 ``{"标记": 值}`` 字典的形式传入任意 VASP INCAR 标记。
            这些值将叠加在*所有*其他设置之上（计算类型默认值、泛函补丁、
            DFT+U、MAGMOM），因此具有最高优先级。支持所有标准 VASP 标记，
            无白名单限制。默认值：``None``（仅使用计算类型默认值）。

        magmom (list[float] | dict[str, float] | None): Initial magnetic moments
            for ISPIN=2 calculations.  Two formats are accepted:
            - ``List[float]``: per-site moments in the same order as atoms in
              the structure, e.g. ``[5.0, 5.0, 3.0, 3.0]``.
            - ``Dict[str, float]``: per-element moments; pymatgen expands the
              dict against the structure's site order automatically,
              e.g. ``{"Fe": 5.0, "Co": 3.0, "O": 0.0}``.
            Default: ``None`` (no MAGMOM tag written; pymatgen uses its own
            default if the functional requires spin polarisation).
        magmom (list[float] | dict[str, float] | None): ISPIN=2 计算的初始磁矩。
            支持两种格式：
            - ``List[float]``：按结构中原子顺序排列的 per-site 磁矩列表，
              如 ``[5.0, 5.0, 3.0, 3.0]``。
            - ``Dict[str, float]``：per-element 磁矩字典，pymatgen 会自动按
              结构位点顺序展开，如 ``{"Fe": 5.0, "Co": 3.0, "O": 0.0}``。
            默认值：``None``（不写入 MAGMOM；若泛函要求自旋极化，pymatgen
            使用自身默认值）。

        dft_u (dict | None): DFT+U (Hubbard U) parameters per element.
            ``LDAUTYPE=2`` (Dudarev simplified, U_eff = U − J) is added
            automatically.  Three equivalent input formats are accepted::

                # Recommended — short keys
                {"Fe": {"U": 4.0, "l": 2, "J": 0.0},
                 "Co": {"U": 3.0, "l": 2}}

                # VASP tag names
                {"Fe": {"LDAUU": 4.0, "LDAUL": 2, "LDAUJ": 0.0}}

                # Scalar shorthand — U value only; l=2 (d-orbital), J=0 assumed
                {"Fe": 4.0, "Co": 3.0}

            Key meanings:
            ``"U"`` / ``"LDAUU"`` — Coulomb U in eV;
            ``"l"`` / ``"LDAUL"`` — angular momentum of correlated shell
              (0=s, 1=p, 2=d, 3=f);
            ``"J"`` / ``"LDAUJ"`` — exchange J in eV (usually 0 for Dudarev).
            Default: ``None`` (DFT+U disabled).
        dft_u (dict | None): 各元素的 DFT+U（Hubbard U）参数。
            ``LDAUTYPE=2``（Dudarev 简化，U_eff = U − J）将被自动添加。
            支持三种等价格式（见英文示例）。
            键的含义：
            ``"U"`` / ``"LDAUU"`` — Coulomb U（eV）；
            ``"l"`` / ``"LDAUL"`` — 关联壳层角量子数（0=s,1=p,2=d,3=f）；
            ``"J"`` / ``"LDAUJ"`` — 交换 J（eV），Dudarev 方案通常为 0。
            默认值：``None``（禁用 DFT+U）。

        cohp_generator (str | list[str] | None): COHP bond-length range
            specification(s) passed to the lobsterin file.  Only used when
            ``calc_type="lobster"``.
            - ``str``: a single range entry written to ``cohpGenerator`` in
              the lobsterin overwrite dict,
              e.g. ``"from 1.5 to 1.9 orbitalwise"``.
            - ``List[str]``: multiple entries.  The **first** entry replaces
              the pymatgen-generated ``cohpGenerator`` default; each subsequent
              entry is appended as a raw ``cohpGenerator …`` line at the end
              of the lobsterin file.
            Default: ``None`` (pymatgen generates a default cohpGenerator
            from the structure's shortest bond lengths).
        cohp_generator (str | list[str] | None): 写入 lobsterin 文件的 COHP
            键长范围规格。仅在 ``calc_type="lobster"`` 时生效。
            - ``str``：单条范围，写入 lobsterin 的 ``cohpGenerator`` 覆盖字典，
              如 ``"from 1.5 to 1.9 orbitalwise"``。
            - ``List[str]``：多条范围。**第一条**替换 pymatgen 生成的默认
              ``cohpGenerator``；其余各条作为 ``cohpGenerator …`` 原始行
              追加到 lobsterin 文件末尾。
            默认值：``None``（由 pymatgen 根据结构中最短键长自动生成）。

        lobsterin (dict | None): Additional key-value pairs written directly
            to the lobsterin overwrite dict, complementing ``cohp_generator``.
            Only used when ``calc_type="lobster"``.
            Example: ``{"COHPstartEnergy": -20.0, "COHPendEnergy": 20.0}``.
            Default: ``None``.
        lobsterin (dict | None): 直接写入 lobsterin 覆盖字典的额外键值对，
            与 ``cohp_generator`` 配合使用。仅在 ``calc_type="lobster"`` 时生效。
            示例：``{"COHPstartEnergy": -20.0, "COHPendEnergy": 20.0}``。
            默认值：``None``。

        nbo_config (dict | None): NBO analysis configuration passed directly to
            the NBO input-set builder.  Only used when ``calc_type="nbo"``.
            Supported keys:

            ``"occ_1c"`` (bool) — enable one-centre NBO occupancy analysis;
            ``"occ_2c"`` (bool) — enable two-centre NBO occupancy analysis;
            ``"basis_source"`` (str) — path or identifier for the NBO basis
              set, e.g. ``"ANO-RCC-MB"`` or a path to a custom basis file;
            ``"nbo_keywords"`` (list[str]) — additional raw NBO keyword strings
              appended verbatim to the NBO input file.

            Example::

                nbo_config={
                    "occ_1c":       True,                 # enable 1-centre occupancy / 启用单中心占据
                    "occ_2c":       True,                 # enable 2-centre occupancy / 启用双中心占据
                    "basis_source": "ANO-RCC-MB",         # basis set identifier / 基组标识符
                    "nbo_keywords": ["$NBO BNDIDX $END"], # extra NBO keywords / 额外 NBO 关键字
                }

            Default: ``None`` (NBO input set built with defaults only).
        nbo_config (dict | None): NBO 分析配置，直接传递给 NBO 输入集构造函数。
            仅在 ``calc_type="nbo"`` 时生效。支持的键：

            ``"occ_1c"`` (bool) — 启用单中心 NBO 占据分析；
            ``"occ_2c"`` (bool) — 启用双中心 NBO 占据分析；
            ``"basis_source"`` (str) — NBO 基组路径或标识符，
              如 ``"ANO-RCC-MB"`` 或自定义基组文件路径；
            ``"nbo_keywords"`` (list[str]) — 逐字追加到 NBO 输入文件末尾的
              额外原始 NBO 关键字字符串列表。

            默认值：``None``（使用默认参数构建 NBO 输入集）。

        walltime (str | None): Wall-clock time limit for the PBS submission
            script in ``"HH:MM:SS"`` format, e.g. ``"48:00:00"``.
            ``None`` → automatically chosen per calc_type
            (e.g. ``"124:00:00"`` for relaxations, ``"48:00:00"`` for statics).
        walltime (str | None): PBS 提交脚本的墙钟时间限制，格式为 ``"HH:MM:SS"``，
            如 ``"48:00:00"``。``None`` → 按计算类型自动选择
            （如弛豫默认 ``"124:00:00"``，静态计算默认 ``"48:00:00"``）。

        ncores (int | None): Number of CPU cores for the PBS submission script.
            ``None`` → automatically chosen per calc_type (default: 72).
        ncores (int | None): PBS 提交脚本的 CPU 核数。``None`` → 按计算类型自动
            选择（默认值：72）。

        dry_run (bool): When ``True``, return a configuration preview dict
            **without writing any files**.  Safe to call with a non-existent
            structure path — useful for inspecting or testing parameter
            combinations before a real run.  The returned dict contains:
            ``"incar"`` — merged INCAR key-value pairs (``dict``);
            ``"calc_type"`` — resolved CalcType enum value string;
            ``"functional"`` — uppercased functional string;
            ``"kpoints_density"`` — k-point density (``float``);
            ``"lobsterin"`` — lobsterin overwrite dict (Lobster only, if set);
            ``"lobsterin_custom_lines"`` — extra raw lobsterin lines (if set).
            Default: ``False``.
        dry_run (bool): 为 ``True`` 时，**不写入任何文件**，直接返回配置预览字典。
            允许传入不存在的结构路径——适用于在正式运行前检查或测试参数组合。
            返回字典包含：
            ``"incar"`` — 合并后的 INCAR 键值对（``dict``）；
            ``"calc_type"`` — 解析后的 CalcType 枚举值字符串；
            ``"functional"`` — 大写泛函字符串；
            ``"kpoints_density"`` — K 点密度（``float``）；
            ``"lobsterin"`` — lobsterin 覆盖字典（仅 Lobster，若已设置）；
            ``"lobsterin_custom_lines"`` — 额外的 lobsterin 原始行（若已设置）。
            默认值：``False``。

    Returns:
        str: ``dry_run=False`` (default) — absolute path to the output
        directory containing the generated VASP input files.
        str: ``dry_run=False``（默认）— 包含生成的 VASP 输入文件的输出目录绝对路径。

        dict: ``dry_run=True`` — configuration preview dict (see ``dry_run``
        parameter above for the key listing).
        dict: ``dry_run=True`` — 配置预览字典（键列表见上方 ``dry_run`` 参数说明）。

    Examples::

        from flow.api import generate_inputs

        # 1. Standard PBE bulk relaxation — minimal call
        #    标准 PBE 体相弛豫——最简调用
        out = generate_inputs("bulk_relax", "POSCAR")

        # 2. Custom INCAR settings — any VASP tag via incar=
        #    自定义 INCAR 设置——通过 incar= 传入任意 VASP 标记
        out = generate_inputs(
            "slab_relax", "POSCAR",
            incar={"EDIFFG": -0.01, "ENCUT": 600, "NPAR": 4, "LREAL": False},
        )

        # 3. BEEF functional with DFT+U (Dudarev, short-key format)
        #    BEEF 泛函 + DFT+U（Dudarev，短键格式）
        out = generate_inputs(
            "bulk_relax", "Fe_bulk/POSCAR", functional="BEEF",
            dft_u={"Fe": {"U": 4.0, "l": 2}, "Co": {"U": 3.0, "l": 2}},
            magmom={"Fe": 5.0, "Co": 3.0},
        )

        # 4. Lobster with multiple element-specific COHP ranges
        #    带多条元素专属 COHP 范围的 Lobster 计算
        out = generate_inputs(
            "lobster", "POSCAR", prev_dir="./relax",
            cohp_generator=[
                "from 1.5 to 2.2 type Pt type C orbitalwise",
                "from 1.5 to 2.1 type Pt type O orbitalwise",
            ],
            lobsterin={"COHPstartEnergy": -20.0, "COHPendEnergy": 20.0},
        )

        # 5. Dry run — inspect merged INCAR without writing files
        #    Dry run——在不写文件的情况下检查合并后的 INCAR
        preview = generate_inputs("bulk_relax", "POSCAR", dry_run=True)
        print(preview["incar"]["IBRION"])   # → 2
        print(preview["incar"]["ENCUT"])    # → 520
    """
    # ── 0. Validate all parameters before any transformation or file I/O ───
    _validator_validate(
        calc_type=calc_type,
        structure=structure,
        functional=functional,
        kpoints_density=kpoints_density,
        output_dir=output_dir,
        prev_dir=prev_dir,
        incar=incar,
        magmom=magmom,
        dft_u=dft_u,
        walltime=walltime,
        ncores=ncores,
        dry_run=dry_run,
        # calc_type-specific params forwarded for cross-field warning checks
        lobsterin=lobsterin,
        cohp_generator=cohp_generator,
        nbo_config=nbo_config,
    )

    # ── 1. Build extra INCAR dict; DFT+U adds LDAUTYPE=2 automatically ────
    extra_incar: Dict[str, Any] = dict(incar or {})

    dft_u_params: Optional[DFTPlusUParams] = None
    if dft_u:
        dft_u_params = DFTPlusUParams(
            enabled=True,
            values=_normalise_dft_u(dft_u),
        )
        extra_incar.setdefault("LDAUTYPE", 2)

    # ── 2. MAGMOM — accept list (per-site) or dict (per-element) ──────────
    magmom_params: Optional[MagmomParams] = None
    if magmom is not None:
        if isinstance(magmom, list):
            magmom_params = MagmomParams(
                enabled=True,
                per_atom=[float(v) for v in magmom],
            )
        else:
            magmom_params = MagmomParams(
                enabled=True,
                per_element={k: float(v) for k, v in magmom.items()},
            )

    # ── 3. Lobster — build overwritedict and custom lines from cohp_generator
    lobster_params: Optional[LobsterParams] = None
    if calc_type == "lobster":
        overwrite: Dict[str, Any] = dict(lobsterin or {})
        custom_lines: Optional[List[str]] = None
        if cohp_generator is not None:
            if isinstance(cohp_generator, str):
                overwrite["cohpGenerator"] = cohp_generator
            else:
                gen_list = list(cohp_generator)
                if gen_list:
                    overwrite["cohpGenerator"] = gen_list[0]
                    if len(gen_list) > 1:
                        custom_lines = [f"cohpGenerator {g}" for g in gen_list[1:]]
        lobster_params = LobsterParams(
            overwritedict=overwrite if overwrite else None,
            custom_lobsterin_lines=custom_lines,
        )

    # ── 3b. NBO config — pass raw dict through to WorkflowConfig.nbo_config ─
    nbo_config_params: Optional[Dict[str, Any]] = dict(nbo_config) if nbo_config else None

    # ── 4. Assemble VaspWorkflowParams ─────────────────────────────────────
    params = VaspWorkflowParams(
        calc_type=calc_type,
        structure=structure,
        functional=functional,
        kpoints_density=kpoints_density,
        output_dir=output_dir,
        prev_dir=prev_dir,
        magmom=magmom_params,
        dft_u=dft_u_params,
        lobster=lobster_params,
        nbo_config=nbo_config_params,
        custom_incar=extra_incar if extra_incar else None,
    )

    # ── 5. Dry run: return preview dict without any file I/O ───────────────
    if dry_run:
        from .script_writer import ScriptWriter as _SW
        config = params.to_workflow_config()
        engine = WorkflowEngine()
        incar_dict = engine._get_incar_params(config)
        preview: Dict[str, Any] = {
            "incar":           incar_dict,
            "calc_type":       config.calc_type.value,
            "functional":      config.functional,
            "kpoints_density": config.kpoints_density,
        }
        if config.lobster_overwritedict:
            preview["lobsterin"] = dict(config.lobster_overwritedict)
        if config.lobster_custom_lines:
            preview["lobsterin_custom_lines"] = list(config.lobster_custom_lines)

        # 1. INCAR preview — printed first
        if incar_dict:
            width = max(len(k) for k in incar_dict) + 1
            print("[dry_run] INCAR preview:")
            for k in sorted(incar_dict):
                print(f"  {k:<{width}}: {incar_dict[k]}")
            print()

        # 2. Script PBS directives — printed last
        _SW().write(
            output_dir=Path(output_dir or f"calc_{calc_type}"),
            calc_type=calc_type,
            functional=functional,
            walltime=walltime,
            ncores=ncores,
            dry_run=True,
        )
        return preview

    # ── 6. Write VASP inputs and PBS/SLURM script ─────────────────────────
    config = params.to_workflow_config()
    out_dir_str = WorkflowEngine().run(
        config,
        generate_script=True,
        cores=ncores,
        walltime=int(walltime.split(":")[0]) if walltime else None,
    )

    return out_dir_str
