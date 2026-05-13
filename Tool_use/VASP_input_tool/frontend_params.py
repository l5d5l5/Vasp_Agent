# -*- coding: utf-8 -*-
"""
frontend_params.py — Frontend parameter dataclasses and parsing helpers.
前端参数数据类与解析辅助函数。

Pure data definitions: no engine imports, no pymatgen imports beyond type hints.
Extracted from api.py to allow independent testing and reuse.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# ============================================================================
# Map frontend XC functional aliases to canonical pymatgen functional names.
# 将前端 XC 泛函别名映射为 pymatgen 规范泛函名称。
# ============================================================================

FRONTEND_XC_MAP = {
    "PBE": "PBE", "RPBE": "RPBE", "BEEF": "BEEF",
    "SCAN": "SCAN", "HSE": "HSE", "LDA": "LDA", "PBEsol": "PBEsol",
}

# Map frontend vdW method strings to canonical method identifiers.
# 将前端 vdW 方法字符串映射为规范方法标识符。
FRONTEND_VDW_MAP = {
    "None": "None", "D3": "D3", "D3BJ": "D3BJ",
    "DFT-D2": "DFT-D2", "DFT-D3": "D3",
}


# ============================================================================
# 前端参数定义（FrontendParams）
# ============================================================================

@dataclass
class StructureInput:
    """Frontend structure input descriptor.

    Supports three source types:
    - ``"file"``: uploaded file content (``content``) or local file path (``id``).
    - ``"library"``: select from a predefined structure library (``id`` is the
      library identifier).
    - ``"task"``: retrieve from a previous task's output directory (``id`` is the
      task directory path).

    Attributes:
        source: Source type — one of ``"file"``, ``"library"``, or ``"task"``.
        id: Identifier — file name, library ID, or task directory path.
        content: Raw file content, used when ``source="file"`` and the file is
            uploaded directly (rather than referenced by path).

    前端结构输入参数。

    支持三种来源：
    - ``"file"``：上传的文件内容（``content``）或本地文件路径（``id``）。
    - ``"library"``：从预定义结构库中选择（``id`` 为库中的结构标识符）。
    - ``"task"``：从之前任务的结果目录中获取（``id`` 为任务目录路径）。

    属性：
        source: 来源类型，取值为 ``"file"``、``"library"`` 或 ``"task"``。
        id: 标识符——文件名、库 ID 或任务路径。
        content: 文件原始内容，当 ``source="file"`` 且直接上传文件（而非路径引用）时使用。
    """
    source: str = "file"
    id: str = ""
    content: str = ""

    def to_path_or_content(self) -> Union[str, Path]:
        """Resolve the structure input to a file path or raw content string.

        Returns:
            - ``source="file"``: returns ``content`` if non-empty, otherwise ``id``.
            - ``source="library"``: returns ``id`` and emits a warning that library
              support must be separately implemented.
            - ``source="task"``: returns ``id`` after verifying the directory exists;
              raises ``FileNotFoundError`` if not found.
            - Unknown source: returns ``id`` with a warning.

        将结构输入解析为文件路径或原始内容字符串。

        返回：
            - ``source="file"``：若 ``content`` 非空则返回之，否则返回 ``id``。
            - ``source="library"``：返回 ``id`` 并发出警告（需要结构库支持）。
            - ``source="task"``：验证目录存在后返回 ``id``；不存在则抛出
              ``FileNotFoundError``。
            - 未知来源：返回 ``id`` 并发出警告。
        """
        if self.source == "file":
            return self.content if self.content else self.id
        elif self.source == "library":
            logger.warning(
                "StructureInput source='library' 需要结构库支持。"
                "当前返回 id='%s'，请确保该标识符在结构库中有效。", self.id
            )
            return self.id
        elif self.source == "task":
            task_path = Path(self.id)
            if not task_path.exists():
                raise FileNotFoundError(
                    f"StructureInput source='task'，但任务目录不存在: {self.id}"
                )
            return self.id
        else:
            logger.warning("未知的 StructureInput source='%s'，回退到使用 id", self.source)
            return self.id


@dataclass
class PrecisionParams:
    """Precision / convergence parameters exposed to the frontend.

    All fields map directly to VASP INCAR tags.  ``None`` means "use the
    InputSet default" and the field is omitted from ``user_incar_overrides``.

    Attributes:
        encut:  Plane-wave energy cutoff in eV (ENCUT).
        ediff:  Electronic convergence criterion in eV (EDIFF).
        ediffg: Ionic convergence criterion in eV or eV/Å (EDIFFG).
        nedos:  Number of DOS grid points (NEDOS).

    精度/收敛参数——前端暴露。

    所有字段直接映射到 VASP INCAR 标记。``None`` 表示"使用 InputSet 默认值"，
    该字段不会被写入 ``user_incar_overrides``。

    属性：
        encut:  平面波截断能（eV），对应 ENCUT。
        ediff:  电子自洽收敛判据（eV），对应 EDIFF。
        ediffg: 离子弛豫收敛判据（eV 或 eV/Å），对应 EDIFFG。
        nedos:  态密度网格点数，对应 NEDOS。
    """
    encut: Optional[int] = None
    ediff: Optional[float] = None
    ediffg: Optional[float] = None
    nedos: Optional[int] = None


@dataclass
class KpointParams:
    """K-point sampling parameters exposed to the frontend.

    Attributes:
        density:         Reciprocal-space k-point density (points per Å⁻¹).
        gamma_centered:  If ``True``, use Gamma-centred mesh; otherwise shifted.

    K 点采样参数——前端暴露。

    属性：
        density:         倒空间 K 点密度（每 Å⁻¹ 的点数）。
        gamma_centered:  ``True`` 表示使用 Gamma 中心网格，否则使用偏移网格。
    """
    density: Optional[float] = None
    gamma_centered: bool = True


@dataclass
class MagmomParams:
    """Magnetic moment parameters exposed to the frontend.

    Supports two input formats:
    - ``per_atom``: ``List[float]`` — site-ordered moments,
      e.g. ``[5.0, 5.0, 3.0, 3.0]``.
    - ``per_element``: ``Dict[str, float]`` — element-keyed moments,
      e.g. ``{"Fe": 5.0, "Co": 3.0}``.

    pymatgen ``user_incar_settings["MAGMOM"]`` expects a per-site
    ``List[float]``.  ``to_pymatgen_format()`` returns the correct type for
    use in ``to_workflow_config()``.

    磁矩参数——前端暴露。

    支持两种格式：
    - ``per_atom``：``List[float]``，按原子顺序排列，如 ``[5.0, 5.0, 3.0, 3.0]``。
    - ``per_element``：``Dict[str, float]``，按元素键值，如 ``{"Fe": 5.0, "Co": 3.0}``。

    pymatgen ``user_incar_settings["MAGMOM"]`` 期望 ``List[float]``（per-site）。
    ``to_pymatgen_format()`` 返回正确类型，供 ``to_workflow_config()`` 使用。
    """
    enabled: bool = False
    per_atom: Optional[List[float]] = None
    per_element: Dict[str, float] = field(default_factory=dict)

    def to_pymatgen_format(self) -> Optional[List[float]]:
        """Return the per-site ``List[float]`` expected by pymatgen.

        - ``per_atom`` takes priority: returned directly.
        - ``per_element``: returns ``None``; the caller should expand the dict
          against the structure's site order after the structure is loaded.

        Returns:
            Per-site moment list, or ``None`` if disabled or only
            ``per_element`` data is available.

        返回 pymatgen 期望的 per-site ``List[float]``。

        - ``per_atom`` 优先：直接返回列表。
        - ``per_element``：返回 ``None``；调用方应在加载结构后按位点顺序展开该字典。

        返回：
            per-site 磁矩列表，若未启用或仅有 ``per_element`` 数据则返回 ``None``。
        """
        if not self.enabled:
            return None
        if self.per_atom:
            return [float(v) for v in self.per_atom]
        return None

    def to_incar_format(self) -> Optional[str]:
        """Return the VASP MAGMOM string for direct INCAR writing.

        Kept for backward compatibility with code paths that write INCAR tags
        directly rather than via pymatgen InputSet.

        Returns:
            Space-separated moment string, or ``None`` if disabled.

        返回 VASP MAGMOM 字符串，用于直接写 INCAR 的兼容场景。

        保留该方法以兼容不经由 pymatgen InputSet 而直接写 INCAR 标记的代码路径。

        返回：
            空格分隔的磁矩字符串，若未启用则返回 ``None``。
        """
        if not self.enabled:
            return None
        if self.per_atom:
            return " ".join(str(v) for v in self.per_atom)
        if self.per_element:
            return " ".join(f"{k} {v}" for k, v in self.per_element.items())
        return None

    @property
    def values(self) -> Dict[str, float]:
        """Compatibility alias for ``per_element``.

        ``per_element`` 的兼容性别名。
        """
        return self.per_element

    @values.setter
    def values(self, val: Dict[str, float]):
        # Redirect legacy attribute writes to the canonical field.
        # 将旧属性写操作重定向到规范字段。
        self.per_element = val


@dataclass
class DFTPlusUParams:
    """DFT+U (Hubbard U) parameters exposed to the frontend.

    ``values`` format::

        {"Fe": {"LDAUU": 4.0, "LDAUL": 2, "LDAUJ": 0.0},
         "Co": {"LDAUU": 3.0, "LDAUL": 2, "LDAUJ": 0.0}}

    pymatgen ``user_incar_settings`` expects three separate dicts::

        LDAUU = {"Fe": 4.0, "Co": 3.0}   # Dict[str, float]
        LDAUL = {"Fe": 2,   "Co": 2}      # Dict[str, int]
        LDAUJ = {"Fe": 0.0, "Co": 0.0}    # Dict[str, float]

    ``to_pymatgen_format()`` performs this conversion.

    DFT+U（Hubbard U）参数——前端暴露。

    ``values`` 格式::

        {"Fe": {"LDAUU": 4.0, "LDAUL": 2, "LDAUJ": 0.0},
         "Co": {"LDAUU": 3.0, "LDAUL": 2, "LDAUJ": 0.0}}

    pymatgen ``user_incar_settings`` 期望三个独立的字典::

        LDAUU = {"Fe": 4.0, "Co": 3.0}   # Dict[str, float]
        LDAUL = {"Fe": 2,   "Co": 2}      # Dict[str, int]
        LDAUJ = {"Fe": 0.0, "Co": 0.0}    # Dict[str, float]

    ``to_pymatgen_format()`` 执行此转换。
    """
    enabled: bool = False
    values: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def to_pymatgen_format(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """Convert the nested ``values`` dict to three separate pymatgen dicts.

        Returns:
            ``{"LDAUU": {...}, "LDAUL": {...}, "LDAUJ": {...}}``, or ``None``
            when DFT+U is disabled or ``values`` is empty.

        将嵌套的 ``values`` 字典转换为 pymatgen 期望的三个独立字典。

        返回：
            ``{"LDAUU": {...}, "LDAUL": {...}, "LDAUJ": {...}}``，
            若 DFT+U 未启用或 ``values`` 为空则返回 ``None``。
        """
        if not self.enabled or not self.values:
            return None
        ldauu: Dict[str, float] = {}
        ldaul: Dict[str, int]   = {}
        ldauj: Dict[str, float] = {}
        for elem, uda in self.values.items():
            ldauu[elem] = float(uda.get("LDAUU", 0.0))
            ldaul[elem] = int(uda.get("LDAUL", 0))
            ldauj[elem] = float(uda.get("LDAUJ", 0.0))
        return {"LDAUU": ldauu, "LDAUL": ldaul, "LDAUJ": ldauj}


@dataclass
class VdwParams:
    """van der Waals dispersion correction parameters exposed to the frontend.

    Attributes:
        method: Dispersion correction method name, e.g. ``"None"``, ``"D3"``,
            ``"D3BJ"``.  Resolved from ``FRONTEND_VDW_MAP`` in
            ``FrontendAdapter.from_frontend_dict()``.

    范德华色散校正参数——前端暴露。

    属性：
        method: 色散校正方法名称，如 ``"None"``、``"D3"``、``"D3BJ"``。
            在 ``FrontendAdapter.from_frontend_dict()`` 中通过 ``FRONTEND_VDW_MAP``
            解析。
    """
    method: str = "None"


@dataclass
class DipoleParams:
    """Dipole correction parameters exposed to the frontend.

    Attributes:
        enabled:   Whether to enable dipole correction (LDIPOL = .TRUE.).
        direction: Cartesian direction along which the correction is applied
            (IDIPOL: 1=x, 2=y, 3=z).

    偶极校正参数——前端暴露。

    属性：
        enabled:   是否启用偶极校正（LDIPOL = .TRUE.）。
        direction: 施加校正的笛卡儿方向（IDIPOL：1=x，2=y，3=z）。
    """
    enabled: bool = True
    direction: int = 3


@dataclass
class FrequencyParams:
    """Vibrational frequency calculation parameters exposed to the frontend.

    Attributes:
        ibrion:             VASP IBRION tag (5 = finite differences, 7 = DFPT).
        potim:              Finite-difference step size in Å (POTIM).
        nfree:              Number of displacements per atom (NFREE).
        vibrate_mode:       Atom-selection strategy: ``"inherit"`` uses
            ``vibrate_indices``; other values are interpreted by the maker layer.
        adsorbate_formula:  Chemical formula of the adsorbate for automatic
            index selection.
        adsorbate_formula_prefer: Preferred end of the structure to match when
            resolving the adsorbate (``"tail"`` or ``"head"``).
        vibrate_indices:    Explicit zero-based atom indices to displace.
        calc_ir:            If ``True``, also compute the dielectric tensor
            (sets LEPSILON and IBRION = 7).

    频率计算参数——前端暴露。

    属性：
        ibrion:                  VASP IBRION 标记（5 = 有限差分，7 = DFPT）。
        potim:                   有限差分步长（Å），对应 POTIM。
        nfree:                   每个原子的位移次数，对应 NFREE。
        vibrate_mode:            原子选择策略：``"inherit"`` 使用 ``vibrate_indices``；
            其他值由 maker 层解释。
        adsorbate_formula:       用于自动选取原子索引的吸附质化学式。
        adsorbate_formula_prefer: 解析吸附质时优先匹配结构的哪一端（``"tail"`` 或 ``"head"``）。
        vibrate_indices:         显式指定的零索引原子下标列表（用于位移计算）。
        calc_ir:                 若为 ``True``，同时计算介电张量（设置 LEPSILON 和
            IBRION = 7）。
    """
    ibrion: int = 5
    potim: float = 0.015
    nfree: int = 2
    vibrate_mode: str = "inherit"
    adsorbate_formula: Optional[str] = None
    adsorbate_formula_prefer: str = "tail"
    vibrate_indices: Optional[List[int]] = None
    calc_ir: bool = False


@dataclass
class LobsterParams:
    """LOBSTER chemical-bonding analysis parameters exposed to the frontend.

    Attributes:
        lobsterin_mode:         Template mode: ``"template"`` (auto-generate) or
            ``"custom"`` (use ``custom_lobsterin``).
        custom_lobsterin:       Full lobsterin content string when
            ``lobsterin_mode="custom"``.
        start_energy:           Lower bound of the energy window (eV).
        end_energy:             Upper bound of the energy window (eV).
        cohp_generator:         COHP bond-length range string passed to lobsterin.
        overwritedict:          Key–value pairs that overwrite the generated
            lobsterin dict before writing.
        custom_lobsterin_lines: Verbatim lines appended to the lobsterin file.

    LOBSTER 化学键分析参数——前端暴露。

    属性：
        lobsterin_mode:         模板模式：``"template"``（自动生成）或
            ``"custom"``（使用 ``custom_lobsterin``）。
        custom_lobsterin:       当 ``lobsterin_mode="custom"`` 时使用的完整
            lobsterin 内容字符串。
        start_energy:           能量窗口下界（eV）。
        end_energy:             能量窗口上界（eV）。
        cohp_generator:         传递给 lobsterin 的 COHP 键长范围字符串。
        overwritedict:          写入前覆盖生成的 lobsterin 字典的键值对。
        custom_lobsterin_lines: 逐字追加到 lobsterin 文件末尾的行列表。
    """
    lobsterin_mode: str = "template"
    custom_lobsterin: Optional[str] = None
    start_energy: float = -20.0
    end_energy: float = 20.0
    cohp_generator: str = "from 1.2 to 1.9 orbitalwise"
    overwritedict: Optional[Dict[str, Any]] = None
    custom_lobsterin_lines: Optional[List[str]] = None


@dataclass
class NBOParams:
    """Natural Bond Orbital (NBO) analysis parameters exposed to the frontend.

    Attributes:
        basis_source:      Basis set identifier (``"ANO-RCC-MB"`` or
            ``"custom"``).
        custom_basis_path: Path to a custom basis set file when
            ``basis_source="custom"``.
        occ_1c:            One-centre occupancy threshold for bond detection.
        occ_2c:            Two-centre occupancy threshold for bond detection.
        print_cube:        Whether to write cube files (``"T"`` / ``"F"``).
        density:           Whether to write density cube (``"T"`` / ``"F"``).
        vis_start:         First orbital index for cube visualisation.
        vis_end:           Last orbital index (``-1`` = last orbital).
        mesh:              Cube-file grid dimensions ``[nx, ny, nz]``.
        box_int:           Integer box extension factors ``[bx, by, bz]``.
        origin_fact:       Fractional origin offset factor.

    自然键轨道（NBO）分析参数——前端暴露。

    属性：
        basis_source:      基组标识符（``"ANO-RCC-MB"`` 或 ``"custom"``）。
        custom_basis_path: 当 ``basis_source="custom"`` 时指向自定义基组文件的路径。
        occ_1c:            单中心占据阈值，用于键的判定。
        occ_2c:            双中心占据阈值，用于键的判定。
        print_cube:        是否输出 cube 文件（``"T"`` / ``"F"``）。
        density:           是否输出密度 cube 文件（``"T"`` / ``"F"``）。
        vis_start:         cube 可视化的起始轨道索引。
        vis_end:           终止轨道索引（``-1`` 表示最后一个轨道）。
        mesh:              cube 文件网格维度 ``[nx, ny, nz]``。
        box_int:           整数盒子扩展因子 ``[bx, by, bz]``。
        origin_fact:       分数原点偏移因子。
    """
    basis_source: str = "ANO-RCC-MB"
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


@dataclass
class MDParams:
    """Molecular dynamics parameters exposed to the frontend.

    Attributes:
        ensemble:        Statistical ensemble — ``"nvt"`` (constant N, V, T)
            or ``"npt"`` (constant N, p, T).
        start_temp:      Starting temperature in K (TEBEG).
        end_temp:        Ending temperature in K (TEEND); equal to
            ``start_temp`` for isothermal runs.
        nsteps:          Total number of MD steps (NSW).
        time_step:       Ionic time step in fs (POTIM); ``None`` uses the
            InputSet default.
        langevin_gamma:  Per-element Langevin friction coefficients (ps⁻¹),
            passed as ``{"Fe": 10.0, …}`` when using the Langevin thermostat.

    分子动力学参数——前端暴露。

    属性：
        ensemble:        统计系综——``"nvt"``（恒定 N、V、T）或
            ``"npt"``（恒定 N、p、T）。
        start_temp:      起始温度（K），对应 TEBEG。
        end_temp:        终止温度（K），对应 TEEND；等温模拟时与 ``start_temp`` 相同。
        nsteps:          MD 总步数，对应 NSW。
        time_step:       离子时间步长（fs），对应 POTIM；``None`` 使用 InputSet 默认值。
        langevin_gamma:  各元素的 Langevin 摩擦系数（ps⁻¹），使用 Langevin
            恒温器时以 ``{"Fe": 10.0, …}`` 形式传入。
    """
    ensemble: str = "nvt"
    start_temp: float = 300.0
    end_temp: float = 300.0
    nsteps: int = 1000
    time_step: Optional[float] = None
    langevin_gamma: Optional[Dict[str, float]] = None


@dataclass
class NEBParams:
    """Nudged Elastic Band (NEB) transition-state search parameters exposed to
    the frontend.

    Attributes:
        n_images:  Number of intermediate images between endpoints.
        use_idpp:  If ``True``, initialise the path with the Image Dependent
            Pair Potential (IDPP) interpolation instead of linear interpolation.

    微动弹性带（NEB）过渡态搜索参数——前端暴露。

    属性：
        n_images:  端点之间的中间像数量。
        use_idpp:  若为 ``True``，使用图像依赖对势（IDPP）内插初始化路径，
            而非线性内插。
    """
    n_images: int = 6
    use_idpp: bool = True


@dataclass
class ResourceParams:
    """Compute resource allocation parameters exposed to the frontend.

    Attributes:
        runtime: Wall-clock time limit in hours.
        cores:   Number of MPI ranks (CPU cores) to request.
        queue:   Scheduler queue / partition name.

    计算资源配置——前端暴露。

    属性：
        runtime: 计算时间上限（小时）。
        cores:   请求的 MPI 进程数（CPU 核心数）。
        queue:   调度器队列/分区名称。
    """
    runtime: int = 72
    cores: int = 72
    queue: str = "low"


# ============================================================================
# 辅助解析函数
# ============================================================================

def _parse_int(value: Any) -> Optional[int]:
    """Safely coerce *value* to ``int``, returning ``None`` on failure.

    Recognises ``None``, empty string, and the em-dash placeholder ``"—"`` as
    absent values.

    安全地将 *value* 转换为 ``int``，失败时返回 ``None``。

    将 ``None``、空字符串以及占位符 ``"—"`` 视为缺失值。
    """
    if value is None or value == "" or value == "—":
        return None
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return None


def _parse_float(value: Any) -> Optional[float]:
    """Safely coerce *value* to ``float``, returning ``None`` on failure.

    Recognises ``None``, empty string, and the em-dash placeholder ``"—"`` as
    absent values.

    安全地将 *value* 转换为 ``float``，失败时返回 ``None``。

    将 ``None``、空字符串以及占位符 ``"—"`` 视为缺失值。
    """
    if value is None or value == "" or value == "—":
        return None
    try:
        return float(str(value))
    except (ValueError, TypeError):
        return None


def _parse_number(value: Any) -> Union[int, float, str]:
    """Safely parse *value* as a number, preferring ``int`` over ``float``.

    Returns the original value unchanged when numeric parsing fails.

    安全地将 *value* 解析为数值，优先返回 ``int``（整型优先）。

    数值解析失败时原样返回原始值。
    """
    if value is None or value == "" or value == "—":
        return value
    try:
        f = float(str(value))
        # Return int when the float is a whole number.
        # 浮点数为整数时返回 int。
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return value


def _parse_number_list(value: Any) -> List[float]:
    """Parse a string or list into a ``List[float]`` for DFT+U legacy format.

    Args:
        value: A ``List``, a space-separated string, or ``None``.

    Returns:
        Parsed list of floats, or an empty list when *value* is ``None``.

    将字符串或列表解析为 ``List[float]``，用于 DFT+U 兼容格式。

    参数：
        value: ``List``、空格分隔的字符串或 ``None``。

    返回：
        解析后的浮点数列表；*value* 为 ``None`` 时返回空列表。
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        return [float(x) for x in value.split()]
    return []


def _parse_magmom_list(value: Any) -> List[float]:
    """Parse a MAGMOM value into a per-site ``List[float]``.

    Handles three input forms:
    - ``List[float]``        — returned directly after float conversion.
    - Space-separated string — split and converted; ``"N*val"`` shorthand is
      expanded (e.g. ``"3*5.0"`` → ``[5.0, 5.0, 5.0]``).
    - Anything else          — returns an empty list.

    将 MAGMOM 值解析为 per-site ``List[float]``。

    支持三种输入形式：
    - ``List[float]``       — float 转换后直接返回。
    - 空格分隔的字符串     — 分割并转换；支持 ``"N*val"`` 简写展开
      （如 ``"3*5.0"`` → ``[5.0, 5.0, 5.0]``）。
    - 其他类型             — 返回空列表。
    """
    if isinstance(value, list):
        return [float(v) for v in value]
    if isinstance(value, str):
        result = []
        for part in value.split():
            if "*" in part:
                # Expand "count*value" shorthand notation.
                # 展开 "count*value" 简写记法。
                count, val = part.split("*")
                result.extend([float(val)] * int(count))
            else:
                result.append(float(part))
        return result
    return []
