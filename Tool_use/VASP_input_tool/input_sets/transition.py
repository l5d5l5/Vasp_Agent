# -*- coding: utf-8 -*-
"""Transition-state and frequency input sets: NEB, Freq, Dimer."""

from pathlib import Path
import logging
import subprocess
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Union

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Incar, Kpoints
from pymatgen.io.vasp.sets import NEBSet

from ..constants import DEFAULT_INCAR_DIMER, DEFAULT_INCAR_FREQ, DEFAULT_INCAR_NEB
from ._base import VaspInputSetEcat
from .static import MPStaticSetEcat

logger = logging.getLogger(__name__)


class NEBSetEcat(VaspInputSetEcat, NEBSet):
    def __init__(
        self,
        start_structure: Union[str, Path, Structure],
        end_structure: Union[str, Path, Structure],
        n_images: int = 6,
        intermediate_structures: Optional[List[Structure]] = None,
        functional: str = "PBE",
        use_default_incar: bool = True,
        use_idpp: bool = True,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        # 避免重复读取已是 Structure 对象的情况
        start_structure = (
            start_structure
            if isinstance(start_structure, Structure)
            else self._load_structure(start_structure)
        )
        end_structure = (
            end_structure
            if isinstance(end_structure, Structure)
            else self._load_structure(end_structure)
        )
        self.functional = functional.upper()

        # ── 插值生成中间像 ────────────────────────────────────────────────
        if intermediate_structures is None:
            if use_idpp:
                try:
                    from pymatgen.analysis.diffusion.neb.pathfinder import IDPPSolver
                    solver = IDPPSolver.from_endpoints(
                        [start_structure, end_structure],
                        n_images=n_images + 2,
                        sort_tol=0.1,
                    )
                    intermediate_structures = solver.run(
                        maxiter=2000, tol=1e-5, species=start_structure.species
                    )
                except Exception as e:
                    logger.warning(
                        "IDPPSolver failed (%s). Falling back to linear interpolation.", e
                    )
                    intermediate_structures = start_structure.interpolate(
                        end_structure, n_images + 1
                    )
            else:
                intermediate_structures = start_structure.interpolate(
                    end_structure, n_images + 1
                )

        # ── 合并 INCAR ────────────────────────────────────────────────────
        incar = self._build_incar(
            self.functional,
            DEFAULT_INCAR_NEB if use_default_incar else None,
            user_incar_settings=user_incar_settings,
        )

        # ── MAGMOM 格式保护 ───────────────────────────────────────────────
        # pymatgen NEBSet.incar (sets.py:614) 对 MAGMOM 调用 .get(sym, 0)，
        # 要求为 Dict[str, float]；list/str 会触发 AttributeError。
        if "MAGMOM" in incar and not isinstance(incar["MAGMOM"], dict):
            mag_val = incar["MAGMOM"]
            mag_list: List[float] = []

            if isinstance(mag_val, (list, tuple)):
                mag_list = [float(v) for v in mag_val]
            elif isinstance(mag_val, str):
                for token in mag_val.split():
                    if "*" in token:
                        count, val = token.split("*", 1)
                        mag_list.extend([float(val)] * int(count))
                    else:
                        mag_list.append(float(token))

            if mag_list:
                per_elem: Dict[str, List[float]] = {}
                for idx, site in enumerate(start_structure):
                    v = mag_list[idx] if idx < len(mag_list) else mag_list[-1]
                    per_elem.setdefault(site.species_string, []).append(v)
                incar["MAGMOM"] = {k: sum(v) / len(v) for k, v in per_elem.items()}
                logger.debug(
                    "NEBSetEcat: converted MAGMOM → per-element dict: %s",
                    incar["MAGMOM"],
                )
            else:
                incar.pop("MAGMOM", None)
                logger.warning(
                    "NEBSetEcat: failed to parse MAGMOM value '%s'; tag removed.",
                    mag_val,
                )

        # ── 传入 pymatgen NEBSet ──────────────────────────────────────────
        super().__init__(
            structures=intermediate_structures,
            user_incar_settings=incar,
            user_kpoints_settings=user_kpoints_settings,
            **extra_kwargs,
        )

    @classmethod
    def from_prev_calc(
        cls,
        prev_dir: Union[str, Path],
        start_structure: Union[str, Path, Structure],
        end_structure: Union[str, Path, Structure],
        n_images: int = 6,
        use_idpp: bool = True,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **kwargs,
    ) -> "NEBSetEcat":
        prev_dir = Path(prev_dir)

        start_struct = (
            start_structure
            if isinstance(start_structure, Structure)
            else cls._load_structure(start_structure)
        )

        inherited_incar, functional = cls._read_and_convert_incar(
            prev_dir / "INCAR",
            structure=start_struct,
        )

        merged_incar = {**inherited_incar, **(user_incar_settings or {})}

        return cls(
            start_structure=start_struct,
            end_structure=end_structure,
            n_images=n_images,
            use_idpp=use_idpp,
            functional=functional,
            use_default_incar=True,
            user_incar_settings=merged_incar,
            user_kpoints_settings=user_kpoints_settings,
            **kwargs,
        )


class FreqSetEcat(MPStaticSetEcat):
    @staticmethod
    def _apply_vibrate_indices(structure: Structure, vibrate_indices: List[int]) -> Structure:
        n = len(structure)
        bad = [i for i in vibrate_indices if (not isinstance(i, int)) or i < 0 or i >= n]
        if bad:
            raise IndexError(f"vibrate_indices out of range for {n} sites: {bad}")

        structure = structure.copy()
        sel_dyn = [[False, False, False] for _ in range(n)]
        for idx in vibrate_indices:
            sel_dyn[idx] = [True, True, True]

        structure.add_site_property("selective_dynamics", sel_dyn)
        return structure

    def __init__(
        self,
        structure: Union[str, Structure, Path],
        functional: str = "PBE",
        use_default_incar: bool = True,
        use_default_kpoints: bool = False,
        kpoints_density: Optional[Union[int, float]] = None,
        calc_ir: bool = False,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        loaded_structure = self._load_structure(structure)
        functional = (functional or "PBE").upper()
        ir_tags = {"LEPSILON": True, "NWRITE": 3, "IBRION": 7} if calc_ir else {}
        base_freq_incar = {**DEFAULT_INCAR_FREQ, **ir_tags}
        incar = self._build_incar(
            functional,
            base_freq_incar if use_default_incar else None,
            user_incar_settings=user_incar_settings
        )

        kpoints = self._resolve_kpoints(
            loaded_structure, use_default_kpoints, user_kpoints_settings, kpoints_density or 25
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
        structure: Optional[Union[str, Structure, Path]] = None,
        vibrate_indices: Optional[List[int]] = None,
        calc_ir: bool = False,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        prev_dir = Path(prev_dir).resolve()
        if structure is None:
            loaded_structure = cls._load_structure(prev_dir)
        else:
            loaded_structure = cls._load_structure(structure)

        if vibrate_indices is not None:
            loaded_structure = cls._apply_vibrate_indices(loaded_structure, vibrate_indices)

        base_incar, functional = cls._read_and_convert_incar(prev_dir / "INCAR", loaded_structure)

        for k in ["IBRION", "NSW", "POTIM", "EDIFF", "EDIFFG", "ISIF", "NPAR", "NCORE"]:
            base_incar.pop(k, None)
        ir_tags = {"LEPSILON": True, "NWRITE": 3, "IBRION": 7} if calc_ir else {}
        extra_incar_combined = {**DEFAULT_INCAR_FREQ, **ir_tags}
        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=extra_incar_combined,
            user_incar_settings=user_incar_settings
        )

        kpoints = user_kpoints_settings
        if kpoints is None:
            try:
                kpoints = Kpoints.from_file(prev_dir / "KPOINTS")
            except FileNotFoundError:
                logger.warning(f"KPOINTS not found in {prev_dir}, will generate default.")
                kpoints = None

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": loaded_structure,
                "functional": functional,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": kpoints,
            }
        )

        return cls(**init_kwargs)


class DimerSetEcat(MPStaticSetEcat):
    """
    通过调用底层 VTST 脚本生成 Dimer 计算输入文件。
    自动读取 IMAGES、补全端点 OUTCAR、覆盖 POSCAR。
    """

    def __init__(
        self,
        structure: Union[str, Structure, Path],
        modecar: Union[str, Path, np.ndarray],
        **kwargs,
    ):
        if modecar is None:
            raise ValueError("CRITICAL ERROR: 'modecar' must be provided! ")
        if isinstance(modecar, (str, Path)):
            modecar_path = Path(modecar).resolve()
            if not modecar_path.exists():
                raise FileNotFoundError(f"Provided MODECAR file does not exist: {modecar_path}")
            self.modecar_data = np.loadtxt(modecar_path)
        elif isinstance(modecar, np.ndarray):
            self.modecar_data = modecar
        else:
            raise TypeError("'modecar' must be either a numpy array or a valid file path.")

        use_default = kwargs.pop("use_default_incar", True)
        user_incar = dict(kwargs.pop("user_incar_settings", None) or {})
        functional = kwargs.get("functional", "PBE")
        merged_incar = self._build_incar(
            functional,
            DEFAULT_INCAR_DIMER if use_default else None,
            user_incar_settings=user_incar or None,
        )
        super().__init__(
            structure=structure,
            use_default_incar=False,
            user_incar_settings=merged_incar,
            **kwargs,
        )

    def write_input(self, output_dir: Union[str, Path], **kwargs):
        super().write_input(output_dir, **kwargs)

        modecar_path = Path(output_dir) / "MODECAR"
        with open(modecar_path, "w") as f:
            for row in self.modecar_data:
                f.write(f"{row[0]:.8f} {row[1]:.8f} {row[2]:.8f}\n")
        logger.info(f"MODECAR successfully written to {modecar_path}")

    @classmethod
    def from_neb_calc(
        cls,
        neb_dir: Union[str, Path],
        num_images: Optional[int] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        neb_dir = Path(neb_dir).resolve()
        incar_path = neb_dir / "INCAR"

        if num_images is not None:
            logger.info(f"User specified num_images={num_images}. Skipping INCAR reading.")
        else:
            logger.info("Auto mode: Reading INCAR to determine IMAGES...")
            if not incar_path.exists():
                raise FileNotFoundError(f"INCAR not found in {neb_dir}")

            neb_incar = Incar.from_file(incar_path)
            raw_images = neb_incar.get("IMAGES")

            if raw_images is None:
                raise ValueError("IMAGES tag not found in INCAR. Is this a valid NEB directory?")

            if isinstance(raw_images, str):
                clean_images = raw_images.split('#')[0].split('!')[0].strip()
            else:
                clean_images = raw_images

            try:
                num_images = int(clean_images)
            except ValueError:
                raise ValueError(f"Failed to parse IMAGES value '{raw_images}' as an integer.")

        num2 = num_images + 1

        logger.info("Creating a temporary sandbox to protect original NEB directory...")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            if incar_path.exists():
                shutil.copy(incar_path, tmp_path / "INCAR")
            for i in range(num2 + 1):
                src_d = neb_dir / f"{i:02d}"
                dst_d = tmp_path / f"{i:02d}"
                dst_d.mkdir()

                outcar_src = src_d / "OUTCAR"
                if not outcar_src.exists():
                    outcar_src = src_d / "OUTCAR.gz"
                if not outcar_src.exists():
                    if i == 0:
                        outcar_src = neb_dir / "01" / "OUTCAR"
                    elif i == num2:
                        outcar_src = neb_dir / f"{num_images:02d}" / "OUTCAR"
                if outcar_src.exists():
                    shutil.copy(outcar_src, dst_d / "OUTCAR")

                contcar_src = src_d / "CONTCAR"
                if not contcar_src.exists():
                    contcar_src = src_d / "CONTCAR.gz"

                if contcar_src.exists() and contcar_src.stat().st_size > 0:
                    shutil.copy(contcar_src, dst_d / "POSCAR")
                else:
                    poscar_src = src_d / "POSCAR"
                    if poscar_src.exists():
                        shutil.copy(poscar_src, dst_d / "POSCAR")

            try:
                logger.info("Running nebresults.pl in sandbox...")
                subprocess.run(["nebresults.pl"], cwd=tmp_path, check=True, capture_output=True)

                logger.info("Running neb2dim.pl in sandbox...")
                subprocess.run(["neb2dim.pl"], cwd=tmp_path, check=True, capture_output=True)
            except FileNotFoundError:
                raise RuntimeError("VTST scripts (nebresults.pl, neb2dim.pl) not found in system PATH.")
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"VTST script execution failed in sandbox:\n{e.stderr.decode()}")

            dim_dir = tmp_path / "dim"
            if not dim_dir.exists():
                raise FileNotFoundError(f"neb2dim.pl failed to create the 'dim' directory in sandbox.")

            saddle_struct = cls._load_structure(dim_dir / "POSCAR")

            modecar_file = dim_dir / "MODECAR"
            if not modecar_file.exists():
                raise FileNotFoundError(f"MODECAR not found in sandbox.")
            modecar_data = np.loadtxt(modecar_file)
            logger.info("Sandbox cleaned up successfully. Original NEB directory is untouched.")

        base_incar, functional = cls._read_and_convert_incar(incar_path, saddle_struct)

        tags_to_remove = [
            "IMAGES", "SPRING", "LCLIMB", "ICHAIN",
            "IBRION", "NSW", "POTIM", "EDIFF", "IOPT", "##NEB"
        ]
        for tag in tags_to_remove:
            base_incar.pop(tag, None)

        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=DEFAULT_INCAR_DIMER,
            user_incar_settings=user_incar_settings
        )

        kpoints = user_kpoints_settings
        if kpoints is None:
            try:
                kpoints = Kpoints.from_file(neb_dir / "KPOINTS")
            except FileNotFoundError:
                logger.warning(f"KPOINTS not found in {neb_dir}, will generate default.")
                kpoints = None

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": saddle_struct,
                "functional": functional,
                "use_default_incar": False,
                "use_default_kpoints": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": kpoints,
                "modecar": modecar_data,
            }
        )

        return cls(**init_kwargs)
