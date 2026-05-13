# -*- coding: utf-8 -*-
"""Base class for all ECAT-style VASP input sets."""

from pathlib import Path
import logging
from typing import Any, Dict, Optional, Sequence, Union

from pymatgen.core import Structure
from pymatgen.io.vasp.inputs import Incar, Kpoints

from ..constants import BEEF_INCAR_SETTINGS
from ..kpoints import build_kpoints_by_lengths
from ..utils import (
    convert_vasp_format_to_pymatgen_dict,
    infer_functional_from_incar,
    load_structure,
)

logger = logging.getLogger(__name__)


class VaspInputSetEcat:
    """Shared helper methods for ECAT-style VASP input sets."""

    @staticmethod
    def _load_structure(struct_source: Union[str, Path, Structure]) -> Structure:
        return load_structure(struct_source)

    def write_input(self, output_dir: Union[str, Path], *args: Any, **kwargs: Any):
        """Wrap write_input to enforce safe LDAU behavior and clean INCAR metadata.

        Post-processing steps:
        1. Remove pymatgen metadata comments (@CLASS / @MODULE lines).
        2. Force LDAU=False when no U values are provided.
        """
        result = super().write_input(output_dir, *args, **kwargs)

        out_path  = Path(output_dir)
        incar_path = out_path / "INCAR"

        if incar_path.exists():
            # ── Step 1：过滤 pymatgen 自动写入的元数据注释行 ──────────────────
            raw_lines = incar_path.read_text(encoding="utf-8").splitlines()
            clean_lines = [
                line for line in raw_lines
                if not line.strip().startswith(("@CLASS", "@MODULE"))
            ]
            incar_path.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")

            # ── Step 2：重新读取清理后的 INCAR，检查 LDAU ─────────────────────
            incar = Incar.from_file(incar_path)
            if self._should_disable_ldau(incar):
                logger.warning(
                    "Detected LDAU=True in written INCAR without any LDAUL/LDAUU/LDAUJ; "
                    "forcing LDAU=False."
                )
                incar["LDAU"] = False
                incar.write_file(incar_path)

                # LDAU 修改后再次清理元数据（write_file 会重新写入）
                raw_lines = incar_path.read_text(encoding="utf-8").splitlines()
                clean_lines = [
                    line for line in raw_lines
                    if not line.strip().startswith(("@CLASS", "@MODULE"))
                ]
                incar_path.write_text("\n".join(clean_lines) + "\n", encoding="utf-8")

        return result

    @classmethod
    def _build_incar(
        cls, functional: str,
        default_incar: Optional[Dict[str, Any]] = None,
        extra_incar: Optional[Dict[str, Any]] = None,
        user_incar_settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build INCAR dict, optionally applying defaults and user overrides."""

        incar: Dict[str, Any] = {}
        if default_incar:
            incar.update(default_incar)

        if "BEEF" in functional.upper():
            incar.update(BEEF_INCAR_SETTINGS)

        if extra_incar:
            incar.update(extra_incar)

        if user_incar_settings:
            incar.update(user_incar_settings)

        # 如果用户开启了 LDAU，但未提供 U 值列表，则告警并将 LDAU 设为 False（等同于未开启 +U）。
        if cls._should_disable_ldau(incar):
            logger.warning(
                "LDAU=True but no LDAUL/LDAUU/LDAUJ provided; setting LDAU=False (no +U)."
            )
            incar["LDAU"] = False

        return incar

    @staticmethod
    def _should_disable_ldau(incar: Dict[str, Any]) -> bool:
        """Determine whether we should turn off LDAU when no U values are provided."""
        if not incar.get("LDAU"):
            return False

        # 允许多种布尔写法
        val = incar.get("LDAU")
        if isinstance(val, str):
            val = val.strip().upper()
            if val in {"FALSE", ".FALSE.", "0"}:
                return False

        # 如果存在任何有效的 U 相关字段，我们认为是有意使用 +U
        def is_valid_u_list(value: Any) -> bool:
            if value is None:
                return False
            if isinstance(value, (list, tuple)) and len(value) == 0:
                return False
            if isinstance(value, str) and value.strip() == "":
                return False
            return True

        for k in ("LDAUL", "LDAUU", "LDAUJ"):
            if k in incar and is_valid_u_list(incar[k]):
                return False

        return True

    @classmethod
    def _resolve_kpoints(
        cls,
        structure: Structure,
        use_default_kpoints: bool,
        user_kpoints_settings: Optional[Any],
        default_density: Union[int, float, Sequence[float]],
    ) -> Optional[Kpoints]:
        if user_kpoints_settings is not None:
            return user_kpoints_settings
        if use_default_kpoints:
            return cls._make_kpoints_from_density(structure, default_density, style=2)
        return None

    @classmethod
    def _read_and_convert_incar(
        cls, incar_path: Union[str, Path], structure: Structure
    ) -> tuple[Dict[str, Any], str]:
        incar_path = Path(incar_path)
        incar = {
            **(Incar.from_file(incar_path).as_dict() if incar_path.exists() else {})
        }
        functional = infer_functional_from_incar(incar)

        format_keys = ["MAGMOM", "LDAUU", "LDAUJ", "LDAUL"]
        converted_params: Dict[str, Any] = {}
        for key in format_keys:
            value = incar.get(key)
            if value is None or isinstance(value, dict):
                continue
            conversion_result = convert_vasp_format_to_pymatgen_dict(structure, key, value)
            if conversion_result:
                converted_params.update(conversion_result)
        for key in format_keys:
            incar.pop(key, None)
        incar.update(converted_params)

        return incar, functional

    @classmethod
    def _make_kpoints_from_density(
        cls,
        structure: Structure,
        kpoints_density: Optional[Union[int, float, Sequence[float]]],
        style: int = 2,
    ) -> Optional[Kpoints]:
        if kpoints_density is None:
            return None
        if isinstance(kpoints_density, (int, float)):
            densities = [float(kpoints_density)] * 3
        elif isinstance(kpoints_density, (list, tuple)) and len(kpoints_density) == 3:
            densities = [float(x) for x in kpoints_density]
        else:
            raise ValueError("kpoints_density must be a number or a sequence of 3 numbers.")
        return build_kpoints_by_lengths(structure=structure, length_densities=densities, style=style)
