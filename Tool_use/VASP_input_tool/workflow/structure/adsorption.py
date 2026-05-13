"""
structure/adsorption.py
=======================
AdsorptionModify – adsorption site finder and structure builder.

Extends pymatgen's AdsorbateSiteFinder with:
  - Universal structure input (path / dir / in-memory object)
  - Logging support
  - Fluent ``generate()`` / ``place_relative()`` / ``save_all()`` API
  - ``run_from_dict(config)`` static factory (kept for backward compatibility)
  - ``describe_adsorption_site()`` – neighbor-count analysis
  - ``plot_slab_with_labels()`` – labelled site visualisation
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np

from pymatgen.analysis.adsorption import AdsorbateSiteFinder, plot_slab
from pymatgen.core import Molecule, Structure
from pymatgen.core.surface import Slab
from pymatgen.io.vasp import Poscar

from .utils import load_structure


class AdsorptionModify(AdsorbateSiteFinder):
    """Enhanced adsorption-site finder and structure modifier.

    Supports three operating modes (selectable via ``run_from_dict``):
      - ``"analyze"``  – find and optionally plot adsorption sites
      - ``"generate"`` – place a molecule on all (or selected) sites
      - ``"relative"`` – copy adsorbate geometry from a reference structure
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(
        self,
        slab_source: Union[Slab, Structure, str, Path],
        selective_dynamics: bool = False,
        height: float = 0.9,
        mi_vec: Optional[np.ndarray] = None,
        save_dir: Optional[Union[str, Path]] = None,
        log_to_file: bool = True,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.slab, self.source_info = self._load_slab(slab_source)
        super().__init__(
            slab=self.slab,
            selective_dynamics=selective_dynamics,
            height=height,
            mi_vec=mi_vec,
        )

        self.save_dir = (
            Path(save_dir)
            if save_dir
            else Path.cwd() / f"adsorption_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

        if logger is not None:
            self.logger = logger
        else:
            self.logger = self._make_logger(self.save_dir, log_to_file)
            self.logger.info("Initialized AdsorptionModify from: %s", self.source_info)

        self._generated: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Static factory
    # ------------------------------------------------------------------

    @staticmethod
    def run_from_dict(
        config: Dict[str, Any],
    ) -> Union[List[Structure], Dict[str, Any]]:
        """Execute a complete workflow from a config dict.

        Required keys:
            ``target_slab_source``  – slab source (path / Structure)
            ``mode``                – ``"analyze"`` | ``"generate"`` | ``"relative"``

        See ``generate()`` and ``place_relative()`` for per-mode keys.
        """
        source = config.get("target_slab_source")
        if not source:
            raise ValueError("Config error: 'target_slab_source' is required.")

        mode = str(config.get("mode", "analyze")).lower()
        if mode not in ("analyze", "generate", "relative"):
            raise ValueError(f"Invalid mode {mode!r}. Must be 'analyze', 'generate', or 'relative'.")

        gen_params = config.get("generate_params", {})
        modifier = AdsorptionModify(
            slab_source=source,
            save_dir=config.get("save_dir"),
            log_to_file=config.get("log_to_file", True),
            selective_dynamics=gen_params.get("selective_dynamics", False),
        )
        modifier.logger.info("Running in mode: %s", mode)

        if mode == "analyze":
            return modifier.analyze(
                plot=config.get("plot", True),
                plot_params=config.get("plot_params", {}),
            )

        if mode == "relative":
            rel = config.get("relative_params") or {}
            ref_source = rel.get("reference_slab_source")
            if not ref_source:
                raise ValueError("Mode 'relative' requires 'relative_params.reference_slab_source'.")
            for key in ("adsorbate_indices", "adsorbate_anchor_indices"):
                if key not in rel or rel[key] is None:
                    raise ValueError(f"Mode 'relative' requires 'relative_params.{key}'.")
            modifier.place_relative(
                reference_slab_source=ref_source,
                adsorbate_indices=rel["adsorbate_indices"],
                adsorbate_anchor_indices=rel["adsorbate_anchor_indices"],
                find_args=rel.get("find_args", {}),
                movable_adsorbate_indices=rel.get("movable_adsorbate_indices"),
            )

        elif mode == "generate":
            mol_formula = gen_params.get("molecule_formula")
            if not mol_formula:
                raise ValueError("Mode 'generate' requires 'generate_params.molecule_formula'.")
            modifier.generate(
                molecule_formula=mol_formula,
                find_args=gen_params.get("find_args", {}),
                reorient=gen_params.get("reorient", True),
                plot=config.get("plot", True),
                plot_params=config.get("plot_params", {}),
            )

        # Unified save logic
        save_opts = config.get("save_options", {})
        if save_opts.get("save", True) and modifier._generated:
            modifier.save_all(
                filename_prefix=save_opts.get("filename", "POSCAR"),
                fmt=save_opts.get("fmt", "poscar"),
                as_subdirs=save_opts.get("as_subdirs", True),
            )

        return modifier.get_structures()

    # ------------------------------------------------------------------
    # Fluent API
    # ------------------------------------------------------------------

    def analyze(
        self,
        plot: bool = True,
        plot_params: Optional[Dict] = None,
    ) -> Dict[str, List[np.ndarray]]:
        """Find adsorption sites and optionally plot them.

        Returns a dict ``{site_type: [coords, …]}`` (``"all"`` key excluded).
        """
        sites = self.find_adsorption_sites()
        sites.pop("all", None)
        self.logger.info("Found sites: %s", {k: len(v) for k, v in sites.items()})
        if plot:
            self._plot_and_show(plot_params or {}, sites)
        return sites

    def generate(
        self,
        molecule_formula: str,
        find_args: Optional[Dict] = None,
        reorient: bool = True,
        plot: bool = False,
        plot_params: Optional[Dict] = None,
    ) -> "AdsorptionModify":
        """Place a molecule on every (or selected) adsorption site.  Fluent."""
        if not molecule_formula:
            raise ValueError("molecule_formula is required for generation.")

        molecule = self._resolve_molecule(molecule_formula)
        mol_name = Path(molecule_formula).stem if Path(molecule_formula).exists() else molecule_formula

        args = dict(find_args or {})
        requested = args.pop("positions", [])

        all_sites = self.find_adsorption_sites(**args)
        all_sites.pop("all", None)

        self._generated = []
        self.logger.info("Generating structures for %s …", mol_name)

        for site_type, coords_list in all_sites.items():
            if requested and site_type not in requested:
                continue
            for i, coords in enumerate(coords_list):
                struct = self.add_adsorbate(molecule, coords, reorient=reorient)
                self._generated.append(
                    {"structure": struct, "site_type": site_type, "index": i, "molecule": mol_name}
                )

        self.logger.info("Generated %d structures.", len(self._generated))
        if plot:
            self._plot_and_show(plot_params or {}, all_sites)
        return self

    def place_relative(
        self,
        reference_slab_source: Union[Structure, str, Path],
        adsorbate_indices: List[int],
        adsorbate_anchor_indices: List[int],
        find_args: Optional[Dict] = None,
        movable_adsorbate_indices: Optional[List[int]] = None,
    ) -> "AdsorptionModify":
        """Copy adsorbate geometry from a reference slab onto all sites.  Fluent."""
        ref_struct = load_structure(reference_slab_source)
        args = dict(find_args or {})
        requested = args.pop("positions", [])
        args["distance"] = 0.0  # heights come from the reference geometry

        all_sites = self.find_adsorption_sites(**args)
        all_sites.pop("all", None)

        self._generated = []
        self.logger.info("Placing relative adsorbate …")

        for site_type, coords_list in all_sites.items():
            if requested and site_type not in requested:
                continue
            for i, coords in enumerate(coords_list):
                struct, _ = self._place_relative_logic(
                    ref_struct, self.slab, adsorbate_indices,
                    adsorbate_anchor_indices, coords, movable_adsorbate_indices,
                )
                self._generated.append(
                    {"structure": struct, "site_type": site_type, "index": i, "molecule": "relative"}
                )

        self.logger.info("Placed relative adsorbate on %d sites.", len(self._generated))
        return self

    def get_structures(self) -> List[Structure]:
        """Return copies of all generated structures."""
        return [item["structure"].copy() for item in self._generated]

    def save_all(
        self,
        filename_prefix: str = "POSCAR",
        fmt: str = "poscar",
        as_subdirs: bool = True,
    ) -> None:
        """Persist all generated structures to ``self.save_dir``."""
        if not self._generated:
            self.logger.warning("No structures to save.")
            return

        self.save_dir.mkdir(parents=True, exist_ok=True)
        for item in self._generated:
            identifier = f"{item['site_type']}_{item['index']}"
            if as_subdirs:
                d = self.save_dir / f"{item['molecule']}_{identifier}"
                d.mkdir(parents=True, exist_ok=True)
                out = d / filename_prefix
            else:
                out = self.save_dir / f"{filename_prefix}_{identifier}"

            if fmt.lower() == "poscar":
                with open(out, "wt", encoding="utf-8") as fh:
                    fh.write(Poscar(item["structure"]).get_string())
            else:
                item["structure"].to(filename=str(out), fmt=fmt)

        self.logger.info("Saved %d structures to %s", len(self._generated), self.save_dir)

    def save_structure(self, structure: Structure, filename: str) -> None:
        out = self.save_dir / filename
        Poscar(structure).write_file(str(out))
        self.logger.info("Saved structure to %s", out)

    # ------------------------------------------------------------------
    # Site analysis
    # ------------------------------------------------------------------

    def describe_adsorption_site(
        self,
        slab: Structure,
        site_coords: np.ndarray,
        radius: float = 3.0,
        top_n: int = 10,
    ) -> Dict[str, Any]:
        """Return neighbour count and species-count around a site coordinate."""
        neighbours = slab.get_sites_in_sphere(site_coords, radius, include_index=True)
        neighbours.sort(key=lambda x: x.nn_distance)
        species = [str(n.species_string) for n in neighbours[:top_n]]
        return {"neighbors": len(neighbours), "species_count": dict(Counter(species))}

    # ------------------------------------------------------------------
    # Molecule loader
    # ------------------------------------------------------------------

    @classmethod
    def ase2pmg(cls, formula: str) -> Molecule:
        """Load a molecule from the ASE database by formula string."""
        from ase.build import molecule as ase_molecule
        from pymatgen.io.ase import AseAtomsAdaptor
        return AseAtomsAdaptor.get_molecule(ase_molecule(formula))

    def _resolve_molecule(self, formula: str) -> Molecule:
        """Try ASE database, then file (Molecule.from_file or Structure→Molecule)."""
        try:
            return self.ase2pmg(formula)
        except Exception:
            pass

        fpath = Path(formula)
        if fpath.exists():
            try:
                return Molecule.from_file(str(fpath))
            except Exception:
                pass
            try:
                tmp = Structure.from_file(str(fpath))
                return Molecule(tmp.species, tmp.cart_coords)
            except Exception as exc:
                raise ValueError(
                    f"Failed to parse '{fpath}' as Molecule or Structure: {exc}"
                ) from exc

        raise ValueError(
            f"Cannot load molecule '{formula}': not in ASE database and file not found."
        )

    # ------------------------------------------------------------------
    # Internal placement
    # ------------------------------------------------------------------

    @staticmethod
    def _anchor_coords(structure: Structure, indices: List[int]) -> np.ndarray:
        coords = [structure[i].coords for i in indices]
        return coords[0] if len(coords) == 1 else np.mean(coords, axis=0)

    def _place_relative_logic(
        self,
        ref_struct: Structure,
        target_struct: Structure,
        ads_indices: List[int],
        anchor_indices: List[int],
        target_coords: np.ndarray,
        movable: Optional[List[int]] = None,
    ) -> Tuple[Structure, List[int]]:
        anchor = self._anchor_coords(ref_struct, anchor_indices)
        rel_pos = [ref_struct[i].coords - anchor for i in ads_indices]
        species = [ref_struct[i].specie for i in ads_indices]

        combined = target_struct.copy()
        new_indices: List[int] = []
        for sp, rp in zip(species, rel_pos):
            combined.append(sp, target_coords + rp, coords_are_cartesian=True)
            new_indices.append(len(combined) - 1)

        sd_existing = target_struct.site_properties.get("selective_dynamics")
        sd: List[List[bool]] = (
            [list(x) for x in sd_existing]
            if sd_existing
            else [[False, False, False]] * len(target_struct)
        )
        movable_set = set(movable) if movable is not None else set(range(len(species)))
        for i in range(len(species)):
            sd.append([True, True, True] if i in movable_set else [False, False, False])

        combined.add_site_property("selective_dynamics", sd)
        return combined, new_indices

    # ------------------------------------------------------------------
    # Plotting helpers
    # ------------------------------------------------------------------

    def _plot_and_show(self, plot_params: Dict, sites: Dict) -> None:
        params = dict(plot_params)
        figsize = params.pop("figsize", (6, 6))
        fig, ax = plt.subplots(figsize=figsize)
        self.plot_slab_with_labels(self.slab, ax=ax, ads_sites=sites, **params)
        out = self.save_dir / "adsorption_sites.png"
        fig.savefig(str(out), dpi=300, bbox_inches="tight")
        plt.show()

    @classmethod
    def plot_slab_with_labels(
        cls,
        slab: Slab,
        ax: Optional[plt.Axes] = None,
        scale: float = 0.8,
        repeat: Tuple[int, int, int] = (1, 1, 1),
        window: float = 1.5,
        decay: float = 0.2,
        adsorption_sites: bool = True,
        inverse: bool = False,
        label_offset: Tuple[float, float] = (0.0, 0.0),
        ads_sites: Optional[Dict] = None,
    ) -> plt.Axes:
        """Plot a slab top-down with adsorption-site labels."""
        if ax is None:
            fig = plt.figure(figsize=(6, 6))
            ax = fig.add_subplot(111)

        working = slab.copy()
        rx, ry, rz = (repeat or (1, 1, 1))
        if repeat:
            working.make_supercell([rx, ry, rz])

        try:
            plot_slab(
                working, ax=ax, scale=scale, repeat=1, window=window,
                draw_unit_cell=True, decay=decay, adsorption_sites=False, inverse=inverse,
            )
        except TypeError:
            plot_slab(working, ax=ax, scale=scale, adsorption_sites=False, inverse=inverse)

        if not adsorption_sites:
            ax.set_aspect("equal")
            return ax

        if ads_sites is None:
            found = AdsorbateSiteFinder(slab).find_adsorption_sites()
            flat = found["ontop"] + found["bridge"] + found["hollow"]
        elif isinstance(ads_sites, dict):
            flat = ads_sites.get("ontop", []) + ads_sites.get("bridge", []) + ads_sites.get("hollow", [])
        else:
            flat = list(ads_sites)

        if not flat:
            return ax

        R = cls._get_rot_matrix_for_slab(working)
        lattice = slab.lattice.matrix
        va, vb = lattice[0], lattice[1]

        xs, ys, labels = [], [], []
        for idx, site in enumerate(flat):
            coords = np.array(site)
            for i in range(rx):
                for j in range(ry):
                    rot = np.dot(R, coords + i * va + j * vb)
                    xs.append(rot[0])
                    ys.append(rot[1])
                    labels.append(str(idx))

        ax.plot(xs, ys, linestyle="", marker="x", markersize=6, mew=1.5, color="red", zorder=500)
        for x, y, label in zip(xs, ys, labels):
            ax.text(
                x + label_offset[0], y + label_offset[1], label,
                fontsize=9, color="blue", fontweight="bold", zorder=501,
                ha="center", va="bottom",
            )
        ax.set_aspect("equal")
        return ax

    @staticmethod
    def _rotation_matrix_from_vectors(v1: np.ndarray, v2: np.ndarray) -> np.ndarray:
        a = v1 / np.linalg.norm(v1)
        b = v2 / np.linalg.norm(v2)
        v = np.cross(a, b)
        c = np.dot(a, b)
        if np.allclose(v, 0) and c > 0.999999:
            return np.eye(3)
        if np.allclose(v, 0) and c < -0.999999:
            orth = np.array([0.0, 1.0, 0.0]) if abs(a[0]) > 0.9 else np.array([1.0, 0.0, 0.0])
            v = np.cross(a, orth)
            v /= np.linalg.norm(v)
            return -np.eye(3) + 2 * np.outer(v, v)
        s = np.linalg.norm(v)
        K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        return np.eye(3) + K + K @ K * ((1 - c) / (s ** 2))

    @classmethod
    def _get_rot_matrix_for_slab(cls, slab: Slab) -> np.ndarray:
        if hasattr(slab, "normal"):
            return cls._rotation_matrix_from_vectors(
                np.array(slab.normal), np.array([0.0, 0.0, 1.0])
            )
        return np.eye(3)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_slab(
        source: Union[Slab, Structure, str, Path],
    ) -> Tuple[Structure, str]:
        """Load slab and return (structure, source_description)."""
        if isinstance(source, (Structure, Slab)):
            return source, "in-memory object"
        struct = load_structure(source)
        return struct, str(source)

    @staticmethod
    def _make_logger(output_dir: Path, log_to_file: bool) -> logging.Logger:
        logger = logging.getLogger(f"AdsorptionModify.{id(output_dir)}")
        logger.setLevel(logging.INFO)
        if logger.hasHandlers():
            logger.handlers.clear()
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)
        if log_to_file:
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(output_dir / "adsorption.log", mode="w", encoding="utf-8")
                fh.setFormatter(fmt)
                logger.addHandler(fh)
            except Exception:
                pass
        return logger
