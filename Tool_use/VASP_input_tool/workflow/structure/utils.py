"""
structure/utils.py
==================
Shared low-level utilities for loading and analysing pymatgen Structure objects.

Rule: this is the ONLY module in the package that imports pymatgen and
      constructs Structure objects from disk.  All other modules must call
      load_structure() rather than calling Structure.from_file() directly.
"""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np
from collections import defaultdict

from pymatgen.core import Structure
from pymatgen.core.surface import Slab
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


# ---------------------------------------------------------------------------
# Structure loader
# ---------------------------------------------------------------------------

def load_structure(source: Union[Structure, Slab, str, Path]) -> Structure:
    """Load a pymatgen Structure from a variety of sources.

    Accepts:
    - An in-memory ``Structure`` or ``Slab`` object  (returned as-is).
    - A path to a file (any format pymatgen understands: POSCAR, CIF, …).
    - A path to a directory – searches in priority order:
      CONTCAR, POSCAR, POSCAR.vasp, then ``*.cif``.

    Raises:
        FileNotFoundError: if the path does not exist.
        ValueError:        if no valid structure file is found in a directory.
    """
    if isinstance(source, (Structure, Slab)):
        return source  # type: ignore[return-value]

    path = Path(source).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Structure source not found: {path}")

    if path.is_file():
        return Structure.from_file(str(path))

    if path.is_dir():
        priority = ["CONTCAR", "POSCAR", "POSCAR.vasp"]
        for name in priority:
            candidate = path / name
            if candidate.exists() and candidate.stat().st_size > 0:
                try:
                    return Structure.from_file(str(candidate))
                except Exception:
                    continue

        # Fallback: any CIF
        for cif in sorted(path.glob("*.cif")):
            if cif.stat().st_size > 0:
                try:
                    return Structure.from_file(str(cif))
                except Exception:
                    continue

        # Broader glob fallback
        for pattern in ["*CONTCAR*", "*POSCAR*", "*.vasp"]:
            for fpath in sorted(path.glob(pattern)):
                if fpath.is_file() and fpath.stat().st_size > 0:
                    try:
                        return Structure.from_file(str(fpath))
                    except Exception:
                        continue

        raise ValueError(f"No valid structure file found in directory: {path}")

    raise ValueError(f"Invalid structure source: {source}")


def get_best_structure_path(directory: Path) -> Optional[Path]:
    """Return CONTCAR if it exists and is non-empty, else POSCAR, else None."""
    for name in ("CONTCAR", "POSCAR"):
        p = directory / name
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


# ---------------------------------------------------------------------------
# Supercell matrix parser
# ---------------------------------------------------------------------------

def parse_supercell_matrix(
    matrix: Optional[Union[str, Sequence[int], Sequence[Sequence[int]]]]
) -> Optional[List[List[int]]]:
    """Parse supercell matrix input into a 3×3 scaling matrix.

    Accepts:
    - ``None``                    → returns ``None``
    - ``"2x2"`` / ``"2x2x1"``    → diagonal matrix
    - ``[2, 2]`` / ``[2, 2, 1]`` → diagonal matrix
    - 3×3 nested list / ndarray  → returned as-is
    """
    if matrix is None:
        return None

    if isinstance(matrix, str):
        factors = [int(x) for x in matrix.lower().split("x")]
        if len(factors) == 2:
            return [[factors[0], 0, 0], [0, factors[1], 0], [0, 0, 1]]
        if len(factors) == 3:
            return [[factors[0], 0, 0], [0, factors[1], 0], [0, 0, factors[2]]]
        raise ValueError(f"Invalid supercell matrix string: {matrix!r}")

    arr = np.array(matrix)
    if arr.shape == (3, 3):
        return arr.tolist()
    if arr.ndim == 1:
        if len(arr) == 2:
            return [[int(arr[0]), 0, 0], [0, int(arr[1]), 0], [0, 0, 1]]
        if len(arr) == 3:
            return [[int(arr[0]), 0, 0], [0, int(arr[1]), 0], [0, 0, int(arr[2])]]

    raise ValueError(f"Unsupported supercell matrix format: {matrix!r}")


# ---------------------------------------------------------------------------
# Atomic layer detector
# ---------------------------------------------------------------------------

def get_atomic_layers(
    structure: Structure,
    hcluster_cutoff: float = 0.25,
) -> List[List[int]]:
    """Identify atomic layers via hierarchical clustering on Z-coordinates.

    Returns a list of site-index groups sorted from lowest to highest Z.
    Each inner list holds the indices of sites that belong to one layer.
    """
    sites = structure.sites
    n = len(sites)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    frac_z = np.array([s.frac_coords[2] for s in sites])
    c = structure.lattice.c

    dist_matrix = np.zeros((n, n))
    for i, j in combinations(range(n), 2):
        dz = abs(frac_z[i] - frac_z[j]) * c
        dist_matrix[i, j] = dz
        dist_matrix[j, i] = dz

    condensed = squareform(dist_matrix)
    z_linkage = linkage(condensed, method="average")
    cluster_ids = fcluster(z_linkage, hcluster_cutoff, criterion="distance")

    raw: defaultdict[int, List[int]] = defaultdict(list)
    for idx, cid in enumerate(cluster_ids):
        raw[cid].append(idx)

    avg_z = {cid: float(np.mean(frac_z[indices])) for cid, indices in raw.items()}
    sorted_cids = sorted(avg_z, key=lambda k: avg_z[k])
    return [raw[cid] for cid in sorted_cids]
