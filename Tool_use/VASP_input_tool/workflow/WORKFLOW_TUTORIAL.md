# High-Throughput VASP Workflow — Complete Usage Guide

> **Scope:** This document covers every aspect of the `flow.workflow` package —
> configuration, stage-by-stage operation, CLI commands, the marker-file state
> machine, and a complete troubleshooting handbook.  It is written so a new user
> can follow it top-to-bottom, while experienced users can jump directly to any
> section as a quick reference.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Project Directory Layout](#3-project-directory-layout)
4. [params.yaml — Complete Reference](#4-paramsyaml--complete-reference)
5. [Workflow Stages — How Each One Works](#5-workflow-stages--how-each-one-works)
6. [CLI Commands](#6-cli-commands)
7. [Marker Files and State Machine](#7-marker-files-and-state-machine)
8. [Running a Calculation End-to-End](#8-running-a-calculation-end-to-end)
9. [Common Errors and How to Fix Them](#9-common-errors-and-how-to-fix-them)
10. [Advanced Topics](#10-advanced-topics)
    - [10.1 Adding a custom stage](#101-adding-a-custom-stage)
    - [10.2 Using a structure object directly (programmatic API)](#102-using-a-structure-object-directly-programmatic-api)
    - [10.3 Inspecting the manifest programmatically](#103-inspecting-the-manifest-programmatically)
    - [10.4 Bulk-marking many completed jobs as done](#104-bulk-marking-many-completed-jobs-as-done)
    - [10.5 Understanding DirLock on shared filesystems](#105-understanding-dirlock-on-shared-filesystems)
    - [10.6 DFT+U and MAGMOM Configuration](#106-dftu-and-magmom-configuration)
    - [10.7 Multiple cohpGenerator Entries in lobsterin](#107-multiple-cohpgenerator-entries-in-lobsterin)
11. [Alternative Entry Points](#11-alternative-entry-points)

---

## 1. Architecture Overview

```
params.yaml  ──►  load_config()  ──►  WorkflowConfig
                                           │
                  hook.py (CLI)            │
                  ┌────────────────────────┘
                  │
                  ├─ expand_manifest()   build / refresh manifest.json
                  │    ├── BulkToSlabGenerator   (structure/slab.py)
                  │    └── AdsorptionModify       (structure/adsorption.py)
                  │
                  ├─ _submit_task()
                  │    ├── stage.prepare()  →  FrontendAdapter → WorkflowEngine
                  │    ├── render_template()  (pbs.py, Jinja2)
                  │    └── submit_job()       (pbs.py, qsub)
                  │
                  └─ mark_done_by_workdir()   check OUTCAR / lobsterout
```

**Key design decisions:**

| Concern | Where handled |
|---|---|
| Configuration | `config.py` — typed dataclasses, validated at load |
| Stage logic | `stages/` — one class per stage, ABC contract |
| Structure generation | `structure/` — `BulkToSlabGenerator`, `AdsorptionModify` |
| PBS submission | `pbs.py` — `DirLock`, `render_template`, `submit_job` |
| State on disk | `markers.py` — `done.ok`, `submitted.json` |
| VASP input writing | `flow.api.FrontendAdapter` + `flow.workflow_engine.WorkflowEngine` |
| Task graph | `manifest.json` inside `run_root/` |

The workflow is **re-entrant**: you can run the hook repeatedly (e.g. from a
PBS epilogue or a cron job) and it will always do the right thing — skip
completed tasks, pick up submitted ones, and generate only what is new.

---

## 2. Prerequisites

### Python packages

```bash
pip install pymatgen ase jinja2 pyyaml scipy numpy
```

### Cluster environment

- PBS/Torque scheduler (`qsub`, `qstat` on `$PATH`)
- VASP executable accessible from the PBS node (paths hardcoded in `pbs_hook.sh.tpl`)
- For Lobster stages: set `LOBSTER_BIN` in your `~/.bashrc` or cluster module:
  ```bash
  export LOBSTER_BIN=/path/to/lobster
  ```
- For NBO stages: set `NBO_BIN` in your `~/.bashrc` or cluster module:
  ```bash
  export NBO_BIN=/path/to/nbo7
  ```

> **Note:** Binary paths for LOBSTER and NBO are **not** configured in
> `params.yaml`.  They are read from shell environment variables at runtime.

### Environment smoke-test

```bash
# 使用集群上的完整 Python 路径替换 /path/to/python（参见 params.yaml python_runtime 配置）
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
cd /data2/home/luodh/high-calc-2

$PYTHON -c "from flow.workflow import hook; print('hook OK')"
$PYTHON -c "from flow.workflow.stages import STAGE_ORDER; print(STAGE_ORDER)"
$PYTHON -c "from flow.workflow.structure.utils import load_structure; print('structure OK')"
$PYTHON -c "
from flow.workflow.config import load_config
cfg = load_config('flow/workflow/params.yaml')
print('config OK:', cfg.project.run_root)
"
```

All four lines should print without errors.

---

## 3. Project Directory Layout

```
/data2/home/luodh/high-calc-2/          ← project_root
├── structure/                           ← input bulk structures
│   ├── POSCAR_PtSnCu
│   ├── POSCAR_Fe3O4
│   └── ...
├── workflow/
│   └── pbs_hook.sh.tpl                 ← PBS script Jinja2 template
└── runs/                               ← run_root (created automatically)
    ├── manifest.json                   ← task graph (auto-managed)
    ├── _generated_slabs/               ← intermediate slab POSCARs
    │   └── PtSnCu/hkl_110/5L/
    ├── _generated_ads/                 ← intermediate adsorption POSCARs
    └── bulk_relax/
        └── PtSnCu/
            ├── INCAR  KPOINTS  POSCAR  POTCAR
            ├── job.pbs
            ├── submitted.json          ← written after qsub
            └── done.ok                 ← written after mark-done
```

**Structure file naming convention:**

The workflow auto-extracts a `bulk_id` from each file name:

| File name | Extracted `bulk_id` |
|---|---|
| `POSCAR_PtSnCu` | `PtSnCu` |
| `CONTCAR_Fe3O4` | `Fe3O4` |
| `POSCAR.CoMnO2` | `CoMnO2` |
| `my_structure`  | `my_structure` (stem) |

The `bulk_id` becomes the directory name under every stage, e.g.
`runs/bulk_relax/PtSnCu/`.

---

## 4. params.yaml — Complete Reference

Below is a fully annotated version of `params.yaml`.  Fields marked
**[required]** will raise `ValueError` at load time if missing.

```yaml
# ─────────────────────────────────────────────────────────────
# PROJECT — paths (all resolved to absolute at load time)
# ─────────────────────────────────────────────────────────────
project:
  project_root: /data2/home/luodh/high-calc-2   # [required] repo root
  run_root:     /data2/home/luodh/high-calc-2/runs  # [required] all calc dirs live here
  templates_dir: /data2/home/luodh/high-calc-2/workflow  # optional

# ─────────────────────────────────────────────────────────────
# PBS — job scheduler settings
# nodes is intentionally omitted: the template hard-wires nodes=1
# ─────────────────────────────────────────────────────────────
pbs:
  queue: low                     # [required] PBS queue name
  ppn: 72                        # processors per node (default: 72)
  walltime: "124:00:00"          # max wall-clock time (HH:MM:SS)
  job_name_prefix: "high_calc"   # prepended to every submitted job name
  template_file: "./pbs_hook.sh.tpl"  # [required] path to Jinja2 PBS template

# ─────────────────────────────────────────────────────────────
# PYTHON RUNTIME — conda env used inside PBS jobs
# ─────────────────────────────────────────────────────────────
python_runtime:
  conda_sh:   "/data2/home/luodh/anaconda3/etc/profile.d/conda.sh"
  conda_env:  "workflow"
  python_bin: "/data2/home/luodh/anaconda3/envs/workflow/bin/python"

# ─────────────────────────────────────────────────────────────
# STRUCTURE — path to bulk structure file(s)
# Required when bulk_relax is enabled.
# Can be a single file or a directory.
# Directory: scanned for POSCAR_*, CONTCAR_*, POSCAR.*, CONTCAR.*
# ─────────────────────────────────────────────────────────────
structure: "/data2/home/luodh/high-calc-2/structure"

# ─────────────────────────────────────────────────────────────
# WORKFLOW.STAGES — enable/disable each stage
# ─────────────────────────────────────────────────────────────
workflow:
  stages:
    bulk_relax:         true
    bulk_dos:           true
    bulk_lobster:       false
    bulk_nbo:           false
    slab_relax:         true
    slab_dos:           true
    slab_lobster:       true
    slab_nbo:           false
    adsorption:         true
    adsorption_freq:    true
    adsorption_lobster: false
    adsorption_nbo:     false

# ─────────────────────────────────────────────────────────────
# BULK — VASP settings for bulk_relax
# ─────────────────────────────────────────────────────────────
bulk:
  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 50
    user_incar_settings:
      NPAR: 4
      ISIF: 3          # full cell relaxation
      MAGMOM:          # per-element initial moments
        Co: 3.0
        Fe: 5.0
        O: 0.6

# ─────────────────────────────────────────────────────────────
# BULK_DOS — VASP settings for bulk_dos (non-SCF DOS)
# ─────────────────────────────────────────────────────────────
bulk_dos:
  vasp:
    functional: "BEEF"
    kpoints_density: 50
    number_of_dos: 2001   # sets NEDOS in INCAR (also accepted as number_of_docs)
    user_incar_settings:
      LORBIT: 11
      ISMEAR: -5

# ─────────────────────────────────────────────────────────────
# SLAB — slab generation + VASP settings for slab_relax
# ─────────────────────────────────────────────────────────────
slab:
  miller_list: [[1,1,0], [1,1,1]]  # one slab run per miller index

  slabgen:
    target_layers: 5           # [required] desired number of atomic layers
    vacuum_thickness: 15       # Å
    fix_bottom_layers: 2       # layers with selective_dynamics=F
    fix_top_layers: 0
    all_fix: false             # if true, ALL atoms are fixed
    symmetric: false           # trim symmetrically from top AND bottom
    center: true               # center slab in vacuum
    primitive: true
    lll_reduce: true
    hcluster_cutoff: 0.25      # Å, hierarchical clustering threshold for layer detection
    supercell_matrix: null     # e.g. [[2,0,0],[0,2,0],[0,0,1]] or null
    standardize_bulk: true

  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 25
    auto_dipole: true
    user_incar_settings:
      LVHAR: true
      IDIPOL: 3
      MAGMOM: {Co: 3.0, Fe: 5.0}

# ─────────────────────────────────────────────────────────────
# SLAB_DOS — VASP settings for slab_dos
# ─────────────────────────────────────────────────────────────
slab_dos:
  vasp:
    functional: "BEEF"
    kpoints_density: 60
    number_of_dos: 2001
    user_incar_settings:
      LORBIT: 11
      ISMEAR: -5
      ENCUT: 520

# ─────────────────────────────────────────────────────────────
# ADSORPTION — molecule placement + VASP settings
# ─────────────────────────────────────────────────────────────
adsorption:
  build:
    mode: "site"              # "site" or "enumerate"
    molecule_formula: "CO"    # ASE molecule name or path to a structure file
    site_type: "ontop"        # default site type (used as fallback)
    height: 1.8               # Å above the surface
    reorient: true            # orient molecule toward surface normal
    selective_dynamics: false
    find_args:                # passed to AdsorbateSiteFinder.find_adsorption_sites()
      positions: ["ontop"]    # which site types to enumerate

  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 25
    auto_dipole: true
    user_incar_settings:
      LVHAR: true
      IDIPOL: 3

# ─────────────────────────────────────────────────────────────
# FREQ — vibrational frequency calculation
# ─────────────────────────────────────────────────────────────
freq:
  vasp:
    functional: "BEEF"
    kpoints_density: 25
    user_incar_settings:
      IBRION: 5
      POTIM: 0.015
      NFREE: 2
      NSW: 1
  settings:
    mode: "adsorbate"              # "inherit" / "adsorbate" / "indices"
    adsorbate_formula: "CO"
    adsorbate_formula_prefer: "tail"   # "tail" = last N atoms in POSCAR

# ─────────────────────────────────────────────────────────────
# LOBSTER — per-stage COHP analysis
#
# Each stage (bulk_lobster / slab_lobster / adsorption_lobster)
# has its own configuration section below.  If you need all stages
# to share identical settings, you may instead use a single top-level
# "lobster:" section as a global fallback.
#
# Binary path: set in your cluster environment, NOT here:
#   export LOBSTER_BIN=/path/to/lobster
# ─────────────────────────────────────────────────────────────

# bulk_lobster — used when workflow.stages.bulk_lobster: true
bulk_lobster:
  vasp_singlepoint:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LORBIT: 11
      LWAVE: true
      LCHARG: false
      ISYM: 0
    lobsterin_settings:             # written to lobsterin, NOT INCAR
      COHPstartEnergy: -20.0
      COHPendEnergy: 20.0
      cohpGenerator: "from 1.5 to 1.9 orbitalwise"

# slab_lobster — used when workflow.stages.slab_lobster: true
slab_lobster:
  vasp_singlepoint:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LORBIT: 11
      LWAVE: true
      LCHARG: false
      ISYM: 0
    lobsterin_settings:
      COHPstartEnergy: -20.0
      COHPendEnergy: 20.0
      cohpGenerator: "from 1.5 to 1.9 orbitalwise"

# adsorption_lobster — used when workflow.stages.adsorption_lobster: true
adsorption_lobster:
  vasp_singlepoint:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LORBIT: 11
      LWAVE: true
      LCHARG: false
      ISYM: 0
    lobsterin_settings:
      COHPstartEnergy: -20.0
      COHPendEnergy: 20.0
      cohpGenerator: "from 1.5 to 1.9 orbitalwise"

# ─────────────────────────────────────────────────────────────
# NBO — per-stage Natural Bond Orbital analysis
#
# Each stage (bulk_nbo / slab_nbo / adsorption_nbo) has its own
# configuration section.  A global "nbo:" fallback is also supported.
#
# Binary path: set in your cluster environment, NOT here:
#   export NBO_BIN=/path/to/nbo7
# ─────────────────────────────────────────────────────────────

# bulk_nbo — used when workflow.stages.bulk_nbo: true
bulk_nbo:
  vasp_singlepoint:
    functional: "BEEF"
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LWAVE: true
      LCHARG: false
      ISYM: 0
  settings:                         # NBO program input parameters
    basis_source: "ANO-RCC-MB"      # or "custom" + custom_basis_path
    occ_1c: 1.60
    occ_2c: 1.85

# slab_nbo — used when workflow.stages.slab_nbo: true
slab_nbo:
  vasp_singlepoint:
    functional: "BEEF"
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LWAVE: true
      LCHARG: false
      ISYM: 0
  settings:
    basis_source: "ANO-RCC-MB"
    occ_1c: 1.60
    occ_2c: 1.85

# adsorption_nbo — used when workflow.stages.adsorption_nbo: true
adsorption_nbo:
  vasp_singlepoint:
    functional: "BEEF"
    kpoints_density: 50
    user_incar_settings:
      IBRION: -1
      NSW: 0
      LWAVE: true
      LCHARG: false
      ISYM: 0
  settings:
    basis_source: "ANO-RCC-MB"
    occ_1c: 1.60
    occ_2c: 1.85
```

---

## 5. Workflow Stages — How Each One Works

The stages run in a fixed dependency order:

```
bulk_relax ──► bulk_dos
            ├► bulk_lobster
            ├► bulk_nbo
            └► slab_relax ──► slab_dos
                           ├► slab_lobster
                           ├► slab_nbo
                           └► adsorption ──► adsorption_freq
                                          ├► adsorption_lobster
                                          └► adsorption_nbo
```

An arrow `A ──► B` means *B will not be submitted until A has a `done.ok`
marker*.

### 5.1 `bulk_relax`

**What it does:** Full ionic + cell relaxation of the bulk structure (ISIF=3).

**Inputs needed:**
- `task_meta["structure"]` — path to the POSCAR/CONTCAR file (set by
  `expand_manifest()` from your `structure:` directory).

**Success check:** OUTCAR contains `"total cpu time used"`,
`"voluntary context switches"`, or
`"General timing and accounting informations"`.

**Key params.yaml section:** `bulk.vasp`

---

### 5.2 `bulk_dos`

**What it does:** Non-self-consistent DOS calculation. Reads charge density
from `bulk_relax` workdir.

**Gate:** `bulk_relax` must be marked done.

**Key params.yaml section:** `bulk_dos.vasp`  
Set `number_of_dos: 2001` (or `number_of_docs`) to control NEDOS.

---

### 5.3 `bulk_lobster` / `slab_lobster` / `adsorption_lobster`

**What it does:** Re-runs a VASP single-point with `LWAVE=true`, then calls the
LOBSTER binary to compute COHP.

**Gate:** The preceding relax stage must be done.

**LOBSTER binary:** Read from environment variable `$LOBSTER_BIN`.  Set this
in your `~/.bashrc` or cluster module before submitting jobs.

**Success check (all four required, in order):**
1. OUTCAR shows normal termination
2. `lobsterout` exists and is non-empty
3. `ICOHPLIST.lobster` exists and is non-empty
4. `lobsterout` tail contains `finished in <N>` (LOBSTER timing summary line)

**Key params.yaml sections:** Each stage has its own section:
- `bulk_lobster.vasp_singlepoint` — INCAR settings for bulk Lobster
- `slab_lobster.vasp_singlepoint` — INCAR settings for slab Lobster
- `adsorption_lobster.vasp_singlepoint` — INCAR settings for adsorption Lobster
- `*.vasp_singlepoint.lobsterin_settings` — lobsterin parameters (not INCAR)

---

### 5.4 `slab_relax`

**What it does:** Generates slabs from the relaxed bulk structure and relaxes
each one.

**Gate:** `bulk_relax` done (uses CONTCAR as the slab source).

**Slab generation (inside `expand_manifest()`):**
1. Acquires a `DirLock` on `_generated_slabs/<bulk_id>/<hkl>/<L>L/.slabgen.lock`.
2. Calls `BulkToSlabGenerator.run_from_dict()` for each Miller index listed in
   `slab.miller_list`.
3. Writes one POSCAR per termination into each task's workdir.
4. Registers all tasks in `manifest.json`.

**Key params.yaml sections:**  
- `slab.miller_list` — which Miller planes to cut  
- `slab.slabgen.*` — layer count, vacuum, fixation, supercell  
- `slab.vasp` — INCAR / kpoints

---

### 5.5 `slab_dos`

Analogous to `bulk_dos` but for slabs.  Gate: `slab_relax` done.

**Key params.yaml section:** `slab_dos.vasp`

---

### 5.6 `adsorption`

**What it does:** Places a molecule on each adsorption site found on each
relaxed slab and submits a relaxation.

**Gate:** `slab_relax` done.

**Site enumeration (inside `expand_manifest()`):**
1. Acquires `DirLock` on `_generated_ads/.../.adsgen.lock`.
2. Instantiates `AdsorptionModify` with the slab CONTCAR.
3. Calls `find_adsorption_sites(**find_args)`.
4. For each site type and index, places the molecule and writes a POSCAR.

**Key params.yaml section:** `adsorption.build.*`

---

### 5.7 `adsorption_freq`

**What it does:** Vibrational frequency calculation.  Uses IBRION=5 with the
adsorbate atoms free and the slab frozen.

**Gate:** `adsorption` done.

**Vibrate-index resolution (in order of priority):**
1. `freq.settings.vibrate_indices` in params.yaml (explicit list).
2. `freq.settings.adsorbate_formula` — the code searches the CONTCAR for the
   matching molecule by element or tail-position and auto-generates indices.
3. `adsorption.build.molecule_formula` as a fallback formula.

If none of the above resolves, `prepare()` raises:
```
adsorption_freq: mode='inherit' and no adsorbate_formula/vibrate_indices found.
```

---

### 5.8 `bulk_nbo` / `slab_nbo` / `adsorption_nbo`

**What it does:** VASP single-point (LWAVE=True) followed by NBO7 program analysis.

**NBO binary:** Read from environment variable `$NBO_BIN`.  Set this in your
`~/.bashrc` or cluster module before submitting jobs.

**Success check:** OUTCAR OK **and** `nboout` exists and is non-empty.

**Key params.yaml sections:** Each stage has its own section with
`vasp_singlepoint` and `settings` sub-sections:
- `bulk_nbo` — for bulk NBO
- `slab_nbo` — for slab NBO
- `adsorption_nbo` — for adsorption NBO

---

## 6. CLI Commands

All commands require `--params` pointing at `params.yaml`.

```
python -m flow.workflow.hook --params /path/to/params.yaml <subcommand> [options]
```

### `expand`

Scans structure files and `manifest.json`, adds new tasks that are now
reachable (gates satisfied), writes updated `manifest.json`.  Does **not**
submit anything.

```bash
python -m flow.workflow.hook --params params.yaml expand
```

Use this to preview what tasks would be created, or to refresh the manifest
after you manually copy a structure file.

---

### `auto`

Expands the manifest, then submits the **single highest-priority eligible task**
(lowest stage-order rank, then lexicographic task id).

```bash
python -m flow.workflow.hook --params params.yaml auto

# Re-submit even if submitted.json exists (作业被队列杀死后重新递交):
python -m flow.workflow.hook --params params.yaml auto --resubmit

# Re-run even if done.ok exists (重跑已完成任务，谨慎使用):
python -m flow.workflow.hook --params params.yaml auto --rerun-done

# Submit only tasks of a specific stage (只递交指定阶段的内容):
python -m flow.workflow.hook --params params.yaml auto --stage slab_relax
```

| Option | Description |
|---|---|
| `--resubmit` | Re-submit even if `submitted.json` already exists (use when scheduler killed the job) |
| `--rerun-done` | Re-run even if `done.ok` already exists (use with caution) |
| `--ignore-deps` | Skip dependency gate checks (dangerous) |
| `--stage STAGE` | Filter to tasks of one specific stage |

Typical usage: call `auto` from a PBS epilogue so that each completing job
automatically triggers the next one.

---

### `submit-all`

Expands the manifest, then submits **all currently eligible tasks** in one
call.

```bash
python -m flow.workflow.hook --params params.yaml submit-all

# Submit at most 5 tasks at once (控制单次递交的数目):
python -m flow.workflow.hook --params params.yaml submit-all --limit 5

# Only submit adsorption tasks (只递交吸附阶段的内容):
python -m flow.workflow.hook --params params.yaml submit-all --stage adsorption
```

| Option | Description |
|---|---|
| `--resubmit` | Re-submit even if `submitted.json` exists |
| `--rerun-done` | Re-run even if `done.ok` exists (use with caution) |
| `--ignore-deps` | Skip dependency gate checks (dangerous) |
| `--stage STAGE` | Filter to tasks of one specific stage |
| `--limit N` | Cap total submissions at N (0 = unlimited, default) |

---

### `mark-done`

Manually checks OUTCAR (and lobsterout/nboout for lobster/nbo stages) in a
given workdir and writes `done.ok` if the check passes.

```bash
python -m flow.workflow.hook --params params.yaml mark-done \
    --workdir /data2/home/luodh/high-calc-2/runs/bulk_relax/PtSnCu
```

This is called automatically from the PBS epilogue script (via `pbs_hook.sh.tpl`),
but you can also run it manually to recover a completed job whose epilogue
did not fire.

---

### `extract`

Parses all completed calculations and reports energies (and optionally
adsorption energies relative to molecule references).

```bash
# Print table to stdout (default):
python -m flow.workflow.hook --params params.yaml extract

# Write to file in a specific format:
python -m flow.workflow.hook --params params.yaml extract \
    --output results.csv --format csv

# Filter to specific stages:
python -m flow.workflow.hook --params params.yaml extract \
    --stages bulk_relax,slab_relax

# Provide molecule reference energies for adsorption energy calculation:
python -m flow.workflow.hook --params params.yaml extract \
    --mol-ref CO=-14.78 --mol-ref H2=-6.77
```

| Option | Description |
|---|---|
| `--output FILE` | Output file path; omit to write to stdout |
| `--format` | `table` (default) / `json` / `csv` |
| `--stages` | Comma-separated stage filter; omit for all stages |
| `--mol-ref FORMULA=eV` | Molecule reference energy (repeatable) |

---

### Recommended PBS epilogue pattern

Inside `pbs_hook.sh.tpl`, the final block calls only `mark-done`:

```bash
# At the end of the PBS script, after VASP / LOBSTER finish:
"${PYTHON}" "${HOOK_SCRIPT}" --params "${PARAMS_FILE}" \
    mark-done --workdir "${WORKDIR}" >> "${LOG_FILE}" 2>&1
```

> **Note:** The template does **not** automatically call `auto`.  To advance
> downstream tasks you need to trigger `auto` or `submit-all` from outside
> the PBS job — either from a cron job or by running it manually after
> checking which tasks completed:
>
> ```bash
> # Manual: submit all newly eligible tasks after jobs finish
> python -m flow.workflow.hook --params params.yaml submit-all
> ```
>
> See §8 Step 7 and the deployment guide (`DEPLOYMENT.md`) for recommended
> cron-based automation patterns.

---

## 7. Marker Files and State Machine

The workflow uses **three marker files per workdir** as the sole source of truth.
The PBS scheduler is never queried to determine whether a job is "still running".

```
workdir/
├── submitted.json     written immediately after qsub succeeds
├── done.ok            written after mark-done passes its success check
└── failed.json        written after MAX_RETRIES (3) stale resubmissions
```

### State transitions

```
[not started]
     │
     │  deps satisfied → prepare() + submit_job()
     ▼
[submitted]   submitted.json exists
     │
     ├─ job completes → PBS epilogue calls mark-done
     │       ▼
     │   [done]    done.ok exists  (terminal success state)
     │
     ├─ job goes stale, check_success passes → mark-done → [done]
     │
     ├─ job goes stale, retry_count < MAX_RETRIES (3) → resubmit → [submitted]
     │
     └─ job goes stale, retry_count ≥ MAX_RETRIES → write failed.json
             ▼
         [failed]  failed.json exists  (terminal failure state; task skipped)
```

A submission is considered **stale** when `submitted.json` exists but the
`job_id` recorded in it no longer appears in `qstat` output, and the grace
period (`_STALE_GRACE_PERIOD_SECONDS = 300 s`) has passed.

### submitted.json contents

```json
{
  "task_id":     "bulk_relax:PtSnCu",
  "stage":       "bulk_relax",
  "workdir":     "/data2/home/luodh/high-calc-2/runs/bulk_relax/PtSnCu",
  "job_id":      "12345.pbs-server",
  "time":        "2025-03-01 14:22:10",
  "retry_count": 0
}
```

### done.ok contents

```json
{
  "workdir":       "/data2/home/luodh/high-calc-2/runs/bulk_relax/PtSnCu",
  "time":          "2025-03-01 18:47:03",
  "success_check": "OUTCAR",
  "stage":         "bulk_relax"
}
```

### failed.json contents

Written when a task exceeds `MAX_RETRIES = 3` stale resubmissions:

```json
{
  "task_id":     "bulk_relax:PtSnCu",
  "stage":       "bulk_relax",
  "workdir":     "/data2/home/luodh/high-calc-2/runs/bulk_relax/PtSnCu",
  "time":        "2025-03-01 20:10:05",
  "retry_count": 4,
  "reason":      "exceeded MAX_RETRIES"
}
```

### Manually resetting a task

To force a task to re-run from scratch:

```bash
# Remove all three markers and re-submit
rm runs/bulk_relax/PtSnCu/done.ok
rm runs/bulk_relax/PtSnCu/submitted.json
rm -f runs/bulk_relax/PtSnCu/failed.json
python -m flow.workflow.hook --params params.yaml auto --stage bulk_relax
```

To force re-submission without re-generating inputs:

```bash
rm runs/bulk_relax/PtSnCu/submitted.json
python -m flow.workflow.hook --params params.yaml auto --resubmit --stage bulk_relax
```

To recover a task stuck in the failed state (exceeded retry limit):

```bash
# Investigate why it failed, fix the underlying issue, then:
rm runs/bulk_relax/PtSnCu/failed.json
rm runs/bulk_relax/PtSnCu/submitted.json
python -m flow.workflow.hook --params params.yaml auto --stage bulk_relax
```

---

## 8. Running a Calculation End-to-End

### Step 1 — Prepare your structure files

```bash
mkdir -p /data2/home/luodh/high-calc-2/structure
cp my_bulk_structure.vasp /data2/home/luodh/high-calc-2/structure/POSCAR_MyMaterial
```

File names must follow `POSCAR_<id>`, `CONTCAR_<id>`, `POSCAR.<id>`, or
`CONTCAR.<id>`.

### Step 2 — Edit params.yaml

At minimum:
1. Set `project.project_root`, `project.run_root`.
2. Set `structure` to the directory containing your bulk POSCARs.
3. Set `pbs.template_file` to your PBS template path.
4. Enable the stages you want under `workflow.stages`.
5. Set `slab.miller_list` and `slab.slabgen.target_layers` if using slab stages.
6. Set `adsorption.build.molecule_formula` if using adsorption stages.
7. Configure per-stage Lobster/NBO sections if those stages are enabled.

### Step 3 — Verify config loads cleanly

```bash
python -c "
from flow.workflow.config import load_config
cfg = load_config('flow/workflow/params.yaml')
print('project_root:', cfg.project.run_root)
print('enabled stages:', [s for s in ['bulk_relax','slab_relax','adsorption']
      if getattr(cfg.workflow, s)])
"
```

### Step 4 — Expand manifest (dry run)

```bash
python -m flow.workflow.hook --params flow/workflow/params.yaml expand
cat runs/manifest.json | python -m json.tool | head -60
```

You should see tasks for `bulk_relax` per bulk material.  Slab and adsorption
tasks will not appear yet (their gate — bulk_relax done — is not satisfied).

### Step 5 — Submit first wave

```bash
# Submit all bulk_relax tasks at once:
python -m flow.workflow.hook --params flow/workflow/params.yaml \
    submit-all --stage bulk_relax
```

Or submit one at a time (safer for testing):
```bash
python -m flow.workflow.hook --params flow/workflow/params.yaml auto
```

### Step 6 — Wait for jobs and monitor

```bash
qstat -u $USER

# Check which tasks are done:
find runs/ -name done.ok | sort

# Check which are submitted but not done:
find runs/ -name submitted.json | sort
```

### Step 7 — PBS epilogue auto-advances

The `pbs_hook.sh.tpl` should call `mark-done` and then `auto` at the end of
each job.  This is what propagates:
- `bulk_relax done` → triggers slab generation → submits `slab_relax`
- `slab_relax done` → triggers adsorption generation → submits `adsorption`
- And so on.

### Step 8 — Manual recovery

```bash
# Mark all completed VASP runs as done:
for d in runs/bulk_relax/*/; do
    python -m flow.workflow.hook --params flow/workflow/params.yaml \
        mark-done --workdir "$d"
done

# Then advance the workflow:
python -m flow.workflow.hook --params flow/workflow/params.yaml submit-all
```

---

## 9. Common Errors and How to Fix Them

---

### E-01 — `FileNotFoundError: params.yaml not found`

**Full message:**
```
FileNotFoundError: params.yaml not found: /absolute/path/to/params.yaml
```

**Root cause:** The path passed to `--params` does not exist or is relative and
the working directory is wrong.

**Fix:**
```bash
# Use an absolute path:
python -m flow.workflow.hook \
    --params /data2/home/luodh/high-calc-2/flow/workflow/params.yaml \
    expand

# Or cd to the repo root first:
cd /data2/home/luodh/high-calc-2
python -m flow.workflow.hook --params flow/workflow/params.yaml expand
```

---

### E-02 — `ValueError: Required field 'X' is missing`

**Full message example:**
```
ValueError: Required field 'project_root' is missing in project.
ValueError: Required field 'queue' is missing in pbs.
ValueError: Required field 'template_file' is missing in pbs.
```

**Root cause:** A required key is absent from `params.yaml`.

**Fix:** Open `params.yaml` and add the missing field.  The error message names
the exact key and its YAML section.  See §4 for the complete annotated template.

---

### E-03 — `ValueError: params.yaml must specify at least one of: 'structure', 'slab_source', or 'adsorption_source'`

**Root cause:** None of the three structure source keys are present in
`params.yaml`.

**Fix:** Add at least one:
```yaml
structure: "/data2/home/luodh/high-calc-2/structure"
# or
slab_source: "/path/to/pre-built-slabs"
# or
adsorption_source: "/path/to/pre-built-ads"
```

---

### E-04 — `No structure files found under <path>`

**Full message:**
```
[hook] ERROR: No structure files found under /data2/.../structure.
Expected files like POSCAR_PtSnCu or POSCAR.Fe3O4.
```

**Root cause:** The `structure:` path exists but contains no files matching
`POSCAR_*`, `CONTCAR_*`, `POSCAR.*`, or `CONTCAR.*`.

**Fixes:**
```bash
# Check what's in the directory:
ls /data2/home/luodh/high-calc-2/structure/

# Rename files to the expected pattern:
mv my_material.vasp POSCAR_MyMaterial
```

---

### E-05 — `No stages enabled in workflow.stages`

**Full message:**
```
[hook] ERROR: No stages enabled in workflow.stages.
```

**Root cause:** All stages are set to `false` in `params.yaml`.

**Fix:**
```yaml
workflow:
  stages:
    bulk_relax: true   # enable at least one stage
```

---

### E-06 — `FileNotFoundError: PBS template not found`

**Full message:**
```
FileNotFoundError: PBS template not found: /path/to/pbs_hook.sh.tpl
```

**Root cause:** `pbs.template_file` in `params.yaml` points to a non-existent
file.

**Fix:**
```bash
# Verify the template exists:
ls -la /data2/home/luodh/high-calc-2/workflow/pbs_hook.sh.tpl

# If missing, copy the example template from the repo:
cp flow/workflow/pbs_hook.sh.tpl \
   /data2/home/luodh/high-calc-2/workflow/pbs_hook.sh.tpl
```

---

### E-07 — `jinja2.UndefinedError: 'X' is undefined`

**Full message:**
```
jinja2.UndefinedError: 'conda_env' is undefined
```

**Root cause:** The PBS template references a variable that is not being
passed in the template context.

**Fixes:**

1. Check which variables your template uses: `grep '{{' workflow/pbs_hook.sh.tpl`
2. All variables provided to the template by `_build_pbs_ctx()` are:
   - `project_root`, `run_root`, `stage`, `workdir`, `task_id`, `bulk_id`
   - `params_file`, `hook_script`
   - `queue`, `ppn`, `walltime`, `job_name`
   - `TYPE1` (auto-derived: `"beef"` for BEEF functional, `"org"` for all others)
   - `conda_sh`, `conda_env`, `python_bin`
3. VASP binary details (VER, TYPE2, OPT, COMPILER, VASPHOME, etc.) are
   **hardcoded** inside `pbs_hook.sh.tpl` — do not add them to `params.yaml`.
4. If you need a custom variable, add it to `_build_pbs_ctx()` in `hook.py`.

---

### E-08 — `RuntimeError: qsub failed (rc=1)`

**Full message:**
```
RuntimeError: qsub failed (rc=1). stdout='' stderr='qsub: submit error ...'
```

**Common root causes and fixes:**

| stderr message | Fix |
|---|---|
| `qsub: Unknown queue` | Change `pbs.queue` in params.yaml to a valid queue name (`qstat -Q` lists queues) |
| `qsub: Job exceeds queue resource limits` | Reduce `ppn` or `walltime` |
| `qsub: script file does not exist` | The job.pbs was not written — check the prepare() error earlier in the log |
| `Permission denied` | Ensure the workdir and script are readable by the PBS daemon user |

---

### E-09 — Slab generation fails silently (no slab_relax tasks in manifest)

**Symptom:** After `bulk_relax` tasks finish, running `expand` adds no
`slab_relax` tasks.

**Most likely root causes:**

1. **`slab_relax` not enabled:**
   ```yaml
   workflow:
     stages:
       slab_relax: true   # was false
   ```

2. **`slab.slabgen.target_layers` too large for the structure:** The generator
   requests more layers than pymatgen can produce.  Fix: reduce `target_layers`
   or check the log file at
   `_generated_slabs/<bulk_id>/<hkl>/<L>L/slab_gen.log`.

3. **`slab.miller_list` format is wrong:** Must be a list of lists:
   ```yaml
   miller_list: [[1,1,0]]   # correct
   miller_list: [110]        # wrong — this is parsed as a single integer
   ```

4. **Stale `.slabgen.lock` directory:** If a previous run crashed, the lock
   directory may still exist:
   ```bash
   find runs/_generated_slabs -name ".slabgen.lock" -type d
   rm -rf runs/_generated_slabs/PtSnCu/hkl_110/5L/.slabgen.lock
   ```

5. **`bulk_relax` not marked done:** The slab generation gate requires
   `done.ok` in the bulk_relax workdir.  Check:
   ```bash
   ls runs/bulk_relax/PtSnCu/done.ok
   ```

---

### E-10 — `ValueError: slab.slabgen.target_layers is required`

**Root cause:** The `slabgen` section is present but `target_layers` is missing.

**Fix:**
```yaml
slab:
  slabgen:
    target_layers: 5   # add this
```

---

### E-11 — Adsorption generation produces no tasks

**Symptom:** `slab_relax` tasks finish, `expand` adds no `adsorption` tasks.

**Root causes (check in order):**

1. **`adsorption` not enabled in `workflow.stages`.**

2. **`adsorption.build.molecule_formula` is empty or unrecognised.**
   Verify ASE can build it:
   ```python
   from ase.build import molecule
   molecule("CO")   # should not raise
   ```

3. **`find_adsorption_sites` finds no sites of the requested type.**
   Try broadening the `find_args`:
   ```yaml
   find_args:
     positions: ["ontop", "bridge", "hollow"]
   ```

4. **Stale `.adsgen.lock`:**
   ```bash
   find runs/_generated_ads -name ".adsgen.lock" -type d
   rm -rf runs/_generated_ads/.../.../.adsgen.lock
   ```

---

### E-12 — `adsorption_freq: mode='inherit' and no adsorbate_formula/vibrate_indices found`

**Root cause:** The frequency stage cannot determine which atoms to vibrate.

**Fix (choose one):**

Option A — resolve by formula (recommended):
```yaml
freq:
  settings:
    mode: "adsorbate"
    adsorbate_formula: "CO"
    adsorbate_formula_prefer: "tail"
```

Option B — explicit indices:
```yaml
freq:
  settings:
    mode: "indices"
    vibrate_indices: [72, 73]   # 0-based atom indices in CONTCAR
```

Option C — ensure the CONTCAR from adsorption has correct `selective_dynamics`.
When `mode: "inherit"`, the code reads the CONTCAR and vibrates all atoms
where `selective_dynamics = T T T`.

---

### E-13 — LOBSTER stage never marks done

**Symptom:** The LOBSTER job completes but `done.ok` is never written.

**Success check requires ALL of (in order):**
1. OUTCAR shows normal termination
2. `lobsterout` exists and is non-empty
3. `ICOHPLIST.lobster` exists and is non-empty
4. `lobsterout` tail contains `finished in <N>` (LOBSTER timing summary line)

**Diagnose:**
```bash
WORKDIR=runs/bulk_lobster/PtSnCu

# Check OUTCAR:
tail -20 $WORKDIR/OUTCAR | grep -i "total cpu"

# Check lobsterout:
ls -lh $WORKDIR/lobsterout

# Check required files:
ls -lh $WORKDIR/ICOHPLIST.lobster
```

**Common fixes:**

| Problem | Fix |
|---|---|
| OUTCAR missing or empty | VASP did not run — check PBS stdout/stderr |
| `lobsterout` is empty | LOBSTER crashed — check `lobsterout` for error text |
| `ICOHPLIST.lobster` missing | Wrong `cohpGenerator` range; LOBSTER found no pairs |
| `lobsterout` lacks `finished in N` | LOBSTER terminated abnormally — check `lobster.log` for errors |
| LOBSTER binary not found | Ensure `$LOBSTER_BIN` is set in your cluster environment |

To manually mark done after verifying everything looks correct:
```bash
python -m flow.workflow.hook --params params.yaml \
    mark-done --workdir runs/bulk_lobster/PtSnCu
```

---

### E-14 — `[hook] task locked, skip: id=...`

**Message:**
```
[hook] task locked, skip: id=bulk_relax:PtSnCu
```

**Root cause:** Another process acquired the `DirLock` for this task's workdir.
This is normal when two PBS epilogues fire simultaneously.

**Detecting and removing a stale lock:**
```bash
# The lock directory contains a meta.json with the PID that created it:
cat runs/bulk_relax/PtSnCu/.lock/meta.json
# → {"pid": 98765, "time": "2025-03-01 14:22:10"}

# Check if that PID is still running:
ps -p 98765    # if no output, the process is dead

# If dead, remove the lock:
rm -rf runs/bulk_relax/PtSnCu/.lock
```

---

### E-15 — `[hook] deps not satisfied, skip: id=...`

**Message:**
```
[hook] deps not satisfied, skip: id=slab_relax:PtSnCu:hkl_110:5L:term0
```

**Root cause:** One or more prerequisite tasks listed in `manifest.json`
`deps` array do not have a `done.ok` marker.

**Diagnose:**
```bash
python -c "
import json, os
m = json.load(open('runs/manifest.json'))
t = m['tasks']['slab_relax:PtSnCu:hkl_110:5L:term0']
for dep in t['deps']:
    w = m['tasks'].get(dep, {}).get('workdir', '?')
    print(dep, '  done:', os.path.exists(w+'/done.ok'))
"
```

**Fix:** Mark the blocking upstream task as done (see §6, `mark-done` command).

---

### E-16 — `ValueError: No VASP config found for stage 'slab_relax'`

**Root cause:** `slab_relax` is enabled in `workflow.stages` but the `slab:`
section is missing from `params.yaml`.

**Fix:** Add the complete `slab:` section including `slab.vasp`.

---

### E-17 — `SlabRelaxStage.prepare: POSCAR not found in <workdir>`

**Root cause:** `expand_manifest()` was supposed to write the POSCAR into the
slab workdir, but it is missing.

**Fix:**
```bash
# Check the slab gen log:
cat runs/_generated_slabs/PtSnCu/hkl_110/5L/slab_gen.log

# Re-run expand to regenerate:
rm -rf runs/_generated_slabs/PtSnCu/hkl_110/5L/.slabgen.lock
python -m flow.workflow.hook --params params.yaml expand
```

---

### E-18 — `BulkRelaxStage.prepare: task_meta['structure'] is required`

**Root cause:** The manifest task for `bulk_relax` does not have a `structure`
key in its `meta` dict (e.g. from a hand-edited or old-schema manifest).

**Fix:** Delete and regenerate the manifest:
```bash
rm runs/manifest.json
python -m flow.workflow.hook --params params.yaml expand
```

---

## 10. Advanced Topics

### 10.1 Adding a custom stage

1. Create `flow/workflow/stages/my_stage.py` inheriting `BaseStage`:

```python
from flow.workflow.stages.base import BaseStage
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

class MyCustomStage(BaseStage):
    stage_name = "my_custom"
    calc_type  = "static_sp"

    def prepare(self, workdir, prev_dir, cfg, task_meta=None):
        vasp_cfg = cfg.get_stage_vasp(self.stage_name)
        self._write_vasp_inputs(
            calc_type=self.calc_type,
            workdir=workdir,
            structure_path=Path(task_meta["structure"]),
            prev_dir=prev_dir,
            vasp_cfg=vasp_cfg,
        )

    # check_success is NOT required for stages that only need OUTCAR to be OK.
    # BaseStage.check_success already does: return self.outcar_ok(workdir)
    # Only override if you need to check additional output files, e.g.:
    #
    # def check_success(self, workdir, cfg):
    #     return self.outcar_ok(workdir) and (workdir / "my_output.dat").exists()
```

2. Register it in `stages/__init__.py`:

```python
from .my_stage import MyCustomStage

STAGE_ORDER = [..., "my_custom"]

_REGISTRY["my_custom"] = MyCustomStage()
```

3. Add the corresponding flag and VASP config to `params.yaml`.

4. Wire task creation into `expand_manifest()` in `hook.py` (copy the pattern
   from an existing stage block).

---

### 10.2 Using a structure object directly (programmatic API)

```python
from flow.workflow.config import load_config
from flow.workflow.hook import expand_manifest, submit_all_ready

cfg = load_config("/path/to/params.yaml")
m   = expand_manifest(cfg)
n   = submit_all_ready(cfg, stage_filter="bulk_relax")
print(f"Submitted {n} tasks")
```

---

### 10.3 Inspecting the manifest programmatically

```python
import json
from pathlib import Path

m = json.loads(Path("runs/manifest.json").read_text())
tasks = m["tasks"]

# Group by stage:
from collections import Counter
print(Counter(t["stage"] for t in tasks.values()))

# Find all pending adsorption tasks:
from flow.workflow.markers import is_done, is_submitted
pending = [
    t for t in tasks.values()
    if t["stage"] == "adsorption"
    and not is_done(Path(t["workdir"]))
    and not is_submitted(Path(t["workdir"]))
]
print(f"{len(pending)} adsorption tasks not yet submitted")
```

---

### 10.4 Bulk-marking many completed jobs as done

After a cluster incident where epilogues were skipped:

```bash
PARAMS=flow/workflow/params.yaml

for stage in bulk_relax slab_relax adsorption; do
    for d in runs/${stage}/*/; do
        if [ -f "${d}OUTCAR" ] && [ ! -f "${d}done.ok" ]; then
            python -m flow.workflow.hook --params $PARAMS \
                mark-done --workdir "${d}" 2>&1 | grep -v WARNING
        fi
    done
done
```

Then re-expand and submit the newly unlocked downstream tasks:
```bash
python -m flow.workflow.hook --params $PARAMS submit-all
```

---

### 10.5 Understanding `DirLock` on shared filesystems

`DirLock` uses `mkdir` atomicity, which is reliable on NFS and Lustre for
preventing duplicate slab/adsorption generation when multiple epilogues fire
simultaneously.  It is **not** a cluster-wide job-submission lock — two
simultaneous `submit_task()` calls on different machines may both succeed for
the same task.  The `is_submitted()` check inside `_submit_task()` reduces this
window but does not eliminate it.

If you see the same task submitted twice (two entries in `qstat`), simply delete
the extra `submitted.json` and let the faster job complete normally.

---

### 10.6 DFT+U and MAGMOM Configuration

Both DFT+U (Hubbard-U corrections) and explicit magnetic moment initialisation
are fully supported through `user_incar_settings` in any stage's `vasp:` block.

#### 10.6.1 MAGMOM — initial magnetic moments

Provide `MAGMOM` as a **per-element dict** (recommended) or as a **per-atom
list / VASP compact string**.

| Format | params.yaml syntax | pymatgen behaviour |
|--------|-------------------|-------------------|
| Per-element dict | `MAGMOM: {Fe: 5.0, Co: 3.0}` | pymatgen expands each element to all its sites |
| Per-atom list | `MAGMOM: [5.0, 5.0, 3.0, 3.0]` | averaged per element, then expanded |
| VASP compact string | `MAGMOM: "4*5.0 2*0.6"` | parsed to list, averaged per element, then expanded |

> **Warning — antiferromagnetic systems:** When using a per-atom list or compact
> string, `_apply_magmom_compat` averages the moments for each element.  For
> AFM systems where sites of the same element must differ, use the per-element
> dict format or inherit from a previous calculation.

#### 10.6.2 DFT+U — Hubbard-U corrections

```yaml
user_incar_settings:
  LDAU:     true
  LDAUTYPE: 2           # 2 = Dudarev (U_eff = U - J)
  LDAUU:
    Fe: 4.0
    O:  0.0
  LDAUL:
    Fe: 2
    O:  -1              # -1 disables U for this species
  LDAUJ:
    Fe: 0.0
    O:  0.0
```

pymatgen expands the per-element dicts to per-site arrays in INCAR and
automatically writes `LMAXMIX = 4` for d-orbital systems.

#### 10.6.3 Complete params.yaml example

```yaml
bulk:
  vasp:
    functional: "PBE"
    kpoints_density: 50
    user_incar_settings:
      LDAU:     true
      LDAUTYPE: 2
      LDAUU:
        Fe: 4.0
        O:  0.0
      LDAUL:
        Fe: 2
        O:  -1
      LDAUJ:
        Fe: 0.0
        O:  0.0
      MAGMOM:
        Fe: 5.0
        O:  0.6
      ISPIN:   2
      LMAXMIX: 4
      NPAR: 4

slab:
  vasp:
    functional: "PBE"
    kpoints_density: 25
    user_incar_settings:
      LDAU:     true
      LDAUTYPE: 2
      LDAUU: {Fe: 4.0, O: 0.0}
      LDAUL: {Fe: 2,   O: -1}
      LDAUJ: {Fe: 0.0, O: 0.0}
      MAGMOM: {Fe: 5.0, O: 0.6}
      ISPIN:   2
      LMAXMIX: 4
```

The same `user_incar_settings` block works in any stage (`slab:`, `adsorption:`,
`slab_lobster.vasp_singlepoint:`, etc.).

---

### 10.7 Multiple cohpGenerator Entries in lobsterin

More than one `cohpGenerator` line can be written to `lobsterin` by supplying a
**list of strings** under `lobsterin_settings.cohpGenerator`.  A single string
is also accepted and behaves identically to a one-element list.

#### How it works internally

```
params.yaml  cohpGenerator: ["range-A", "range-B", "range-C"]
    │
    ▼  config.py  _parse_stage_vasp()
    │  normalises any single string → ["string"]
    │
    ▼  base.py  _write_vasp_inputs()
    │  first entry  → frontend_dict["lobsterin"]["cohpGenerator"]   (overwrites pymatgen default)
    │  entries 2..N → frontend_dict["lobsterin_custom_lines"]        (["cohpGenerator range-B", ...])
    │
    ▼  api.py  from_frontend_dict() → LobsterParams
    │  .overwritedict          = {"cohpGenerator": "range-A", ...other lobsterin keys...}
    │  .custom_lobsterin_lines = ["cohpGenerator range-B", "cohpGenerator range-C"]
    │
    ▼  workflow_engine.py  WorkflowConfig
    │  .lobster_overwritedict  = overwritedict
    │  .lobster_custom_lines   = custom_lobsterin_lines
    │
    ▼  workflow_engine.py  _write_lobster() → LobsterSetEcat.write_input()
    │  overwritedict updates the pymatgen-generated Lobsterin object
    │  custom_lobsterin_lines appended verbatim under "! --- Custom User Lines ---"
    │
    ▼  lobsterin  (disk)
       cohpGenerator range-A           ← from overwritedict
       ...
       ! --- Custom User Lines ---
       cohpGenerator range-B
       cohpGenerator range-C
```

#### params.yaml example (per-stage format)

```yaml
slab_lobster:
  vasp_singlepoint:
    functional: "PBE"
    kpoints_density: 60
    user_incar_settings:
      IBRION:  -1
      NSW:     0
      LORBIT:  11
      LWAVE:   true
      LCHARG:  false
      ISYM:    0
    lobsterin_settings:
      COHPstartEnergy: -20.0
      COHPendEnergy:    20.0
      # Single generator (string):
      # cohpGenerator: "from 1.5 to 1.9 orbitalwise"
      #
      # Multiple generators (list) — each becomes a separate lobsterin line:
      cohpGenerator:
        - "from 1.5 to 1.9 type Pt type C orbitalwise"
        - "from 1.5 to 2.1 type Pt type O orbitalwise"
        - "from 2.0 to 2.5 type Pt type Pt orbitalwise"
```

The resulting `lobsterin` file will contain one `cohpGenerator` line per entry.

> **Tip — range overlap:** Overlapping bond-length windows between generators are
> allowed.  LOBSTER counts each bond once regardless of how many generators match
> it, so there is no risk of double-counting.

---

## 11. Alternative Entry Points

The workflow supports three shortcut modes that let you skip upstream stages when
you already have structures prepared outside the normal pipeline.

---

### 11.1 Slab-Only Entry Point

**Use case:** You have pre-relaxed slab POSCAR files and want to start the workflow
from `slab_relax`, skipping all bulk stages (`bulk_relax`, `bulk_dos`, etc.).

#### params.yaml configuration

```yaml
# Do NOT set 'structure' — it is not required when using slab_source.
slab_source: /path/to/my/slabs   # file or directory

workflow:
  stages:
    bulk_relax: false   # disabled — no bulk input provided
    bulk_dos: false
    slab_relax: true
    slab_dos: true
    adsorption: true
    # ... other downstream stages as needed
```

`slab_source` accepts either:
- A **single file** — treated as one slab with `bulk_id` derived from the filename.
- A **directory** — scanned for files matching `POSCAR_*`, `CONTCAR_*`, `POSCAR.*`,
  `CONTCAR.*`. Multiple files in the same directory are indexed as separate terminations
  (`term=0`, `term=1`, …).

#### What happens internally

- `expand_manifest()` scans `slab_source` and immediately creates `slab_relax`
  tasks with `deps: []` — no bulk gate is required.
- Each slab file is copied to `<run_root>/slab_relax/<bulk_id>/000/0L/term<N>/POSCAR`.
- All downstream stages (slab_dos, adsorption, etc.) fan out from these tasks exactly
  as in a normal run.

#### Running the workflow

```bash
# Expand the manifest — slab_relax tasks appear immediately
python -m flow.workflow.hook --params params.yaml expand

# Submit all ready tasks
python -m flow.workflow.hook --params params.yaml submit-all
```

---

### 11.2 Adsorption-Only Entry Point

**Use case:** You have pre-built adsorption-structure POSCAR files and want to run
only `adsorption` relaxation, skipping all prior stages.

#### params.yaml configuration

```yaml
adsorption_source: /path/to/my/ads_structures   # file or directory

workflow:
  stages:
    bulk_relax: false
    slab_relax: false
    adsorption: true
    adsorption_freq: true    # optional downstream stages still work
```

#### Running the workflow

```bash
python -m flow.workflow.hook --params params.yaml expand
python -m flow.workflow.hook --params params.yaml submit-all
```

---

*End of tutorial.  For questions or bug reports, check the log output at
`WARNING` level (the default) or set `logging.basicConfig(level=logging.DEBUG)`
for full tracing.*
