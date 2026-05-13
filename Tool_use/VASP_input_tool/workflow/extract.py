"""
extract.py
==========
Standalone result extraction — parses completed VASP output directories and
reports total energies, per-atom energies, adsorption energies, and DOS
availability without re-running any VASP jobs.

Entry point:  python -m flow extract  (via hook.py main())
"""
from __future__ import annotations

import csv
import json
import logging
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

from flow.workflow.stages.base import Stage
from flow.workflow.task import WorkflowTask

logger = logging.getLogger(__name__)

# ── OUTCAR parsers ────────────────────────────────────────────────────────────

def _parse_toten(outcar: Path) -> Optional[float]:
    """Return the last 'TOTEN = X eV' value from OUTCAR, or None."""
    last: Optional[float] = None
    try:
        with outcar.open("r", errors="replace") as fh:
            for line in fh:
                if "TOTEN" in line:
                    m = re.search(r"TOTEN\s*=\s*(-?\d+\.\d+)", line)
                    if m:
                        last = float(m.group(1))
    except OSError:
        pass
    return last


def _parse_nions(outcar: Path) -> Optional[int]:
    """Return NIONS from OUTCAR, or None."""
    try:
        with outcar.open("r", errors="replace") as fh:
            for line in fh:
                if "NIONS" in line:
                    m = re.search(r"NIONS\s*=\s*(\d+)", line)
                    if m:
                        return int(m.group(1))
    except OSError:
        pass
    return None


def _check_converged(outcar: Path) -> bool:
    """Return True if OUTCAR contains 'reached required accuracy'."""
    try:
        with outcar.open("r", errors="replace") as fh:
            for line in fh:
                if "reached required accuracy" in line:
                    return True
    except OSError:
        pass
    return False


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class TaskResult:
    task_id: str
    stage: str
    bulk_id: str
    workdir: str
    done: bool
    converged: bool
    energy_ev: Optional[float]
    n_atoms: Optional[int]
    energy_per_atom_ev: Optional[float]
    has_doscar: bool
    has_vasprun: bool
    ads_energy_ev: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)


# ── Per-task extraction ───────────────────────────────────────────────────────

def _is_done(workdir: Path) -> bool:
    return (workdir / "done.ok").exists()


def _extract_task(task: WorkflowTask) -> TaskResult:
    wdir = Path(task["workdir"])
    outcar = wdir / "OUTCAR"
    done = _is_done(wdir)

    energy: Optional[float] = None
    nions: Optional[int] = None
    converged = False

    if outcar.exists():
        energy = _parse_toten(outcar)
        nions = _parse_nions(outcar)
        converged = _check_converged(outcar)

    epa: Optional[float] = None
    if energy is not None and nions and nions > 0:
        epa = energy / nions

    meta = task.get("meta", {})
    return TaskResult(
        task_id=task["id"],
        stage=task.get("stage", ""),
        bulk_id=meta.get("bulk_id", ""),
        workdir=str(wdir),
        done=done,
        converged=converged,
        energy_ev=energy,
        n_atoms=nions,
        energy_per_atom_ev=epa,
        has_doscar=(wdir / "DOSCAR").exists(),
        has_vasprun=(wdir / "vasprun.xml").exists(),
        meta=meta,
    )


# ── Manifest reader ───────────────────────────────────────────────────────────

def _manifest_path(cfg: "WorkflowConfig") -> Path:
    return cfg.project.run_root / "manifest.json"


def extract_manifest_results(
    cfg: "WorkflowConfig",
    stages: Optional[List[str]] = None,
) -> List[TaskResult]:
    """Load manifest.json and extract results for all (or filtered) tasks."""
    mp = _manifest_path(cfg)
    if not mp.exists():
        logger.warning("manifest.json not found at %s — nothing to extract.", mp)
        return []

    with mp.open() as fh:
        manifest = json.load(fh)

    results: List[TaskResult] = []
    for task in manifest.get("tasks", {}).values():
        if stages and task.get("stage") not in stages:
            continue
        try:
            results.append(_extract_task(task))
        except Exception:
            logger.exception("Failed to extract task %s", task.get("id"))

    results.sort(key=lambda r: (r.stage, r.bulk_id, r.task_id))
    return results


# ── Adsorption energy computation ─────────────────────────────────────────────

def compute_adsorption_energies(
    results: List[TaskResult],
    mol_refs: Optional[Dict[str, float]] = None,
) -> None:
    """Compute E_ads = E(ads) - E(slab) - E(mol) and store in TaskResult.ads_energy_ev.

    mol_refs maps molecule formula to reference energy in eV (e.g. {"CO": -14.78}).
    Slab reference is looked up by matching bulk_id + hkl + layers + term.
    """
    if mol_refs is None:
        mol_refs = {}

    slab_energies: Dict[str, Optional[float]] = {}
    for r in results:
        if r.stage == Stage.SLAB_RELAX and r.energy_ev is not None:
            key = _slab_key(r.meta)
            slab_energies[key] = r.energy_ev

    for r in results:
        if r.stage != Stage.ADSORPTION or r.energy_ev is None:
            continue
        skey = _slab_key(r.meta)
        e_slab = slab_energies.get(skey)
        if e_slab is None:
            continue
        mol_formula = r.meta.get("molecule_formula") or r.meta.get("adsorbate_formula")
        e_mol = mol_refs.get(mol_formula) if mol_formula else None
        if e_mol is None:
            r.ads_energy_ev = r.energy_ev - e_slab
        else:
            r.ads_energy_ev = r.energy_ev - e_slab - e_mol


def _slab_key(meta: Dict[str, Any]) -> str:
    bid = meta.get("bulk_id", "")
    hkl = meta.get("hkl", [0, 0, 0])
    layers = meta.get("layers", 0)
    term = meta.get("term", 0)
    return f"{bid}:{hkl}:{layers}:{term}"


# ── Output formatters ─────────────────────────────────────────────────────────

_TABLE_COLS = [
    ("task_id", 40),
    ("stage", 18),
    ("done", 5),
    ("conv", 5),
    ("energy_ev", 14),
    ("epa_ev", 14),
    ("ads_ev", 12),
    ("dos", 4),
]


def print_table(results: List[TaskResult], file=None) -> None:
    if file is None:
        file = sys.stdout
    header = "  ".join(f"{col:<{w}}" for col, w in _TABLE_COLS)
    print(header, file=file)
    print("-" * len(header), file=file)
    for r in results:
        row = [
            f"{r.task_id:<40}",
            f"{r.stage:<18}",
            f"{'Y' if r.done else 'N':<5}",
            f"{'Y' if r.converged else 'N':<5}",
            f"{r.energy_ev:<14.6f}" if r.energy_ev is not None else f"{'—':<14}",
            f"{r.energy_per_atom_ev:<14.6f}" if r.energy_per_atom_ev is not None else f"{'—':<14}",
            f"{r.ads_energy_ev:<12.4f}" if r.ads_energy_ev is not None else f"{'—':<12}",
            f"{'Y' if r.has_doscar else 'N':<4}",
        ]
        print("  ".join(row), file=file)


def save_json(results: List[TaskResult], path: str) -> None:
    data = [asdict(r) for r in results]
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)
    logger.info("JSON results written to %s", path)


def save_csv(results: List[TaskResult], path: str) -> None:
    fields = [
        "task_id", "stage", "bulk_id", "workdir", "done", "converged",
        "energy_ev", "n_atoms", "energy_per_atom_ev", "ads_energy_ev",
        "has_doscar", "has_vasprun",
    ]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({f: getattr(r, f) for f in fields})
    logger.info("CSV results written to %s", path)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_extract(
    cfg: "WorkflowConfig",
    output: Optional[str] = None,
    fmt: str = "table",
    mol_refs: Optional[Dict[str, float]] = None,
    stages: Optional[List[str]] = None,
) -> None:
    """Extract and report results from completed VASP calculations."""
    results = extract_manifest_results(cfg, stages=stages)
    if not results:
        print("[extract] No results found.", file=sys.stderr)
        return

    compute_adsorption_energies(results, mol_refs=mol_refs)

    if fmt == "json":
        if output:
            save_json(results, output)
        else:
            print(json.dumps([asdict(r) for r in results], indent=2))
    elif fmt == "csv":
        if output:
            save_csv(results, output)
        else:
            # CSV to stdout
            import io
            buf = io.StringIO()
            fields = [
                "task_id", "stage", "bulk_id", "done", "converged",
                "energy_ev", "n_atoms", "energy_per_atom_ev", "ads_energy_ev",
            ]
            w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in results:
                w.writerow({f: getattr(r, f) for f in fields})
            print(buf.getvalue(), end="")
    else:
        if output:
            with open(output, "w") as fh:
                print_table(results, file=fh)
        else:
            print_table(results)

    n_done = sum(1 for r in results if r.done)
    n_conv = sum(1 for r in results if r.converged)
    print(
        f"\n[extract] {len(results)} tasks | {n_done} done | {n_conv} converged",
        file=sys.stderr,
    )
