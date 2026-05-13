"""
stages/adsorption.py
====================
Stage classes for adsorption-phase calculations.

Contains three stage classes that handle the adsorption calculation sequence:
geometry relaxation of the adsorbed system, vibrational frequency analysis,
and LOBSTER chemical-bonding analysis.

吸附相计算的阶段类。

包含处理吸附计算序列的三个阶段类：吸附体系的几何弛豫、振动频率分析和
LOBSTER 化学键分析。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .base import BaseStage, Stage
from .bulk import _lobster_success, _nbo_prepare, _nbo_success

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

logger = logging.getLogger(__name__)


class AdsorptionStage(BaseStage):
    """Geometry optimisation of an adsorbed system (slab_relax type).

    POSCAR is placed by expand_manifest() before prepare() is called.
    Uses ``slab_relax`` calc_type so the engine applies slab-appropriate
    INCAR settings (ions relaxed, cell fixed).

    吸附体系的几何优化（slab_relax 类型）。

    prepare() 调用前，POSCAR 由 expand_manifest() 放置。
    使用 ``slab_relax`` calc_type，使引擎应用适合板面的 INCAR 设置（离子弛豫，晶胞固定）。
    """

    # Unique stage key used in STAGE_ORDER and manifest.
    # STAGE_ORDER 和清单中使用的唯一阶段键。
    stage_name = Stage.ADSORPTION

    # Uses slab_relax calc_type: ions relax, cell is fixed.
    # 使用 slab_relax 计算类型：离子弛豫，晶胞固定。
    calc_type = "slab_relax"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for adsorption geometry relaxation.

        Args:
            workdir:   Directory that must already contain a POSCAR file.
            prev_dir:  Not used for this stage.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            FileNotFoundError: if POSCAR is absent from *workdir*.

        写入吸附几何弛豫的 VASP 输入文件。

        Args:
            workdir:   必须已包含 POSCAR 文件的目录。
            prev_dir:  本阶段不使用。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            FileNotFoundError: 若 *workdir* 中不存在 POSCAR。
        """
        # POSCAR is written by expand_manifest() before this stage runs.
        # POSCAR 在本阶段运行之前已由 expand_manifest() 写入。
        poscar = workdir / "POSCAR"
        if not poscar.exists():
            raise FileNotFoundError(
                f"AdsorptionStage.prepare: POSCAR not found in {workdir}."
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=poscar,
            prev_dir=None,
            vasp_cfg=vasp_cfg,
        )


class AdsorptionFreqStage(BaseStage):
    """Frequency (vibrational) calculation following adsorption relaxation.

    Determines which atoms to vibrate from three sources (in priority order):
      1. ``freq.settings.vibrate_indices`` – explicit atom index list
      2. ``freq.settings.adsorbate_formula`` / ``task_meta['adsorbate_formula']``
      3. ``cfg.adsorption.build.molecule_formula`` – molecule used during build

    The ``vibrate_mode`` and atom selection are passed to the engine as
    extra INCAR-style settings so the engine can set selective dynamics.

    继吸附弛豫之后的频率（振动）计算。

    从三个来源（按优先级顺序）确定需要振动的原子：
      1. ``freq.settings.vibrate_indices`` – 显式原子索引列表
      2. ``freq.settings.adsorbate_formula`` / ``task_meta['adsorbate_formula']``
      3. ``cfg.adsorption.build.molecule_formula`` – 构建时使用的分子

    ``vibrate_mode`` 和原子选择以额外 INCAR 风格设置的形式传递给引擎，
    使引擎能够设置选择性动力学。
    """

    stage_name = Stage.ADSORPTION_FREQ
    calc_type = "freq"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for a vibrational frequency calculation.

        Args:
            workdir:   Pre-created directory for VASP inputs.
            prev_dir:  Completed adsorption directory; engine reads CONTCAR from here.
            cfg:       Full workflow configuration (reads ``cfg.freq`` and
                       ``cfg.adsorption`` sub-configs).
            task_meta: Optional dict that may carry ``"adsorbate_formula"``.

        Raises:
            ValueError: if *prev_dir* is None or does not exist.
            ValueError: if ``mode='inherit'`` and no adsorbate identification
                        source is available.

        写入振动频率计算的 VASP 输入文件。

        Args:
            workdir:   已预先创建的 VASP 输入目录。
            prev_dir:  已完成的 adsorption 目录；引擎从此处读取 CONTCAR。
            cfg:       完整的工作流配置（读取 ``cfg.freq`` 和 ``cfg.adsorption`` 子配置）。
            task_meta: 可选字典，可携带 ``"adsorbate_formula"``。

        Raises:
            ValueError: 若 *prev_dir* 为 None 或不存在。
            ValueError: 若 ``mode='inherit'`` 且无任何吸附物识别来源可用。
        """
        if prev_dir is None or not prev_dir.exists():
            raise ValueError(
                f"AdsorptionFreqStage.prepare: valid prev_dir is required (workdir={workdir})"
            )
        meta = task_meta or {}
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        freq_settings = cfg.freq.settings if cfg.freq else None

        # Resolve vibration mode; default to "inherit" (read from CONTCAR selective_dynamics).
        # 解析振动模式；默认为 "inherit"（从 CONTCAR 选择性动力学读取）。
        mode = freq_settings.mode if freq_settings else "inherit"
        vibrate_indices: Optional[List[int]] = (
            freq_settings.vibrate_indices if freq_settings else None
        )

        # Resolve adsorbate formula from multiple fallback sources.
        # 从多个回退来源解析吸附物化学式。
        ads_formula: Optional[str] = None
        if freq_settings:
            ads_formula = freq_settings.adsorbate_formula
        if ads_formula is None:
            # Fall back to manifest task metadata.
            # 回退到清单任务元数据。
            ads_formula = meta.get("adsorbate_formula")
        if ads_formula is None and cfg.adsorption:
            # Last resort: use the molecule formula from the adsorption build config.
            # 最后手段：使用吸附构建配置中的分子化学式。
            ads_formula = cfg.adsorption.build.molecule_formula or None
        adsorbate_prefer = freq_settings.adsorbate_formula_prefer if freq_settings else "tail"

        # Validation (preserve the original error check).
        # 验证（保留原有的错误检查逻辑）。
        if mode == "inherit" and vibrate_indices is None and ads_formula is None:
            raise ValueError(
                "adsorption_freq: mode='inherit' and no adsorbate_formula/vibrate_indices found. "
                "Set freq.settings.adsorbate_formula or vibrate_indices in params.yaml, "
                "or ensure the adsorption CONTCAR has correct selective_dynamics."
            )

        # Build extra settings dict forwarded to the engine as INCAR-like overrides.
        # 构建转发给引擎作为类 INCAR 覆盖项的额外设置字典。
        extra: Dict[str, Any] = {
            "vibrate_mode": mode,
            "adsorbate_formula_prefer": adsorbate_prefer,
        }
        if ads_formula:
            extra["adsorbate_formula"] = ads_formula
        if vibrate_indices:
            # Indices are serialised as a comma-separated string for the engine.
            # 索引序列化为逗号分隔字符串传递给引擎。
            extra["vibrate_indices"] = ",".join(str(i) for i in vibrate_indices)

        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=None,        # engine reads CONTCAR from prev_dir
            # 引擎从 prev_dir 读取 CONTCAR
            prev_dir=prev_dir,
            vasp_cfg=vasp_cfg,
            extra_settings=extra,
        )

    def check_success(self, workdir: Path, cfg: "WorkflowConfig") -> bool:
        """Return True if OUTCAR shows normal VASP termination.

        Args:
            workdir: Directory containing VASP output files.
            cfg:     Full workflow configuration (unused here).

        Returns:
            True if OUTCAR termination patterns are present.

        若 OUTCAR 显示 VASP 正常结束则返回 True。

        Args:
            workdir: 包含 VASP 输出文件的目录。
            cfg:     完整工作流配置（此处不使用）。

        Returns:
            若 OUTCAR 结束模式存在则为 True。
        """
        return self.outcar_ok(workdir)


class AdsLobsterStage(BaseStage):
    """VASP single-point + LOBSTER analysis following adsorption relaxation.

    Selects the best available structure from *prev_dir* (CONTCAR preferred)
    and writes inputs for a single-point VASP calculation with wave-function
    output, then runs LOBSTER chemical-bonding analysis on the adsorbed system.

    继吸附弛豫之后的 VASP 单点 + LOBSTER 分析。

    从 *prev_dir* 选择最优可用结构（CONTCAR 优先），写入含波函数输出的单点 VASP
    计算输入文件，随后对吸附体系运行 LOBSTER 化学键分析。
    """

    stage_name = Stage.ADSORPTION_LOBSTER
    calc_type = "lobster"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP + lobsterin inputs for LOBSTER bond analysis on the adsorbed system.

        Args:
            workdir:   Pre-created directory for VASP and lobsterin inputs.
            prev_dir:  Completed adsorption directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:        if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于吸附体系 LOBSTER 键分析的 VASP + lobsterin 输入文件。

        Args:
            workdir:   已预先创建的 VASP 和 lobsterin 输入目录。
            prev_dir:  已完成的 adsorption 目录；必须在磁盘上存在。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError:        若 *prev_dir* 为 None 或不存在。
            FileNotFoundError: 若在 *prev_dir* 中找不到 CONTCAR 或 POSCAR。
        """
        if prev_dir is None or not prev_dir.exists():
            raise ValueError(
                f"AdsLobsterStage.prepare: valid prev_dir required (workdir={workdir})"
            )
        from flow.workflow.structure.utils import get_best_structure_path
        # Prefer CONTCAR (relaxed geometry) over POSCAR (initial geometry).
        # 优先使用 CONTCAR（弛豫后的几何结构）而非 POSCAR（初始几何结构）。
        pos_src = get_best_structure_path(prev_dir)
        if not pos_src:
            raise FileNotFoundError(
                f"AdsLobsterStage: no CONTCAR/POSCAR found in {prev_dir}"
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=pos_src,
            prev_dir=prev_dir,
            vasp_cfg=vasp_cfg,
        )

    def check_success(self, workdir: Path, cfg: "WorkflowConfig") -> bool:
        """Return True if both VASP single-point and LOBSTER completed successfully.

        Args:
            workdir: Directory containing VASP and LOBSTER output files.
            cfg:     Full workflow configuration (passed to ``_lobster_success``).

        Returns:
            True if OUTCAR is clean and all required LOBSTER output files exist.

        若 VASP 单点和 LOBSTER 均成功完成则返回 True。

        Args:
            workdir: 包含 VASP 和 LOBSTER 输出文件的目录。
            cfg:     完整工作流配置（传递给 ``_lobster_success``）。

        Returns:
            若 OUTCAR 正常且所有必需的 LOBSTER 输出文件存在则为 True。
        """
        return _lobster_success(workdir, cfg)

class AdsNboStage(BaseStage):
    """NBO analysis following adsorption relaxation.

    Selects the best available structure from *prev_dir* (CONTCAR preferred)
    and writes inputs for NBO analysis on the adsorbed system.

    继吸附弛豫之后的 NBO 分析。

    从 *prev_dir* 选择最优可用结构（CONTCAR 优先），并写入吸附体系的
    NBO 分析输入文件。
    """

    stage_name = Stage.ADSORPTION_NBO
    calc_type = "nbo"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write inputs for NBO analysis on the adsorbed system.

        Args:
            workdir:   Pre-created directory for NBO inputs.
            prev_dir:  Completed adsorption directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:        if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于吸附体系 NBO 分析的输入文件。

        Args:
            workdir:   已预先创建的 NBO 输入目录。
            prev_dir:  已完成的 adsorption 目录；必须在磁盘上存在。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError:        若 *prev_dir* 为 None 或不存在。
            FileNotFoundError: 若在 *prev_dir* 中找不到 CONTCAR 或 POSCAR。
        """
        _nbo_prepare(
            stage_name=self.stage_name,
            workdir=workdir,
            prev_dir=prev_dir,
            cfg=cfg,
        )

    def check_success(self, workdir: Path, cfg: "WorkflowConfig") -> bool:
        """Return True if the NBO analysis completed successfully.

        Args:
            workdir: Directory containing VASP and NBO output files.
            cfg:     Full workflow configuration (passed to ``_nbo_success``).

        Returns:
            True if OUTCAR is clean and all required NBO output files exist.

        若 NBO 分析成功完成则返回 True。

        Args:
            workdir: 包含 VASP 和 NBO 输出文件的目录。
            cfg:     完整工作流配置（传递给 ``_nbo_success``）。

        Returns:
            若 OUTCAR 正常且所有必需的 NBO 输出文件存在则为 True。
        """
        return _nbo_success(workdir, cfg)