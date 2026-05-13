"""
config.py
=========
Typed dataclasses for params.yaml and the ``load_config()`` entry point.

All path fields are resolved to absolute ``Path`` objects at load time.
Required fields that are missing or empty raise ``ValueError`` with a clear
message so misconfigured runs fail fast at startup.

此模块为 params.yaml 提供类型化数据类，以及 ``load_config()`` 入口函数。
所有路径字段在加载时解析为绝对 ``Path`` 对象。
缺失或为空的必填字段将抛出 ``ValueError``，确保配置错误在启动时即被发现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml


# ---------------------------------------------------------------------------
# Success marker files for post-run checks
# 运行完成后的成功标记文件
# ---------------------------------------------------------------------------

# Files whose presence signals a successful Lobster run.
# 存在这些文件表示 Lobster 运行成功。
LOBSTER_SUCCESS_FILES: List[str] = ["ICOHPLIST.lobster"]

# Files whose presence signals a successful NBO run.
# 存在这些文件表示 NBO 运行成功。
NBO_SUCCESS_FILES: List[str] = ["nboout"]


# ---------------------------------------------------------------------------
# Config dataclasses
# 配置数据类
# ---------------------------------------------------------------------------

@dataclass
class ProjectConfig:
    """Filesystem paths for the project and run roots.

    Holds the top-level directory layout required by all workflow stages.

    存储项目及运行根目录的文件系统路径。
    包含所有工作流阶段所需的顶级目录结构。
    """
    # Absolute path to the project root directory.
    # 项目根目录的绝对路径。
    project_root: Path

    # Absolute path where per-task run directories are created.
    # 每个任务运行目录的创建位置（绝对路径）。
    run_root: Path

    # Optional directory containing PBS/Jinja2 template files.
    # 可选的 PBS/Jinja2 模板文件目录。
    templates_dir: Optional[Path] = None


@dataclass
class PbsConfig:
    """PBS/Torque scheduler submission parameters.

    Controls queue selection, resource allocation, and the job script template.
    ``nodes`` is intentionally omitted: the template hard-wires ``nodes=1``.

    PBS/Torque 调度器的提交参数。
    控制队列选择、资源分配以及作业脚本模板。
    ``nodes`` 已移除：模板中固定写 ``nodes=1``。
    """
    # Name of the PBS queue to which jobs are submitted.
    # 提交作业的 PBS 队列名称。
    queue: str

    # Number of processors per node (ppn).
    # 每个节点的处理器数量（ppn）。
    ppn: int

    # Maximum wall-clock time allowed per job (HH:MM:SS format).
    # 每个作业允许的最大挂钟时间（格式：HH:MM:SS）。
    walltime: str

    # String prefix prepended to every submitted job name.
    # 附加到每个提交作业名称前的字符串前缀。
    job_name_prefix: str

    # Absolute path to the Jinja2 PBS script template file.
    # Jinja2 PBS 脚本模板文件的绝对路径。
    template_file: Path


@dataclass
class PythonRuntimeConfig:
    """Python / conda environment settings used inside job scripts.

    Specifies how the scheduler script activates the correct conda environment.

    作业脚本中使用的 Python/conda 环境设置。
    指定调度脚本如何激活正确的 conda 环境。
    """
    # Absolute path to the conda shell initialisation script (conda.sh).
    # conda shell 初始化脚本（conda.sh）的绝对路径。
    conda_sh: str

    # Name of the conda environment to activate.
    # 要激活的 conda 环境名称。
    conda_env: str

    # Path or name of the python binary inside the activated environment.
    # 激活环境中 python 二进制文件的路径或名称。
    python_bin: str


@dataclass
class StageVaspConfig:
    """VASP input parameters for a single workflow stage.

    Stores the DFT functional, k-point density, INCAR overrides, and optional
    Lobster bond-analysis settings for one named stage (e.g. bulk_relax).

    Args:
        functional:          XC functional label recognised by pymatgen (e.g. "PBE").
        kpoints_density:     Reciprocal-space density for automatic k-mesh generation.
        user_incar_settings: Key-value pairs that override the default INCAR.
        is_metal:            When True, applies metallic smearing settings.
        auto_dipole:         When True, enables automatic dipole correction.
        number_of_dos:       NEDOS grid points for DOS calculations (bulk_dos / slab_dos).
        lobsterin_settings:  Extra key-value pairs written into the lobsterin file.

    单个工作流阶段的 VASP 输入参数。
    存储一个命名阶段（如 bulk_relax）的 DFT 泛函、k 点密度、INCAR 覆盖值
    以及可选的 Lobster 键分析设置。

    参数：
        functional:          pymatgen 识别的交换相关泛函标签（如 "PBE"）。
        kpoints_density:     自动 k 网格生成的倒空间密度。
        user_incar_settings: 覆盖默认 INCAR 的键值对。
        is_metal:            为 True 时启用金属展宽设置。
        auto_dipole:         为 True 时启用自动偶极修正。
        number_of_dos:       DOS 计算的 NEDOS 网格点数（bulk_dos/slab_dos）。
        lobsterin_settings:  写入 lobsterin 文件的额外键值对。
    """
    functional: str = "PBE"
    kpoints_density: int = 50
    user_incar_settings: Dict[str, Any] = field(default_factory=dict)
    is_metal: bool = False
    auto_dipole: bool = False
    number_of_dos: Optional[int] = None        # bulk_dos / slab_dos nedos
    lobsterin_settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LobsterConfig:
    """Top-level Lobster section parsed from params.yaml.

    Bundles the enabled flag with the single-point VASP config that precedes
    the Lobster charge-analysis run.

    Args:
        enabled:           Whether the Lobster stage is active for this run.
        vasp_singlepoint:  VASP settings for the wavefunction single-point calculation.

    从 params.yaml 解析的 Lobster 顶层配置节。
    将启用标志与 Lobster 电荷分析运行前的单点 VASP 配置绑定在一起。

    参数：
        enabled:           当前运行是否启用 Lobster 阶段。
        vasp_singlepoint:  波函数单点计算的 VASP 设置。
    """
    # Flag controlling whether Lobster analysis runs for this workflow.
    # 控制当前工作流是否运行 Lobster 分析的标志。
    enabled: bool

    # VASP single-point calculation settings that feed Lobster.
    # 向 Lobster 提供输入的 VASP 单点计算设置。
    vasp_singlepoint: StageVaspConfig


@dataclass
class NboSettingsConfig:
    """NBO program input parameters.

    Controls basis set selection, occupancy thresholds, cube-file output,
    and visualisation mesh for the NBO7 run.

    Args:
        basis_source:      Source of the basis set ("ANO-RCC-MB" or "custom").
        custom_basis_path: Path to a custom basis file when basis_source is "custom".
        occ_1c:            One-centre occupancy threshold for NBO search.
        occ_2c:            Two-centre occupancy threshold for NBO search.
        print_cube:        "T"/"F" flag to enable cube-file generation.
        density:           "T"/"F" flag to write density cube files.
        vis_start:         First orbital index for visualisation.
        vis_end:           Last orbital index for visualisation (-1 means last orbital).
        mesh:              Grid dimensions [nx, ny, nz] for cube files.
        box_int:           Box extension integers [bx, by, bz] around the molecule.
        origin_fact:       Fractional shift applied to the cube-file origin.

    NBO 程序的输入参数。
    控制基组选择、占据阈值、cube 文件输出以及 NBO7 运行的可视化网格。

    参数：
        basis_source:      基组来源（"ANO-RCC-MB" 或 "custom"）。
        custom_basis_path: basis_source 为 "custom" 时的自定义基组文件路径。
        occ_1c:            NBO 搜索的单中心占据阈值。
        occ_2c:            NBO 搜索的双中心占据阈值。
        print_cube:        控制是否生成 cube 文件的 "T"/"F" 标志。
        density:           控制是否写入密度 cube 文件的 "T"/"F" 标志。
        vis_start:         可视化的起始轨道索引。
        vis_end:           可视化的结束轨道索引（-1 表示最后一个轨道）。
        mesh:              cube 文件的网格维度 [nx, ny, nz]。
        box_int:           分子周围盒子扩展整数 [bx, by, bz]。
        origin_fact:       应用于 cube 文件原点的分数位移。
    """
    basis_source: str = "ANO-RCC-MB"   # "ANO-RCC-MB" or "custom"
    custom_basis_path: Optional[str] = None
    occ_1c: float = 1.60
    occ_2c: float = 1.85
    print_cube: str = "F"
    density: str = "F"
    vis_start: int = 0
    vis_end: int = -1
    mesh: List[int] = field(default_factory=lambda: [0, 0, 0])
    box_int: List[int] = field(default_factory=lambda: [1, 1, 1])
    origin_fact: float = 0.00

    def to_dict(self) -> Dict[str, Any]:
        """Return the dict that WorkflowConfig.nbo_config expects.

        Serialises all NBO settings into a plain dictionary suitable for
        downstream template rendering or JSON serialisation.

        Returns:
            Dict mapping each NBO setting name to its current value.

        返回 WorkflowConfig.nbo_config 所期望的字典。
        将所有 NBO 设置序列化为适合下游模板渲染或 JSON 序列化的普通字典。

        返回：
            将每个 NBO 设置名称映射到其当前值的字典。
        """
        return {
            "basis_source":      self.basis_source,
            "custom_basis_path": self.custom_basis_path,
            "occ_1c":            self.occ_1c,
            "occ_2c":            self.occ_2c,
            "print_cube":        self.print_cube,
            "density":           self.density,
            "vis_start":         self.vis_start,
            "vis_end":           self.vis_end,
            "mesh":              list(self.mesh),
            "box_int":           list(self.box_int),
            "origin_fact":       self.origin_fact,
        }


@dataclass
class NboConfig:
    """Top-level NBO section from params.yaml.

    Bundles the enabled flag, single-point VASP settings, and detailed NBO
    program settings for the NBO7 analysis stage.

    Args:
        enabled:          Whether the NBO stage is active for this run.
        vasp_singlepoint: VASP settings for the wavefunction single-point calculation.
        settings:         Detailed NBO program input parameters.

    来自 params.yaml 的 NBO 顶层配置节。
    将启用标志、单点 VASP 设置以及 NBO7 分析阶段的详细程序设置绑定在一起。

    参数：
        enabled:          当前运行是否启用 NBO 阶段。
        vasp_singlepoint: 波函数单点计算的 VASP 设置。
        settings:         详细的 NBO 程序输入参数。
    """
    # Flag controlling whether the NBO stage runs.
    # 控制 NBO 阶段是否运行的标志。
    enabled: bool

    # VASP single-point settings that generate the wavefunction for NBO.
    # 为 NBO 生成波函数的 VASP 单点设置。
    vasp_singlepoint: StageVaspConfig

    # Detailed NBO7 program parameters.
    # 详细的 NBO7 程序参数。
    settings: NboSettingsConfig


@dataclass
class SlabGenConfig:
    """Parameters controlling pymatgen slab generation.

    All numeric defaults match common surface-science conventions.

    控制 pymatgen 表面板层生成的参数。
    所有数值默认值与常见表面科学惯例一致。
    """
    # Number of atomic layers to target in the generated slab.
    # 生成板层中目标原子层数。
    target_layers: int

    # Vacuum thickness in Angstroms added above and below the slab.
    # 在板层上下添加的真空层厚度（埃）。
    vacuum_thickness: float = 15.0

    # Number of layers fixed at the bottom of the slab.
    # 板层底部固定的层数。
    fix_bottom_layers: int = 0

    # Number of layers fixed at the top of the slab.
    # 板层顶部固定的层数。
    fix_top_layers: int = 0

    # When True, all atoms in the slab are fixed (overrides per-layer fixes).
    # 为 True 时，板层中所有原子均被固定（覆盖逐层固定设置）。
    all_fix: bool = False

    # When True, the slab is generated with inversion symmetry.
    # 为 True 时，生成具有反演对称性的板层。
    symmetric: bool = False

    # When True, the slab is centred in the simulation cell.
    # 为 True 时，板层在模拟晶胞中居中。
    center: bool = True

    # When True, pymatgen searches for the primitive surface unit cell.
    # 为 True 时，pymatgen 搜索本原表面单元晶胞。
    primitive: bool = True

    # When True, the LLL lattice reduction algorithm is applied.
    # 为 True 时，应用 LLL 晶格约简算法。
    lll_reduce: bool = True

    # Distance cutoff (fractional) for grouping surface hydrogen clusters.
    # 表面氢原子簇分组的距离截断（分数坐标）。
    hcluster_cutoff: float = 0.25

    # Optional supercell transformation matrix applied after slab generation.
    # 板层生成后可选的超胞变换矩阵。
    supercell_matrix: Optional[Any] = None

    # When True, standardise the bulk cell before slicing.
    # 为 True 时，在切片前对体相晶胞进行标准化。
    standardize_bulk: bool = True


@dataclass
class SlabConfig:
    """Configuration for the slab-relaxation stage.

    Groups the list of Miller indices, slab-generation settings, and per-stage
    VASP parameters.

    板层弛豫阶段的配置。
    将 Miller 指数列表、板层生成设置及单阶段 VASP 参数组合在一起。
    """
    # List of [h, k, l] Miller index triplets to generate slabs for.
    # 需要生成板层的 [h, k, l] Miller 指数三元组列表。
    miller_list: List[List[int]]

    # Slab geometry and generation parameters.
    # 板层几何形状和生成参数。
    slabgen: SlabGenConfig

    # VASP parameters used for the slab relaxation calculation.
    # 板层弛豫计算使用的 VASP 参数。
    vasp: StageVaspConfig


@dataclass
class AdsorptionBuildConfig:
    """Parameters controlling adsorbate placement on slab surfaces.

    Controls both the site-based and enumeration-based placement modes.

    控制吸附质在板层表面放置的参数。
    同时控制基于位点和基于枚举的放置模式。
    """
    # Placement mode: "site" for explicit site or "enumerate" for full search.
    # 放置模式："site" 表示显式位点，"enumerate" 表示全面搜索。
    mode: str = "site"

    # Chemical formula of the molecule being adsorbed.
    # 被吸附分子的化学式。
    molecule_formula: str = ""

    # Adsorption site type when mode is "site" (e.g. "ontop", "bridge", "hollow").
    # mode 为 "site" 时的吸附位点类型（如 "ontop"、"bridge"、"hollow"）。
    site_type: str = "ontop"

    # Initial height in Angstroms of the adsorbate above the surface.
    # 吸附质初始位于表面上方的高度（埃）。
    height: float = 1.8

    # When True, the molecule is reoriented to point away from the surface.
    # 为 True 时，分子被重新定向使其远离表面。
    reorient: bool = True

    # When True, selective dynamics tags are added to the POSCAR.
    # 为 True 时，在 POSCAR 中添加选择性动力学标签。
    selective_dynamics: bool = False

    # Extra keyword arguments passed to the site-finder routine.
    # 传递给位点查找程序的额外关键字参数。
    find_args: Dict[str, Any] = field(default_factory=dict)

    # Parameters forwarded to the enumeration builder.
    # 传递给枚举构建器的参数。
    enumerate: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdsorptionConfig:
    """Configuration for the adsorption-relaxation stage.

    Combines adsorbate placement settings with the VASP calculation parameters.

    吸附弛豫阶段的配置。
    将吸附质放置设置与 VASP 计算参数组合在一起。
    """
    # Adsorbate geometry build parameters.
    # 吸附质几何形状构建参数。
    build: AdsorptionBuildConfig

    # VASP parameters used for the adsorption relaxation calculation.
    # 吸附弛豫计算使用的 VASP 参数。
    vasp: StageVaspConfig


@dataclass
class FreqSettingsConfig:
    """Settings that control which atoms are vibrated in a frequency calculation.

    Controls atom selection strategy and adsorbate formula resolution.

    控制频率计算中哪些原子参与振动的设置。
    控制原子选择策略和吸附质化学式解析。
    """
    # Strategy for selecting vibrating atoms: "inherit", "adsorbate", or "indices".
    # 选择振动原子的策略："inherit"、"adsorbate" 或 "indices"。
    mode: str = "inherit"

    # Formula of the adsorbate whose atoms will be vibrated (used when mode="adsorbate").
    # 将被振动的吸附质化学式（当 mode="adsorbate" 时使用）。
    adsorbate_formula: Optional[str] = None

    # Whether to resolve the adsorbate from the "head" or "tail" of the structure.
    # 是从结构的 "head"（头部）还是 "tail"（尾部）解析吸附质。
    adsorbate_formula_prefer: str = "tail"

    # Explicit list of atom indices to vibrate (used when mode="indices").
    # 要振动的原子索引显式列表（当 mode="indices" 时使用）。
    vibrate_indices: Optional[List[int]] = None


@dataclass
class FreqConfig:
    """Configuration for the frequency (vibrational analysis) stage.

    Pairs the VASP calculation parameters with atom-selection settings.

    频率（振动分析）阶段的配置。
    将 VASP 计算参数与原子选择设置配对。
    """
    # VASP parameters used for the frequency calculation.
    # 频率计算使用的 VASP 参数。
    vasp: StageVaspConfig

    # Atom-selection settings for the finite-difference displacement.
    # 有限差分位移的原子选择设置。
    settings: FreqSettingsConfig


@dataclass
class WorkflowStagesConfig:
    """Boolean flags enabling or disabling each workflow stage.

    Each attribute corresponds to one named stage in STAGE_ORDER.
    Stages set to False are skipped entirely by the scheduler.

    启用或禁用每个工作流阶段的布尔标志。
    每个属性对应 STAGE_ORDER 中的一个命名阶段。
    设置为 False 的阶段将被调度器完全跳过。
    """
    bulk_relax: bool = False
    bulk_dos: bool = False
    bulk_lobster: bool = False
    slab_relax: bool = False
    slab_dos: bool = False
    slab_lobster: bool = False
    adsorption: bool = False
    adsorption_freq: bool = False
    adsorption_lobster: bool = False
    bulk_nbo: bool = False
    slab_nbo: bool = False
    adsorption_nbo: bool = False


@dataclass
class WorkflowConfig:
    """Top-level config object built from params.yaml.

    Aggregates every section of the YAML file into a single typed object.
    All paths are resolved to absolute ``Path`` objects during construction
    by ``load_config``.

    Args:
        project:                   Filesystem layout (project_root, run_root, templates_dir).
        pbs:                       PBS scheduler parameters.
        python_runtime:            Python/conda environment settings.
        workflow:                  Per-stage enable/disable flags.
        structure:                 Glob pattern or path to bulk structure file(s).
        slab_source:               Path to pre-built slab files (skips bulk stages).
        adsorption_source:         Path to pre-built adsorption files (skips all prior stages).
        bulk:                      VASP settings for bulk relaxation.
        bulk_dos:                  VASP settings for bulk DOS.
        slab:                      Slab generation + VASP settings.
        slab_dos:                  VASP settings for slab DOS.
        adsorption:                Adsorption build + VASP settings.
        freq:                      Frequency calculation settings.
        lobster:                   Global fallback Lobster settings (all lobster stages).
        bulk_lobster_config:       Per-stage Lobster override for bulk_lobster.
        slab_lobster_config:       Per-stage Lobster override for slab_lobster.
        adsorption_lobster_config: Per-stage Lobster override for adsorption_lobster.
        nbo:                       Global fallback NBO settings (all NBO stages).
        bulk_nbo_config:           Per-stage NBO override for bulk_nbo.
        slab_nbo_config:           Per-stage NBO override for slab_nbo.
        adsorption_nbo_config:     Per-stage NBO override for adsorption_nbo.
        _params_file:              Absolute path to the source params.yaml (internal use).

    从 params.yaml 构建的顶层配置对象。
    将 YAML 文件的每个配置节聚合为单一类型化对象。
    所有路径在 ``load_config`` 构建期间解析为绝对 ``Path`` 对象。

    参数：
        project:                   文件系统布局（project_root、run_root、templates_dir）。
        pbs:                       PBS 调度器参数。
        python_runtime:            Python/conda 环境设置。
        workflow:                  每阶段启用/禁用标志。
        structure:                 体相结构文件的 glob 模式或路径。
        slab_source:               预构建板层文件的路径（跳过体相阶段）。
        adsorption_source:         预构建吸附文件的路径（跳过所有前置阶段）。
        bulk:                      体相弛豫的 VASP 设置。
        bulk_dos:                  体相 DOS 的 VASP 设置。
        slab:                      板层生成和 VASP 设置。
        slab_dos:                  板层 DOS 的 VASP 设置。
        adsorption:                吸附构建和 VASP 设置。
        freq:                      频率计算设置。
        lobster:                   全局 Lobster 设置（所有 lobster 阶段的后备配置）。
        bulk_lobster_config:       bulk_lobster 阶段的专属 Lobster 配置（覆盖全局）。
        slab_lobster_config:       slab_lobster 阶段的专属 Lobster 配置（覆盖全局）。
        adsorption_lobster_config: adsorption_lobster 阶段的专属 Lobster 配置（覆盖全局）。
        nbo:                       全局 NBO 设置（所有 NBO 阶段的后备配置）。
        bulk_nbo_config:           bulk_nbo 阶段的专属 NBO 配置（覆盖全局）。
        slab_nbo_config:           slab_nbo 阶段的专属 NBO 配置（覆盖全局）。
        adsorption_nbo_config:     adsorption_nbo 阶段的专属 NBO 配置（覆盖全局）。
        _params_file:              源 params.yaml 的绝对路径（内部使用）。
    """
    project: ProjectConfig
    pbs: PbsConfig
    python_runtime: PythonRuntimeConfig
    workflow: WorkflowStagesConfig
    # ── Input structure sources (at least one required) ──────────────────────
    structure: Optional[str] = None          # path to bulk structure file(s)
    slab_source: Optional[str] = None        # pre-built slab files → skips bulk stages
    adsorption_source: Optional[str] = None  # pre-built ads files → skips all prior stages
    # ── Per-stage VASP configs ────────────────────────────────────────────────
    bulk: Optional[StageVaspConfig] = None
    bulk_dos: Optional[StageVaspConfig] = None
    slab: Optional[SlabConfig] = None
    slab_dos: Optional[StageVaspConfig] = None
    adsorption: Optional[AdsorptionConfig] = None
    freq: Optional[FreqConfig] = None
    # ── Lobster: global fallback + per-stage overrides ────────────────────────
    lobster: Optional[LobsterConfig] = None
    bulk_lobster_config: Optional[LobsterConfig] = None
    slab_lobster_config: Optional[LobsterConfig] = None
    adsorption_lobster_config: Optional[LobsterConfig] = None
    # ── NBO: global fallback + per-stage overrides ────────────────────────────
    nbo: Optional[NboConfig] = None
    bulk_nbo_config: Optional[NboConfig] = None
    slab_nbo_config: Optional[NboConfig] = None
    adsorption_nbo_config: Optional[NboConfig] = None
    _params_file: str = ""

    # ------------------------------------------------------------------
    # Public accessor for the internal _params_file field
    # ------------------------------------------------------------------

    @property
    def params_file(self) -> str:
        """Absolute path to the source params.yaml file.

        Exposes the internal ``_params_file`` field through a public interface.

        源 params.yaml 文件的绝对路径（对外公开的只读属性）。
        """
        return self._params_file

    # ------------------------------------------------------------------
    # Convenience: get NboConfig / LobsterConfig for a named stage
    # 便利方法：获取命名阶段的 NboConfig / LobsterConfig
    # ------------------------------------------------------------------

    def get_stage_nbo_config(self, stage: str) -> Optional["NboConfig"]:
        """Return the NboConfig for *stage*, preferring per-stage over global.

        Args:
            stage: One of "bulk_nbo", "slab_nbo", "adsorption_nbo".

        Returns:
            Per-stage NboConfig if configured, else the global ``nbo`` fallback,
            or None if neither is configured.

        返回 *stage* 对应的 NboConfig，优先使用阶段专属配置，回退至全局配置。
        """
        per_stage: Dict[str, Optional[NboConfig]] = {
            "bulk_nbo":        self.bulk_nbo_config,
            "slab_nbo":        self.slab_nbo_config,
            "adsorption_nbo":  self.adsorption_nbo_config,
        }
        return per_stage.get(stage) or self.nbo

    def get_stage_lobster_config(self, stage: str) -> Optional["LobsterConfig"]:
        """Return the LobsterConfig for *stage*, preferring per-stage over global.

        Args:
            stage: One of "bulk_lobster", "slab_lobster", "adsorption_lobster".

        Returns:
            Per-stage LobsterConfig if configured, else the global ``lobster``
            fallback, or None if neither is configured.

        返回 *stage* 对应的 LobsterConfig，优先使用阶段专属配置，回退至全局配置。
        """
        per_stage: Dict[str, Optional[LobsterConfig]] = {
            "bulk_lobster":        self.bulk_lobster_config,
            "slab_lobster":        self.slab_lobster_config,
            "adsorption_lobster":  self.adsorption_lobster_config,
        }
        return per_stage.get(stage) or self.lobster

    # ------------------------------------------------------------------
    # Convenience: get the VASP config for a named stage
    # 便利方法：获取命名阶段的 VASP 配置
    # ------------------------------------------------------------------

    def get_stage_vasp(self, stage: str) -> StageVaspConfig:
        """Return the StageVaspConfig for *stage*.

        For Lobster/NBO stages, per-stage config takes precedence over the
        global fallback section.

        Args:
            stage: Stage name string (e.g. "bulk_relax", "slab_dos",
                   "adsorption_lobster", "bulk_nbo").

        Returns:
            The ``StageVaspConfig`` associated with the requested stage.

        Raises:
            ValueError: if *stage* is not found or the corresponding config is None.

        返回 *stage* 对应的 StageVaspConfig。
        对于 Lobster/NBO 阶段，阶段专属配置优先于全局后备配置。
        """
        def _lob_vasp(s: str) -> Optional[StageVaspConfig]:
            lob = self.get_stage_lobster_config(s)
            return lob.vasp_singlepoint if lob else None

        def _nbo_vasp(s: str) -> Optional[StageVaspConfig]:
            nb = self.get_stage_nbo_config(s)
            return nb.vasp_singlepoint if nb else None

        mapping: Dict[str, Optional[StageVaspConfig]] = {
            "bulk_relax":         self.bulk,
            "bulk_dos":           self.bulk_dos,
            "bulk_lobster":       _lob_vasp("bulk_lobster"),
            "bulk_nbo":           _nbo_vasp("bulk_nbo"),
            "slab_relax":         self.slab.vasp if self.slab else None,
            "slab_dos":           self.slab_dos,
            "slab_lobster":       _lob_vasp("slab_lobster"),
            "slab_nbo":           _nbo_vasp("slab_nbo"),
            "adsorption":         self.adsorption.vasp if self.adsorption else None,
            "adsorption_freq":    self.freq.vasp if self.freq else None,
            "adsorption_lobster": _lob_vasp("adsorption_lobster"),
            "adsorption_nbo":     _nbo_vasp("adsorption_nbo"),
        }
        cfg = mapping.get(stage)
        if cfg is None:
            raise ValueError(f"No VASP config found for stage {stage!r}.")
        return cfg


# ---------------------------------------------------------------------------
# Stage dependency validation
# 阶段依赖校验
# ---------------------------------------------------------------------------

# Maps a downstream stage to the upstream stages it requires.
# Used by validate_enabled_stages() to catch misconfigured params.yaml early.
# 下游阶段到其所需上游阶段的映射。
# 由 validate_enabled_stages() 在启动时及早捕获配置错误。
_REQUIRED_STAGE_DEPS: Dict[str, List[str]] = {
    "slab_relax":          ["bulk_relax"],    # exempt when slab_source is set
    "adsorption":          ["slab_relax"],    # exempt when adsorption_source is set
    "bulk_dos":            ["bulk_relax"],
    "bulk_lobster":        ["bulk_relax"],
    "bulk_nbo":            ["bulk_relax"],
    "slab_dos":            ["slab_relax"],
    "slab_lobster":        ["slab_relax"],
    "slab_nbo":            ["slab_relax"],
    "adsorption_freq":     ["adsorption"],
    "adsorption_lobster":  ["adsorption"],
    "adsorption_nbo":      ["adsorption"],
}


def validate_enabled_stages(cfg: "WorkflowConfig") -> None:
    """Check that every enabled stage has its required upstream stages also enabled.

    Raises ``ValueError`` on the first violated dependency so users get a
    clear error at config-load time rather than a silent workflow stall.

    Exemptions:
    - ``slab_source`` is set: slab tasks can run without ``bulk_relax``.
    - ``adsorption_source`` is set: adsorption tasks can run without ``slab_relax``.

    校验每个已启用阶段的所需上游阶段是否也已启用。

    首次发现依赖违规时抛出 ``ValueError``，确保用户在配置加载时获得清晰的报错，
    而非静默地让工作流卡住。

    豁免规则：
    - 设置了 ``slab_source``：板层任务可在无 ``bulk_relax`` 的情况下运行。
    - 设置了 ``adsorption_source``：吸附任务可在无 ``slab_relax`` 的情况下运行。
    """
    flags = cfg.workflow
    for stage, deps in _REQUIRED_STAGE_DEPS.items():
        if not getattr(flags, stage, False):
            continue
        for dep in deps:
            if not getattr(flags, dep, False):
                # Exemption: slab_source bypasses the bulk_relax requirement.
                # 豁免：slab_source 绕过 bulk_relax 要求。
                if dep == "bulk_relax" and cfg.slab_source:
                    continue
                # Exemption: adsorption_source bypasses the slab_relax requirement.
                # 豁免：adsorption_source 绕过 slab_relax 要求。
                if dep == "slab_relax" and cfg.adsorption_source:
                    continue
                raise ValueError(
                    f"Stage '{stage}' requires '{dep}' to be enabled. "
                    f"Add '{dep}' to workflow.stages in params.yaml."
                )


# ---------------------------------------------------------------------------
# Entry point
# 入口函数
# ---------------------------------------------------------------------------

def load_config(path: Union[str, Path]) -> WorkflowConfig:
    """Load and validate params.yaml, returning a fully typed ``WorkflowConfig``.

    Reads the YAML file, resolves all path fields to absolute paths, validates
    that at least one structure source is present, and constructs the full
    ``WorkflowConfig`` object by delegating each section to a private parser.

    Args:
        path: Absolute or relative path to params.yaml.

    Returns:
        ``WorkflowConfig`` with all paths resolved to absolute ``Path`` objects.

    Raises:
        FileNotFoundError: if *path* does not exist.
        ValueError:        if a required field is missing or invalid.

    加载并验证 params.yaml，返回完整类型化的 ``WorkflowConfig``。
    读取 YAML 文件，将所有路径字段解析为绝对路径，验证至少存在一个结构来源，
    并通过委托各私有解析器构造完整的 ``WorkflowConfig`` 对象。

    参数：
        path: params.yaml 的绝对或相对路径。

    返回：
        所有路径均解析为绝对 ``Path`` 对象的 ``WorkflowConfig``。

    异常：
        FileNotFoundError: 若 *path* 不存在。
        ValueError:        若必填字段缺失或无效。
    """
    # Expand user home-dir shortcuts and resolve to absolute path.
    # 展开用户主目录快捷方式并解析为绝对路径。
    params_path = Path(path).expanduser().resolve()
    if not params_path.exists():
        raise FileNotFoundError(f"params.yaml not found: {params_path}")

    # Parse the YAML file; default to empty dict if file is empty.
    # 解析 YAML 文件；若文件为空则默认为空字典。
    with params_path.open("r", encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}

    # Extract the three mutually exclusive structure source options.
    # 提取三个互斥的结构来源选项。
    base_dir = params_path.parent
    structure = _parse_structure(raw, base_dir)
    slab_source = _parse_optional_path(raw, "slab_source", base_dir)
    adsorption_source = _parse_optional_path(raw, "adsorption_source", base_dir)

    # At least one source of atomic structures must be provided.
    # 必须提供至少一种原子结构来源。
    if not structure and not slab_source and not adsorption_source:
        raise ValueError(
            "params.yaml must specify at least one of: "
            "'structure', 'slab_source', or 'adsorption_source'."
        )

    # Delegate every YAML section to its dedicated private parser function.
    # 将每个 YAML 配置节委托给其专用的私有解析函数。
    cfg = WorkflowConfig(
        project=_parse_project(raw, base_dir),
        pbs=_parse_pbs(raw, base_dir),
        python_runtime=_parse_python_runtime(raw),
        workflow=_parse_workflow_stages(raw),
        structure=structure,
        slab_source=slab_source,
        adsorption_source=adsorption_source,
        bulk=_parse_stage_vasp(raw.get("bulk", {}).get("vasp")),
        bulk_dos=_parse_stage_vasp(raw.get("bulk_dos", {}).get("vasp")),
        slab=_parse_slab(raw.get("slab")),
        slab_dos=_parse_stage_vasp(raw.get("slab_dos", {}).get("vasp")),
        adsorption=_parse_adsorption(raw.get("adsorption")),
        freq=_parse_freq(raw.get("freq")),
        lobster=_parse_lobster(raw.get("lobster")),
        bulk_lobster_config=_parse_lobster(raw.get("bulk_lobster")),
        slab_lobster_config=_parse_lobster(raw.get("slab_lobster")),
        adsorption_lobster_config=_parse_lobster(raw.get("adsorption_lobster")),
        nbo=_parse_nbo(raw.get("nbo")),
        bulk_nbo_config=_parse_nbo(raw.get("bulk_nbo")),
        slab_nbo_config=_parse_nbo(raw.get("slab_nbo")),
        adsorption_nbo_config=_parse_nbo(raw.get("adsorption_nbo")),
        _params_file=str(params_path),
    )
    validate_enabled_stages(cfg)
    return cfg


# ---------------------------------------------------------------------------
# Private parsers
# 私有解析函数
# ---------------------------------------------------------------------------

def _require(d: Dict[str, Any], key: str, context: str) -> Any:
    """Retrieve a required key from dict *d*, raising ValueError if absent.

    Args:
        d:       The dictionary to search.
        key:     The required key name.
        context: Human-readable label used in the error message.

    Returns:
        The value associated with *key*.

    Raises:
        ValueError: if *key* is absent or its value is None or empty string.

    从字典 *d* 中获取必填键，若缺失则抛出 ValueError。

    参数：
        d:       待搜索的字典。
        key:     必填键名。
        context: 错误消息中使用的可读标签。

    返回：
        与 *key* 关联的值。

    异常：
        ValueError: 若 *key* 缺失或其值为 None 或空字符串。
    """
    val = d.get(key)
    if val is None or val == "":
        raise ValueError(f"Required field '{key}' is missing in {context}.")
    return val


def _expand_str(val: Any) -> str:
    """Expand environment variables and trim whitespace for string-like values."""
    if val is None:
        return ""
    return os.path.expandvars(str(val)).strip()


def _resolve_config_path(val: Any, base_dir: Path) -> Path:
    """Resolve a config path relative to the params.yaml directory."""
    p = Path(_expand_str(val)).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()


def _parse_project(raw: Dict[str, Any], base_dir: Path) -> ProjectConfig:
    """Parse the 'project' section of params.yaml into a ProjectConfig.

    Args:
        raw: Top-level params.yaml dictionary.

    Returns:
        ProjectConfig with resolved absolute paths.

    将 params.yaml 的 'project' 节解析为 ProjectConfig。

    参数：
        raw: params.yaml 顶层字典。

    返回：
        包含已解析绝对路径的 ProjectConfig。
    """
    p = raw.get("project") or {}
    project_root = _resolve_config_path(_require(p, "project_root", "project"), base_dir)
    run_root = _resolve_config_path(_require(p, "run_root", "project"), base_dir)
    # templates_dir is optional; resolve only when explicitly provided.
    # templates_dir 是可选的；仅在显式提供时才解析。
    templates_dir = _resolve_config_path(p["templates_dir"], base_dir) if p.get("templates_dir") else None
    return ProjectConfig(project_root=project_root, run_root=run_root, templates_dir=templates_dir)


def _parse_pbs(raw: Dict[str, Any], base_dir: Path) -> PbsConfig:
    """Parse the 'pbs' section of params.yaml into a PbsConfig.

    ``nodes`` is no longer read: the template hard-wires ``nodes=1``.

    Args:
        raw: Top-level params.yaml dictionary.

    Returns:
        PbsConfig with sensible defaults for omitted fields.

    将 params.yaml 的 'pbs' 节解析为 PbsConfig。
    ``nodes`` 已不再读取：模板中固定写 ``nodes=1``。

    参数：
        raw: params.yaml 顶层字典。

    返回：
        对省略字段使用合理默认值的 PbsConfig。
    """
    p = raw.get("pbs") or {}
    return PbsConfig(
        queue=str(_require(p, "queue", "pbs")),
        ppn=int(p.get("ppn", 72)),
        walltime=str(p.get("walltime", "24:00:00")),
        job_name_prefix=str(p.get("job_name_prefix", "job")),
        template_file=_resolve_config_path(_require(p, "template_file", "pbs"), base_dir),
    )


def _parse_python_runtime(raw: Dict[str, Any]) -> PythonRuntimeConfig:
    """Parse the 'python_runtime' section into a PythonRuntimeConfig.

    Args:
        raw: Top-level params.yaml dictionary.

    Returns:
        PythonRuntimeConfig (all fields default to empty string if absent).

    将 'python_runtime' 节解析为 PythonRuntimeConfig。

    参数：
        raw: params.yaml 顶层字典。

    返回：
        PythonRuntimeConfig（所有字段若缺失则默认为空字符串）。
    """
    p = raw.get("python_runtime") or {}
    return PythonRuntimeConfig(
        conda_sh=_expand_str(p.get("conda_sh", "")),
        conda_env=str(p.get("conda_env", "")),
        python_bin=_expand_str(p.get("python_bin", "")),
    )


def _parse_structure(raw: Dict[str, Any], base_dir: Path) -> Optional[str]:
    """Extract and validate the 'structure' key from the top-level YAML dict.

    Args:
        raw: Top-level params.yaml dictionary.

    Returns:
        The structure path string, or None if the key is absent.

    Raises:
        ValueError: if 'structure' is present but not a string.

    从顶层 YAML 字典中提取并验证 'structure' 键。

    参数：
        raw: params.yaml 顶层字典。

    返回：
        结构路径字符串，若键缺失则返回 None。

    异常：
        ValueError: 若 'structure' 存在但不是字符串。
    """
    val = raw.get("structure")
    if not val:
        return None
    if not isinstance(val, str):
        raise ValueError("'structure' must be a path string.")
    return str(_resolve_config_path(val, base_dir))


def _parse_optional_path(raw: Dict[str, Any], key: str, base_dir: Path) -> Optional[str]:
    """Extract an optional path string from the top-level YAML dict.

    Args:
        raw: Top-level params.yaml dictionary.
        key: The YAML key to look up.

    Returns:
        The path string, or None if the key is absent.

    Raises:
        ValueError: if the key is present but its value is not a string.

    从顶层 YAML 字典中提取可选的路径字符串。

    参数：
        raw: params.yaml 顶层字典。
        key: 要查找的 YAML 键。

    返回：
        路径字符串，若键缺失则返回 None。

    异常：
        ValueError: 若键存在但其值不是字符串。
    """
    val = raw.get(key)
    if not val:
        return None
    if not isinstance(val, str):
        raise ValueError(f"'{key}' must be a path string.")
    return str(_resolve_config_path(val, base_dir))


def _parse_workflow_stages(raw: Dict[str, Any]) -> WorkflowStagesConfig:
    """Parse the 'workflow.stages' subsection into a WorkflowStagesConfig.

    Args:
        raw: Top-level params.yaml dictionary.

    Returns:
        WorkflowStagesConfig with each stage flag set to False by default.

    将 'workflow.stages' 子节解析为 WorkflowStagesConfig。

    参数：
        raw: params.yaml 顶层字典。

    返回：
        每个阶段标志默认设置为 False 的 WorkflowStagesConfig。
    """
    # Navigate two levels: workflow → stages; default to empty dict at each level.
    # 逐层导航：workflow → stages；每层默认为空字典。
    stages = (raw.get("workflow") or {}).get("stages") or {}
    return WorkflowStagesConfig(
        bulk_relax=bool(stages.get("bulk_relax", False)),
        bulk_dos=bool(stages.get("bulk_dos", False)),
        bulk_lobster=bool(stages.get("bulk_lobster", False)),
        bulk_nbo=bool(stages.get("bulk_nbo", False)),
        slab_relax=bool(stages.get("slab_relax", False)),
        slab_dos=bool(stages.get("slab_dos", False)),
        slab_lobster=bool(stages.get("slab_lobster", False)),
        slab_nbo=bool(stages.get("slab_nbo", False)),
        adsorption=bool(stages.get("adsorption", False)),
        adsorption_freq=bool(stages.get("adsorption_freq", False)),
        adsorption_lobster=bool(stages.get("adsorption_lobster", False)),
        adsorption_nbo=bool(stages.get("adsorption_nbo", False)),
    )


def _parse_stage_vasp(vasp: Optional[Dict[str, Any]]) -> Optional[StageVaspConfig]:
    """Parse a VASP sub-dict into a StageVaspConfig, or return None if absent.

    Handles the legacy ``overwritedict`` alias for ``lobsterin_settings`` and
    normalises ``cohpGenerator`` to a list so the lobsterin writer can emit
    multiple lines for repeated keys.

    Args:
        vasp: Dictionary from the YAML 'vasp' subsection, or None.

    Returns:
        StageVaspConfig populated from *vasp*, or None if *vasp* is falsy.

    将 VASP 子字典解析为 StageVaspConfig，若缺失则返回 None。
    处理 ``lobsterin_settings`` 的旧版 ``overwritedict`` 别名，
    并将 ``cohpGenerator`` 标准化为列表，以便 lobsterin 写入器能为重复键
    生成多行输出。

    参数：
        vasp: 来自 YAML 'vasp' 子节的字典，或 None。

    返回：
        由 *vasp* 填充的 StageVaspConfig，若 *vasp* 为假值则返回 None。
    """
    if not vasp:
        return None
    # Accept both new key and legacy alias
    # 同时接受新键名和旧版别名
    raw_ls: Dict[str, Any] = dict(
        vasp.get("lobsterin_settings") or vasp.get("overwritedict") or {}
    )
    # Normalise cohpGenerator to a list so the lobsterin writer can emit multiple lines
    # 将 cohpGenerator 标准化为列表，以便 lobsterin 写入器生成多行输出
    cg = raw_ls.get("cohpGenerator")
    if cg is not None and not isinstance(cg, list):
        # Single string value: wrap in a list.
        # 单个字符串值：包装为列表。
        raw_ls["cohpGenerator"] = [str(cg)]
    elif isinstance(cg, list):
        # Already a list: ensure all elements are strings.
        # 已经是列表：确保所有元素均为字符串。
        raw_ls["cohpGenerator"] = [str(g) for g in cg]
    return StageVaspConfig(
        functional=str(vasp.get("functional", "PBE")),
        kpoints_density=int(vasp.get("kpoints_density", 50)),
        user_incar_settings=dict(vasp.get("user_incar_settings") or {}),
        is_metal=bool(vasp.get("is_metal", False)),
        auto_dipole=bool(vasp.get("auto_dipole", False)),
        # Support both "number_of_docs" (legacy typo) and "number_of_dos".
        # 同时支持 "number_of_docs"（旧版拼写错误）和 "number_of_dos"。
        number_of_dos=vasp.get("number_of_docs") or vasp.get("number_of_dos"),
        lobsterin_settings=raw_ls,
    )


def _parse_slab(slab: Optional[Dict[str, Any]]) -> Optional[SlabConfig]:
    """Parse the 'slab' section into a SlabConfig.

    Args:
        slab: Dictionary from the YAML 'slab' section, or None.

    Returns:
        SlabConfig with parsed Miller indices, slab-gen params, and VASP config,
        or None if *slab* is falsy.

    Raises:
        ValueError: if miller_list is present but not a list.

    将 'slab' 节解析为 SlabConfig。

    参数：
        slab: 来自 YAML 'slab' 节的字典，或 None。

    返回：
        包含已解析 Miller 指数、板层生成参数和 VASP 配置的 SlabConfig，
        若 *slab* 为假值则返回 None。

    异常：
        ValueError: 若 miller_list 存在但不是列表。
    """
    if not slab:
        return None
    miller_list = slab.get("miller_list") or []
    if miller_list and not isinstance(miller_list, list):
        raise ValueError("slab.miller_list must be a list of [h,k,l] lists.")
    sg_raw = slab.get("slabgen") or {}
    slabgen = SlabGenConfig(
        target_layers=int(sg_raw.get("target_layers", 0)),
        vacuum_thickness=float(sg_raw.get("vacuum_thickness", 15.0)),
        fix_bottom_layers=int(sg_raw.get("fix_bottom_layers", 0)),
        fix_top_layers=int(sg_raw.get("fix_top_layers", 0)),
        all_fix=bool(sg_raw.get("all_fix", False)),
        symmetric=bool(sg_raw.get("symmetric", False)),
        center=bool(sg_raw.get("center", True)),
        primitive=bool(sg_raw.get("primitive", True)),
        lll_reduce=bool(sg_raw.get("lll_reduce", True)),
        hcluster_cutoff=float(sg_raw.get("hcluster_cutoff", 0.25)),
        supercell_matrix=sg_raw.get("supercell_matrix"),
        standardize_bulk=bool(sg_raw.get("standardize_bulk", True)),
    )
    return SlabConfig(
        # Convert each [h, k, l] element to int to guard against YAML string parsing.
        # 将每个 [h, k, l] 元素转换为整数，防止 YAML 字符串解析问题。
        miller_list=[[int(x) for x in hkl] for hkl in miller_list],
        slabgen=slabgen,
        vasp=_parse_stage_vasp(slab.get("vasp")) or StageVaspConfig(),
    )


def _parse_adsorption(ads: Optional[Dict[str, Any]]) -> Optional[AdsorptionConfig]:
    """Parse the 'adsorption' section into an AdsorptionConfig.

    Args:
        ads: Dictionary from the YAML 'adsorption' section, or None.

    Returns:
        AdsorptionConfig with build and VASP sub-configs,
        or None if *ads* is falsy.

    将 'adsorption' 节解析为 AdsorptionConfig。

    参数：
        ads: 来自 YAML 'adsorption' 节的字典，或 None。

    返回：
        包含构建和 VASP 子配置的 AdsorptionConfig，
        若 *ads* 为假值则返回 None。
    """
    if not ads:
        return None
    build_raw = ads.get("build") or {}
    # Enumeration parameters are stored at adsorption level alongside build.
    # 枚举参数与构建参数一起存储在吸附层级。
    enumerate_raw = ads.get("enumerate") or {}
    build = AdsorptionBuildConfig(
        mode=str(build_raw.get("mode", "site")),
        molecule_formula=str(build_raw.get("molecule_formula", "")),
        site_type=str(build_raw.get("site_type", "ontop")),
        height=float(build_raw.get("height", 1.8)),
        reorient=bool(build_raw.get("reorient", True)),
        selective_dynamics=bool(build_raw.get("selective_dynamics", False)),
        find_args=dict(build_raw.get("find_args") or {}),
        enumerate=dict(enumerate_raw),
    )
    return AdsorptionConfig(
        build=build,
        vasp=_parse_stage_vasp(ads.get("vasp")) or StageVaspConfig(),
    )


def _parse_freq(freq: Optional[Dict[str, Any]]) -> Optional[FreqConfig]:
    """Parse the 'freq' section into a FreqConfig.

    Handles both list and comma-separated string forms of vibrate_indices.

    Args:
        freq: Dictionary from the YAML 'freq' section, or None.

    Returns:
        FreqConfig with VASP and frequency settings, or None if *freq* is falsy.

    将 'freq' 节解析为 FreqConfig。
    同时处理 vibrate_indices 的列表形式和逗号分隔字符串形式。

    参数：
        freq: 来自 YAML 'freq' 节的字典，或 None。

    返回：
        包含 VASP 和频率设置的 FreqConfig，若 *freq* 为假值则返回 None。
    """
    if not freq:
        return None
    s = freq.get("settings") or {}
    vi_raw = s.get("vibrate_indices")
    vi: Optional[List[int]] = None
    if vi_raw is not None:
        if isinstance(vi_raw, list):
            # Direct list of integer indices.
            # 整数索引的直接列表。
            vi = [int(x) for x in vi_raw]
        elif isinstance(vi_raw, str):
            # Comma-separated string form: parse and filter empty tokens.
            # 逗号分隔字符串形式：解析并过滤空标记。
            vi = [int(x.strip()) for x in vi_raw.split(",") if x.strip()]
    return FreqConfig(
        vasp=_parse_stage_vasp(freq.get("vasp")) or StageVaspConfig(),
        settings=FreqSettingsConfig(
            mode=str(s.get("mode", "inherit")),
            adsorbate_formula=s.get("adsorbate_formula"),
            adsorbate_formula_prefer=str(s.get("adsorbate_formula_prefer", "tail")),
            vibrate_indices=vi,
        ),
    )


def _parse_nbo(nbo: Optional[Dict[str, Any]]) -> Optional[NboConfig]:
    """Parse the 'nbo' section into an NboConfig.

    Accepts both ``vasp_singlepoint`` and the legacy ``vasp`` key for the
    single-point VASP sub-section.

    Args:
        nbo: Dictionary from the YAML 'nbo' section, or None.

    Returns:
        NboConfig with enabled flag, VASP single-point config, and NBO settings,
        or None if *nbo* is falsy.

    将 'nbo' 节解析为 NboConfig。
    同时接受单点 VASP 子节的 ``vasp_singlepoint`` 和旧版 ``vasp`` 键。

    参数：
        nbo: 来自 YAML 'nbo' 节的字典，或 None。

    返回：
        包含启用标志、VASP 单点配置和 NBO 设置的 NboConfig，
        若 *nbo* 为假值则返回 None。
    """
    if not nbo:
        return None
    # Accept legacy 'vasp' key in addition to the canonical 'vasp_singlepoint'.
    # 除规范的 'vasp_singlepoint' 外，还接受旧版 'vasp' 键。
    vasp_sp = _parse_stage_vasp(nbo.get("vasp_singlepoint") or nbo.get("vasp")) or StageVaspConfig()
    s = nbo.get("settings") or {}

    # Inner helper: coerce a YAML value to a list of ints with a fallback default.
    # 内部辅助函数：将 YAML 值强制转换为整数列表，若不是列表则使用默认值。
    def _int_list(val: Any, default: List[int]) -> List[int]:
        if isinstance(val, list):
            return [int(x) for x in val]
        return default

    settings = NboSettingsConfig(
        basis_source=str(s.get("basis_source", "ANO-RCC-MB")),
        custom_basis_path=s.get("custom_basis_path"),
        occ_1c=float(s.get("occ_1c", 1.60)),
        occ_2c=float(s.get("occ_2c", 1.85)),
        print_cube=str(s.get("print_cube", "F")),
        density=str(s.get("density", "F")),
        vis_start=int(s.get("vis_start", 0)),
        vis_end=int(s.get("vis_end", -1)),
        mesh=_int_list(s.get("mesh"), [0, 0, 0]),
        box_int=_int_list(s.get("box_int"), [1, 1, 1]),
        origin_fact=float(s.get("origin_fact", 0.00)),
    )
    return NboConfig(
        enabled=bool(nbo.get("enabled", True)),
        vasp_singlepoint=vasp_sp,
        settings=settings,
    )


def _parse_lobster(lob: Optional[Dict[str, Any]]) -> Optional[LobsterConfig]:
    """Parse the 'lobster' section into a LobsterConfig.

    The ``lobsterin_settings`` (and its legacy alias ``overwritedict``) are
    handled inside ``_parse_stage_vasp``.

    Args:
        lob: Dictionary from the YAML 'lobster' section, or None.

    Returns:
        LobsterConfig with enabled flag and single-point VASP config,
        or None if *lob* is falsy.

    将 'lobster' 节解析为 LobsterConfig。
    ``lobsterin_settings``（及其旧版别名 ``overwritedict``）在
    ``_parse_stage_vasp`` 内部处理。

    参数：
        lob: 来自 YAML 'lobster' 节的字典，或 None。

    返回：
        包含启用标志和单点 VASP 配置的 LobsterConfig，
        若 *lob* 为假值则返回 None。
    """
    if not lob:
        return None
    # _parse_stage_vasp already reads lobsterin_settings (and overwritedict alias)
    # _parse_stage_vasp 已读取 lobsterin_settings（及 overwritedict 别名）
    vasp_sp = _parse_stage_vasp(lob.get("vasp_singlepoint")) or StageVaspConfig()
    return LobsterConfig(
        enabled=bool(lob.get("enabled", True)),
        vasp_singlepoint=vasp_sp,
    )
