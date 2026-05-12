# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

An LLM + Tool Call system for querying materials databases. An LLM (DeepSeek/Qwen/GLM/OpenAI) orchestrates tool calls to answer materials science questions and download crystal structures.

Supports two databases (switched via `DB_BACKEND`):
- **Materials Project** (default) — requires API key, supports MCP mode
- **OQMD** — no API key needed, always local REST API (no MCP server available)

## Running the Tool

All commands run from `Search_tool/`. API keys are loaded from `Search_tool/.env` — never read or commit this file.

```powershell
# Combined mode (default) — LLM sees all 10 tools and routes by user intent
python mp_tool_use.py

# Force OQMD only — no API key required
$env:DB_BACKEND = "oqmd"
python mp_tool_use.py
Remove-Item Env:DB_BACKEND

# Force MP only (local)
$env:DB_BACKEND = "mp"
python mp_tool_use.py
Remove-Item Env:DB_BACKEND

# Combined mode with MCP backend for MP tools
# Must set env vars explicitly (MCP server is a subprocess, can't read .env)
$env:MP_API_KEY       = "your_key"
$env:LLM_API_KEY      = "your_key"
$env:MP_EXECUTOR_MODE = "mcp_llm"
python mp_tool_use.py
Remove-Item Env:MP_EXECUTOR_MODE

# Chinese tool schema (affects LLM tool descriptions)
$env:MP_SCHEMA_LANG = "cn"
python mp_tool_use.py
Remove-Item Env:MP_SCHEMA_LANG
```

## Architecture

```
mp_tool_use.py          ← Entry point: LLM agentic loop + executor selection
search.py               ← MPQueryService: MP API wrapper with TTL cache + structure converters
oqmd_search.py          ← OQMDQueryService: OQMD REST API wrapper (reuses search.py utilities)
mp_tool_schemas.py      ← Pydantic models for MP tools → OpenAI function-calling schema
oqmd_tool_schemas.py    ← Pydantic models for OQMD tools
structures/             ← Downloaded structure files (auto-created)
```

### Executor Pattern

`MPToolExecutor` (abstract) has four implementations:

- **`LocalToolExecutor`** — calls `MPQueryService` directly; supports all 5 MP tools with precise numeric filtering (band gap ranges, hull energy, etc.)
- **`MCPToolExecutor`** — spawns `mp_api.mcp.server` as a subprocess via `fastmcp`; exposes MP native MCP tools. `mp_download` always runs locally (MCP has no download tool). Auto-degrades to `LocalToolExecutor` on startup failure.
- **`OQMDLocalToolExecutor`** — calls `OQMDQueryService` directly against OQMD REST API; supports 5 OQMD tools (`oqmd_*` prefix). OQMD has no MCP server, so this is always local (no API key required).
- **`CombinedToolExecutor`** — default mode; wraps an MP executor + OQMD executor and exposes all 10 tools. Routes calls by prefix: `oqmd_*` → OQMD, everything else → MP. The LLM automatically picks the right tools based on the user's prompt (e.g., "search OQMD for..." → `oqmd_*`, "Materials Project..." → `mp_*`). Each executor also has a `system_hint` property that fills in the system prompt to guide the LLM.

### OQMD vs MP Key Differences

| | Materials Project | OQMD |
|---|---|---|
| API Key | Required | Not needed |
| Primary key | `material_id` (str `mp-XXXX`) | `entry_id` (int) |
| Hull distance | `energy_above_hull` | `stability` (≤0 = stable) |
| MCP support | Yes | No (always local REST) |
| Structure source | `MPRester` (native) | Manual assembly from `unit_cell` + `sites` strings |

### LLM Loop (`run()`)

`run()` in `mp_tool_use.py` implements a standard agentic loop: send messages → check for tool calls → execute in parallel via `asyncio.gather` → append results → repeat until the model returns a final text response.

All LLM providers use the OpenAI-compatible SDK interface. Provider configs (base URL, model, extras) are in the `LLM_CONFIGS` dict. Switch provider by changing `llm_provider=` in the `run()` call inside `main()`.

### The 5 Local Tools

| Tool | Service method | Key parameters |
|---|---|---|
| `mp_search_formula` | `query_by_formula()` | `formula`, `only_stable`, `max_results` |
| `mp_search_elements` | `query_by_elements()` | `elements`, `num_elements`, `only_stable` |
| `mp_search_criteria` | `query_by_criteria()` | range params (`band_gap_min/max`, etc.), boolean flags |
| `mp_fetch` | `query_by_material_id()` | `material_ids` (list) |
| `mp_download` | `query_by_material_id()` + `save_structure_to_disk()` | `material_id`, `fmt` (cif/poscar/xyz), `save_dir` |

### `MPQueryService` (search.py)

- Wraps `MPRester` (mp-api) with a thread-safe TTL cache (`_TTLCache`, 300s default, 256 entries max)
- Retries all API calls up to 3× with exponential backoff (`_retry` decorator)
- `_build_result()` converts raw MP docs to normalized dicts; always converts to conventional standard cell via `SpacegroupAnalyzer`
- Structure serialization: `structure_to_cif()`, `structure_to_poscar()`, `structure_to_xyz()` — pre-computed and stored in each result dict under `"cif"`, `"poscar"`, `"xyz"` keys; the pymatgen object is stored under `"_structure"` for downstream use
- `save_structure_to_disk()` handles file writing; POSCAR files use `POSCAR_<filename>` naming (no extension, VASP convention)

## Key Constraints

- **MCP mode requires explicit `$env:MP_API_KEY`** set in PowerShell before running — the MCP server subprocess cannot inherit values from `load_dotenv()`
- `mp_search_criteria` requires at least one filter; returns an error dict otherwise
- Windows event loop policy must be `WindowsSelectorEventLoopPolicy` (set at bottom of `mp_tool_use.py`)
- `_EXCLUDE` fields (`_structure`, `xyz`, `cif`, `poscar`) are stripped from search/fetch responses to the LLM to avoid massive token usage

## Customizing Queries

Edit the `QUESTIONS` list in `main()` inside `mp_tool_use.py`. Supports both English and Chinese natural language.

## Structure_tool Package

A standalone pymatgen/ASE toolkit for VASP catalysis structure preparation. Independent of Search_tool — no LLM or API keys required. Import directly:

```python
from Structure_tool import BulkToSlabGenerator, AdsorptionModify, StructureModify, ParticleGenerator
```

### Classes

| Class | File | Purpose |
|---|---|---|
| `BulkToSlabGenerator` | `bulk_to_slab.py` | Bulk → slab with layer count control and selective dynamics fixation |
| `AdsorptionModify` | `adsorption.py` | Adsorption site finding and adsorbate placement (extends `AdsorbateSiteFinder`) |
| `StructureModify` | `structure_modify.py` | Supercell expansion, atom insertion/deletion, substitution |
| `ParticleGenerator` | `Particle.py` | Nanoparticle generation via ASE geometric shapes or pymatgen Wulff construction |

All classes support both **Fluent API** (chained calls) and **step-by-step** usage. `BulkToSlabGenerator` also has a `run_from_dict(config)` static method for dict-driven batch workflows.

`ParticleGenerator` gracefully degrades when ASE is not installed (geometric shapes unavailable, Wulff construction still works).

### Supporting Modules

- `structure_io.py` — format converters (Structure → CIF/POSCAR/XYZ string); returns text content, does not write to disk
- `ml_meta.py` — FAIRChem/OCPCalculator-based structure relaxation and energy prediction; model path resolution order: `model_name` arg → `FAIRCHEM_MODEL_PATH` env → `ML_MODEL_DIR/ML_DEFAULT_MODEL` env → auto-discovery in `ML_MODEL_DIR`
- `utils/structure_utils.py` — shared helpers: `load_structure()`, `get_atomic_layers()`, `parse_supercell_matrix()`

### Structure Tool_use (LLM Agent)

Six tools exposed as OpenAI function-calling tools for LLM orchestration. All accept file paths and return structure summaries + saved file paths — never raw CIF/POSCAR content (mirrors Search_tool's token-efficient pattern).

| Tool | Operation | Key args |
|---|---|---|
| `struct_load` | Inspect structure | `file_path` |
| `struct_supercell` | Expand unit cell | `file_path`, `supercell_matrix` (e.g. `"2x2x1"`) |
| `struct_vacancy` | Vacancy/substitution defects | `file_path`, `element`, `dopant`, `num_vacancies` |
| `struct_slab` | Bulk → slab | `file_path`, `miller_indices`, `target_layers` |
| `struct_adsorption` | Find sites / place adsorbate | `file_path`, `mode` (`analyze`\|`generate`), `molecule_formula` |
| `struct_particle` | Nanoparticle generation | `element`, `mode` (`wulff`\|`sphere`\|`octahedron`\|...) |

Run from `Tool_use/` (or import as a subagent module):

```powershell
python -m Structure_tool.structure_tool_use
```

LLM provider and API key: set `LLM_API_KEY` in `Search_tool/.env` (auto-loaded). Change `llm_provider=` in `main()` to switch between `deepseek`/`qwen`/`glm`/`openai`.
