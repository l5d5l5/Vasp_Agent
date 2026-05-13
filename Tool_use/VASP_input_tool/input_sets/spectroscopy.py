# -*- coding: utf-8 -*-
"""Spectroscopy input sets: LOBSTER, NBO, NMR."""

from pathlib import Path
import logging
from typing import Any, Dict, List, Optional, Union

from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Kpoints
try:
    from pymatgen.io.lobster.sets import LobsterSet
except ImportError:
    from pymatgen.io.vasp.sets import LobsterSet

from ..constants import (
    DEFAULT_INCAR_LOBSTER,
    DEFAULT_INCAR_NBO,
    DEFAULT_INCAR_NMR_CS,
    DEFAULT_INCAR_NMR_EFG,
    DEFAULT_NBO_CONFIG_PARAMS,
    NBO_CONFIG_TEMPLATE,
    NBO_BASIS_PATH,
)
from ._base import VaspInputSetEcat
from .static import MPStaticSetEcat

logger = logging.getLogger(__name__)


class LobsterSetEcat(VaspInputSetEcat, LobsterSet):
    def __init__(
        self,
        structure: Union[str, Structure],
        functional: str = "PBE",
        isym: int = 0,
        ismear: int = -5,
        reciprocal_density: Optional[int] = None,
        user_supplied_basis: Optional[dict] = None,
        use_default_incar: bool = True,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        self.functional = functional.upper()
        self.user_supplied_basis = user_supplied_basis
        loaded_structure = self._load_structure(structure)

        incar = self._build_incar(
            self.functional,
            DEFAULT_INCAR_LOBSTER if use_default_incar else None,
            user_incar_settings=user_incar_settings
        )

        super().__init__(
            structure=loaded_structure,
            isym=isym,
            ismear=ismear,
            reciprocal_density=reciprocal_density,
            user_supplied_basis=user_supplied_basis,
            user_incar_settings=incar,
            user_kpoints_settings=user_kpoints_settings,
            **extra_kwargs,
        )

    def write_input(self, output_dir, overwritedict: Optional[Dict[str, Any]] = None,
                    custom_lobsterin_lines: Optional[List[str]] = None,
                    *args, **kwargs):
        super().write_input(output_dir, *args, **kwargs)
        output_dir = Path(output_dir).resolve()
        from pymatgen.io.lobster.inputs import Lobsterin
        try:
            lb = Lobsterin.standard_calculations_from_vasp_files(
                POSCAR_input=output_dir / "POSCAR",
                INCAR_input=output_dir / "INCAR",
                POTCAR_input=output_dir / "POTCAR",
                dict_for_basis=self.user_supplied_basis,
            )
            if overwritedict:
                lb.update(overwritedict)
            lobsterin_path = output_dir / "lobsterin"
            lb.write_lobsterin(lobsterin_path)
            if custom_lobsterin_lines:
                with open(lobsterin_path, "a", encoding="utf-8") as f:
                    f.write("\n! --- Custom User Lines ---\n")
                    for line in custom_lobsterin_lines:
                        f.write(f"{line}\n")
        except Exception as e:
            logger.warning(f"生成 lobsterin 文件失败: {e}")

    @classmethod
    def from_prev_calc_ecat(
        cls,
        prev_dir: Union[str, Path],
        kpoints_density: int = 50,
        isym: int = 0,
        ismear: int = -5,
        reciprocal_density: Optional[int] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        user_supplied_basis: Optional[dict] = None,
        **extra_kwargs,
    ):
        prev_dir = Path(prev_dir).resolve()
        loaded_structure = cls._load_structure(prev_dir)
        base_incar, functional = cls._read_and_convert_incar(prev_dir / "INCAR", loaded_structure)

        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=DEFAULT_INCAR_LOBSTER,
            user_incar_settings=user_incar_settings,
        )
        if user_kpoints_settings is not None:
            final_kpts = user_kpoints_settings
            final_recip = None
        elif reciprocal_density is not None:
            final_kpts = None
            final_recip = reciprocal_density
        else:
            final_kpts = cls._make_kpoints_from_density(loaded_structure, kpoints_density)
            final_recip = None
        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": loaded_structure,
                "functional": functional,
                "isym": isym,
                "ismear": ismear,
                "reciprocal_density": final_recip,
                "user_supplied_basis": user_supplied_basis,
                "use_default_incar": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": final_kpts,
            }
        )

        return cls(**init_kwargs)


class NBOSetEcat(MPStaticSetEcat):
    """
    用于 VASP-NBO 计算的输入文件生成器。
    支持自动解析全局基组文件，生成严格符合 Fortran 格式的 nbo.config。
    """

    def __init__(
        self,
        structure: Union[str, Structure, Path],
        basis_source: Union[str, Path, Dict[str, str], None] = None,
        nbo_config: Optional[Dict[str, Any]] = None,
        prev_dir: Optional[Union[str, Path]] = None,
        **kwargs,
    ):
        # 1. 初始化 NBO 专属参数
        self.nbo_config_params = {**DEFAULT_NBO_CONFIG_PARAMS, **(nbo_config or {})}
        self.prev_dir = Path(prev_dir).resolve() if prev_dir else None

        loaded_structure = self._load_structure(structure)

        # 2. 解析基组
        if basis_source is None:
            basis_source = NBO_BASIS_PATH
            logger.info(f"Using default basis set from: {basis_source}")

        if isinstance(basis_source, dict):
            self.basis_settings = basis_source
        else:
            logger.info("Parsing master basis set file/string...")
            self.basis_settings = self._parse_basis_file(basis_source)

        elements_in_struct = {str(el) for el in loaded_structure.composition.elements}
        missing_elements = elements_in_struct - set(self.basis_settings.keys())
        if missing_elements:
            raise ValueError(
                f"CRITICAL: Missing basis set definitions for elements: {missing_elements}. "
            )

        use_default = kwargs.pop("use_default_incar", True)
        user_incar = dict(kwargs.pop("user_incar_settings", None) or {})
        functional = kwargs.get("functional", "PBE")
        merged_incar = self._build_incar(
            functional,
            DEFAULT_INCAR_NBO if use_default else None,
            user_incar_settings=user_incar or None,
        )
        super().__init__(
            structure=loaded_structure,
            use_default_incar=False,
            user_incar_settings=merged_incar,
            **kwargs,
        )

        ispin = int(self.incar.get("ISPIN", 1))
        if ispin == 2:
            logger.info("ISPIN=2 detected in INCAR. Halving occ_1c (LP) and occ_2c (DP) cutoffs.")
            for key in ["occ_1c", "occ_2c"]:
                if key in self.nbo_config_params:
                    orig_val = float(self.nbo_config_params[key])
                    new_val = orig_val / 2.0
                    formatted_val = f"{new_val:.3f}".rstrip('0').rstrip('.')
                    self.nbo_config_params[key] = formatted_val
                    logger.debug(f"Adjusted {key}: {orig_val} -> {formatted_val}")

    @classmethod
    def from_prev_calc(
        cls,
        prev_dir: Union[str, Path],
        basis_source: Union[str, Path, Dict[str, str], None] = None,
        nbo_config: Optional[Dict[str, Any]] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        """从前一步计算（如静态计算或优化）继承参数，生成 NBO 计算任务。"""
        prev_dir = Path(prev_dir).resolve()
        loaded_structure = cls._load_structure(prev_dir)
        incar_path = prev_dir / "INCAR"

        if not incar_path.exists():
            raise FileNotFoundError(f"INCAR not found in {prev_dir}")

        base_incar, functional = cls._read_and_convert_incar(incar_path, loaded_structure)

        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=DEFAULT_INCAR_NBO,
            user_incar_settings=user_incar_settings
        )

        kpoints = user_kpoints_settings
        if kpoints is None:
            try:
                kpoints = Kpoints.from_file(prev_dir / "KPOINTS")
                logger.info(f"Inheriting KPOINTS from {prev_dir}")
            except FileNotFoundError:
                logger.warning(f"KPOINTS not found in {prev_dir}, will generate default.")
                kpoints = None

        final_struct = extra_kwargs.pop("structure", loaded_structure)
        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": final_struct,
                "functional": functional,
                "basis_source": basis_source,
                "nbo_config": nbo_config,
                "prev_dir": prev_dir,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": kpoints,
            }
        )

        return cls(**init_kwargs)

    def write_input(self, output_dir: Union[str, Path], **kwargs):
        """写入 VASP 输入文件、NBO 专属文件，并拷贝波函数"""
        super().write_input(output_dir, **kwargs)
        output_dir = Path(output_dir).resolve()

        self._write_nbo_config(output_dir / "nbo.config")
        self._write_basis_inp(output_dir / "basis.inp")

        logger.info(f"NBO specific input files written to {output_dir}")

    @staticmethod
    def _parse_basis_file(source: Union[str, Path]) -> Dict[str, str]:
        basis_dict = {}
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).is_file()):
            with open(source, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        else:
            lines = source.splitlines()

        current_element = None
        current_basis = []

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('!'):
                continue
            if stripped == '****':
                if current_element:
                    basis_dict[current_element] = '\n'.join(current_basis)
                    current_element = None
                    current_basis = []
                continue
            parts = stripped.split()
            if len(parts) == 2 and parts[0].isalpha() and parts[1] == '0' and current_element is None:
                current_element = parts[0].capitalize()
            elif current_element:
                current_basis.append(line.rstrip())

        return basis_dict

    def _write_nbo_config(self, filepath: Path):
        with open(filepath, "w") as f:
            f.write(NBO_CONFIG_TEMPLATE.format(**self.nbo_config_params))

    def _write_basis_inp(self, filepath: Path):
        header = """!----------------------------------------------------------------------
! Basis Set Exchange
! Version 0.12
! https://www.basissetexchange.org
!----------------------------------------------------------------------
!   Basis set: ANO-RCC-MB
! Description: ANO-RCC-MB
!        Role: orbital
!     Version: 1  (Data from OpenMolCAS)
!----------------------------------------------------------------------
"""
        elements_in_struct = [str(el) for el in self.structure.composition.elements]

        with open(filepath, "w") as f:
            f.write(header)
            f.write("****\n")
            for el in elements_in_struct:
                f.write(f"{el}     0\n")
                f.write(self.basis_settings[el] + "\n")
                f.write("****\n")


class NMRSetEcat(MPStaticSetEcat):
    """
    用于 VASP NMR 计算的输入文件生成器。

    支持两种模式：
    - ``"cs"``：化学位移（Chemical Shift），启用 LCHIMAG。
    - ``"efg"``：电场梯度（Electric Field Gradient），启用 LEFG 并自动设置 QUAD_EFG。

    Args:
        structure (str | Path | Structure): 输入结构或前序计算目录。
        mode (str): NMR 计算模式，``"cs"`` 或 ``"efg"``。默认 ``"cs"``。
        isotopes (list[str]): EFG 模式下用于四极矩的同位素列表，格式如 ``["Li-7", "O-17"]``。
            对 CS 模式无效。
        functional (str): 交换关联泛函，默认 ``"PBE"``。
        use_default_incar (bool): 是否应用对应模式的默认 INCAR 参数。默认 True。
        use_default_kpoints (bool): 是否自动生成默认 KPOINTS。默认 True。
        kpoints_density (int): 倒空间 k 点密度（用于 Gamma-centered 网格）。默认 100。
        user_incar_settings (dict): 用户自定义 INCAR 参数（优先级最高）。
        user_kpoints_settings: 用户自定义 KPOINTS 对象。
        **extra_kwargs: 其他传递给底层 MPStaticSetEcat 的关键字参数。
    """

    def __init__(
        self,
        structure: Union[str, Structure, Path],
        mode: str = "cs",
        isotopes: Optional[List[str]] = None,
        functional: str = "PBE",
        use_default_incar: bool = True,
        use_default_kpoints: bool = True,
        kpoints_density: int = 100,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        self.mode = mode.lower()
        self.isotopes = isotopes or []

        if self.mode not in ("cs", "efg"):
            raise ValueError(f"NMR mode must be 'cs' or 'efg', got '{mode}'.")

        loaded_structure = self._load_structure(structure)
        functional = (functional or "PBE").upper()

        # 根据模式选择默认 INCAR 参数
        if self.mode == "cs":
            default_nmr_incar = DEFAULT_INCAR_NMR_CS
        else:
            default_nmr_incar = dict(DEFAULT_INCAR_NMR_EFG)
            # EFG 模式：根据结构自动计算 QUAD_EFG
            if loaded_structure is not None:
                isotope_map = {iso.split("-")[0]: iso for iso in self.isotopes}
                try:
                    from pymatgen.core import Species as PmgSpecies
                    quad_efg = [
                        float(PmgSpecies(sp.name).get_nmr_quadrupole_moment(isotope_map.get(sp.name)))
                        for sp in loaded_structure.species
                    ]
                    default_nmr_incar["QUAD_EFG"] = quad_efg
                except Exception as exc:
                    logger.warning("Failed to auto-calculate QUAD_EFG: %s. Set it manually via user_incar_settings.", exc)

        incar = self._build_incar(
            functional,
            default_nmr_incar if use_default_incar else None,
            user_incar_settings=user_incar_settings,
        )

        kpoints = self._resolve_kpoints(
            loaded_structure,
            use_default_kpoints,
            user_kpoints_settings,
            kpoints_density,
        )

        super().__init__(
            structure=loaded_structure,
            functional=functional,
            use_default_incar=False,
            use_default_kpoints=False,
            user_incar_settings=incar,
            user_kpoints_settings=kpoints,
            **extra_kwargs,
        )

    @classmethod
    def from_prev_calc_ecat(
        cls,
        prev_dir: Union[str, Path],
        mode: str = "cs",
        isotopes: Optional[List[str]] = None,
        kpoints_density: int = 100,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        """从前序计算目录继承结构与 INCAR，生成 NMR 计算任务。"""
        prev_dir = Path(prev_dir).resolve()
        loaded_structure = cls._load_structure(prev_dir)
        base_incar, functional = cls._read_and_convert_incar(prev_dir / "INCAR", loaded_structure)

        for k in ["IBRION", "NSW", "POTIM", "EDIFF", "EDIFFG", "ISIF", "NPAR", "NCORE",
                  "LCHIMAG", "LEFG", "QUAD_EFG", "LNMR_SYM_RED", "NLSPLINE"]:
            base_incar.pop(k, None)

        mode_lower = mode.lower()
        if mode_lower not in ("cs", "efg"):
            raise ValueError(f"NMR mode must be 'cs' or 'efg', got '{mode}'.")

        if mode_lower == "cs":
            extra_nmr = dict(DEFAULT_INCAR_NMR_CS)
        else:
            extra_nmr = dict(DEFAULT_INCAR_NMR_EFG)
            isotopes = isotopes or []
            isotope_map = {iso.split("-")[0]: iso for iso in isotopes}
            try:
                from pymatgen.core import Species as PmgSpecies
                quad_efg = [
                    float(PmgSpecies(sp.name).get_nmr_quadrupole_moment(isotope_map.get(sp.name)))
                    for sp in loaded_structure.species
                ]
                extra_nmr["QUAD_EFG"] = quad_efg
            except Exception as exc:
                logger.warning("Failed to auto-calculate QUAD_EFG: %s. Set it manually via user_incar_settings.", exc)

        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=extra_nmr,
            user_incar_settings=user_incar_settings,
        )

        kpoints = user_kpoints_settings
        if kpoints is None:
            try:
                kpoints = Kpoints.from_file(prev_dir / "KPOINTS")
            except FileNotFoundError:
                logger.warning("KPOINTS not found in %s, generating default with density=%d.", prev_dir, kpoints_density)
                kpoints = cls._make_kpoints_from_density(loaded_structure, kpoints_density)

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": loaded_structure,
                "mode": mode,
                "isotopes": isotopes,
                "functional": functional,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": kpoints,
            }
        )
        return cls(**init_kwargs)
