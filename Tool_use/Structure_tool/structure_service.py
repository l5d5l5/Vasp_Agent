from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .utils.structure_utils import load_structure, parse_supercell_matrix


def _structure_summary(struct: Structure) -> Dict[str, Any]:
    lat = struct.lattice
    comp = struct.composition
    try:
        sga = SpacegroupAnalyzer(struct, symprec=0.1)
        sg = sga.get_space_group_symbol()
    except Exception:
        sg = "Unknown"
    cell_type = "slab" if lat.c > max(lat.a, lat.b) * 1.5 else "bulk"
    return {
        "formula": comp.formula.replace(" ", ""),
        "reduced_formula": comp.reduced_formula,
        "nsites": len(struct),
        "a": round(lat.a, 4),
        "b": round(lat.b, 4),
        "c": round(lat.c, 4),
        "alpha": round(lat.alpha, 4),
        "beta": round(lat.beta, 4),
        "gamma": round(lat.gamma, 4),
        "volume": round(lat.volume, 4),
        "space_group": sg,
        "cell_type": cell_type,
    }


def _save_poscar(struct: Structure, save_dir: str, filename: str) -> str:
    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    with open(out_path, "wt", encoding="utf-8") as f:
        f.write(Poscar(struct).get_str())
    return str(out_path.resolve())


class StructureService:

    def load(self, file_path: str) -> Dict[str, Any]:
        try:
            struct = load_structure(file_path)
            return _structure_summary(struct)
        except Exception as e:
            return {"error": str(e)}

    def supercell(
        self,
        file_path: str,
        supercell_matrix: str,
        save_dir: str = "./structures",
        filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            struct = load_structure(file_path)
            matrix = parse_supercell_matrix(supercell_matrix)
            struct.make_supercell(matrix)
            if filename is None:
                formula = struct.composition.formula.replace(" ", "")
                filename = f"POSCAR_{formula}_{supercell_matrix}"
            saved = _save_poscar(struct, save_dir, filename)
            return {
                "structure": _structure_summary(struct),
                "supercell_matrix": supercell_matrix,
                "saved_files": [saved],
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}
