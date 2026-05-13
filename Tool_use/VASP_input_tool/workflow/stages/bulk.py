"""
stages/bulk.py
==============
Stage classes for bulk-phase calculations.

Contains three stage classes that cover the standard bulk calculation
sequence: geometry relaxation, density-of-states, and LOBSTER bond analysis.
A shared helper ``_lobster_success`` is also defined here and re-used by
slab and adsorption lobster stages.

体相计算的阶段类。

包含覆盖标准体相计算序列的三个阶段类：几何弛豫、态密度和 LOBSTER 键分析。
此处还定义了共享辅助函数 ``_lobster_success``，供板面和吸附 lobster 阶段复用。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from .base import BaseStage, Stage
from flow.workflow.config import LOBSTER_SUCCESS_FILES, NBO_SUCCESS_FILES

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

logger = logging.getLogger(__name__)


class BulkRelaxStage(BaseStage):
    """Full geometry optimisation of the bulk structure (ISIF=3).

    Reads the initial structure from ``task_meta['structure']`` and writes
    VASP inputs for a full ionic + cell relaxation.

    体相结构的全几何优化（ISIF=3）。

    从 ``task_meta['structure']`` 读取初始结构，并写入用于全离子+晶胞弛豫的 VASP 输入文件。
    """

    # Unique stage key used in STAGE_ORDER and manifest.
    # STAGE_ORDER 和清单中使用的唯一阶段键。
    stage_name = Stage.BULK_RELAX

    # Calculation type forwarded to FrontendAdapter.
    # 转发给 FrontendAdapter 的计算类型。
    calc_type = "bulk_relax"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for bulk geometry relaxation.

        Args:
            workdir:   Pre-created directory where VASP inputs will be written.
            prev_dir:  Not used for this stage (bulk relaxation has no predecessor).
            cfg:       Full workflow configuration.
            task_meta: Must contain ``"structure"`` key with path to the input file.

        Raises:
            ValueError: if ``task_meta['structure']`` is absent or empty.

        写入体相几何弛豫的 VASP 输入文件。

        Args:
            workdir:   已预先创建的目录，VASP 输入将写入此处。
            prev_dir:  本阶段不使用（体相弛豫无前置阶段）。
            cfg:       完整的工作流配置。
            task_meta: 必须包含 ``"structure"`` 键，其值为输入文件路径。

        Raises:
            ValueError: 若 ``task_meta['structure']`` 缺失或为空。
        """
        meta = task_meta or {}
        # Require an explicit structure file path from the task manifest.
        # 要求任务清单中提供显式的结构文件路径。
        structure_file = meta.get("structure")
        if not structure_file:
            raise ValueError(
                f"BulkRelaxStage.prepare: task_meta['structure'] is required "
                f"(workdir={workdir})"
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=Path(structure_file).expanduser().resolve(),
            prev_dir=None,
            vasp_cfg=vasp_cfg,
        )


class BulkDosStage(BaseStage):
    """Non-self-consistent DOS calculation following bulk_relax.

    Reads the converged charge density from *prev_dir* and writes a
    static DOS run with an increased number of energy grid points (NEDOS).

    继 bulk_relax 之后的非自洽态密度计算。

    从 *prev_dir* 读取收敛后的电荷密度，写入带有增大能量网格点数（NEDOS）的静态 DOS 计算。
    """

    stage_name = Stage.BULK_DOS
    calc_type = "static_dos"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs for a non-self-consistent DOS calculation.

        Args:
            workdir:   Pre-created directory for VASP inputs.
            prev_dir:  Completed bulk_relax directory; provides CHGCAR and structure.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError: if *prev_dir* is None.

        写入非自洽态密度计算的 VASP 输入文件。

        Args:
            workdir:   已预先创建的 VASP 输入目录。
            prev_dir:  已完成的 bulk_relax 目录；提供 CHGCAR 和结构。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError: 若 *prev_dir* 为 None。
        """
        if prev_dir is None:
            raise ValueError(
                f"BulkDosStage.prepare: prev_dir is required (workdir={workdir})"
            )
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        # For DOS, number_of_dos becomes NEDOS in INCAR.
        # 对于 DOS 计算，number_of_dos 对应 INCAR 中的 NEDOS。
        extra: Dict[str, Any] = {}
        if vasp_cfg.number_of_dos:
            extra["NEDOS"] = vasp_cfg.number_of_dos
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=None,   # engine reads structure from prev_dir
            # 计算引擎从 prev_dir 读取结构
            prev_dir=prev_dir,
            vasp_cfg=vasp_cfg,
            extra_settings=extra,
        )


class BulkLobsterStage(BaseStage):
    """VASP single-point + LOBSTER analysis following bulk_relax.

    Copies the best available structure (CONTCAR preferred over POSCAR) from
    *prev_dir* and runs a single-point VASP calculation with wave-function
    output, then executes the LOBSTER program for chemical-bonding analysis.

    继 bulk_relax 之后的 VASP 单点 + LOBSTER 分析。

    从 *prev_dir* 复制最优可用结构（CONTCAR 优先于 POSCAR），运行含波函数输出的单点
    VASP 计算，随后执行 LOBSTER 程序进行化学键分析。
    """

    stage_name = Stage.BULK_LOBSTER
    calc_type = "lobster"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP + lobsterin inputs for LOBSTER bond analysis.

        Args:
            workdir:   Pre-created directory for VASP and lobsterin inputs.
            prev_dir:  Completed bulk_relax directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:       if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于 LOBSTER 键分析的 VASP + lobsterin 输入文件。

        Args:
            workdir:   已预先创建的 VASP 和 lobsterin 输入目录。
            prev_dir:  已完成的 bulk_relax 目录；必须在磁盘上存在。
            cfg:       完整的工作流配置。
            task_meta: 可选；本阶段不使用。

        Raises:
            ValueError:        若 *prev_dir* 为 None 或不存在。
            FileNotFoundError: 若在 *prev_dir* 中找不到 CONTCAR 或 POSCAR。
        """
        if prev_dir is None or not prev_dir.exists():
            raise ValueError(
                f"BulkLobsterStage.prepare: valid prev_dir required (workdir={workdir})"
            )
        from flow.workflow.structure.utils import get_best_structure_path
        # Prefer CONTCAR (relaxed geometry) over POSCAR (initial geometry).
        # 优先使用 CONTCAR（弛豫后的几何结构）而非 POSCAR（初始几何结构）。
        pos_src = get_best_structure_path(prev_dir)
        if not pos_src:
            raise FileNotFoundError(
                f"BulkLobsterStage: no CONTCAR/POSCAR found in {prev_dir}"
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


class BulkNboStage(BaseStage):
    """NBO analysis stage following bulk_relax.

    Selects the best available structure from *prev_dir* and writes the
    required inputs for bulk NBO analysis.

    继 bulk_relax 之后的 NBO 分析阶段。

    从 *prev_dir* 选择最优可用结构，并写入体相 NBO 分析所需输入文件。
    """

    stage_name = Stage.BULK_NBO
    calc_type = "nbo"

    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write inputs for bulk NBO analysis.

        Args:
            workdir:   Pre-created directory for NBO-stage inputs.
            prev_dir:  Completed bulk_relax directory; must exist on disk.
            cfg:       Full workflow configuration.
            task_meta: Optional; not used by this stage.

        Raises:
            ValueError:        if *prev_dir* is None or does not exist.
            FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.

        写入用于体相 NBO 分析的输入文件。
        """
        _nbo_prepare(
            stage_name=self.stage_name,
            workdir=workdir,
            prev_dir=prev_dir,
            cfg=cfg,
        )

    def check_success(self, workdir: Path, cfg: "WorkflowConfig") -> bool:
        """Return True if the bulk NBO stage completed successfully.

        Args:
            workdir: Directory containing NBO-stage output files.
            cfg:     Full workflow configuration.

        Returns:
            True if OUTCAR is clean and all required NBO output files exist.

        若体相 NBO 阶段成功完成则返回 True。
        """
        return _nbo_success(workdir, cfg)
    
# ---------------------------------------------------------------------------
# Shared lobster helpers
# ---------------------------------------------------------------------------

def _lobster_success(workdir: Path, cfg: "WorkflowConfig") -> bool:
    """Return True if VASP single-point + LOBSTER both completed successfully.

    Checks, in order:
      1. OUTCAR contains a normal-termination pattern (via ``BaseStage.outcar_ok``).
      2. ``lobsterout`` exists and is non-empty.
      3. Every file listed in ``LOBSTER_SUCCESS_FILES`` exists and is non-empty.

    Args:
        workdir: Directory containing VASP and LOBSTER output files.
        cfg:     Full workflow configuration (currently unused but kept for API
                 consistency with ``check_success``).

    Returns:
        True only if all three checks pass.

    若 VASP 单点 + LOBSTER 均成功完成则返回 True。

    依次检查：
      1. OUTCAR 包含正常结束模式（通过 ``BaseStage.outcar_ok``）。
      2. ``lobsterout`` 存在且非空。
      3. ``LOBSTER_SUCCESS_FILES`` 中列出的每个文件均存在且非空。

    Args:
        workdir: 包含 VASP 和 LOBSTER 输出文件的目录。
        cfg:     完整工作流配置（当前未使用，但为保持与 ``check_success`` 的 API 一致而保留）。

    Returns:
        仅当三项检查均通过时为 True。
    """
    if not BaseStage.outcar_ok(workdir):
        return False

    # lobsterout must exist and contain data.
    # lobsterout 必须存在且包含数据。
    lobsterout = workdir / "lobsterout"
    if not lobsterout.exists() or lobsterout.stat().st_size == 0:
        return False

    # Verify all files that LOBSTER writes on successful completion.
    # 验证 LOBSTER 成功完成后写入的所有文件。
    for fname in LOBSTER_SUCCESS_FILES:
        p = workdir / str(fname)
        if not p.exists() or p.stat().st_size == 0:
            return False

    # lobsterout must end with LOBSTER's timing summary line.
    # lobsterout 末尾必须包含 LOBSTER 的耗时汇总行。
    try:
        with lobsterout.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(size - 4_000, 0))
            tail = f.read().decode("utf-8", errors="ignore")
        if not re.search(r"finished in\s+\d+", tail):
            return False
    except OSError:
        return False

    return True


# ---------------------------------------------------------------------------
# Shared NBO helpers
# 共享 NBO 辅助函数
# ---------------------------------------------------------------------------

def _nbo_prepare(
    stage_name: str,
    workdir: Path,
    prev_dir: Optional[Path],
    cfg: "WorkflowConfig",
) -> None:
    """Write inputs for an NBO stage.

    This helper is shared by bulk, slab, and adsorption NBO stages.  It selects
    the best available structure from *prev_dir*, builds the workflow input
    configuration with ``calc_type="nbo"``, and writes the corresponding input
    files into *workdir*.

    此辅助函数供 bulk、slab 和 adsorption 的 NBO 阶段复用。它从 *prev_dir*
    中选择最优可用结构，使用 ``calc_type="nbo"`` 构建工作流输入配置，并将
    对应输入文件写入 *workdir*。

    Args:
        stage_name: Name of the current NBO stage.
        workdir:    Directory where inputs will be written.
        prev_dir:   Completed predecessor directory.
        cfg:        Full workflow configuration.

    Raises:
        ValueError:        if *prev_dir* is None or does not exist.
        FileNotFoundError: if no CONTCAR or POSCAR is found in *prev_dir*.
    """
    if prev_dir is None or not prev_dir.exists():
        raise ValueError(
            f"{stage_name}.prepare: valid prev_dir required "
            f"(workdir={workdir})"
        )

    from flow.api import FrontendAdapter
    from flow.workflow_engine import WorkflowEngine
    from flow.workflow.structure.utils import get_best_structure_path

    # Prefer CONTCAR over POSCAR as the input structure.
    # 优先使用 CONTCAR 作为输入结构。
    pos_src = get_best_structure_path(prev_dir)
    if not pos_src:
        raise FileNotFoundError(
            f"{stage_name}: no CONTCAR/POSCAR found in {prev_dir}"
        )

    vasp_cfg = cfg.get_stage_vasp(stage_name)

    # Prefer per-stage NBO config; fall back to global nbo section.
    # 优先使用阶段级 NBO 配置；否则回退到全局 NBO 配置。
    nbo_cfg = cfg.get_stage_nbo_config(stage_name)

    # NBO-stage VASP settings.
    # NBO 阶段所需的 VASP 设置。
    settings: Dict[str, Any] = dict(vasp_cfg.user_incar_settings or {})
    settings.setdefault("LWAVE", True)
    settings.setdefault("NSW", 0)
    settings.setdefault("IBRION", -1)

    params = FrontendAdapter.from_frontend_dict(
        {
            "calc_type": "nbo",
            "structure": {
                "source": "file",
                "id": str(pos_src),
            },
            "xc": vasp_cfg.functional,
            "kpoints": {
                "density": vasp_cfg.kpoints_density,
            },
            "settings": settings,
            "prev_dir": str(prev_dir),
        }
    )
    params.output_dir = workdir

    # Build WorkflowConfig and inject NBO config.
    # 构建 WorkflowConfig 并注入 NBO 配置。
    wf_config = params.to_workflow_config()
    if nbo_cfg and nbo_cfg.settings:
        wf_config.nbo_config = nbo_cfg.settings.to_dict()

    WorkflowEngine().run(wf_config, generate_script=False)

    logger.debug("%s wrote inputs to %s", stage_name, workdir)


def _nbo_success(workdir: Path, cfg: "WorkflowConfig") -> bool:
    """Return True if NBO analysis completed successfully.

    Checks, in order:
      1. OUTCAR contains a normal-termination pattern.
      2. Every file listed in ``NBO_SUCCESS_FILES`` exists and is non-empty.

    Args:
        workdir: Directory containing NBO-stage output files.
        cfg:     Full workflow configuration.

    Returns:
        True only if all checks pass.

    若 NBO 分析成功完成则返回 True。

    依次检查：
      1. OUTCAR 包含正常结束模式。
      2. ``NBO_SUCCESS_FILES`` 中列出的每个文件均存在且非空。
    """
    if not BaseStage.outcar_ok(workdir):
        return False

    for fname in NBO_SUCCESS_FILES:
        p = workdir / str(fname)
        if not p.exists() or p.stat().st_size == 0:
            return False

    return True