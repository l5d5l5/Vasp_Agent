# -*- coding: utf-8 -*-
"""Static (single-point) input set."""

from pathlib import Path
import logging
from typing import Any, Dict, Optional, Union

from pymatgen.core import Structure
from pymatgen.io.vasp.sets import MPStaticSet

from ..constants import DEFAULT_INCAR_STATIC
from ._base import VaspInputSetEcat

logger = logging.getLogger(__name__)


class MPStaticSetEcat(VaspInputSetEcat, MPStaticSet):
    """单点计算（MPStaticSet + ECAT 默认值）。"""

    def __init__(
        self,
        structure: Union[str, Structure],
        functional: str = "PBE",
        use_default_incar: bool = True,
        use_default_kpoints: bool = True,
        number_of_docs: Optional[int] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        self.functional = functional.upper()
        loaded_structure = self._load_structure(structure)

        extra_incar = {"NEDOS": number_of_docs} if number_of_docs is not None else None
        incar = self._build_incar(
            self.functional,
            DEFAULT_INCAR_STATIC if use_default_incar else None,
            extra_incar=extra_incar,
            user_incar_settings=user_incar_settings
        )

        kpoints = self._resolve_kpoints(
            loaded_structure, use_default_kpoints, user_kpoints_settings, [40, 40, 40]
        )

        super().__init__(
            structure=loaded_structure,
            user_incar_settings=incar,
            user_kpoints_settings=kpoints,
            **extra_kwargs,
        )

    @classmethod
    def from_prev_calc_ecat(
        cls,
        prev_dir: Union[str, Path],
        kpoints_density: int = 50,
        number_of_docs: Optional[int] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        prev_dir = Path(prev_dir).resolve()
        loaded_structure = cls._load_structure(prev_dir)
        base_incar, functional = cls._read_and_convert_incar(prev_dir / "INCAR", loaded_structure)

        # 从 prev INCAR 继承全部设置，然后用静态计算的默认值覆盖（比如 IBRION/NSW）
        merged_incar = {**base_incar, **DEFAULT_INCAR_STATIC}
        if user_incar_settings:
            merged_incar.update(user_incar_settings)

        if number_of_docs is not None:
            merged_incar["NEDOS"] = int(number_of_docs)

        incar = cls._build_incar(functional, None, user_incar_settings=merged_incar)

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": loaded_structure,
                "functional": functional,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "number_of_docs": number_of_docs,
                "user_incar_settings": incar,
                "user_kpoints_settings": user_kpoints_settings
                or cls._make_kpoints_from_density(loaded_structure, kpoints_density),
            }
        )
        return cls(**init_kwargs)
