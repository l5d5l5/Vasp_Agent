"""
structure/slab.py
=================
BulkToSlabGenerator – generate and trim slabs from a bulk structure.

Public API (kept for backward compatibility with hook.py):
  BulkToSlabGenerator.run_from_dict(config) -> List[Slab]
  BulkToSlabGenerator().generate(**params)   -> BulkToSlabGenerator  (fluent)
  .get_slabs()                               -> List[Slab]
  .get_slab(termination_index)               -> Slab
  .save_slab(slab, filename, fmt, output_dir)
"""
from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from pymatgen.core import Structure
from pymatgen.core.surface import Slab, SlabGenerator, center_slab
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .utils import get_atomic_layers, get_best_structure_path, load_structure, parse_supercell_matrix


class BulkToSlabGenerator:
    """Robust generator for creating slabs from bulk, with layer control and fixation.

    Supports both a fluent chain API and the legacy ``run_from_dict`` static method.
    """

    def __init__(
        self,
        structure_source: Union[Structure, str, Path],
        save_dir: Optional[Union[str, Path]] = None,
        standardize: bool = True,
    ) -> None:
        self.bulk_structure = load_structure(structure_source)
        self.save_dir: Optional[Path] = Path(save_dir) if save_dir else None

        if standardize:
            try:
                sga = SpacegroupAnalyzer(self.bulk_structure, symprec=0.1)
                self.bulk_structure = sga.get_conventional_standard_structure()
            except Exception as exc:
                warnings.warn(f"Standardization failed ({exc}), using original structure.")

        self._slabs: List[Slab] = []

    # ------------------------------------------------------------------
    # Static factory (backward-compatible hook API)
    # ------------------------------------------------------------------

    @staticmethod
    def run_from_dict(config: Dict[str, Any]) -> List[Slab]:
        """Execute a full slab generation pipeline from a config dict.

        Required keys::

            structure_source   – path to bulk structure file/dir
            generate_params    – dict containing at least:
                miller_indices      (int | str | [h,k,l])
                target_layers       (int)

        Optional keys::

            save_dir           – output directory (auto-derived if absent)
            standardize_bulk   – bool, default True
            save_options       – dict: save, filename, filename_prefix, fmt
        """
        source = config.get("structure_source")
        if not source:
            raise ValueError("Config error: 'structure_source' is required.")

        gen_params = config.get("generate_params")
        if not gen_params:
            raise ValueError("Config error: 'generate_params' is required.")
        for key in ("miller_indices", "target_layers"):
            if key not in gen_params or gen_params[key] is None:
                raise ValueError(f"Config error: '{key}' is required in 'generate_params'.")

        # Auto-derive save_dir when not provided
        save_dir = config.get("save_dir")
        save_opts = config.get("save_options", {})
        should_save = save_opts.get("save", True)

        if should_save and not save_dir:
            if isinstance(source, (str, Path)):
                base = Path(source).expanduser().resolve().parent
                hkl = gen_params["miller_indices"]
                hkl_str = "".join(map(str, hkl)) if isinstance(hkl, (list, tuple)) else str(hkl)
                layers = gen_params["target_layers"]
                sc = gen_params.get("supercell_matrix")
                sc_str = (
                    f"{sc[0]}x{sc[1]}" if isinstance(sc, (list, tuple)) else str(sc)
                ) if sc else "1x1"
                save_dir = base / f"slab_{hkl_str}_{layers}L_{sc_str}"
            else:
                raise ValueError(
                    "Config error: 'save_dir' must be provided when 'structure_source' "
                    "is an in-memory Structure object."
                )

        generator = BulkToSlabGenerator(
            structure_source=source,
            save_dir=save_dir,
            standardize=config.get("standardize_bulk", True),
        )

        slabs = generator.generate(**gen_params).get_slabs()

        if should_save and slabs:
            fmt = save_opts.get("fmt", "poscar")
            user_filename = save_opts.get("filename", save_opts.get("filename_prefix", "POSCAR"))
            for i, slab in enumerate(slabs):
                fname = user_filename if len(slabs) == 1 else f"{user_filename}_term{i}"
                generator.save_slab(slab, filename=fname, fmt=fmt)

        return slabs

    # ------------------------------------------------------------------
    # Fluent generation pipeline
    # ------------------------------------------------------------------

    def generate(
        self,
        miller_indices: Union[int, str, Tuple[int, int, int]],
        target_layers: int,
        vacuum_thickness: float = 15.0,
        shift: Optional[float] = None,
        supercell_matrix: Optional[Union[str, Sequence[int]]] = None,
        fix_bottom_layers: int = 0,
        fix_top_layers: int = 0,
        all_fix: bool = False,
        symmetric: bool = False,
        center: bool = True,
        primitive: bool = True,
        lll_reduce: bool = True,
        hcluster_cutoff: float = 0.25,
    ) -> "BulkToSlabGenerator":
        """Generate slabs and store them in ``self._slabs``.  Returns *self* for chaining."""
        hkl = self._normalize_miller_indices(miller_indices)
        sc_mat = parse_supercell_matrix(supercell_matrix) if supercell_matrix else None
        estimated_min = target_layers * 2.5 + 8.0

        slabgen = SlabGenerator(
            self.bulk_structure, hkl,
            min_slab_size=estimated_min,
            min_vacuum_size=vacuum_thickness,
            center_slab=center, primitive=primitive, lll_reduce=lll_reduce,
        )

        if shift is not None:
            raw_slabs = [slabgen.get_slab(shift=shift)]
        else:
            raw_slabs = slabgen.get_slabs(tol=0.1, max_broken_bonds=0)
            if not raw_slabs:
                slabgen2 = SlabGenerator(
                    self.bulk_structure, hkl,
                    min_slab_size=estimated_min * 2,
                    min_vacuum_size=vacuum_thickness,
                    center_slab=center, primitive=primitive, lll_reduce=lll_reduce,
                )
                raw_slabs = slabgen2.get_slabs(tol=0.1, max_broken_bonds=0)
                if not raw_slabs:
                    raise ValueError(f"Failed to generate slabs for miller index {hkl}.")

        processed: List[Slab] = []
        for i, raw in enumerate(raw_slabs):
            try:
                slab = self._trim_to_target_layers(raw, target_layers, symmetric, hcluster_cutoff)
                try:
                    slab = slab.get_orthogonal_c_slab()
                except Exception:
                    pass
                if sc_mat:
                    slab.make_supercell(sc_mat)
                if center:
                    slab = center_slab(slab)
                slab = self._set_selective_dynamics(slab, fix_bottom_layers, fix_top_layers, all_fix, hcluster_cutoff)
                processed.append(slab)
            except ValueError as exc:
                warnings.warn(f"Skipping termination {i}: {exc}")

        self._slabs = processed
        return self

    def get_slabs(self) -> List[Slab]:
        """Return copies of all generated slabs."""
        return [s.copy() for s in self._slabs]

    def get_slab(self, termination_index: int = 0) -> Slab:
        if not self._slabs:
            raise ValueError("No slabs generated yet. Call generate() first.")
        return self._slabs[termination_index].copy()

    def select_termination(self, index: int) -> "BulkToSlabGenerator":
        if not self._slabs:
            raise ValueError("No slabs. Call generate() first.")
        self._slabs = [self._slabs[index]]
        return self

    def make_supercell(self, supercell_matrix: Union[str, Sequence[int], int]) -> "BulkToSlabGenerator":
        matrix = parse_supercell_matrix(supercell_matrix)
        for slab in self._slabs:
            slab.make_supercell(matrix)
        return self

    def set_fixation(
        self,
        fix_bottom_layers: int = 0,
        fix_top_layers: int = 0,
        all_fix: bool = False,
        hcluster_cutoff: float = 0.25,
    ) -> "BulkToSlabGenerator":
        self._slabs = [
            self._set_selective_dynamics(s, fix_bottom_layers, fix_top_layers, all_fix, hcluster_cutoff)
            for s in self._slabs
        ]
        return self

    # ------------------------------------------------------------------
    # Save helper
    # ------------------------------------------------------------------

    def save_slab(
        self,
        slab: Structure,
        filename: Union[str, Path],
        fmt: str = "poscar",
        output_dir: Optional[Union[str, Path]] = None,
    ) -> Path:
        """Write a single slab to disk. Returns the output path."""
        file_path = Path(filename)

        if output_dir:
            target_dir = Path(output_dir)
            out = target_dir / file_path.name
        elif file_path.parent != Path("") and str(file_path.parent) != ".":
            target_dir = file_path.parent
            out = file_path
        elif self.save_dir:
            target_dir = self.save_dir
            out = target_dir / file_path.name
        else:
            target_dir = Path.cwd()
            out = target_dir / file_path.name

        target_dir.mkdir(parents=True, exist_ok=True)

        if fmt.lower() == "poscar":
            Poscar(slab).write_file(str(out))
        else:
            slab.to(filename=str(out), fmt=fmt)

        return out

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _normalize_miller_indices(
        self, miller: Union[int, str, Sequence[int]]
    ) -> Tuple[int, int, int]:
        try:
            if isinstance(miller, int):
                s = str(miller)
                if len(s) == 3:
                    return tuple(int(c) for c in s)  # type: ignore[return-value]
            elif isinstance(miller, str):
                parts = re.findall(r"-?\d+", miller)
                if len(parts) == 3:
                    return tuple(int(p) for p in parts)  # type: ignore[return-value]
                if len(parts) == 1 and len(parts[0]) == 3:
                    return tuple(int(c) for c in parts[0])  # type: ignore[return-value]
            elif isinstance(miller, (list, tuple, np.ndarray)):
                arr = np.array(miller).flatten()
                if len(arr) == 3:
                    return tuple(int(x) for x in arr)  # type: ignore[return-value]
        except Exception:
            pass
        raise ValueError(f"Invalid miller_indices: {miller!r}")

    def _trim_to_target_layers(
        self,
        slab: Slab,
        target_layers: int,
        symmetric: bool = False,
        hcluster_cutoff: float = 0.25,
    ) -> Slab:
        layers = get_atomic_layers(slab, hcluster_cutoff)
        n = len(layers)
        if n < target_layers:
            raise ValueError(f"Slab too thin ({n} layers < target {target_layers}).")
        if n == target_layers:
            return slab

        excess = n - target_layers
        if symmetric:
            remove_bot = excess // 2
            remove_top = excess - remove_bot
            keep = layers[remove_bot: n - remove_top]
        else:
            keep = layers[:target_layers]

        keep_idx = {i for layer in keep for i in layer}
        remove_idx = sorted(set(range(len(slab))) - keep_idx, reverse=True)
        trimmed = slab.copy()
        trimmed.remove_sites(remove_idx)
        return trimmed

    def _set_selective_dynamics(
        self,
        slab: Slab,
        fix_bottom: int,
        fix_top: int,
        all_fix: bool,
        hcluster_cutoff: float = 0.25,
    ) -> Slab:
        n = len(slab)
        if all_fix:
            sd = [[False, False, False]] * n
        else:
            sd = [[True, True, True] for _ in range(n)]
            if fix_bottom > 0 or fix_top > 0:
                layers = get_atomic_layers(slab, hcluster_cutoff)
                nl = len(layers)
                for i in range(min(fix_bottom, nl)):
                    for idx in layers[i]:
                        sd[idx] = [False, False, False]
                for i in range(min(fix_top, nl)):
                    li = nl - 1 - i
                    if li >= 0:
                        for idx in layers[li]:
                            sd[idx] = [False, False, False]

        new_slab = slab.copy()
        new_slab.add_site_property("selective_dynamics", sd)
        return new_slab
