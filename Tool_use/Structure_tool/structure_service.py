from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

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

    def vacancy(
        self,
        file_path: str,
        element: str,
        dopant: Optional[str] = None,
        num_vacancies: int = 1,
        num_structs: int = 1,
        top_layers: Optional[int] = None,
        random_seed: Optional[int] = None,
        save_dir: str = "./structures",
        filename_prefix: str = "POSCAR_vac",
    ) -> Dict[str, Any]:
        try:
            from .structure_modify import StructureModify
            struct = load_structure(file_path)
            modifier = StructureModify(struct)
            kwargs: Dict[str, Any] = {}
            if top_layers is not None:
                kwargs["top_layers"] = top_layers
            structures = modifier.generate_defects_batch(
                substitute_element=element,
                dopant=dopant,
                dopant_num=num_vacancies,
                num_structs=num_structs,
                random_seed=random_seed,
                **kwargs,
            )
            if not structures:
                return {"error": f"No candidate sites found for element '{element}'.", "success": False}
            saved_files: list = []
            summaries: list = []
            for i, s in enumerate(structures):
                fname = f"{filename_prefix}_{i}"
                saved = _save_poscar(s, save_dir, fname)
                saved_files.append(saved)
                summaries.append(_structure_summary(s))
            return {
                "num_generated": len(structures),
                "structures": summaries,
                "saved_files": saved_files,
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    def adsorption(
        self,
        file_path: str,
        mode: str = "analyze",
        molecule_formula: Optional[str] = None,
        positions: Optional[List[str]] = None,
        save_dir: str = "./structures",
    ) -> Dict[str, Any]:
        try:
            from .adsorption import AdsorptionModify
            if mode == "generate" and not molecule_formula:
                return {"error": "molecule_formula is required for generate mode.", "success": False}
            modifier = AdsorptionModify(slab_source=file_path, save_dir=save_dir)
            if mode == "analyze":
                sites = modifier.analyze(plot=False)
                site_counts = {k: len(v) for k, v in sites.items()}
                site_coords = {
                    k: [list(map(float, arr)) for arr in v]
                    for k, v in sites.items()
                }
                return {
                    "mode": "analyze",
                    "site_counts": site_counts,
                    "site_coords": site_coords,
                    "success": True,
                }
            # mode == "generate"
            find_args: Dict[str, Any] = {}
            if positions:
                find_args["positions"] = positions
            modifier.generate(molecule_formula=molecule_formula, find_args=find_args, plot=False)
            structures = modifier.get_structures()
            if not structures:
                return {"error": "No adsorption structures generated.", "success": False}
            saved_files: List[str] = []
            summaries: List[Dict[str, Any]] = []
            for i, s in enumerate(structures):
                fname = f"POSCAR_{molecule_formula}_{i}"
                saved = _save_poscar(s, save_dir, fname)
                saved_files.append(saved)
                summaries.append(_structure_summary(s))
            return {
                "mode": "generate",
                "molecule": molecule_formula,
                "num_generated": len(structures),
                "structures": summaries,
                "saved_files": saved_files,
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    def particle(
        self,
        element: str,
        mode: str = "wulff",
        lattice_constant: Optional[float] = None,
        lattice_type: Optional[str] = None,
        surface_energies: Optional[Dict[str, float]] = None,
        particle_size: Optional[float] = None,
        layers: Optional[List[int]] = None,
        surfaces: Optional[List[List[int]]] = None,
        p: Optional[int] = None,
        q: Optional[int] = None,
        r: Optional[int] = None,
        n_shells: Optional[int] = None,
        rod_radius: Optional[float] = None,
        rod_length: Optional[float] = None,
        vacuum: float = 15.0,
        save_dir: str = "./structures",
        filename: str = "POSCAR",
    ) -> Dict[str, Any]:
        try:
            from .Particle import ParticleGenerator
            gen = ParticleGenerator(
                element=element,
                lattice_constant=lattice_constant,
                lattice_type=lattice_type,
                save_dir=save_dir,
            )
            if mode == "wulff":
                if not surface_energies:
                    return {"error": "surface_energies required for wulff mode.", "success": False}
                gen.wulff(surface_energies=surface_energies, size=particle_size or 20.0, vacuum=vacuum)
            elif mode == "sphere":
                if particle_size is None:
                    return {"error": "particle_size required for sphere mode.", "success": False}
                gen.sphere(radius=particle_size, vacuum=vacuum)
            elif mode == "octahedron":
                if not layers:
                    return {"error": "layers required for octahedron mode.", "success": False}
                gen.octahedron(layers=layers, vacuum=vacuum)
            elif mode == "decahedron":
                if p is None or q is None or r is None:
                    return {"error": "p, q, r required for decahedron mode.", "success": False}
                gen.decahedron(p=p, q=q, r=r, vacuum=vacuum)
            elif mode == "icosahedron":
                if n_shells is None:
                    return {"error": "n_shells required for icosahedron mode.", "success": False}
                gen.icosahedron(n_shells=n_shells, vacuum=vacuum)
            elif mode == "fcc_cube":
                if not surfaces or not layers:
                    return {"error": "surfaces and layers required for fcc_cube mode.", "success": False}
                gen.fcc_cube(surfaces=surfaces, layers=layers, vacuum=vacuum)
            elif mode == "rod":
                if rod_radius is None or rod_length is None:
                    return {"error": "rod_radius and rod_length required for rod mode.", "success": False}
                gen.rod(radius=rod_radius, length=rod_length, vacuum=vacuum)
            else:
                return {"error": f"Unknown mode: {mode}", "success": False}
            struct = gen.get_structure()
            saved = _save_poscar(struct, save_dir, filename)
            return {
                "element": element,
                "mode": mode,
                "structure": _structure_summary(struct),
                "saved_files": [saved],
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    def slab(
        self,
        file_path: str,
        miller_indices: str,
        target_layers: int,
        vacuum_thickness: float = 15.0,
        supercell_matrix: Optional[str] = None,
        fix_bottom_layers: int = 0,
        fix_top_layers: int = 0,
        termination_index: int = 0,
        save_dir: str = "./structures",
        filename: str = "POSCAR",
    ) -> Dict[str, Any]:
        try:
            from .bulk_to_slab import BulkToSlabGenerator
            gen = BulkToSlabGenerator(file_path, save_dir=save_dir)
            gen.generate(
                miller_indices=miller_indices,
                target_layers=target_layers,
                vacuum_thickness=vacuum_thickness,
                supercell_matrix=supercell_matrix,
                fix_bottom_layers=fix_bottom_layers,
                fix_top_layers=fix_top_layers,
            )
            slabs = gen.get_slabs()
            if not slabs:
                return {"error": "No slabs generated. Try adjusting miller_indices or target_layers.", "success": False}
            idx = min(termination_index, len(slabs) - 1)
            selected = slabs[idx]
            saved = _save_poscar(selected, save_dir, filename)
            return {
                "structure": _structure_summary(selected),
                "miller_indices": miller_indices,
                "target_layers": target_layers,
                "termination_index": idx,
                "num_terminations": len(slabs),
                "saved_files": [saved],
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}
