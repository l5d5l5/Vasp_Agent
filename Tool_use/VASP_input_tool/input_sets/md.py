# -*- coding: utf-8 -*-
"""Molecular dynamics input set."""

from pathlib import Path
import logging
from typing import Any, Dict, List, Optional, Union

from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Incar, Kpoints

from ..constants import DEFAULT_INCAR_MD, DEFAULT_INCAR_MD_NPT
from .static import MPStaticSetEcat

logger = logging.getLogger(__name__)


class MDSetEcat(MPStaticSetEcat):
    """
    用于 VASP 分子动力学（MD）计算的输入文件生成器。

    支持两种系综：
    - ``"nvt"``：NVT（正则系综），对应 MPMDSet 风格。
    - ``"npt"``：NPT（等温等压系综），对应 MVLNPTMDSet 风格，使用 Langevin 控温控压。

    Args:
        structure (str | Path | Structure): 输入结构或前序计算目录。
        ensemble (str): MD 系综，``"nvt"`` 或 ``"npt"``。默认 ``"nvt"``。
        start_temp (float): 起始温度（K）。默认 300.0。
        end_temp (float): 终止温度（K），与 start_temp 相同则为恒温 MD。默认 300.0。
        nsteps (int): MD 步数（NSW）。默认 1000。
        time_step (float | None): 时间步长（fs）。为 None 时自动判断：含 H 为 0.5 fs，否则为 2.0 fs。
            NPT 系综时默认 2.0 fs（不自动调整）。
        spin_polarized (bool): 是否开启自旋极化（ISPIN=2）。默认 False。
        langevin_gamma (list[float] | None): NPT 模式下各元素的 Langevin 阻尼系数（LANGEVIN_GAMMA）。
            为 None 时自动设置为 ``[10] * n_elems``。
        functional (str): 交换关联泛函，默认 ``"PBE"``。
        use_default_incar (bool): 是否应用对应系综的默认 INCAR 参数。默认 True。
        user_incar_settings (dict): 用户自定义 INCAR 参数（优先级最高）。
        user_kpoints_settings: 用户自定义 KPOINTS（默认使用 Gamma-only 1×1×1）。
        **extra_kwargs: 其他传递给底层 MPStaticSetEcat 的关键字参数。
    """

    def __init__(
        self,
        structure: Union[str, Structure, Path],
        ensemble: str = "nvt",
        start_temp: float = 300.0,
        end_temp: float = 300.0,
        nsteps: int = 1000,
        time_step: Optional[float] = None,
        spin_polarized: bool = False,
        langevin_gamma: Optional[List[float]] = None,
        functional: str = "PBE",
        use_default_incar: bool = True,
        use_default_kpoints: bool = True,  # accepted but ignored — MD always uses Gamma-only
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        self.ensemble = ensemble.lower()
        self.start_temp = start_temp
        self.end_temp = end_temp
        self.nsteps = nsteps
        self.time_step = time_step
        self.spin_polarized = spin_polarized
        self.langevin_gamma = langevin_gamma

        if self.ensemble not in ("nvt", "npt"):
            raise ValueError(f"MD ensemble must be 'nvt' or 'npt', got '{ensemble}'.")

        loaded_structure = self._load_structure(structure)
        functional = (functional or "PBE").upper()

        # 构建与系综相关的 INCAR 更新
        md_extra = self._build_md_incar(loaded_structure)

        if self.ensemble == "nvt":
            base_default = DEFAULT_INCAR_MD if use_default_incar else None
        else:
            base_default = DEFAULT_INCAR_MD_NPT if use_default_incar else None

        incar = self._build_incar(
            functional,
            base_default,
            extra_incar=md_extra,
            user_incar_settings=user_incar_settings,
        )

        # MD 使用 Gamma-only 1×1×1 k 点
        kpoints = user_kpoints_settings if user_kpoints_settings is not None else Kpoints.gamma_automatic()

        super().__init__(
            structure=loaded_structure,
            functional=functional,
            use_default_incar=False,
            use_default_kpoints=False,
            user_incar_settings=incar,
            user_kpoints_settings=kpoints,
            **extra_kwargs,
        )

    def _build_md_incar(self, structure: Structure) -> Dict[str, Any]:
        """根据系综和参数构建 MD 专属 INCAR 更新字典。"""
        updates: Dict[str, Any] = {
            "TEBEG": self.start_temp,
            "TEEND": self.end_temp,
            "NSW": self.nsteps,
            "ISPIN": 2 if self.spin_polarized else 1,
        }

        if not self.spin_polarized:
            updates["MAGMOM"] = None

        if self.ensemble == "nvt":
            updates["EDIFF_PER_ATOM"] = 0.00001

            if self.time_step is None:
                has_hydrogen = any(el.symbol == "H" for el in structure.composition.elements)
                if has_hydrogen:
                    updates["POTIM"] = 0.5
                    updates["NSW"] = self.nsteps * 4
                else:
                    updates["POTIM"] = 2.0
            else:
                updates["POTIM"] = self.time_step

        else:  # npt
            updates["EDIFF_PER_ATOM"] = 0.000001
            updates["POTIM"] = self.time_step if self.time_step is not None else 2.0

            n_elems = structure.n_elems
            gamma = self.langevin_gamma if self.langevin_gamma is not None else [10.0] * n_elems
            updates["LANGEVIN_GAMMA"] = gamma

            # NPT：ENCUT 设为 1.5 × VASP 默认最大值以消除 Pulay 应力
            updates["_npt_encut_auto"] = True

        return updates

    def write_input(self, output_dir: Union[str, Path], **kwargs):
        """写入 VASP 输入文件；NPT 模式下额外修正 ENCUT。"""
        super().write_input(output_dir, **kwargs)

        if self.ensemble == "npt":
            out_path = Path(output_dir).resolve()
            incar_path = out_path / "INCAR"
            potcar_path = out_path / "POTCAR"

            if incar_path.exists() and potcar_path.exists():
                try:
                    from pymatgen.io.vasp.inputs import Potcar as PmgPotcar
                    potcar = PmgPotcar.from_file(potcar_path)
                    enmax_vals = [p.keywords["ENMAX"] for p in potcar]
                    encut_npt = max(enmax_vals) * 1.5

                    incar = Incar.from_file(incar_path)
                    incar.pop("_npt_encut_auto", None)
                    incar["ENCUT"] = encut_npt
                    incar.write_file(incar_path)
                    logger.info("NPT MD: set ENCUT=%.1f eV (1.5 × ENMAX) in %s", encut_npt, incar_path)
                except Exception as exc:
                    logger.warning("Failed to auto-set NPT ENCUT from POTCAR: %s. Set ENCUT manually.", exc)
            else:
                if incar_path.exists():
                    incar = Incar.from_file(incar_path)
                    incar.pop("_npt_encut_auto", None)
                    incar.write_file(incar_path)

    @classmethod
    def from_prev_calc_ecat(
        cls,
        prev_dir: Union[str, Path],
        ensemble: str = "nvt",
        start_temp: float = 300.0,
        end_temp: float = 300.0,
        nsteps: int = 1000,
        time_step: Optional[float] = None,
        spin_polarized: bool = False,
        langevin_gamma: Optional[List[float]] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
        user_kpoints_settings: Optional[Any] = None,
        **extra_kwargs,
    ):
        """从前序计算目录继承结构与泛函，生成 MD 计算任务。"""
        prev_dir = Path(prev_dir).resolve()
        loaded_structure = cls._load_structure(prev_dir)
        base_incar, functional = cls._read_and_convert_incar(prev_dir / "INCAR", loaded_structure)

        for k in ["IBRION", "NSW", "POTIM", "EDIFF", "EDIFFG", "ISIF",
                  "NPAR", "NCORE", "TEBEG", "TEEND", "SMASS", "ISYM",
                  "ISMEAR", "SIGMA", "NELMIN", "LCHARG", "LWAVE",
                  "EDIFF_PER_ATOM", "MDALGO", "LANGEVIN_GAMMA", "LANGEVIN_GAMMA_L",
                  "PMASS", "PSTRESS", "ENCUT"]:
            base_incar.pop(k, None)

        ensemble_lower = ensemble.lower()
        if ensemble_lower not in ("nvt", "npt"):
            raise ValueError(f"MD ensemble must be 'nvt' or 'npt', got '{ensemble}'.")

        extra_md = DEFAULT_INCAR_MD if ensemble_lower == "nvt" else DEFAULT_INCAR_MD_NPT
        incar = cls._build_incar(
            functional,
            base_incar,
            extra_incar=extra_md,
            user_incar_settings=user_incar_settings,
        )

        kpoints = user_kpoints_settings if user_kpoints_settings is not None else Kpoints.gamma_automatic()

        init_kwargs = extra_kwargs.copy()
        init_kwargs.update(
            {
                "structure": loaded_structure,
                "ensemble": ensemble,
                "start_temp": start_temp,
                "end_temp": end_temp,
                "nsteps": nsteps,
                "time_step": time_step,
                "spin_polarized": spin_polarized,
                "langevin_gamma": langevin_gamma,
                "functional": functional,
                "use_default_incar": False,
                "user_incar_settings": incar,
                "user_kpoints_settings": kpoints,
            }
        )
        return cls(**init_kwargs)
