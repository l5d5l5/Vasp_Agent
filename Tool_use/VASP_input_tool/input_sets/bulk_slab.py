# -*- coding: utf-8 -*-
"""Bulk relaxation and slab input sets."""

from pathlib import Path
import logging
from typing import Any, Dict, Optional, Union

from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Kpoints
from pymatgen.io.vasp.sets import MPMetalRelaxSet, MVLSlabSet

from ..constants import DEFAULT_INCAR_BULK, DEFAULT_INCAR_SLAB
from ._base import VaspInputSetEcat

logger = logging.getLogger(__name__)


class SlabSetEcat(VaspInputSetEcat, MVLSlabSet):
    """Slab 计算输入集（MVLSlabSet + ECAT 默认值）。"""

    def __init__(
        self,
        structure: Union[str, Structure],
        functional: str = "PBE",
        kpoints_density: int = 25,
        use_default_incar: bool = True,
        use_default_kpoints: bool = True,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        auto_dipole: bool = True,
        **extra_kwargs,
    ):
        loaded_structure = self._load_structure(structure)
        self.functional = functional.upper()

        incar = self._build_incar(
            self.functional,
            DEFAULT_INCAR_SLAB if use_default_incar else None,
            user_incar_settings=user_incar_settings,
        )

        kpoints = self._resolve_kpoints(
            loaded_structure, use_default_kpoints,
            user_kpoints_settings, [kpoints_density, kpoints_density, 1]
        )

        super().__init__(
            structure=loaded_structure,
            auto_dipole=auto_dipole,
            user_incar_settings=incar,
            user_kpoints_settings=kpoints,
            **extra_kwargs,
        )

    @classmethod
    def ads_from_prev_calc(
        cls,
        structure: Union[str, Structure],
        prev_dir: Union[str, Path],
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        auto_dipole: bool = True,
        **extra_kwargs,
    ):
        prev_dir = Path(prev_dir).resolve()
        incar_path = prev_dir / "INCAR"
        if not incar_path.exists():
            raise FileNotFoundError(f"INCAR not found in prev_dir: {prev_dir}")

        loaded_prev_structure = Structure.from_file(
            prev_dir / "CONTCAR" if (prev_dir / "CONTCAR").exists() else prev_dir / "POSCAR"
        )

        base_incar, functional = cls._read_and_convert_incar(incar_path, loaded_prev_structure)

        kpoints = user_kpoints_settings
        if kpoints is None and (prev_dir / "KPOINTS").exists():
            kpoints = Kpoints.from_file(prev_dir / "KPOINTS")

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "functional": functional,
                "structure": structure,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "auto_dipole": auto_dipole,
                "user_incar_settings": cls._build_incar(functional, base_incar, user_incar_settings=user_incar_settings),
                "user_kpoints_settings": kpoints,
            }
        )

        return cls(**init_kwargs)


class BulkRelaxSetEcat(VaspInputSetEcat, MPMetalRelaxSet):
    """Bulk 结构松弛输入集（MPMetalRelaxSet + ECAT 默认值）。"""

    def __init__(
        self,
        structure: Union[str, Structure],
        functional: str = "PBE",
        is_metal: bool = True,
        kpoints_density: int = 25,
        use_default_incar: bool = True,
        use_default_kpoints: bool = True,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        self.functional = functional.upper()
        loaded_structure = self._load_structure(structure)

        extra_incar = {"ISMEAR": 1, "SIGMA": 0.20} if is_metal else {"ISMEAR": 0, "SIGMA": 0.05}
        incar = self._build_incar(
            self.functional,
            DEFAULT_INCAR_BULK if use_default_incar else None,
            extra_incar=extra_incar,
            user_incar_settings=user_incar_settings
        )

        kpoints = self._resolve_kpoints(
            loaded_structure, use_default_kpoints, user_kpoints_settings, kpoints_density
        )

        super().__init__(
            structure=loaded_structure,
            user_incar_settings=incar,
            user_kpoints_settings=kpoints,
            **extra_kwargs,
        )
