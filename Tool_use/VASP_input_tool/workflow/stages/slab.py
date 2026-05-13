"""
stages/slab.py
==============
Stage classes for slab-phase calculations.

Contains three stage classes mirroring the bulk sequence but operating on
slab geometries: relaxation, density-of-states, and LOBSTER analysis.
The slab POSCAR is expected to have been written into the workdir by
``expand_manifest()`` before ``prepare()`` is called.

板面相计算的阶段类。

包含与体相序列对应的三个阶段类，但针对板面几何结构：弛豫、态密度和 LOBSTER 分析。
在调用 ``prepare()`` 之前，板面 POSCAR 应已由 ``expand_manifest()`` 写入工作目录。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from .base import BaseStage, Stage
from .bulk import _lobster_success, _nbo_prepare, _nbo_success

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

logger = logging.getLogger(__name__)


class SlabRelaxStage(BaseStage):
    """Geometry optimisation of a slab (POSCAR already placed in workdir by expand_manifest).

    Reads the POSCAR written by ``expand_manifest()`` and runs a slab-type
    geometry relaxation (ions only, cell fixed).

    板面的几何优化（POSCAR 已由 expand_manifest 放置在工作目录中）。

    读取 ``expand_manifest()`` 写入的 POSCAR，执行板面类型的几何弛豫（仅离子，晶胞固定）。
    """

    # Unique stage key used in STAGE_ORDER and manifest.
    # STAGE_ORDER 和清单中使用的唯一阶段键。
    stage_name = Stage.SLAB_RELAX

    # Calculation type forwarded to FrontendAdapter.
    # 转发给 FrontendAdapter 的计算类型。
    calc_type = "slab_relax"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for slab geometry relaxation.

        Args:
            workdir:   Directory that must already contain a POSCAR file.
            prev_dir:  Not used for slab relaxation (no predecessor stage).
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            FileNotFoundError: if POSCAR is absent from *workdir*.

        写入板面几何弛豫的 VASP 输入文件。

        Args:
            workdir:   必须已包含 POSCAR 文件的目录。
            prev_dir:  板面弛豫不使用（无前置阶段）。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            FileNotFoundError: 若 *workdir* 中不存在 POSCAR。
        """
        # POSCAR must be pre-placed by expand_manifest before this call.
        # POSCAR 必须在此调用之前由 expand_manifest 预先放置。
        poscar = workdir / "POSCAR"
        if not poscar.exists():
            raise FileNotFoundError(
                f"SlabRelaxStage.prepare: POSCAR not found in {workdir}. "
                "It should have been written by expand_manifest()."
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=poscar,
            prev_dir=None,
            vasp_cfg=vasp_cfg,
        )


class SlabDosStage(BaseStage):
    """Non-self-consistent DOS calculation following slab_relax.

    Reads converged charge density from *prev_dir* and runs a static DOS
    calculation with an increased energy grid (NEDOS).

    继 slab_relax 之后的非自洽态密度计算。

    从 *prev_dir* 读取收敛后的电荷密度，运行带有增大能量网格（NEDOS）的静态 DOS 计算。
    """

    stage_name = Stage.SLAB_DOS
    calc_type = "static_dos"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for a non-self-consistent DOS calculation on a slab.

        Args:
            workdir:   Pre-created directory for VASP inputs.
            prev_dir:  Completed slab_relax directory; provides CHGCAR and structure.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError: if *prev_dir* is None.

        写入板面非自洽态密度计算的 VASP 输入文件。

        Args:
            workdir:   已预先创建的 VASP 输入目录。
            prev_dir:  已完成的 slab_relax 目录；提供 CHGCAR 和结构。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError: 若 *prev_dir* 为 None。
        """
        if prev_dir is None:
            raise ValueError(
                f"SlabDosStage.prepare: prev_dir is required (workdir={workdir})"
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        # Map number_of_dos configuration field to NEDOS INCAR tag.
        # 将 number_of_dos 配置字段映射到 NEDOS INCAR 标签。
        extra: Dict[str, Any] = {}
        if vasp_cfg.number_of_dos:
            extra["NEDOS"] = vasp_cfg.number_of_dos
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=None,
            # Engine reads structure from prev_dir.
            # 计算引擎从 prev_dir 读取结构。
            prev_dir=prev_dir,
            vasp_cfg=vasp_cfg,
            extra_settings=extra,
        )


class SlabLobsterStage(BaseStage):
    """VASP single-point + LOBSTER analysis following slab_relax.

    Selects the best available structure from *prev_dir* (CONTCAR preferred)
    and writes inputs for a single-point VASP calculation with wave-function
    output followed by LOBSTER bond analysis.

    继 slab_relax 之后的 VASP 单点 + LOBSTER 分析。

    从 *prev_dir* 选择最优可用结构（CONTCAR 优先），写入含波函数输出的单点 VASP
    计算输入文件，随后执行 LOBSTER 键分析。
    """

    stage_name = Stage.SLAB_LOBSTER
    calc_type = "lobster"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP + lobsterin inputs for LOBSTER bond analysis on a slab.

        Args:
            workdir:   Pre-created directory for VASP and lobsterin inputs.
            prev_dir:  Completed slab_relax directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:        if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于板面 LOBSTER 键分析的 VASP + lobsterin 输入文件。

        Args:
            workdir:   已预先创建的 VASP 和 lobsterin 输入目录。
            prev_dir:  已完成的 slab_relax 目录；必须在磁盘上存在。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError:        若 *prev_dir* 为 None 或不存在。
            FileNotFoundError: 若在 *prev_dir* 中找不到 CONTCAR 或 POSCAR。
        """
        if prev_dir is None or not prev_dir.exists():
            raise ValueError(
                f"SlabLobsterStage.prepare: valid prev_dir required (workdir={workdir})"
            )
        from flow.workflow.structure.utils import get_best_structure_path
        # CONTCAR (relaxed) is preferred over POSCAR (initial) as the input structure.
        # CONTCAR（弛豫后）优先于 POSCAR（初始）作为输入结构。
        pos_src = get_best_structure_path(prev_dir)
        if not pos_src:
            raise FileNotFoundError(
                f"SlabLobsterStage: no CONTCAR/POSCAR found in {prev_dir}"
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
    
class SlabNboStage(BaseStage):
    """NBO analysis following slab_relax.

    Selects the best available structure from *prev_dir* and writes inputs for
    slab NBO analysis.

    继 slab_relax 之后的 NBO 分析。

    从 *prev_dir* 选择最优可用结构，并写入板面 NBO 分析输入文件。
    """

    stage_name = Stage.SLAB_NBO
    calc_type = "nbo"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write inputs for NBO analysis on a slab.

        Args:
            workdir:   Pre-created directory for NBO inputs.
            prev_dir:  Completed slab_relax directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:        if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于板面 NBO 分析的输入文件。

        Args:
            workdir:   已预先创建的 NBO 输入目录。
            prev_dir:  已完成的 slab_relax 目录；必须在磁盘上存在。
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