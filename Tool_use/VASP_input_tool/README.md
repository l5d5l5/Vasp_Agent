# VASP Flow Module — Code Logic Reference

## Table of Contents

1. [Module Overview](#1-module-overview)
2. [Architecture and Data Flow](#2-architecture-and-data-flow)
3. [Module Details](#3-module-details)
   - [api.py — Frontend Adapter](#31-apipy--frontend-adapter)
   - [workflow_engine.py — Workflow Engine](#32-workflow_enginepy--workflow-engine)
   - [input_sets/ — Input Set Wrappers](#33-input_sets--input-set-wrappers)
   - [maker.py — Legacy Direct-Use Factory](#34-makerpy--legacy-direct-use-factory)
   - [constants.py — Constants and Defaults](#35-constantspy--constants-and-defaults)
   - [kpoints.py — K-point Generator](#36-kpointspy--k-point-generator)
   - [utils.py — Utility Functions](#37-utilspy--utility-functions)
   - [script.py — Job Script Generator](#38-scriptpy--job-script-generator)
4. [Supported Calculation Types](#4-supported-calculation-types)
5. [Parameter Priority and Merge Rules](#5-parameter-priority-and-merge-rules)
6. [Extension Guide](#6-extension-guide)
7. [Usage Examples](#7-usage-examples)

---

## 1. Module Overview

| File | Responsibility | Key classes / functions |
|------|---------------|------------------------|
| `api.py` | Frontend dict → typed parameter objects | `FrontendAdapter`, `VaspWorkflowParams`, `VaspAPI` |
| `frontend_params.py` | Frontend parameter dataclasses and parse helpers | `StructureInput`, `MagmomParams`, `DFTPlusUParams`, `MDParams`, … |
| `workflow_engine.py` | CalcType registry + dispatch engine + `_write_*` functions | `CalcType`, `WorkflowConfig`, `WorkflowEngine`, `_write_bulk`, … |
| `input_sets/` | pymatgen InputSet subclasses (package) | `BulkRelaxSetEcat`, `SlabSetEcat`, … |
| `maker.py` | Legacy direct-use factory (not called by WorkflowEngine) | `VaspInputMaker` |
| `constants.py` | INCAR defaults, functional patches | `DEFAULT_INCAR_*`, `FUNCTIONAL_INCAR_PATCHES` |
| `calc_registry.py` | Single source of truth for all CalcType-level mappings | `CalcType`, `CalcTypeEntry`, `CALC_REGISTRY`, `VDW_FUNCTIONALS`, `calc_type_from_str` |
| `kpoints.py` | K-point mesh generation | `build_kpoints_by_lengths` |
| `utils.py` | Structure loading, format conversion | `load_structure`, `infer_functional_from_incar` |
| `script.py` | PBS/SLURM script rendering | `Script`, `CalcCategory` |
| `script_writer.py` | High-level script writer; copies `vdw_kernel.bindat` for BEEF | `ScriptWriter` |

---

## 2. Architecture and Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  External caller / workflow stage                               │
│  frontend_dict = { "calc_type": "bulk_relax", … }              │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  api.py — FrontendAdapter.from_frontend_dict()                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  1. Parse structure input  (StructureInput)             │    │
│  │  2. Extract sub-param groups:                           │    │
│  │     MAGMOM, DFT+U, vdW, dipole, lobster, NBO,          │    │
│  │     frequency, NMR, MD, NEB                             │    │
│  │  3. Normalise → VaspWorkflowParams                      │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ .to_workflow_config()
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  workflow_engine.py — WorkflowConfig dataclass                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  CalcType enum value + all engine params                │    │
│  │  (structure, dirs, INCAR overrides, MD/NEB/freq/…)      │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ WorkflowEngine().run(config)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  workflow_engine.py — WorkflowEngine.run()                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  1. Auto-detect prev_dir                                │    │
│  │  2. Validate config                                     │    │
│  │  3. Resolve structure path                              │    │
│  │  4. Pre-check WAVECAR/CHGCAR → ICHARG/ISTART tags       │    │
│  │  5. _get_incar_params(): merge registry + user overrides│    │
│  │  6. match CalcType → call _write_*(config, incar, dir)  │    │
│  │  7. Copy WAVECAR/CHGCAR from prev_dir                   │    │
│  │  8. Copy vdw_kernel.bindat for vdW functionals          │    │
│  │  9. Generate PBS/SLURM script (optional)                │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ module-level _write_*(config, incar, output_dir)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  workflow_engine.py — _write_bulk / _write_slab / … (private)   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  1. Load structure                                      │    │
│  │  2. _apply_magmom_compat(): VASP MAGMOM → pymatgen dict │    │
│  │  3. Instantiate the matching *SetEcat object            │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │ .write_input(output_dir)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│  input_sets/ — *SetEcat.write_input()                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  1. _build_incar(): defaults → functional patch →       │    │
│  │     user overrides                                      │    │
│  │  2. Call pymatgen parent to write files                 │    │
│  │  3. Strip @CLASS/@MODULE metadata comments              │    │
│  │  4. Enforce LDAU=False if no U values provided          │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
            POSCAR / INCAR / KPOINTS / POTCAR / lobsterin (disk)
```

---

## 3. Module Details

### 3.1 `api.py` — Frontend Adapter

**Role:** Convert an unstructured frontend dict into strongly typed parameter objects, decoupling the frontend from the engine internals.

#### Frontend parameter dataclasses (defined in `frontend_params.py`)

```
StructureInput       Structure source (file / library / task)
PrecisionParams      ENCUT, EDIFF, EDIFFG, NEDOS
KpointParams         K-point density, gamma-centred flag
MagmomParams         MAGMOM — per_atom list OR per_element dict
DFTPlusUParams       DFT+U — nested {elem: {LDAUU, LDAUL, LDAUJ}}
VdwParams            vdW correction method (None / D3 / D3BJ / …)
DipoleParams         LDIPOL / IDIPOL settings
FrequencyParams      IBRION, POTIM, NFREE, vibrate_mode, adsorbate_formula,
                     adsorbate_formula_prefer, vibrate_indices, calc_ir
LobsterParams        lobsterin_mode, overwritedict, custom_lobsterin_lines
NBOParams            NBO program config (basis, occ thresholds, …)
MDParams             MD ensemble, temperatures, steps, time_step
NEBParams            n_images, use_idpp, start/end structures
ResourceParams       cores, walltime, queue
VaspWorkflowParams   Top-level container holding all of the above
```

#### Structure input resolution (`StructureInput.to_path_or_content`)

```
source="file"    → returns content (if non-empty) or id (file path)
source="library" → returns id (requires external library implementation)
source="task"    → verifies directory exists, then returns id
```

#### Main entry point: `FrontendAdapter.from_frontend_dict(data)`

```
Input: dict (raw frontend data)
  ├── extract calc_type → stored as string; resolved to CalcType in to_workflow_config()
  ├── extract xc / functional → FRONTEND_XC_MAP alias resolution
  ├── extract kpoints → KpointParams
  ├── extract structure → StructureInput
  ├── extract settings:
  │     ├── NEDOS / ENCUT / EDIFF / EDIFFG → PrecisionParams
  │     ├── MAGMOM  → MagmomParams (per_atom or per_element)
  │     ├── LDAUU / LDAUL / LDAUJ → DFTPlusUParams
  │     ├── lobsterin_mode / cohp_generator → LobsterParams
  │     ├── basis_source / nbo_config → NBOParams
  │     ├── IBRION / vibrate_indices / adsorbate_formula_prefer → FrequencyParams
  │     └── everything else → custom_incar (passed as user_incar_overrides)
  └── extract prev_dir / resource
Output: VaspWorkflowParams
```

#### `VaspWorkflowParams.to_workflow_config()` — key conversions

| What | How |
|---|---|
| `calc_type` string | `calc_type_from_str()` → `CalcType` enum |
| `PrecisionParams.encut` | `user_incar_overrides["ENCUT"]` |
| `MagmomParams.per_element` | `user_incar_overrides["MAGMOM"]` = `Dict[str, float]` |
| `MagmomParams.per_atom` | `user_incar_overrides["MAGMOM"]` = `List[float]`; auto-inject `ISPIN=2` |
| `DFTPlusUParams` | `LDAUU/LDAUL/LDAUJ` per-element dicts + `LDAU=True` |
| `MDParams` | `WorkflowConfig.start_temp`, `.end_temp`, `.nsteps`, `.time_step` |
| `NEBParams` | `WorkflowConfig.start_structure`, `.end_structure`, `.n_images` |
| `FrequencyParams` | `WorkflowConfig.vibrate_indices`, `.calc_ir` |

#### `VaspAPI` — programmatic workflow runner

`VaspAPI.run_workflow(params)` executes the full pipeline from a `VaspWorkflowParams` object:
1. `params.to_workflow_config()` → `WorkflowConfig`
2. `WorkflowEngine.run(config)` → writes VASP input files

---

### 3.2 `workflow_engine.py` — Workflow Engine

#### `CalcType` enum (defined in `calc_registry.py`, re-exported here)

The single canonical name for every supported calculation type:

| Enum value | Frontend string | Description |
|---|---|---|
| `BULK_RELAX` | `bulk_relax` | Bulk ionic + cell relaxation |
| `SLAB_RELAX` | `slab_relax` | Surface slab relaxation |
| `STATIC_SP`  | `static_sp` | Single-point (no charge/wave output) |
| `DOS_SP`     | `static_dos` | Static + DOS (retains CHGCAR) |
| `CHG_SP`     | `static_charge` | Static + charge density |
| `ELF_SP`     | `static_elf` | Static + ELF |
| `NEB`        | `neb` | Minimum energy path (VTST) |
| `DIMER`      | `dimer` | Dimer transition-state (VTST) |
| `FREQ`       | `freq` | Vibrational frequency |
| `FREQ_IR`    | `freq_ir` | Frequency + IR (DFPT) |
| `LOBSTER`    | `lobster` | COHP chemical-bonding analysis |
| `NMR_CS`     | `nmr_cs` | NMR chemical shift |
| `NMR_EFG`    | `nmr_efg` | NMR electric field gradient |
| `NBO`        | `nbo` | Natural Bond Orbital analysis |
| `MD_NVT`     | `md_nvt` | NVT molecular dynamics |
| `MD_NPT`     | `md_npt` | NPT molecular dynamics |

`WorkflowConfig.calc_type` also accepts plain strings — `__post_init__` calls `calc_type_from_str()` to convert them.

#### `CALC_REGISTRY` (imported from `calc_registry.py` as `CALC_TYPE_REGISTRY`)

Maps each `CalcType` to a `CalcTypeEntry`:

```python
@dataclass(frozen=True)
class CalcTypeEntry:
    incar_base:      Dict[str, Any]   # DEFAULT_INCAR_* from constants.py
    incar_delta:     Dict[str, Any]   # incremental overrides on top of base
    need_wavecharge: bool             # retain WAVECAR/CHGCAR after job
    need_vtst:       bool             # require VTST-patched VASP binary
    beef_compatible: bool             # False for NMR, NBO, LOBSTER
    script_category: CalcCategory     # PBS template category
    frontend_name:   str              # canonical user-facing string
    template_name:   str              # PBS template file name
    str_aliases:     Tuple[str, ...]  # additional lookup aliases
```

`get_merged_incar(user_overrides)` merges `incar_base + incar_delta + user_overrides`
and is called by `WorkflowEngine._get_incar_params()`.

#### `WorkflowConfig` dataclass

Complete parameter set consumed by `WorkflowEngine.run()`:

```
Core:            calc_type, structure, functional, kpoints_density,
                 output_dir, prev_dir
MD:              start_temp, end_temp, nsteps, time_step  (→ MDSetEcat constructor)
NEB:             n_images, use_idpp, start_structure, end_structure
Frequency:       vibrate_indices, calc_ir
NMR:             isotopes
NBO:             nbo_config
Lobster:         lobster_overwritedict, lobster_custom_lines
Advanced:        user_incar_overrides
```

`calc_type` accepts both `CalcType` enum values and plain strings.

#### `WorkflowEngine.run(config)` dispatch

```python
engine = WorkflowEngine()
engine.run(config)
```

Dispatch sequence:
```
1. Auto-detect prev_dir (tries sibling directories: relax, opt, …)
2. Validate config (raises ValueError on bad params)
3. Resolve structure path (file → use directly; dir → CONTCAR > POSCAR;
   missing → fall back to prev_dir/CONTCAR or prev_dir/POSCAR)
4. Pre-check prev_dir for WAVECAR/CHGCAR → inject ICHARG=1 / ISTART=1
5. _get_incar_params(): merge CALC_REGISTRY base + functional patch + user overrides
6. match config.calc_type:
     BULK_RELAX              → _write_bulk(struct, incar, output_dir, config)
     SLAB_RELAX              → _write_slab(struct, incar, output_dir, config)
     STATIC_SP / DOS_SP /
       CHG_SP / ELF_SP       → _write_noscf(struct, incar, output_dir, config, prev)
     NEB                     → _write_neb(incar, output_dir, config)
     DIMER                   → _write_dimer(incar, output_dir, prev)
     FREQ                    → _write_freq(struct, incar, output_dir, config, prev, calc_ir=False)
     FREQ_IR                 → _write_freq(struct, incar, output_dir, config, prev, calc_ir=True)
     LOBSTER                 → _write_lobster(struct, incar, output_dir, config, prev)
     NMR_CS / NMR_EFG        → _write_nmr(struct, incar, output_dir, config, prev, mode)
     NBO                     → _write_nbo(struct, incar, output_dir, config, prev)
     MD_NVT / MD_NPT         → _write_md(struct, incar, output_dir, config, prev, ensemble)
7. Copy WAVECAR/CHGCAR from prev_dir (silent no-op if absent)
8. Copy vdw_kernel.bindat for BEEF/BEEFVTST functionals
9. Optionally write PBS/SLURM job script
```

#### `_write_*` module-level functions

Each function receives the already-merged `incar_params` dict and a pre-created `output_dir`. Per-type logic lives here:

| Function | InputSet used | Special handling |
|---|---|---|
| `_write_bulk` | `BulkRelaxSetEcat` | `_apply_magmom_compat` |
| `_write_slab` | `SlabSetEcat` | `_apply_magmom_compat`, `auto_dipole=True` |
| `_write_noscf` | `MPStaticSetEcat` | `from_prev_calc_ecat` when prev is set |
| `_write_neb` | `NEBSetEcat` | `from_prev_calc` when dir-style inputs |
| `_write_dimer` | `DimerSetEcat` | `from_neb_calc`; requires prev_dir |
| `_write_lobster` | `LobsterSetEcat` | `overwritedict`, `custom_lobsterin_lines` |
| `_write_freq` | `FreqSetEcat` | `vibrate_indices`, `adsorbate_formula_prefer`, `calc_ir`; CONTCAR-aware |
| `_write_nbo` | `NBOSetEcat` | `basis_source`, `nbo_config` |
| `_write_nmr` | `NMRSetEcat` | `mode` (`"cs"` or `"efg"`); NMR kpoints ≥ 100 |
| `_write_md` | `MDSetEcat` | `start_temp`, `end_temp`, `nsteps`, `time_step` from `WorkflowConfig` |

---

### 3.3 `input_sets/` — Input Set Wrappers

The `input_sets/` directory is a package split from the former `input_sets.py` monolith.
All classes are re-exported from `input_sets/__init__.py` for backward compatibility.

**Sub-modules:**

| File | Classes |
|---|---|
| `_base.py` | `VaspInputSetEcat` — shared base class |
| `bulk_slab.py` | `BulkRelaxSetEcat`, `SlabSetEcat` |
| `static.py` | `MPStaticSetEcat` |
| `spectroscopy.py` | `LobsterSetEcat`, `NBOSetEcat`, `NMRSetEcat` |
| `transition.py` | `NEBSetEcat`, `FreqSetEcat`, `DimerSetEcat` |
| `md.py` | `MDSetEcat` |

#### Base class `VaspInputSetEcat`

Shared base for all `*SetEcat` classes, providing two key methods:

**`_build_incar(functional, default_incar, extra_incar, user_incar_settings)`**

```
INCAR build priority (lowest → highest):
┌──────────────────────┐
│  default_incar       │  DEFAULT_INCAR_* from constants.py
├──────────────────────┤
│  FUNCTIONAL_PATCH    │  Per-functional patch (BEEF / SCAN / …)
├──────────────────────┤
│  extra_incar         │  Caller-supplied extras
├──────────────────────┤
│  user_incar_settings │  User final overrides (highest priority)
└──────────────────────┘
```

**`write_input(output_dir)` post-processing:**
1. Call pymatgen parent to write files
2. Strip `@CLASS` / `@MODULE` metadata comment lines
3. If `LDAU=True` but no U values, force `LDAU=False`

#### SetEcat class hierarchy

| Class | pymatgen parent | Calculation |
|---|---|---|
| `BulkRelaxSetEcat` | `MPMetalRelaxSet` | Bulk relaxation |
| `SlabSetEcat` | `MVLSlabSet` | Surface slab |
| `MPStaticSetEcat` | `MPStaticSet` | Static single-point |
| `LobsterSetEcat` | `LobsterSet` | Lobster COHP |
| `NEBSetEcat` | `NEBSet` | NEB |
| `FreqSetEcat` | `MPStaticSetEcat` | Frequency / vibrational |
| `DimerSetEcat` | `MPStaticSetEcat` | Dimer transition-state |
| `NBOSetEcat` | `MPStaticSetEcat` | NBO analysis |
| `NMRSetEcat` | `MPStaticSetEcat` | NMR (CS or EFG) |
| `MDSetEcat` | `MPStaticSetEcat` | Molecular dynamics |

> Note: `FreqSetEcat`, `DimerSetEcat`, `NBOSetEcat`, `NMRSetEcat`, and `MDSetEcat`
> all inherit from the project's own `MPStaticSetEcat` (not directly from pymatgen's
> `MPStaticSet`), so they pick up the `_build_incar` post-processing logic.

#### `MDSetEcat` — dedicated MD constructor params

Unlike other SetEcat classes, `MDSetEcat` takes MD-specific constructor arguments
(not just `user_incar_settings`):

```python
MDSetEcat(
    structure=...,
    ensemble="nvt",       # "nvt" or "npt"
    start_temp=300.0,     # TEBEG
    end_temp=300.0,       # TEEND
    nsteps=1000,          # NSW
    time_step=None,       # POTIM; auto-set: 0.5 fs if H present, else 2.0 fs (NVT)
    spin_polarized=False, # ISPIN=2 if True
    langevin_gamma=None,  # NPT: per-element Langevin friction [10.0]*n_elems default
    ...
)
```

`WorkflowEngine._write_md()` reads `start_temp`, `end_temp`, `nsteps`, `time_step`
from `WorkflowConfig` fields and passes them as constructor arguments.

---

### 3.4 `maker.py` — Legacy Direct-Use Factory

> **Note:** `VaspInputMaker` is **no longer called by `WorkflowEngine`**.  
> The `WorkflowEngine.run()` dispatch was refactored to call module-level `_write_*()`
> functions in `workflow_engine.py` directly.  
> `VaspInputMaker` is retained for:
> - Direct low-level use in scripts or notebooks
> - `VaspAPI` backward-compatibility

#### `VaspInputMaker` dataclass attributes

| Attribute | Default | Description |
|---|---|---|
| `functional` | `"PBE"` | DFT functional |
| `kpoints_density` | `50.0` | K-point density |
| `use_default_incar` | `True` | Apply built-in INCAR defaults |
| `use_default_kpoints` | `True` | Auto-generate KPOINTS |
| `user_incar_settings` | `{}` | Global INCAR overrides |
| `user_potcar_functional` | `"PBE_54"` | POTCAR functional tag |

#### `write_*` methods

| Method | Calc types served |
|---|---|
| `write_bulk(structure, output_dir)` | `BULK_RELAX` |
| `write_slab(structure, output_dir)` | `SLAB_RELAX` |
| `write_noscf(output_dir, structure, prev_dir)` | `STATIC_SP`, `DOS_SP`, `CHG_SP`, `ELF_SP` |
| `write_neb(output_dir, start, end, n_images, use_idpp)` | `NEB` |
| `write_dimer(output_dir, neb_dir)` | `DIMER` |
| `write_lobster(output_dir, structure, prev_dir, …)` | `LOBSTER` |
| `write_freq(output_dir, prev_dir, structure, calc_ir, vibrate_indices, adsorbate_formula_prefer)` | `FREQ`, `FREQ_IR` |
| `write_nbo(output_dir, structure, prev_dir, nbo_config)` | `NBO` |
| `write_nmr(output_dir, structure, isotopes)` | `NMR_CS`, `NMR_EFG` |
| `write_md(output_dir, structure, ensemble, …)` | `MD_NVT`, `MD_NPT` |

---

### 3.5 `constants.py` — Constants and Defaults

#### `FUNCTIONAL_INCAR_PATCHES`

Per-functional INCAR patches applied automatically in `_build_incar`.

**User-facing DFT functionals** (specify in `params.yaml`): `PBE` (default), `BEEF`, `SCAN`, `PBE0`, `HSE`.
`BEEFVTST` and `VTST` are **not** separate DFT choices — they are internal PBS script `TYPE1` labels that select the VTST-patched VASP binary for transition-state calculations (NEB/DIMER).

| Functional key | Key INCAR settings |
|---|---|
| `BEEF` | `GGA=BF`, `LUSE_VDW=True`, `AGGAC=0.0`, `LASPH=True` |
| `BEEFVTST` | Identical INCAR to `BEEF`; `TYPE1="beefvtst"` selects VTST-patched binary |
| `SCAN` | `METAGGA=SCAN`, `LASPH=True`, `ADDGRID=True` |
| `HSE` | `LHFCALC=True`, `AEXX=0.25`, `HFSCREEN=0.2`, `LASPH=True` |
| `PBE0` | `LHFCALC=True`, `AEXX=0.25`, `LASPH=True` |

#### `DEFAULT_INCAR_*` templates

One dict per calculation type, used by `CALC_REGISTRY` entries and `*SetEcat` constructors:

```
DEFAULT_INCAR_BULK      Bulk relaxation
DEFAULT_INCAR_SLAB      Surface slab
DEFAULT_INCAR_STATIC    Static calculation (base; MPStaticSetEcat applies this internally)
DEFAULT_INCAR_NEB       NEB
DEFAULT_INCAR_DIMER     Dimer
DEFAULT_INCAR_FREQ      Frequency / vibrational (finite difference)
DEFAULT_INCAR_FREQ_IR   Frequency + IR (DFPT)
DEFAULT_INCAR_LOBSTER   Lobster single-point
DEFAULT_INCAR_NBO       NBO analysis
DEFAULT_INCAR_NMR_CS    NMR chemical shift
DEFAULT_INCAR_NMR_EFG   NMR electric field gradient
DEFAULT_INCAR_MD        MD (NVT)
DEFAULT_INCAR_MD_NPT    MD (NPT)
```

`INCAR_DELTA_STATIC_SP / _DOS / _CHG / _ELF` — incremental overrides applied on
top of the static base for the four static sub-types.

---

### 3.6 `kpoints.py` — K-point Generator

#### `build_kpoints_by_lengths(structure, density)`

Auto-derives a Monkhorst-Pack mesh from lattice vector lengths and a target density:

```
For each lattice direction i:
    n_i = max(1, round(density / |a_i|))

Returns: Kpoints object (Gamma-centred or Monkhorst-Pack)
```

---

### 3.7 `utils.py` — Utility Functions

#### `load_structure(struct_source)`

Smart structure loading supporting multiple input forms:

```
Structure object  → returned directly
File path         → parsed by pymatgen (POSCAR / CIF / CONTCAR / …)
Directory path    → searched in priority order:
                    CONTCAR > POSCAR > POSCAR.vasp > *.vasp > *.cif
String content    → parsed as POSCAR format
```

#### Other utility functions

| Function | Description |
|---|---|
| `convert_vasp_format_to_pymatgen_dict` | VASP format string → Python dict |
| `infer_functional_from_incar` | Infer functional from INCAR file |
| `pick_adsorbate_indices_by_formula_strict` | Select adsorbate atom indices by formula |
| `get_best_structure_path` | Return CONTCAR if it exists, else POSCAR |

---

### 3.8 `script.py` — Job Script Generator

#### `CalcCategory` enum

Calculation category used for PBS/SLURM template selection:

```
RELAX     → relaxation jobs
STATIC    → static single-point
NEB       → NEB / transition-state
DIMER     → Dimer transition-state
LOBSTER   → Lobster post-processing
NBO       → NBO post-processing
FREQ      → frequency calculations
NMR       → NMR calculations
MD        → molecular dynamics
```

#### `Script` class

Renders PBS/SLURM scripts via `{{KEY}}`-style string substitution (not Jinja2; Jinja2 is used only in `workflow/pbs.py`).

**Parameter priority (lowest → highest):**
```
Cluster-wide defaults (cluster_defaults)
    ↓
CalcCategory auto-derived values (walltime / cores / compiler)
    ↓
Explicit user values (cores / walltime / queue)
    ↓
custom_context (full override)
```

---

## 4. Supported Calculation Types

| Calc type | Frontend string | CalcType enum | Description |
|---|---|---|---|
| Bulk relaxation | `bulk_relax` | `BULK_RELAX` | Crystal structure optimisation |
| Slab relaxation | `slab_relax` | `SLAB_RELAX` | Surface model optimisation |
| Static SP | `static_sp` | `STATIC_SP` | Single-point energy |
| Static DOS | `static_dos` | `DOS_SP` | Static + DOS (non-SCF) |
| Static charge | `static_charge` | `CHG_SP` | Static + charge density |
| Static ELF | `static_elf` | `ELF_SP` | Static + electron localisation |
| NEB | `neb` | `NEB` | Minimum energy path |
| Dimer | `dimer` | `DIMER` | Transition-state search |
| Frequency | `freq` | `FREQ` | Vibrational frequency / ZPE |
| Frequency IR | `freq_ir` | `FREQ_IR` | Frequency + IR (DFPT) |
| Lobster | `lobster` | `LOBSTER` | COHP chemical-bonding analysis |
| NMR CS | `nmr_cs` | `NMR_CS` | NMR chemical shift |
| NMR EFG | `nmr_efg` | `NMR_EFG` | NMR electric field gradient |
| NBO | `nbo` | `NBO` | Natural Bond Orbital analysis |
| MD NVT | `md_nvt` | `MD_NVT` | NVT molecular dynamics |
| MD NPT | `md_npt` | `MD_NPT` | NPT molecular dynamics |

---

## 5. Parameter Priority and Merge Rules

### INCAR merge (lowest → highest priority)

```
constants.py DEFAULT_INCAR_*            ← calc-type base template
     ↓ overridden by
constants.py INCAR_DELTA_STATIC_*       ← static sub-type increments
     ↓ overridden by
FUNCTIONAL_INCAR_PATCHES                ← functional-specific patch (BEEF/SCAN/…)
     ↓ overridden by
WorkflowConfig.user_incar_overrides     ← merged in WorkflowEngine._get_incar_params()
     ↓ forwarded as user_incar_settings to
*SetEcat constructor → _build_incar()   ← final layer applied inside InputSet
```

Note: when `prev_dir` is set, the relevant `from_prev_calc_ecat()` class methods
inherit the previous INCAR and apply the calc-type-specific defaults on top, then
apply `user_incar_settings` as the final override.

### LDAU safety check

`VaspInputSetEcat.write_input()` enforces:
> If `LDAU=True` is in the INCAR but none of `LDAUL`/`LDAUU`/`LDAUJ` are
> provided, `LDAU` is silently forced to `False` and a warning is logged.

### MAGMOM auto-ISPIN injection

`WorkflowEngine._get_incar_params()` automatically injects `ISPIN=2` when
`MAGMOM` is present in the merged INCAR and the user has not explicitly set `ISPIN`.

---

## 6. Extension Guide

### Adding a new calculation type

**Step 1** — `calc_registry.py`: add a `CalcType` enum value
```python
class CalcType(Enum):
    NEW_TYPE = "new_type"
```

**Step 2** — `constants.py`: add `DEFAULT_INCAR_NEW` dict

**Step 3** — `calc_registry.py`: add a `CalcTypeEntry` row to `CALC_REGISTRY`
```python
CalcType.NEW_TYPE: CalcTypeEntry(
    incar_base=DEFAULT_INCAR_NEW,
    script_category=CalcCategory.STATIC,
    frontend_name="new_type",
),
```

**Step 4** — `input_sets/`: create `NewTypeSetEcat` in the appropriate sub-module
(inherit from the most appropriate `*SetEcat` parent)

**Step 5** — `workflow_engine.py`: add a `_write_new_type()` module-level function
```python
def _write_new_type(
    struct, incar: Dict[str, Any], output_dir: Path, config: "WorkflowConfig",
) -> None:
    struct_obj = load_structure(struct)
    struct_obj = _apply_magmom_compat(struct_obj, incar) or struct_obj
    NewTypeSetEcat(
        structure=struct_obj,
        functional=config.functional,
        kpoints_density=config.kpoints_density,
        use_default_incar=True,
        user_incar_settings=incar,
        user_potcar_functional=_POTCAR_FUNCTIONAL,
    ).write_input(output_dir)
```

**Step 6** — `workflow_engine.py`: add a `case` arm in `WorkflowEngine.run()`
```python
case CalcType.NEW_TYPE:
    _write_new_type(struct, incar_params, output_dir, config)
```

> **Note:** `api.py` requires no changes for new calc types — `calc_type_from_str()` picks up any new `CalcType` member automatically.  Only add to `frontend_params.py` / `from_frontend_dict()` if the new type needs its own structured sub-params beyond the standard `settings` dict.

### Adding a new functional

Add an entry in `constants.py` → `FUNCTIONAL_INCAR_PATCHES`.  `_build_incar`
applies the matching patch automatically — no other changes required.

---

## 7. Usage Examples

### Example 1: Bulk relaxation (minimal)

```python
from flow.workflow_engine import WorkflowEngine, WorkflowConfig, CalcType

engine = WorkflowEngine()
engine.run(WorkflowConfig(
    calc_type=CalcType.BULK_RELAX,   # or the string "bulk_relax"
    structure="/path/to/POSCAR",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "EDIFFG": -0.02,
        "ENCUT":  520,
        "NPAR":   4,
    },
    output_dir="/path/to/output",
))
# Writes: POSCAR  INCAR  KPOINTS  POTCAR  submit.sh
```

### Example 2: DFT+U bulk relaxation

```python
engine.run(WorkflowConfig(
    calc_type="bulk_relax",
    structure="/path/to/Fe3O4_POSCAR",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "ISPIN":   2,
        "LMAXMIX": 4,
        "MAGMOM":  {"Fe": 5.0, "O": 0.6},
        "LDAU":    True,
        "LDAUTYPE": 2,
        "LDAUU":   {"Fe": 4.0, "O": 0.0},
        "LDAUL":   {"Fe": 2,   "O": -1},
        "LDAUJ":   {"Fe": 0.0, "O": 0.0},
    },
    output_dir="/path/to/output",
))
```

### Example 3: Static DOS using previous calculation

```python
engine.run(WorkflowConfig(
    calc_type="static_dos",
    prev_dir="/path/to/bulk_relax/",  # inherits INCAR/KPOINTS, reads CONTCAR
    functional="PBE",
    kpoints_density=80.0,
    user_incar_overrides={"NEDOS": 4001, "ISMEAR": -5, "NPAR": 4},
    output_dir="/path/to/dos_output",
))
```

### Example 4: Molecular dynamics (NVT)

```python
engine.run(WorkflowConfig(
    calc_type=CalcType.MD_NVT,
    structure="/path/to/Fe_bulk/POSCAR",
    functional="PBE",
    kpoints_density=1.0,        # Gamma-only for MD
    start_temp=1000.0,          # TEBEG (K)
    end_temp=1000.0,            # TEEND (K)  — equal = isothermal
    nsteps=10000,               # NSW
    time_step=2.0,              # POTIM (fs); auto-set to 0.5 fs if H present
    user_incar_overrides={
        "MAGMOM": {"Fe": 2.5},
        "ISPIN":  2,
        "NPAR":   4,
    },
    output_dir="/path/to/md_output",
))
```

### Example 5: NEB transition-state search

```python
engine.run(WorkflowConfig(
    calc_type=CalcType.NEB,
    start_structure="/path/to/IS_relax/CONTCAR",
    end_structure="/path/to/FS_relax/CONTCAR",
    n_images=6,
    use_idpp=True,
    functional="PBE",
    kpoints_density=25.0,
    user_incar_overrides={"SPRING": -5, "NPAR": 4},
    output_dir="/path/to/neb_output",
))
```

### Example 6: Lobster with multiple cohpGenerator entries

```python
engine.run(WorkflowConfig(
    calc_type="lobster",
    prev_dir="/path/to/slab_relax/",
    functional="PBE",
    kpoints_density=50.0,
    lobster_overwritedict={
        "COHPstartEnergy": -20.0,
        "COHPendEnergy":    20.0,
        "cohpGenerator": "from 1.8 to 2.3 type Fe type O orbitalwise",
    },
    lobster_custom_lines=[
        "cohpGenerator from 1.1 to 1.5 type C type O orbitalwise",
    ],
    output_dir="/path/to/lobster_output",
))
```

### Example 7: Via FrontendAdapter (frontend dict path)

```python
from flow.api import FrontendAdapter
from flow.workflow_engine import WorkflowEngine

data = {
    "calc_type": "bulk_relax",
    "xc": "PBE",
    "kpoints": {"density": 50.0},
    "structure": {"source": "file", "id": "/path/to/POSCAR"},
    "settings": {
        "ENCUT": 520,
        "EDIFF": 1e-5,
        "MAGMOM": {"Fe": 5.0, "O": 0.6},
        "LDAUU":  {"Fe": 4.0, "O": 0.0},
        "LDAUL":  {"Fe": 2,   "O": -1},
        "LDAUJ":  {"Fe": 0.0, "O": 0.0},
    },
    "prev_dir": None,
}

params = FrontendAdapter.from_frontend_dict(data)
params.output_dir = "/path/to/output"
WorkflowEngine().run(params.to_workflow_config())
```

### Example 8: Direct VaspInputMaker use (low-level, bypass WorkflowEngine)

```python
from flow.maker import VaspInputMaker
from pymatgen.core import Structure

# VaspInputMaker is NOT used by WorkflowEngine; use it only for low-level control.
maker = VaspInputMaker(
    functional="SCAN",
    kpoints_density=60.0,
    user_incar_settings={"ENCUT": 600, "LASPH": True},
    user_potcar_functional="PBE_54",
)
structure = Structure.from_file("POSCAR")
maker.write_bulk(structure=structure, output_dir="/output/scan_relax")
```

### Example 9: Job script generation

```python
from flow.script import Script, CalcCategory

script = Script(
    calc_category=CalcCategory.RELAX,
    functional="BEEF",
    cores=32,
    walltime=24,
    queue="low",
)
script.render_script(
    output_path="/path/to/submit.pbs",
    job_name="bulk_relax_Fe3O4",
    workdir="/path/to/workdir",
    vasp_cmd="mpirun vasp_std",
    extra_cmd="",
)
```
