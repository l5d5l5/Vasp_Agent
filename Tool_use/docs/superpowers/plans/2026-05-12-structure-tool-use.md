# Structure Tool_use Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose Structure_tool's manipulation operations (supercell, vacancy, slab, adsorption, particle) as OpenAI function-calling tools that an LLM subagent can orchestrate for computational chemistry structure workflows.

**Architecture:** Six tools follow the Search_tool pattern: each tool accepts a file path (never raw structure data), calls the existing Structure_tool classes, saves results to disk, and returns a JSON summary dict (lattice params, formula, nsites, saved file paths). A `StructureService` service layer owns the pymatgen logic; a `StructureToolExecutor` dispatches tool calls using the same `_TOOL_DISPATCH` table pattern as `LocalToolExecutor`.

**Tech Stack:** pymatgen, ASE (optional for particle), pydantic v2, asyncio, openai-compatible SDK — all already in the environment.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `Structure_tool/structure_tool_schemas.py` | **CREATE** | 6 Pydantic models + `get_structure_tool_schema(lang)` |
| `Structure_tool/structure_service.py` | **CREATE** | `StructureService`: file-in → summary-out, wraps Structure_tool classes |
| `Structure_tool/structure_tool_executor.py` | **CREATE** | `StructureToolExecutor`: dispatch table → JSON strings |
| `Structure_tool/structure_tool_use.py` | **CREATE** | Entry point: LLM agentic loop, env setup, QUESTIONS |
| `Structure_tool/tests/__init__.py` | **CREATE** | Empty (makes tests a package) |
| `Structure_tool/tests/test_structure_schemas.py` | **CREATE** | Schema validation + OpenAI schema shape tests |
| `Structure_tool/tests/test_structure_service.py` | **CREATE** | Service layer tests (no LLM, no network) |

**Not modified:** All existing files in `Structure_tool/` (`bulk_to_slab.py`, `adsorption.py`, `structure_modify.py`, `Particle.py`, `structure_io.py`, `utils/`).

---

## Summary Dict Contract

Every tool returns a JSON-serializable dict. The **structure summary** embedded in every response:

```python
{
    "formula": "Fe4O6",           # composition.formula with no spaces
    "reduced_formula": "Fe2O3",   # composition.reduced_formula
    "nsites": 10,                 # len(structure)
    "a": 5.0356,                  # Å
    "b": 5.0356,
    "c": 13.7489,
    "alpha": 90.0,                # degrees
    "beta": 90.0,
    "gamma": 120.0,
    "volume": 301.84,             # Å³
    "space_group": "R-3c",        # from SpacegroupAnalyzer(symprec=0.1)
    "cell_type": "bulk"           # "bulk" | "slab" (heuristic: c > 1.5*max(a,b))
}
```

The tool-level response wraps this under `"structure"` and adds `"saved_files"`, `"success"`, and any tool-specific fields (e.g. `"num_generated"`, `"site_counts"`).

---

## Task 1: Schema Models

**Files:**
- Create: `Structure_tool/structure_tool_schemas.py`
- Create: `Structure_tool/tests/__init__.py`
- Create: `Structure_tool/tests/test_structure_schemas.py`

- [ ] **Step 1.1 — Write failing tests**

```python
# Structure_tool/tests/test_structure_schemas.py
import pytest
from pydantic import ValidationError


def test_load_args_requires_file_path():
    from Structure_tool.structure_tool_schemas import LoadArgs
    with pytest.raises(ValidationError):
        LoadArgs()  # file_path is required


def test_load_args_accepts_path():
    from Structure_tool.structure_tool_schemas import LoadArgs
    a = LoadArgs(file_path="./POSCAR")
    assert a.file_path == "./POSCAR"


def test_supercell_args_defaults():
    from Structure_tool.structure_tool_schemas import SupercellArgs
    a = SupercellArgs(file_path="./POSCAR", supercell_matrix="2x2x1")
    assert a.save_dir == "./structures"
    assert a.filename is None


def test_vacancy_args_defaults():
    from Structure_tool.structure_tool_schemas import VacancyArgs
    a = VacancyArgs(file_path="./POSCAR", element="Fe")
    assert a.num_vacancies == 1
    assert a.num_structs == 1
    assert a.dopant is None


def test_slab_args_defaults():
    from Structure_tool.structure_tool_schemas import SlabArgs
    a = SlabArgs(file_path="./POSCAR", miller_indices="111", target_layers=4)
    assert a.vacuum_thickness == 15.0
    assert a.fix_bottom_layers == 0
    assert a.termination_index == 0


def test_adsorption_args_generate_mode():
    from Structure_tool.structure_tool_schemas import AdsorptionArgs
    a = AdsorptionArgs(file_path="./POSCAR", mode="generate", molecule_formula="CO")
    assert a.molecule_formula == "CO"


def test_adsorption_args_analyze_mode():
    from Structure_tool.structure_tool_schemas import AdsorptionArgs
    a = AdsorptionArgs(file_path="./POSCAR", mode="analyze")
    assert a.molecule_formula is None


def test_particle_args_wulff():
    from Structure_tool.structure_tool_schemas import ParticleArgs
    a = ParticleArgs(
        element="Pt",
        mode="wulff",
        surface_energies={"111": 0.05, "100": 0.07},
        particle_size=15.0,
    )
    assert a.element == "Pt"
    assert a.vacuum == 15.0


def test_get_schema_returns_list_of_6():
    from Structure_tool.structure_tool_schemas import get_structure_tool_schema
    schema = get_structure_tool_schema("en")
    assert len(schema) == 6
    names = [s["function"]["name"] for s in schema]
    assert "struct_load" in names
    assert "struct_supercell" in names
    assert "struct_vacancy" in names
    assert "struct_slab" in names
    assert "struct_adsorption" in names
    assert "struct_particle" in names


def test_schema_entries_have_openai_shape():
    from Structure_tool.structure_tool_schemas import get_structure_tool_schema
    for entry in get_structure_tool_schema("en"):
        assert entry["type"] == "function"
        fn = entry["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        params = fn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        assert "required" in params
```

- [ ] **Step 1.2 — Run tests, confirm FAIL**

```powershell
cd D:\workflow\catalysis_tools_mod\Tool_use
python -m pytest Structure_tool/tests/test_structure_schemas.py -v
```

Expected: `ModuleNotFoundError: No module named 'Structure_tool.structure_tool_schemas'`

- [ ] **Step 1.3 — Create `Structure_tool/tests/__init__.py`**

```python
# Structure_tool/tests/__init__.py
```

- [ ] **Step 1.4 — Implement `structure_tool_schemas.py`**

```python
# Structure_tool/structure_tool_schemas.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# §1  Pydantic 参数模型（6 个工具）
# ══════════════════════════════════════════════

class LoadArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description=(
            "Path to a structure file (POSCAR, CONTCAR, CIF, .vasp) or a "
            "directory containing CONTCAR/POSCAR. Used to load the structure "
            "and return its summary without modifying anything."
        )
    )


class SupercellArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(description="Path to source structure file or directory.")
    supercell_matrix: str = Field(
        description=(
            "Supercell expansion string. Supported formats: "
            "'2x2x1' (a×b×c), '3x3x3', '2x2' (c unchanged). "
            "Expands the unit cell by the given factors along each axis."
        )
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where the new POSCAR will be saved. Created if missing.",
    )
    filename: Optional[str] = Field(
        None,
        description=(
            "Output filename (no extension). Defaults to "
            "'POSCAR_<formula>_<matrix>' if omitted."
        ),
    )


class VacancyArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(description="Path to source structure file or directory.")
    element: str = Field(
        description="Element symbol of the atom to remove or substitute (e.g. 'Fe', 'O')."
    )
    dopant: Optional[str] = Field(
        None,
        description=(
            "Substitution element symbol. If None, creates vacancies. "
            "If provided (e.g. 'Ni'), replaces the target element with the dopant."
        ),
    )
    num_vacancies: int = Field(
        1,
        description="Number of atoms to remove/substitute per generated structure.",
    )
    num_structs: int = Field(
        1,
        description="Number of symmetry-inequivalent structures to generate.",
    )
    top_layers: Optional[int] = Field(
        None,
        description=(
            "Restrict vacancy/doping to the top N atomic layers. "
            "Useful for surface defect studies. Omit to use all layers."
        ),
    )
    random_seed: Optional[int] = Field(
        None, description="Random seed for reproducibility."
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where generated POSCARs will be saved.",
    )
    filename_prefix: str = Field(
        "POSCAR_vac",
        description="Prefix for saved files. Files are named '<prefix>_0', '<prefix>_1', etc.",
    )


class SlabArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(description="Path to bulk structure file or directory.")
    miller_indices: str = Field(
        description=(
            "Miller indices of the surface to cut. Accepted formats: "
            "'111', '1,1,1', '(1,1,1)'. Negative indices use a minus sign: '-101'."
        )
    )
    target_layers: int = Field(
        description="Exact number of atomic layers in the slab (e.g. 4, 6, 8)."
    )
    vacuum_thickness: float = Field(
        15.0,
        description="Vacuum layer thickness in Å on each side. Default: 15.0 Å.",
    )
    supercell_matrix: Optional[str] = Field(
        None,
        description=(
            "In-plane supercell expansion after slicing, e.g. '2x2' or '2x2x1'. "
            "Omit for a 1×1 slab."
        ),
    )
    fix_bottom_layers: int = Field(
        0,
        description=(
            "Number of bottom atomic layers to freeze with selective_dynamics=F. "
            "Typical: 2 for a surface calculation."
        ),
    )
    fix_top_layers: int = Field(
        0, description="Number of top atomic layers to freeze."
    )
    termination_index: int = Field(
        0,
        description=(
            "Which surface termination to use when multiple are generated "
            "(0-indexed). Use 0 (default) unless you know a specific termination is needed."
        ),
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where the slab POSCAR will be saved.",
    )
    filename: str = Field(
        "POSCAR",
        description="Output filename for the POSCAR file.",
    )


class AdsorptionArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(description="Path to slab structure file or directory.")
    mode: Literal["analyze", "generate"] = Field(
        description=(
            "'analyze' — find and count adsorption sites (ontop, bridge, hollow), "
            "return site coordinates. No adsorbate placed. "
            "'generate' — place adsorbate molecule on all found sites and save structures."
        )
    )
    molecule_formula: Optional[str] = Field(
        None,
        description=(
            "Required for 'generate' mode. ASE molecule name (e.g. 'CO', 'OH', 'H2O') "
            "or path to an XYZ/POSCAR adsorbate file."
        ),
    )
    positions: Optional[List[str]] = Field(
        None,
        description=(
            "Restrict to specific site types: any subset of ['ontop', 'bridge', 'hollow']. "
            "Omit to use all site types."
        ),
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where generated adsorption POSCARs will be saved.",
    )


class ParticleArgs(BaseModel):
    model_config = {"extra": "ignore"}

    element: str = Field(
        description=(
            "Element symbol for the nanoparticle (e.g. 'Pt', 'Au', 'Fe'). "
            "Lattice constant is auto-looked up for common metals; "
            "provide 'lattice_constant' for unlisted elements."
        )
    )
    mode: Literal["wulff", "sphere", "octahedron", "decahedron", "icosahedron", "fcc_cube", "rod"] = Field(
        description=(
            "Particle shape:\n"
            "  'wulff'       — equilibrium shape from surface energies (most physical)\n"
            "  'sphere'      — spherical cutout\n"
            "  'octahedron'  — FCC octahedron (ASE)\n"
            "  'decahedron'  — Ino decahedron (ASE)\n"
            "  'icosahedron' — Mackay icosahedron (ASE)\n"
            "  'fcc_cube'    — FCC cube (ASE)\n"
            "  'rod'         — cylindrical nanorod"
        )
    )
    lattice_constant: Optional[float] = Field(
        None,
        description="Lattice constant in Å. Auto-detected for common metals; required for others.",
    )
    lattice_type: Optional[Literal["fcc", "bcc", "hcp", "sc"]] = Field(
        None, description="Crystal structure type. Auto-detected for common metals."
    )
    # Wulff params
    surface_energies: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "Required for 'wulff' mode. Map of Miller index → surface energy (J/m²). "
            "Keys can be '111', '(1,1,1)', or '1,1,1'. "
            "Example: {'111': 0.05, '100': 0.07, '110': 0.09}."
        ),
    )
    particle_size: Optional[float] = Field(
        None,
        description=(
            "For 'wulff': approximate radius in Å. "
            "For 'sphere': exact radius in Å. "
            "Typical range: 8–30 Å."
        ),
    )
    # Octahedron params
    layers: Optional[List[int]] = Field(
        None,
        description=(
            "For 'octahedron': [length, cutoff] where cutoff=0 is a perfect octahedron. "
            "For 'fcc_cube': list of layer counts per surface."
        ),
    )
    surfaces: Optional[List[List[int]]] = Field(
        None, description="For 'fcc_cube': list of surface Miller indices, e.g. [[1,0,0],[1,1,0],[1,1,1]]."
    )
    # Decahedron params
    p: Optional[int] = Field(None, description="For 'decahedron': (100) face layers.")
    q: Optional[int] = Field(None, description="For 'decahedron': (111) face layers.")
    r: Optional[int] = Field(None, description="For 'decahedron': waist reconstruction layers (0 = none).")
    # Icosahedron params
    n_shells: Optional[int] = Field(
        None,
        description="For 'icosahedron': number of shells (1→13 atoms, 2→55, 3→147).",
    )
    # Rod params
    rod_radius: Optional[float] = Field(None, description="For 'rod': cross-section radius in Å.")
    rod_length: Optional[float] = Field(None, description="For 'rod': length in Å.")
    vacuum: float = Field(15.0, description="Vacuum padding on each side in Å. Default: 15.0.")
    save_dir: str = Field("./structures", description="Output directory for the POSCAR.")
    filename: str = Field("POSCAR", description="Output filename.")


# ══════════════════════════════════════════════
# §2  ToolSpec 容器
# ══════════════════════════════════════════════

@dataclass
class ToolSpec:
    name: str
    description_en: str
    description_cn: str
    args_class: type[BaseModel]


_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="struct_load",
        description_en=(
            "Load a crystal structure from a file or directory and return its summary "
            "(formula, lattice parameters, space group, number of sites, cell type). "
            "Use this first to inspect a structure before deciding which operation to apply."
        ),
        description_cn=(
            "从文件或目录加载晶体结构，返回其摘要信息"
            "（化学式、晶格参数、空间群、原子数量、晶胞类型）。"
            "在决定对结构进行何种操作之前，先使用此工具检查结构。"
        ),
        args_class=LoadArgs,
    ),
    ToolSpec(
        name="struct_supercell",
        description_en=(
            "Expand a crystal structure into a supercell by integer multiples along each axis. "
            "Saves the resulting POSCAR and returns a summary. "
            "Example: '2x2x1' doubles the cell along a and b."
        ),
        description_cn=(
            "将晶体结构沿各轴扩展为超胞（整数倍）。"
            "保存生成的 POSCAR 并返回摘要。"
            "例如：'2x2x1' 表示沿 a 和 b 轴各扩展 2 倍。"
        ),
        args_class=SupercellArgs,
    ),
    ToolSpec(
        name="struct_vacancy",
        description_en=(
            "Generate vacancy or substitution defect structures. "
            "Removes or replaces a specified element, applying distance-fingerprint "
            "deduplication to return only symmetry-inequivalent configurations. "
            "Saves all generated POSCARs and returns summaries."
        ),
        description_cn=(
            "生成空位或替位缺陷结构。"
            "移除或替换指定元素，并通过距离指纹去重，"
            "仅返回对称性不等价的构型。"
            "保存所有生成的 POSCAR 并返回摘要。"
        ),
        args_class=VacancyArgs,
    ),
    ToolSpec(
        name="struct_slab",
        description_en=(
            "Cut a slab from a bulk structure along a specified Miller plane. "
            "Generates the slab with exact layer count, optional vacuum, supercell expansion, "
            "and selective dynamics (bottom/top layer fixation). "
            "Returns the first (or specified) termination as a POSCAR."
        ),
        description_cn=(
            "沿指定 Miller 面从体相结构切割出板状结构（slab）。"
            "生成具有精确层数的 slab，支持真空层、超胞扩展和"
            "选择性动力学（底部/顶部层固定）。"
            "返回第一个（或指定的）终止面的 POSCAR。"
        ),
        args_class=SlabArgs,
    ),
    ToolSpec(
        name="struct_adsorption",
        description_en=(
            "Find adsorption sites on a slab surface or place adsorbate molecules. "
            "Mode 'analyze': identifies ontop, bridge, and hollow sites and returns counts + coordinates. "
            "Mode 'generate': places an adsorbate (e.g. CO, OH) on all found sites and saves POSCARs."
        ),
        description_cn=(
            "在 slab 表面寻找吸附位点或放置吸附分子。"
            "分析模式（analyze）：识别顶位（ontop）、桥位（bridge）和空位（hollow）吸附位点，"
            "返回数量和坐标。"
            "生成模式（generate）：在所有找到的位点放置吸附分子（如 CO、OH），并保存 POSCAR。"
        ),
        args_class=AdsorptionArgs,
    ),
    ToolSpec(
        name="struct_particle",
        description_en=(
            "Generate a nanoparticle structure using Wulff construction or geometric shapes. "
            "Supported shapes: wulff (equilibrium from surface energies), sphere, octahedron, "
            "decahedron, icosahedron, fcc_cube, rod. "
            "Saves the structure as POSCAR with vacuum padding."
        ),
        description_cn=(
            "使用 Wulff 构型或几何形状生成纳米粒子结构。"
            "支持形状：wulff（由表面能决定的平衡形状）、sphere、octahedron、"
            "decahedron、icosahedron、fcc_cube、rod。"
            "保存含真空层的 POSCAR 文件。"
        ),
        args_class=ParticleArgs,
    ),
]


# ══════════════════════════════════════════════
# §3  Schema 生成器
# ══════════════════════════════════════════════

def _model_to_openai_schema(model_cls: type[BaseModel]) -> dict:
    """Convert a Pydantic model to the OpenAI function parameters schema."""
    raw = model_cls.model_json_schema()
    props = raw.get("properties", {})
    required = raw.get("required", [])
    # Strip Pydantic title/default noise from each property
    clean_props: Dict[str, Any] = {}
    for k, v in props.items():
        entry: Dict[str, Any] = {}
        if "description" in v:
            entry["description"] = v["description"]
        if "type" in v:
            entry["type"] = v["type"]
        if "enum" in v:
            entry["enum"] = v["enum"]
        if "items" in v:
            entry["items"] = v["items"]
        if "anyOf" in v:
            entry["anyOf"] = v["anyOf"]
        if not entry:
            entry = {kk: vv for kk, vv in v.items() if kk not in ("title", "default")}
        clean_props[k] = entry
    return {
        "type": "object",
        "properties": clean_props,
        "required": required,
    }


def get_structure_tool_schema(lang: str = "en") -> list[dict]:
    """Return OpenAI function-calling schema for all 6 structure tools."""
    result = []
    for spec in _TOOL_SPECS:
        desc = spec.description_en if lang == "en" else spec.description_cn
        result.append({
            "type": "function",
            "function": {
                "name": spec.name,
                "description": desc,
                "parameters": _model_to_openai_schema(spec.args_class),
            },
        })
    return result
```

- [ ] **Step 1.5 — Run tests, confirm PASS**

```powershell
python -m pytest Structure_tool/tests/test_structure_schemas.py -v
```

Expected: All 10 tests PASS.

- [ ] **Step 1.6 — Commit**

```powershell
git add Structure_tool/structure_tool_schemas.py Structure_tool/tests/__init__.py Structure_tool/tests/test_structure_schemas.py
git commit -m "feat: add Structure_tool Pydantic schemas for 6 LLM tool calls"
```

---

## Task 2: StructureService — `load` + `supercell`

**Files:**
- Create: `Structure_tool/structure_service.py` (partial — add more methods in Tasks 3–4)
- Modify: `Structure_tool/tests/test_structure_service.py`

- [ ] **Step 2.1 — Write failing tests**

```python
# Structure_tool/tests/test_structure_service.py
import pytest
from pymatgen.core import Structure, Lattice
from pymatgen.io.vasp import Poscar


def _make_fcc_cu(tmp_path):
    """Helper: write a 4-atom FCC Cu POSCAR and return its path."""
    lat = Lattice.cubic(3.615)
    struct = Structure(
        lat, ["Cu"] * 4,
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]
    )
    path = tmp_path / "POSCAR"
    Poscar(struct).write_file(str(path))
    return str(path)


def _make_bcc_fe(tmp_path):
    """Helper: write a 2-atom BCC Fe POSCAR and return its path."""
    lat = Lattice.cubic(2.867)
    struct = Structure(lat, ["Fe"] * 2, [[0, 0, 0], [0.5, 0.5, 0.5]])
    path = tmp_path / "POSCAR_Fe"
    Poscar(struct).write_file(str(path))
    return str(path)


class TestLoad:
    def test_returns_formula(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().load(path)
        assert result["formula"] == "Cu4"

    def test_returns_nsites(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().load(path)
        assert result["nsites"] == 4

    def test_returns_lattice_params(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().load(path)
        assert abs(result["a"] - 3.615) < 0.01
        assert abs(result["b"] - 3.615) < 0.01
        assert abs(result["c"] - 3.615) < 0.01

    def test_cell_type_bulk(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().load(path)
        assert result["cell_type"] == "bulk"

    def test_missing_file_raises(self):
        from Structure_tool.structure_service import StructureService
        result = StructureService().load("/nonexistent/path/POSCAR")
        assert "error" in result

    def test_loads_from_directory(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        _make_fcc_cu(tmp_path)  # writes tmp_path/POSCAR
        result = StructureService().load(str(tmp_path))
        assert result["nsites"] == 4


class TestSupercell:
    def test_2x2x1_quadruples_atoms(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().supercell(path, "2x2x1", str(tmp_path), "POSCAR_221")
        assert result["structure"]["nsites"] == 16  # 4 * 2 * 2

    def test_saves_file(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().supercell(path, "2x2x1", str(tmp_path), "POSCAR_221")
        assert result["success"] is True
        assert len(result["saved_files"]) == 1
        from pathlib import Path
        assert Path(result["saved_files"][0]).exists()

    def test_default_filename(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().supercell(path, "2x2x1", str(tmp_path))
        assert result["success"] is True

    def test_a_b_doubled(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().supercell(path, "2x2x1", str(tmp_path), "POSCAR_221")
        assert abs(result["structure"]["a"] - 3.615 * 2) < 0.01
        assert abs(result["structure"]["b"] - 3.615 * 2) < 0.01
        assert abs(result["structure"]["c"] - 3.615) < 0.01  # c unchanged
```

- [ ] **Step 2.2 — Run tests, confirm FAIL**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestLoad Structure_tool/tests/test_structure_service.py::TestSupercell -v
```

Expected: `ModuleNotFoundError: No module named 'Structure_tool.structure_service'`

- [ ] **Step 2.3 — Implement `structure_service.py` (load + supercell)**

```python
# Structure_tool/structure_service.py
"""
StructureService: file-path-in → summary-dict-out.
All methods are synchronous (called via asyncio.to_thread from the executor).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pymatgen.core import Structure
from pymatgen.io.vasp import Poscar
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from .utils.structure_utils import load_structure, parse_supercell_matrix


# ──────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────

def _structure_summary(struct: Structure) -> Dict[str, Any]:
    """Return a JSON-serializable summary dict for a Structure."""
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
    """Save structure as POSCAR, return absolute path string."""
    out_dir = Path(save_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    with open(out_path, "wt", encoding="utf-8") as f:
        f.write(Poscar(struct).get_string())
    return str(out_path.resolve())


# ──────────────────────────────────────────────
# Service class
# ──────────────────────────────────────────────

class StructureService:
    """Stateless service: maps tool arguments → structure operations → summary dicts."""

    # ── Tool 1: struct_load ─────────────────────────────────────
    def load(self, file_path: str) -> Dict[str, Any]:
        try:
            struct = load_structure(file_path)
            return _structure_summary(struct)
        except Exception as e:
            return {"error": str(e)}

    # ── Tool 2: struct_supercell ────────────────────────────────
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
                filename = f"POSCAR_{formula}_{supercell_matrix.replace('x', 'x')}"

            saved = _save_poscar(struct, save_dir, filename)
            return {
                "structure": _structure_summary(struct),
                "supercell_matrix": supercell_matrix,
                "saved_files": [saved],
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}
```

- [ ] **Step 2.4 — Run tests, confirm PASS**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestLoad Structure_tool/tests/test_structure_service.py::TestSupercell -v
```

Expected: All 10 tests PASS.

- [ ] **Step 2.5 — Commit**

```powershell
git add Structure_tool/structure_service.py Structure_tool/tests/test_structure_service.py
git commit -m "feat: add StructureService with load() and supercell() methods"
```

---

## Task 3: StructureService — `vacancy` + `slab`

**Files:**
- Modify: `Structure_tool/structure_service.py` (add 2 methods)
- Modify: `Structure_tool/tests/test_structure_service.py` (add 2 test classes)

- [ ] **Step 3.1 — Append failing tests to `test_structure_service.py`**

```python
# Append to Structure_tool/tests/test_structure_service.py

class TestVacancy:
    def test_single_vacancy_reduces_nsites(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_bcc_fe(tmp_path)
        result = StructureService().vacancy(path, "Fe", num_vacancies=1,
                                            num_structs=1, save_dir=str(tmp_path))
        assert result["success"] is True
        assert result["num_generated"] >= 1
        assert result["structures"][0]["nsites"] == 1  # 2 atoms - 1 = 1

    def test_doping_keeps_nsites(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_bcc_fe(tmp_path)
        result = StructureService().vacancy(path, "Fe", dopant="Ni",
                                            num_vacancies=1, num_structs=1,
                                            save_dir=str(tmp_path))
        assert result["success"] is True
        # nsites unchanged after substitution
        assert result["structures"][0]["nsites"] == 2

    def test_saves_files(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_bcc_fe(tmp_path)
        result = StructureService().vacancy(path, "Fe", num_vacancies=1,
                                            num_structs=1, save_dir=str(tmp_path))
        from pathlib import Path
        for saved in result["saved_files"]:
            assert Path(saved).exists()

    def test_error_on_wrong_element(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_bcc_fe(tmp_path)
        result = StructureService().vacancy(path, "Au", save_dir=str(tmp_path))
        assert "error" in result


class TestSlab:
    def test_slab_cell_type_is_slab(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().slab(
            path, miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_slab"
        )
        assert result["success"] is True
        assert result["structure"]["cell_type"] == "slab"

    def test_slab_c_is_large(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result = StructureService().slab(
            path, miller_indices="111", target_layers=4,
            vacuum_thickness=15.0, save_dir=str(tmp_path)
        )
        # c must include vacuum (≥ 15 Å on each side + slab)
        assert result["structure"]["c"] > 15.0

    def test_slab_saves_file(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pathlib import Path
        path = _make_fcc_cu(tmp_path)
        result = StructureService().slab(
            path, miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_111"
        )
        assert result["success"] is True
        assert Path(result["saved_files"][0]).exists()

    def test_supercell_2x2_expands_slab(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_fcc_cu(tmp_path)
        result_1x1 = StructureService().slab(
            path, miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_1x1"
        )
        result_2x2 = StructureService().slab(
            path, miller_indices="111", target_layers=4,
            supercell_matrix="2x2", save_dir=str(tmp_path), filename="POSCAR_2x2"
        )
        assert result_2x2["structure"]["nsites"] == result_1x1["structure"]["nsites"] * 4
```

- [ ] **Step 3.2 — Run tests, confirm FAIL**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestVacancy Structure_tool/tests/test_structure_service.py::TestSlab -v
```

Expected: `AttributeError: 'StructureService' object has no attribute 'vacancy'`

- [ ] **Step 3.3 — Add `vacancy()` and `slab()` to `structure_service.py`**

Append to the `StructureService` class in `Structure_tool/structure_service.py`:

```python
    # ── Tool 3: struct_vacancy ──────────────────────────────────
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

            saved_files: List[str] = []
            summaries: List[Dict[str, Any]] = []
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

    # ── Tool 4: struct_slab ─────────────────────────────────────
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

            # Select the requested termination
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
```

- [ ] **Step 3.4 — Run tests, confirm PASS**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestVacancy Structure_tool/tests/test_structure_service.py::TestSlab -v
```

Expected: All 7 tests PASS. (Slab generation may be slow — allow up to 60 s.)

- [ ] **Step 3.5 — Commit**

```powershell
git add Structure_tool/structure_service.py Structure_tool/tests/test_structure_service.py
git commit -m "feat: add vacancy() and slab() methods to StructureService"
```

---

## Task 4: StructureService — `adsorption` + `particle`

**Files:**
- Modify: `Structure_tool/structure_service.py` (add 2 methods)
- Modify: `Structure_tool/tests/test_structure_service.py` (add 2 test classes)

- [ ] **Step 4.1 — Append failing tests**

```python
# Append to Structure_tool/tests/test_structure_service.py

def _make_cu_slab(tmp_path):
    """
    Helper: generate a minimal Cu(111) slab and save it.
    Uses BulkToSlabGenerator directly so we have a real slab for adsorption tests.
    """
    from Structure_tool.bulk_to_slab import BulkToSlabGenerator
    lat = Lattice.cubic(3.615)
    struct = Structure(
        lat, ["Cu"] * 4,
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]]
    )
    gen = BulkToSlabGenerator(struct, save_dir=str(tmp_path))
    gen.generate(miller_indices="111", target_layers=4, vacuum_thickness=15.0)
    slabs = gen.get_slabs()
    from pymatgen.io.vasp import Poscar
    slab_path = tmp_path / "POSCAR_slab"
    with open(slab_path, "wt", encoding="utf-8") as f:
        f.write(Poscar(slabs[0]).get_string())
    return str(slab_path)


class TestAdsorption:
    def test_analyze_returns_site_counts(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab(tmp_path)
        result = StructureService().adsorption(path, mode="analyze",
                                               save_dir=str(tmp_path))
        assert result["success"] is True
        assert "site_counts" in result
        counts = result["site_counts"]
        # Cu(111) must have at least ontop and hollow sites
        total = sum(counts.values())
        assert total > 0

    def test_generate_creates_structures(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab(tmp_path)
        result = StructureService().adsorption(
            path, mode="generate", molecule_formula="CO",
            save_dir=str(tmp_path)
        )
        assert result["success"] is True
        assert result["num_generated"] > 0

    def test_generate_saves_files(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pathlib import Path
        path = _make_cu_slab(tmp_path)
        result = StructureService().adsorption(
            path, mode="generate", molecule_formula="CO",
            save_dir=str(tmp_path)
        )
        for saved in result["saved_files"]:
            assert Path(saved).exists()

    def test_generate_without_molecule_returns_error(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab(tmp_path)
        result = StructureService().adsorption(path, mode="generate",
                                               save_dir=str(tmp_path))
        assert "error" in result


class TestParticle:
    def test_wulff_pt_generates_structure(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        result = StructureService().particle(
            element="Pt",
            mode="wulff",
            surface_energies={"111": 0.05, "100": 0.07, "110": 0.09},
            particle_size=12.0,
            vacuum=10.0,
            save_dir=str(tmp_path),
            filename="POSCAR_Pt_wulff",
        )
        assert result["success"] is True
        assert result["structure"]["reduced_formula"] == "Pt"
        assert result["structure"]["nsites"] > 0

    def test_sphere_au_generates_structure(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        result = StructureService().particle(
            element="Au",
            mode="sphere",
            particle_size=8.0,
            vacuum=10.0,
            save_dir=str(tmp_path),
            filename="POSCAR_Au_sphere",
        )
        assert result["success"] is True
        assert result["structure"]["reduced_formula"] == "Au"

    def test_saves_file(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pathlib import Path
        result = StructureService().particle(
            element="Pt",
            mode="sphere",
            particle_size=8.0,
            vacuum=10.0,
            save_dir=str(tmp_path),
            filename="POSCAR_Pt_sphere",
        )
        assert result["success"] is True
        assert Path(result["saved_files"][0]).exists()

    def test_unknown_element_with_lattice_constant(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        result = StructureService().particle(
            element="La",
            mode="sphere",
            lattice_constant=3.75,
            lattice_type="fcc",
            particle_size=8.0,
            save_dir=str(tmp_path),
        )
        assert result["success"] is True
```

- [ ] **Step 4.2 — Run tests, confirm FAIL**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestAdsorption Structure_tool/tests/test_structure_service.py::TestParticle -v
```

Expected: `AttributeError: 'StructureService' object has no attribute 'adsorption'`

- [ ] **Step 4.3 — Add `adsorption()` and `particle()` to `structure_service.py`**

Append to the `StructureService` class:

```python
    # ── Tool 5: struct_adsorption ───────────────────────────────
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

            modifier.generate(
                molecule_formula=molecule_formula,
                find_args=find_args,
                plot=False,
            )
            structures = modifier.get_structures()
            if not structures:
                return {"error": "No adsorption structures generated.", "success": False}

            out_dir = Path(save_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

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

    # ── Tool 6: struct_particle ─────────────────────────────────
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
                gen.wulff(
                    surface_energies=surface_energies,
                    size=particle_size or 20.0,
                    vacuum=vacuum,
                )
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
```

- [ ] **Step 4.4 — Run tests, confirm PASS**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestAdsorption Structure_tool/tests/test_structure_service.py::TestParticle -v
```

Expected: All 8 tests PASS.

- [ ] **Step 4.5 — Run full service test suite**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py -v
```

Expected: All tests PASS.

- [ ] **Step 4.6 — Commit**

```powershell
git add Structure_tool/structure_service.py Structure_tool/tests/test_structure_service.py
git commit -m "feat: add adsorption() and particle() methods to StructureService"
```

---

## Task 5: Executor

**Files:**
- Create: `Structure_tool/structure_tool_executor.py`
- Modify: `Structure_tool/tests/test_structure_service.py` (add executor tests)

- [ ] **Step 5.1 — Write failing executor tests**

```python
# Append to Structure_tool/tests/test_structure_service.py

import asyncio
import json as _json


class TestStructureToolExecutor:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_execute_struct_load(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        path = _make_fcc_cu(tmp_path)
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_load", {"file_path": path}))
        result = _json.loads(raw)
        assert result["formula"] == "Cu4"
        assert result["nsites"] == 4

    def test_execute_struct_supercell(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        path = _make_fcc_cu(tmp_path)
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_supercell", {
            "file_path": path,
            "supercell_matrix": "2x2x1",
            "save_dir": str(tmp_path),
            "filename": "POSCAR_221",
        }))
        result = _json.loads(raw)
        assert result["structure"]["nsites"] == 16

    def test_execute_unknown_tool_returns_error(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("nonexistent_tool", {}))
        result = _json.loads(raw)
        assert "error" in result

    def test_tools_property_returns_6_entries(self):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        assert len(executor.tools) == 6

    def test_execute_bad_args_returns_error_json(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_load", {}))  # missing file_path
        result = _json.loads(raw)
        assert "error" in result
```

- [ ] **Step 5.2 — Run tests, confirm FAIL**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestStructureToolExecutor -v
```

Expected: `ModuleNotFoundError: No module named 'Structure_tool.structure_tool_executor'`

- [ ] **Step 5.3 — Create `structure_tool_executor.py`**

```python
# Structure_tool/structure_tool_executor.py
"""
StructureToolExecutor: dispatches LLM tool calls to StructureService.
Mirrors the LocalToolExecutor pattern from Search_tool/mp_tool_use.py.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from .structure_tool_schemas import (
    get_structure_tool_schema,
    LoadArgs, SupercellArgs, VacancyArgs, SlabArgs, AdsorptionArgs, ParticleArgs,
)
from .structure_service import StructureService

_SCHEMA_LANG = "en"  # override via env MP_SCHEMA_LANG if desired


class StructureToolExecutor:
    """
    Async executor for structure manipulation tools.

    Tool dispatch table maps tool name → (Pydantic args model, StructureService method name).
    Validates args with Pydantic before calling the service.
    """

    _TOOL_DISPATCH: Dict[str, tuple] = {
        "struct_load":       (LoadArgs,       "_load"),
        "struct_supercell":  (SupercellArgs,  "_supercell"),
        "struct_vacancy":    (VacancyArgs,    "_vacancy"),
        "struct_slab":       (SlabArgs,       "_slab"),
        "struct_adsorption": (AdsorptionArgs, "_adsorption"),
        "struct_particle":   (ParticleArgs,   "_particle"),
    }

    def __init__(self):
        self._svc = StructureService()

    @property
    def tools(self) -> List[Dict]:
        import os
        lang = os.environ.get("MP_SCHEMA_LANG", "en")
        return get_structure_tool_schema(lang)

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        return await asyncio.to_thread(self._sync_execute, tool_name, tool_args)

    def _sync_execute(self, tool_name: str, tool_args: Dict) -> str:
        try:
            if tool_name not in self._TOOL_DISPATCH:
                return json.dumps({"error": f"Unknown tool: {tool_name}. "
                                            f"Available: {list(self._TOOL_DISPATCH)}"})
            model_cls, method_name = self._TOOL_DISPATCH[tool_name]
            validated = model_cls.model_validate(tool_args)
            clean = validated.model_dump()
            payload = getattr(self, method_name)(clean)
        except Exception as e:
            payload = {"error": str(e)}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ── Dispatch methods (unpack dict → positional/keyword args) ──

    def _load(self, args: Dict) -> Dict:
        return self._svc.load(args["file_path"])

    def _supercell(self, args: Dict) -> Dict:
        return self._svc.supercell(
            file_path=args["file_path"],
            supercell_matrix=args["supercell_matrix"],
            save_dir=args["save_dir"],
            filename=args.get("filename"),
        )

    def _vacancy(self, args: Dict) -> Dict:
        return self._svc.vacancy(
            file_path=args["file_path"],
            element=args["element"],
            dopant=args.get("dopant"),
            num_vacancies=args.get("num_vacancies", 1),
            num_structs=args.get("num_structs", 1),
            top_layers=args.get("top_layers"),
            random_seed=args.get("random_seed"),
            save_dir=args.get("save_dir", "./structures"),
            filename_prefix=args.get("filename_prefix", "POSCAR_vac"),
        )

    def _slab(self, args: Dict) -> Dict:
        return self._svc.slab(
            file_path=args["file_path"],
            miller_indices=args["miller_indices"],
            target_layers=args["target_layers"],
            vacuum_thickness=args.get("vacuum_thickness", 15.0),
            supercell_matrix=args.get("supercell_matrix"),
            fix_bottom_layers=args.get("fix_bottom_layers", 0),
            fix_top_layers=args.get("fix_top_layers", 0),
            termination_index=args.get("termination_index", 0),
            save_dir=args.get("save_dir", "./structures"),
            filename=args.get("filename", "POSCAR"),
        )

    def _adsorption(self, args: Dict) -> Dict:
        return self._svc.adsorption(
            file_path=args["file_path"],
            mode=args["mode"],
            molecule_formula=args.get("molecule_formula"),
            positions=args.get("positions"),
            save_dir=args.get("save_dir", "./structures"),
        )

    def _particle(self, args: Dict) -> Dict:
        return self._svc.particle(
            element=args["element"],
            mode=args["mode"],
            lattice_constant=args.get("lattice_constant"),
            lattice_type=args.get("lattice_type"),
            surface_energies=args.get("surface_energies"),
            particle_size=args.get("particle_size"),
            layers=args.get("layers"),
            surfaces=args.get("surfaces"),
            p=args.get("p"),
            q=args.get("q"),
            r=args.get("r"),
            n_shells=args.get("n_shells"),
            rod_radius=args.get("rod_radius"),
            rod_length=args.get("rod_length"),
            vacuum=args.get("vacuum", 15.0),
            save_dir=args.get("save_dir", "./structures"),
            filename=args.get("filename", "POSCAR"),
        )

    async def close(self):
        pass  # no persistent connections to clean up
```

- [ ] **Step 5.4 — Run executor tests, confirm PASS**

```powershell
python -m pytest Structure_tool/tests/test_structure_service.py::TestStructureToolExecutor -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5.5 — Commit**

```powershell
git add Structure_tool/structure_tool_executor.py Structure_tool/tests/test_structure_service.py
git commit -m "feat: add StructureToolExecutor with dispatch table for all 6 tools"
```

---

## Task 6: Entry Point

**Files:**
- Create: `Structure_tool/structure_tool_use.py`

No new tests for this task (the LLM loop is tested by running it). The executor it calls is already tested.

- [ ] **Step 6.1 — Create `structure_tool_use.py`**

```python
# Structure_tool/structure_tool_use.py
"""
Entry point for the Structure Tool_use LLM agent.

Usage (from Tool_use/Structure_tool/):
    python structure_tool_use.py

Env vars loaded from ../.env (Search_tool's .env) or a local .env:
    LLM_API_KEY  — required
    MP_SCHEMA_LANG — optional, "en" | "cn" (default: "en")

LLM provider is set by changing llm_provider= in main().
Available providers: deepseek | qwen | glm | openai
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Allow running from this directory or parent directory
sys.path.insert(0, str(Path(__file__).parent.parent / "Search_tool"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "Search_tool" / ".env")
load_dotenv()  # also try local .env

from .structure_tool_executor import StructureToolExecutor

# ──────────────────────────────────────────────
# LLM provider configs (same as Search_tool)
# ──────────────────────────────────────────────

LLM_CONFIGS: Dict[str, Dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-chat",
        "extra":    {"parallel_tool_calls": False},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model":    "qwen-max",
        "extra":    {},
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model":    "glm-4-air",
        "extra":    {},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model":    "gpt-4o",
        "extra":    {},
    },
}


def _get_openai_client(provider: str, llm_api_key: str):
    from openai import OpenAI
    cfg = LLM_CONFIGS[provider]
    client = OpenAI(api_key=llm_api_key, base_url=cfg["base_url"])
    client._mp_model = cfg["model"]
    client._mp_extra = cfg["extra"]
    return client


def message_to_dict(msg: Any) -> Dict:
    d: Dict[str, Any] = {
        "role":    msg.role,
        "content": msg.content if msg.content is not None else "",
    }
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id":       tc.id,
                "type":     "function",
                "function": {
                    "name":      tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


# ──────────────────────────────────────────────
# LLM agentic loop
# ──────────────────────────────────────────────

async def run(
    user_message: str,
    executor: StructureToolExecutor,
    llm_provider: str = "deepseek",
    llm_api_key: str = "",
) -> str:
    client  = _get_openai_client(llm_provider, llm_api_key)
    model   = client._mp_model
    extra   = client._mp_extra
    messages: List[Dict] = [
        {
            "role": "system",
            "content": (
                "You are a computational chemistry assistant specialising in crystal structure "
                "manipulation for VASP DFT calculations. You have access to tools that can: "
                "load and inspect structures, create supercells, generate vacancy/substitution "
                "defects, cut slabs, place adsorbates, and build nanoparticles. "
                "All tools work with local file paths. When saving files, use the save_dir "
                "provided by the user or default to './structures'. "
                "Always call struct_load first to inspect an unknown structure before operating on it. "
                "Return a concise summary of what was generated and the saved file paths."
            ),
        },
        {"role": "user", "content": user_message},
    ]

    while True:
        response = client.chat.completions.create(
            model       = model,
            messages    = messages,
            tools       = executor.tools,
            tool_choice = "auto",
            max_tokens  = 2048,
            temperature = 0.3,
            **extra,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content

        messages.append(message_to_dict(msg))

        results = await asyncio.gather(*[
            executor.execute(tc.function.name, json.loads(tc.function.arguments))
            for tc in msg.tool_calls
        ])

        for tc, result in zip(msg.tool_calls, results):
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

async def main():
    LLM_KEY = os.environ.get("LLM_API_KEY")
    if not LLM_KEY:
        raise ValueError("LLM_API_KEY not set. Add it to Search_tool/.env or set it in the environment.")

    executor = StructureToolExecutor()
    print(f"[Tools] {[t['function']['name'] for t in executor.tools]}")

    # ── Example questions — edit as needed ──────────────────────
    # File paths should point to real structure files on disk.
    # The examples below assume the structures/ directory from Search_tool downloads.
    QUESTIONS = [
        "Load the structure at ./structures/mp-19770_Fe2O3.cif and tell me its space group and lattice parameters.",
        "Create a 2×2×1 supercell of ./structures/mp-19770_Fe2O3.cif and save it to ./structures/supercells/.",
        "Generate a Pt Wulff-shape nanoparticle with surface energies {'111': 0.05, '100': 0.07} and size 15 Å, save to ./structures/particles/.",
    ]

    try:
        for q in QUESTIONS:
            print(f"\n{'='*60}\n>>> {q}\n{'='*60}")
            ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
            print(ans)
    finally:
        await executor.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
```

- [ ] **Step 6.2 — Smoke test: verify the module imports cleanly**

```powershell
python -c "from Structure_tool.structure_tool_executor import StructureToolExecutor; e = StructureToolExecutor(); print([t['function']['name'] for t in e.tools])"
```

Expected output:
```
['struct_load', 'struct_supercell', 'struct_vacancy', 'struct_slab', 'struct_adsorption', 'struct_particle']
```

- [ ] **Step 6.3 — Run full test suite**

```powershell
python -m pytest Structure_tool/tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 6.4 — Commit**

```powershell
git add Structure_tool/structure_tool_use.py
git commit -m "feat: add structure_tool_use.py entry point with LLM agentic loop"
```

---

## Task 7: CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 7.1 — Add Structure Tool_use section to CLAUDE.md**

Add the following section after the existing `Structure_tool Package` section:

```markdown
### Structure Tool_use (LLM Agent)

Six tools exposed as OpenAI function-calling tools for LLM orchestration:

| Tool | Operation | Key args |
|---|---|---|
| `struct_load` | Inspect structure | `file_path` |
| `struct_supercell` | Expand unit cell | `file_path`, `supercell_matrix` (e.g. `"2x2x1"`) |
| `struct_vacancy` | Vacancy/substitution defects | `file_path`, `element`, `dopant`, `num_vacancies` |
| `struct_slab` | Bulk → slab | `file_path`, `miller_indices`, `target_layers` |
| `struct_adsorption` | Find sites / place adsorbate | `file_path`, `mode` (`analyze`\|`generate`), `molecule_formula` |
| `struct_particle` | Nanoparticle generation | `element`, `mode` (`wulff`\|`sphere`\|...) |

All tools take file paths (not structure objects) and return summary dicts + `saved_files` paths — never raw CIF/POSCAR content (mirrors Search_tool's token-efficient pattern).

Run from `Structure_tool/` (or as a subagent entry point):
```powershell
python structure_tool_use.py
```

LLM provider and API key: set `LLM_API_KEY` in `Search_tool/.env` (auto-loaded). Change `llm_provider=` in `main()` to switch between `deepseek`/`qwen`/`glm`/`openai`.
```

- [ ] **Step 7.2 — Commit**

```powershell
git add CLAUDE.md
git commit -m "docs: add Structure Tool_use section to CLAUDE.md"
```

---

## Self-Review

### Spec coverage check

| Requirement | Covered by |
|---|---|
| supercell | Task 2 (`struct_supercell`) |
| vacancy | Task 3 (`struct_vacancy`) |
| slab | Task 3 (`struct_slab`) |
| adsorption | Task 4 (`struct_adsorption`) |
| particle | Task 4 (`struct_particle`) |
| Pydantic framework | Task 1 (`structure_tool_schemas.py`) |
| Summary pattern (no raw files) | `_structure_summary()` in `structure_service.py` |
| ml_meta.py not needed | ✅ explicitly excluded |
| LLM tool_use entry point | Task 6 (`structure_tool_use.py`) |
| struct_load for inspection | Task 2 |

All spec requirements are covered.

### Placeholder scan

No TBD / TODO / "similar to Task N" in this plan. All code steps are complete.

### Type consistency

- `_structure_summary(struct)` defined in Task 2.3 and used identically in Tasks 3.3, 4.3 (same function reference, no name drift).
- `_save_poscar(struct, save_dir, filename)` defined in Task 2.3, used consistently.
- `StructureService` method names used in `StructureToolExecutor._TOOL_DISPATCH` match exactly (`_load`, `_supercell`, `_vacancy`, `_slab`, `_adsorption`, `_particle`).
