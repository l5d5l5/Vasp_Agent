# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**Flow** generates VASP (Vienna Ab initio Simulation Package) input files and orchestrates high-throughput computational materials science workflows. It supports 16 calculation types (relaxation, static electronic, transition-state searches, vibrational analysis, NMR, NBO, molecular dynamics) across 5 DFT functionals (PBE, SCAN, BEEF, HSE, PBE0).

## Commands

```powershell
# Run all tests (must be run from D:\workflow)
Set-Location "D:\workflow"; D:\anaconda\envs\workflow\python.exe -m pytest flow/tests/ -x -q

# Run a single test file
Set-Location "D:\workflow"; D:\anaconda\envs\workflow\python.exe -m pytest flow/tests/test_api_engine.py -v

# Run tests matching a pattern
Set-Location "D:\workflow"; D:\anaconda\envs\workflow\python.exe -m pytest flow/tests/ -k "test_bulk_relax" -v

# Install in editable mode (from D:\workflow\flow)
D:\anaconda\envs\workflow\python.exe -m pip install -e .
```

## Architecture

The pipeline has six tiers:

```
FrontendDict → FrontendAdapter (api.py) → VaspWorkflowParams
             → WorkflowConfig → WorkflowEngine (workflow_engine.py)
             → _write_*() → *SetEcat (input_sets/) → files on disk
```

**Core layer (`flow/`):**

| Module | Responsibility |
|--------|---------------|
| `api.py` | Parses untyped frontend dicts into typed `FrontendXxxParams` dataclasses; `FrontendAdapter.from_frontend_dict()` is the entry point |
| `calc_registry.py` | Single source of truth for all CalcType-level mappings: `CALC_REGISTRY` (`CalcTypeEntry` per type), `CALC_TYPE_TO_CATEGORY`, `VDW_FUNCTIONALS`, helper functions |
| `workflow_engine.py` | `WorkflowConfig` dataclass, `WorkflowEngine.run()` dispatches to module-level `_write_*()` functions; imports `CALC_REGISTRY` from `calc_registry` |
| `maker.py` | `VaspInputMaker` legacy factory (not called by `WorkflowEngine`; retained for backward compatibility) |
| `input_sets/` | pymatgen `InputSet` subclasses package (`_base.py`, `bulk_slab.py`, `static.py`, `spectroscopy.py`, `transition.py`, `md.py`) that merge INCAR priorities and write files |
| `constants.py` | `DEFAULT_INCAR_*` dicts per calc type, `FUNCTIONAL_INCAR_PATCHES`, `SUPPORTED_FUNCTIONALS` |
| `calc_type.py` | Thin re-export shim: `from .calc_registry import CalcType` — `CalcType` enum now lives in `calc_registry.py` |
| `kpoints.py` | Monkhorst-Pack / Gamma-centered mesh generation from density |
| `script.py` | `CalcCategory` enum and per-category PBS defaults (`_CATEGORY_CONFIG`); `Script` rendering class; no filesystem I/O |
| `script_writer.py` | `ScriptWriter` — renders PBS templates from `flow/script/`, copies `vdw_kernel.bindat` for BEEF-family (`BEEF`/`BEEFVTST`) functionals |
| `utils.py` | `load_structure()` (dir-aware, CONTCAR > POSCAR priority), INCAR VASP-format parsers, adsorbate index helpers |
| `validator.py` | 3-layer validation: field-level → cross-field → business logic; collects all errors before raising |

**Orchestration layer (`flow/workflow/`):**

| Module | Responsibility |
|--------|---------------|
| `config.py` | Parses `params.yaml` into `WorkflowConfig` / `ProjectConfig` / `PBSConfig` |
| `hook.py` | CLI entry point: `expand`, `auto`, `submit-all`, `mark-done` subcommands; manifest expansion, PBS job submission |
| `task.py` | `WorkflowTask` TypedDict — typed structure for manifest task entries |
| `stages/base.py` | `Stage` enum (12 values: BULK_RELAX … ADSORPTION_NBO) + `BaseStage` ABC |
| `stages/` | Per-stage `prepare()` / `check_success()` classes (bulk, slab, adsorption) |
| `structure/` | `BulkToSlabGenerator`, `AdsorptionModify` — pymatgen structure-generation helpers |
| `extract.py` | Standalone result-extraction CLI |
| `markers.py` | `done.ok` / `submitted.json` / `failed.json` state-marker helpers |
| `pbs.py` | `DirLock`, `render_template`, `submit_job`, `poll_job` primitives |

## INCAR Merge Priority (lowest → highest)

1. `DEFAULT_INCAR_*` — calc-type baseline in `constants.py`
2. `INCAR_DELTA_STATIC_*` — incremental overrides for static sub-types
3. `FUNCTIONAL_INCAR_PATCHES` — functional-specific additions (e.g., BEEF adds `GGA=BF`, `LUSE_VDW=True`)
4. `user_incar_overrides` — from `FrontendAdapter` / user dict
5. Per-call `local_incar` inside `_write_*()` in `workflow_engine.py` — highest priority

## Adding a New Calculation Type (5-step checklist)

1. Add `NEW_TYPE = "new_type"` to `CalcType` enum in `calc_registry.py`
2. Add `DEFAULT_INCAR_NEW` dict in `constants.py`
3. Add `CalcTypeEntry(...)` row to `CALC_REGISTRY` in `calc_registry.py`
4. Create `NewTypeSetEcat` subclass in `input_sets/` (choose the appropriate module: `bulk_slab.py`, `static.py`, `spectroscopy.py`, `transition.py`, or `md.py`)
5. Add `_write_new_type()` module-level function in `workflow_engine.py` and a dispatch `case` in `WorkflowEngine.run()` — `api.py` and `maker.py` require no changes, `calc_type_from_str()` picks up new types automatically

## Test Structure

Tests live in `flow/tests/`. Files numbered `test_01_*` through `test_07_*` test individual output file types (INCAR, POSCAR, KPOINTS, script, MODECAR, NBO files, integration). Named files (`test_api_engine.py`, `test_validator.py`, `test_workflow_engine.py`, etc.) test higher-level architecture. `helpers.py` holds shared test fixtures and structure builders.

Use ASE (not pymatgen) to generate test structures; convert via `AseAtomsAdaptor` if a pymatgen `Structure` is needed.

## Important Notes

- Python 3.10+ is required (code uses `match`/`case` structural pattern matching).
- `LDAU` safety: if `LDAU=True` but no U values are provided, the engine forces `LDAU=False`.
- Workflow orchestration (under `workflow/`) uses a manifest-based, re-entrant state machine; `done.ok`, `submitted.json`, and `failed.json` marker files track task state. The hook is safe to re-run repeatedly from PBS epilogues or cron jobs.
- `Stage` enum in `stages/base.py` is the single source of truth for stage names; it inherits from `str` for JSON round-trip compatibility with `manifest.json`.
- `README.md` is a detailed code-logic reference (not a user guide); `VASP_INPUT_TUTORIAL.md` and `WORKFLOW_TUTORIAL.md` are the user-facing docs.
- `workflow/WORKFLOW_TUTORIAL.md` is the authoritative reference for `params.yaml` fields, CLI subcommands, and the marker-file state machine.
- `workflow/DEPLOYMENT.md` covers cluster deployment: directory layout, `params.yaml` minimal config, PBS template customization, and ops commands (`qstat`, lock cleanup, manifest reset).
- `workflow/problems.md` (and `problems2–4.md`) tracks known bugs and design issues in `hook.py`; review before touching manifest expansion or stage gate logic.

## Workflow CLI (on-cluster use)

```bash
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
PARAMS=flow/workflow/params.yaml

# Expand manifest (creates/refreshes manifest.json, does not submit)
$PYTHON -m flow.workflow.hook --params $PARAMS expand

# Submit first eligible task
$PYTHON -m flow.workflow.hook --params $PARAMS auto

# Submit all eligible tasks (optionally filter by stage)
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all [--stage bulk_relax] [--limit 10]

# Mark a completed workdir as done (writes done.ok)
$PYTHON -m flow.workflow.hook --params $PARAMS mark-done --workdir runs/bulk_relax/PtSnCu
```

The hook is re-entrant: running it repeatedly from PBS epilogues or cron is safe. `DirLock` prevents concurrent duplicate submissions.

### 使用中文回答我的问题

# 环境信息
- Python 路径：`D:\anaconda\envs\workflow\python.exe`
- Conda 环境：`workflow`
- 项目根目录：`D:\workflow`

## ⚠️ 关键约定（每次执行命令必须遵守）

### 1. 激活环境
所有 Python 命令必须先激活 conda 环境：
```
conda activate workflow
```
或直接使用完整路径：
```
D:\anaconda\envs\workflow\python.exe
```

### 2. 工作目录
所有命令必须在 `D:\workflow` 目录下执行，不是子目录。

### 3. 模块导入
`flow` 模块位于 `D:\workflow\flow`，运行前确保：
- cwd = `D:\workflow`
- sys.path 包含 `D:\workflow`

正确示例：
```powershell
Set-Location "D:\workflow"; D:\anaconda\envs\workflow\python.exe -c "from flow.api import generate_inputs"
```

### 4. 测试命令
```powershell
Set-Location "D:\workflow"; D:\anaconda\envs\workflow\python.exe -m pytest flow/tests/ -x -q
```

### 5. 每次修改代码前必须先保存 git 节点
```powershell
# 在开始任何修改之前运行：
git add -A && git commit -m "checkpoint before <简述修改内容>"
```
这确保每个修改都可以回滚。
