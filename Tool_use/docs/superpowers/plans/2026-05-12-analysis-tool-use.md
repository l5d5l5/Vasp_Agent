# Analysis Tool_use LLM Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM agentic loop layer to `Analysis_tool` so an LLM can post-process VASP calculations via six OpenAI function-calling tools (DOS, relaxation, structure info, COHP summary, COHP curves, COHP export).

**Architecture:** Follows the identical three-file pattern established by `Structure_tool`: `analysis_tool_schemas.py` (Pydantic → OpenAI schema), `analysis_tool_executor.py` (async dispatch wrapper around `VaspAnalysisDispatcher`), and `analysis_tool_use.py` (OpenAI-compatible LLM loop). The executor strips large numeric arrays from DOS/COHP responses before returning to the LLM, keeping token usage manageable.

**Tech Stack:** Python 3.10+, Pydantic v2, openai SDK (OpenAI-compatible), asyncio, numpy/pandas (via `Analysis.py`), pymatgen, pytest + pytest-asyncio.

---

## File Map

| Path | Status | Responsibility |
|------|--------|----------------|
| `Analysis_tool/__init__.py` | Create | Package init; exports `VaspAnalysisDispatcher` |
| `Analysis_tool/analysis_tool_schemas.py` | Create | 6 Pydantic arg models + `get_analysis_tool_schema(lang)` |
| `Analysis_tool/analysis_tool_executor.py` | Create | `AnalysisToolExecutor`: async dispatch + array stripping |
| `Analysis_tool/analysis_tool_use.py` | Create | LLM agentic loop entry point (mirrors `structure_tool_use.py`) |
| `Analysis_tool/tests/__init__.py` | Create | Test package |
| `Analysis_tool/tests/test_analysis_executor.py` | Create | Executor unit tests using `Test/dos/` fixtures |

### Key design decisions

- `vasp_dos` accepts `elements: List[str]` and `orbitals: List[str]` (not the raw `curves` list that `DosAnalysis.analyze()` takes internally). The executor constructs the `curves` list. Raw `energy`, `dos_up`, `dos_down` arrays are stripped before returning to LLM — only `stats` (d-band center, width, skewness, kurtosis, filling) are returned.
- `vasp_cohp_curves` also strips raw curve arrays; only curve count + column names are returned. Use `vasp_cohp_export` to write full data to disk.
- `vasp_cohp_export` saves a CSV/JSON file via `CohpAnalysis.get_cohp_curves()` and returns the saved file path.
- `vasp_structure_info` strips `vasp_text` (full POSCAR content) from the response.
- `CohpSummaryArgs.filter_value` is `List[str]` for OpenAI schema compatibility; the executor converts to `List[int]` when `filter_type == "index"`.

---

## Task 1: Package init + failing tests

**Files:**
- Create: `Analysis_tool/__init__.py`
- Create: `Analysis_tool/tests/__init__.py`
- Create: `Analysis_tool/tests/test_analysis_executor.py`

- [ ] **Step 1: Create `Analysis_tool/__init__.py`**

```python
from .Analysis import VaspAnalysisDispatcher

__all__ = ["VaspAnalysisDispatcher"]
```

- [ ] **Step 2: Create `Analysis_tool/tests/__init__.py`**

```python
# tests package
```

- [ ] **Step 3: Write failing tests in `Analysis_tool/tests/test_analysis_executor.py`**

```python
"""
Tests for AnalysisToolExecutor.
Test data: Analysis_tool/Test/dos/  (has DOSCAR, POSCAR, OUTCAR, OSZICAR, CONTCAR)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# This import fails until the executor is created — expected for TDD
from Analysis_tool.analysis_tool_executor import AnalysisToolExecutor

DOS_DIR = str(Path(__file__).parent.parent / "Test" / "dos")


@pytest.fixture
def executor():
    return AnalysisToolExecutor()


@pytest.mark.asyncio
async def test_tools_list(executor):
    """Executor exposes a list of 6 OpenAI-format tool dicts."""
    tools = executor.tools
    assert isinstance(tools, list)
    assert len(tools) == 6
    names = {t["function"]["name"] for t in tools}
    assert names == {
        "vasp_dos",
        "vasp_relax",
        "vasp_structure_info",
        "vasp_cohp_summary",
        "vasp_cohp_curves",
        "vasp_cohp_export",
    }


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(executor):
    """Unknown tool name returns a JSON error, not a Python exception."""
    result = await executor.execute("vasp_nonexistent", {"work_dir": DOS_DIR})
    data = json.loads(result)
    assert "error" in data


@pytest.mark.asyncio
async def test_vasp_structure_info(executor):
    """Structure info returns formula and lattice params from POSCAR/CONTCAR."""
    result = await executor.execute("vasp_structure_info", {"work_dir": DOS_DIR})
    data = json.loads(result)
    assert data.get("success") is True
    info = data["data"]
    assert "formula" in info
    assert "lattice" in info
    assert "totalAtoms" in info
    # vasp_text must be stripped (too large for LLM)
    assert "vasp_text" not in info


@pytest.mark.asyncio
async def test_vasp_relax(executor):
    """Relax analysis returns convergence status and energy history."""
    result = await executor.execute("vasp_relax", {"work_dir": DOS_DIR})
    data = json.loads(result)
    assert data.get("success") is True
    info = data["data"]
    assert "converged" in info
    assert "final_energy_eV" in info
    assert "force_history" in info


@pytest.mark.asyncio
async def test_vasp_dos(executor):
    """DOS analysis returns d-band stats; raw arrays are stripped."""
    result = await executor.execute(
        "vasp_dos",
        {
            "work_dir": DOS_DIR,
            "elements": ["Fe"],
            "orbitals": ["d"],
            "erange": [-10.0, 5.0],
            "show_tdos": False,
        },
    )
    data = json.loads(result)
    assert data.get("success") is True
    curves = data["data"]["curves"]
    assert len(curves) >= 1
    stats = curves[0]["stats"]
    assert "center" in stats
    # Raw arrays must NOT appear in the LLM-facing result
    assert "dos_up" not in curves[0]
    assert "energy" not in data["data"]


@pytest.mark.asyncio
async def test_vasp_cohp_summary_no_lobster(executor):
    """COHP summary returns graceful result when no LOBSTER files exist."""
    result = await executor.execute(
        "vasp_cohp_summary", {"work_dir": DOS_DIR, "n_top_bonds": 10}
    )
    data = json.loads(result)
    # Either succeeds with empty list or returns an error dict — both acceptable
    assert isinstance(data, dict)
```

- [ ] **Step 4: Run tests to confirm they fail with ImportError**

Run from `Tool_use/` directory:
```
pytest Analysis_tool/tests/test_analysis_executor.py -v
```
Expected: `ImportError: cannot import name 'AnalysisToolExecutor'`

- [ ] **Step 5: Commit skeleton**

```bash
git add Analysis_tool/__init__.py Analysis_tool/tests/__init__.py Analysis_tool/tests/test_analysis_executor.py
git commit -m "test: add failing executor tests for Analysis_tool LLM tool use"
```

---

## Task 2: analysis_tool_schemas.py

**Files:**
- Create: `Analysis_tool/analysis_tool_schemas.py`

- [ ] **Step 1: Write the complete schemas file**

```python
# ══════════════════════════════════════════════════════════════
# analysis_tool_schemas.py
# Pydantic models → OpenAI function-calling schema for 6 VASP analysis tools
#
# Public API:
#   get_analysis_tool_schema(lang="en") -> list[dict]
#   DosArgs / RelaxArgs / StructureInfoArgs /
#   CohpSummaryArgs / CohpCurvesArgs / CohpExportArgs
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# §1  Pydantic argument models (6 tools)
# ══════════════════════════════════════════════

class DosArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the VASP calculation directory containing DOSCAR, POSCAR, and OUTCAR. "
            "Can be absolute or relative."
        )
    )
    elements: List[str] = Field(
        description=(
            "List of element symbols to extract projected DOS for "
            "(e.g. ['Fe', 'O']). Each element produces one DOS curve."
        )
    )
    orbitals: List[str] = Field(
        default=["d"],
        description=(
            "Orbital(s) to project onto. Supported: 's', 'p', 'd', "
            "'p_x', 'p_y', 'p_z', 'd_xy', 'd_yz', 'd_z2', 'd_xz', 'd_x2-y2'. "
            "Provide one entry per element, or a single entry applied to all. "
            "Default: ['d']."
        ),
    )
    erange: List[float] = Field(
        default=[-10.0, 5.0],
        description=(
            "Energy window [E_min, E_max] in eV relative to the Fermi level. "
            "Default: [-10.0, 5.0]."
        ),
    )
    show_tdos: bool = Field(
        default=False,
        description="If True, include total DOS statistics in the result. Default: False.",
    )


class RelaxArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the VASP calculation directory containing OUTCAR and OSZICAR."
        )
    )
    get_site_mag: bool = Field(
        default=False,
        description=(
            "If True, parse and return per-atom magnetic moments from OUTCAR. "
            "Slightly slower for large OUTCAR files. Default: False."
        ),
    )


class StructureInfoArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the VASP calculation directory containing POSCAR or CONTCAR. "
            "CONTCAR (final relaxed geometry) is preferred; falls back to POSCAR."
        )
    )


class CohpSummaryArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the LOBSTER output directory containing ICOHPLIST.lobster "
            "and optionally COHPCAR.lobster."
        )
    )
    n_top_bonds: int = Field(
        default=20,
        description=(
            "Number of top bonds to return, sorted by |ICOHP| descending. Default: 20."
        ),
    )
    filter_type: Optional[str] = Field(
        default=None,
        description=(
            "Optional filter mode:\n"
            "  'index'        — filter by bond index numbers (provide integers in filter_value)\n"
            "  'element_pair' — filter by element pair (provide two element symbols in filter_value)\n"
            "  null           — no filter, return all top bonds."
        ),
    )
    filter_value: Optional[List[str]] = Field(
        default=None,
        description=(
            "Filter values matching filter_type:\n"
            "  For 'index': list of bond index strings, e.g. ['1', '3', '5']\n"
            "  For 'element_pair': two element symbols, e.g. ['Fe', 'O']"
        ),
    )


class CohpCurvesArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the LOBSTER output directory containing COHPCAR.lobster."
        )
    )
    bond_labels: List[str] = Field(
        description=(
            "Bond label strings to extract COHP curves for. "
            "Bond labels come from the 'bond_label' field in vasp_cohp_summary output "
            "(e.g. ['1', '2', '5'])."
        )
    )
    erange: Optional[List[float]] = Field(
        default=None,
        description=(
            "Energy window [E_min, E_max] in eV (absolute, not Fermi-shifted). "
            "If omitted, the full energy range from COHPCAR is returned."
        ),
    )
    include_orbitals: bool = Field(
        default=False,
        description=(
            "If True and COHPCAR contains orbital-resolved data, include per-orbital "
            "COHP contributions in the summary. Default: False."
        ),
    )


class CohpExportArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description="Path to the LOBSTER output directory containing COHPCAR.lobster."
    )
    bond_labels: List[str] = Field(
        description=(
            "Bond label strings to export COHP data for "
            "(e.g. ['1', '2']). Use vasp_cohp_summary first to discover bond labels."
        )
    )
    erange: Optional[List[float]] = Field(
        default=None,
        description="Energy window [E_min, E_max] in eV. If omitted, full range is exported.",
    )
    include_orbitals: bool = Field(
        default=False,
        description="If True, include orbital-resolved COHP columns in the export. Default: False.",
    )
    export_format: Literal["csv", "json"] = Field(
        default="csv",
        description="Output file format: 'csv' or 'json'. Default: 'csv'.",
    )
    save_dir: str = Field(
        default="./cohp_export",
        description=(
            "Directory where the export file will be saved. "
            "Created automatically if it does not exist. Default: './cohp_export'."
        ),
    )


# ══════════════════════════════════════════════
# §2  ToolSpec container
# ══════════════════════════════════════════════

@dataclass
class ToolSpec:
    name:           str
    description_en: str
    description_cn: str
    args_class:     type[BaseModel]


_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="vasp_dos",
        description_en=(
            "Extract projected density of states (PDOS) from a VASP DOSCAR file "
            "and compute catalytic descriptors for each requested element-orbital pair. "
            "Returns d-band center, width, skewness, kurtosis, and filling fraction. "
            "Raw DOS arrays are NOT returned — only the statistical descriptors. "
            "Requires DOSCAR and POSCAR in work_dir."
        ),
        description_cn=(
            "从 VASP DOSCAR 文件中提取投影态密度（PDOS）并为每对元素-轨道计算催化描述符。"
            "返回 d 带中心、宽度、偏度、峰度和填充分数。"
            "不返回原始 DOS 数组，仅返回统计描述符。"
            "需要 work_dir 中的 DOSCAR 和 POSCAR。"
        ),
        args_class=DosArgs,
    ),
    ToolSpec(
        name="vasp_relax",
        description_en=(
            "Analyse a VASP structural optimisation (relaxation) run. "
            "Reports convergence status, final total energy, Fermi level, ionic step count, "
            "energy and force convergence history, initial and final structures, "
            "and convergence warnings. "
            "Requires OUTCAR (and optionally OSZICAR) in work_dir."
        ),
        description_cn=(
            "分析 VASP 结构优化（弛豫）计算。"
            "报告收敛状态、最终总能量、费米能级、离子步骤数、"
            "能量和力的收敛历史、初始和最终结构以及收敛警告。"
            "需要 work_dir 中的 OUTCAR（以及可选的 OSZICAR）。"
        ),
        args_class=RelaxArgs,
    ),
    ToolSpec(
        name="vasp_structure_info",
        description_en=(
            "Extract structural information from a VASP POSCAR or CONTCAR file. "
            "Returns chemical formula, element list, total atom count, cell volume, "
            "and lattice parameters (a, b, c, α, β, γ). "
            "Prefers CONTCAR (final geometry) over POSCAR."
        ),
        description_cn=(
            "从 VASP POSCAR 或 CONTCAR 文件中提取结构信息。"
            "返回化学式、元素列表、总原子数、晶胞体积和晶格参数（a, b, c, α, β, γ）。"
            "优先读取 CONTCAR（最终结构），若不存在则回退到 POSCAR。"
        ),
        args_class=StructureInfoArgs,
    ),
    ToolSpec(
        name="vasp_cohp_summary",
        description_en=(
            "Load ICOHPLIST.lobster from a LOBSTER calculation and return a ranked "
            "bond table sorted by |ICOHP| (bond strength). "
            "Each row contains: bond label, atom pair, element pair, bond length, "
            "and ICOHP values (spin-up, spin-down, total). "
            "Optionally filter by bond index or element pair. "
            "Call this first to discover bond labels before using vasp_cohp_curves."
        ),
        description_cn=(
            "从 LOBSTER 计算的 ICOHPLIST.lobster 中加载键列表，"
            "按 |ICOHP|（键强度）排序返回键表。"
            "每行包含：键标签、原子对、元素对、键长和 ICOHP 值（自旋上、自旋下、总计）。"
            "可按键索引或元素对筛选。"
            "先调用此工具以确定键标签，再使用 vasp_cohp_curves 进一步分析。"
        ),
        args_class=CohpSummaryArgs,
    ),
    ToolSpec(
        name="vasp_cohp_curves",
        description_en=(
            "Extract COHP curve data for specified bonds from COHPCAR.lobster. "
            "Returns a compact summary: energy range, bond labels analysed, "
            "number of data points, and column names. "
            "Raw numeric arrays are NOT returned to save tokens. "
            "Use vasp_cohp_export to write the full data to a file on disk."
        ),
        description_cn=(
            "从 COHPCAR.lobster 中提取指定键的 COHP 曲线数据。"
            "返回紧凑摘要：能量范围、分析的键标签、数据点数量和列名。"
            "不返回原始数值数组以节省 token。"
            "使用 vasp_cohp_export 将完整数据写入磁盘文件。"
        ),
        args_class=CohpCurvesArgs,
    ),
    ToolSpec(
        name="vasp_cohp_export",
        description_en=(
            "Export COHP curve data for specified bonds to a CSV or JSON file on disk. "
            "Saves the full numeric data (energy axis + COHP columns per bond) "
            "and returns the saved file path. "
            "Use vasp_cohp_summary to identify bond labels, then call this "
            "to persist data for plotting or further analysis."
        ),
        description_cn=(
            "将指定键的 COHP 曲线数据导出为 CSV 或 JSON 文件保存到磁盘。"
            "保存完整数值数据（能量轴和每个键的 COHP 列），并返回保存的文件路径。"
            "先使用 vasp_cohp_summary 确定键标签，再调用此工具持久化数据以便绘图或进一步分析。"
        ),
        args_class=CohpExportArgs,
    ),
]


# ══════════════════════════════════════════════
# §3  Schema conversion: Pydantic v2 → OpenAI compatible
# ══════════════════════════════════════════════

def _model_to_openai_schema(model_cls: type[BaseModel]) -> Dict[str, Any]:
    schema: Dict[str, Any] = dict(model_cls.model_json_schema())
    schema.pop("title", None)
    schema.pop("$defs", None)

    cleaned_props: Dict[str, Any] = {}
    for field_name, prop in schema.get("properties", {}).items():
        prop = dict(prop)
        prop.pop("title", None)

        if "anyOf" in prop:
            non_null = [t for t in prop["anyOf"] if t != {"type": "null"}]
            if len(non_null) == 1:
                inner = dict(non_null[0])
                prop.pop("anyOf")
                prop.update(inner)

        if "default" in prop and prop["default"] is None:
            prop.pop("default")

        cleaned_props[field_name] = prop

    required = schema.get("required", [])

    return {
        "type": "object",
        "properties": cleaned_props,
        "required": required,
    }


# ══════════════════════════════════════════════
# §4  Public function: get_analysis_tool_schema
# ══════════════════════════════════════════════

def get_analysis_tool_schema(lang: str = "en") -> list[Dict[str, Any]]:
    """
    Generate the OpenAI function-calling tool schema list for the 6 VASP analysis tools.

    Parameters
    ----------
    lang : "en" | "cn"
        Language for tool descriptions. Default: "en".

    Returns
    -------
    list[dict]
        Ready to pass as tools=[...] to openai.chat.completions.create().
    """
    result = []
    for spec in _TOOL_SPECS:
        description = spec.description_cn if lang == "cn" else spec.description_en
        result.append({
            "type": "function",
            "function": {
                "name":        spec.name,
                "description": description,
                "parameters":  _model_to_openai_schema(spec.args_class),
            },
        })
    return result
```

- [ ] **Step 2: Commit**

```bash
git add Analysis_tool/analysis_tool_schemas.py
git commit -m "feat: add analysis_tool_schemas.py with 6 VASP analysis tool schemas"
```

---

## Task 3: analysis_tool_executor.py (make tests pass)

**Files:**
- Create: `Analysis_tool/analysis_tool_executor.py`

- [ ] **Step 1: Write the executor**

```python
# Analysis_tool/analysis_tool_executor.py
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .analysis_tool_schemas import (
    get_analysis_tool_schema,
    DosArgs, RelaxArgs, StructureInfoArgs,
    CohpSummaryArgs, CohpCurvesArgs, CohpExportArgs,
)
from .Analysis import VaspAnalysisDispatcher


class AnalysisToolExecutor:
    """
    Async executor for VASP analysis tools.
    Mirrors StructureToolExecutor from Structure_tool/structure_tool_executor.py.
    """

    _TOOL_DISPATCH: Dict[str, tuple] = {
        "vasp_dos":            (DosArgs,          "_dos"),
        "vasp_relax":          (RelaxArgs,         "_relax"),
        "vasp_structure_info": (StructureInfoArgs, "_structure_info"),
        "vasp_cohp_summary":   (CohpSummaryArgs,   "_cohp_summary"),
        "vasp_cohp_curves":    (CohpCurvesArgs,    "_cohp_curves"),
        "vasp_cohp_export":    (CohpExportArgs,    "_cohp_export"),
    }

    @property
    def tools(self) -> List[Dict]:
        lang = os.environ.get("MP_SCHEMA_LANG", "en")
        return get_analysis_tool_schema(lang)

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
            return getattr(self, method_name)(clean)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── DOS ──────────────────────────────────────────────────────
    def _dos(self, args: Dict) -> str:
        elements = args["elements"]
        orbitals = args["orbitals"]
        if len(orbitals) == 1:
            orbitals = orbitals * len(elements)

        curves = [
            {
                "id":      f"{el}_{orb}",
                "label":   f"{el}-{orb}",
                "mode":    "element",
                "element": el,
                "orbital": orb,
                "color":   "#333",
            }
            for el, orb in zip(elements, orbitals)
        ]

        raw = VaspAnalysisDispatcher.dispatch(
            "dos", args["work_dir"],
            curves=curves,
            erange=args["erange"],
            show_tdos=args["show_tdos"],
        )
        return self._strip_dos_arrays(raw)

    @staticmethod
    def _strip_dos_arrays(raw_json: str) -> str:
        """Remove large numeric arrays from DOS result before returning to LLM."""
        try:
            data = json.loads(raw_json)
            inner = data.get("data", {})
            inner.pop("energy", None)
            inner.pop("tdos", None)
            for curve in inner.get("curves", []):
                curve.pop("dos_up", None)
                curve.pop("dos_down", None)
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw_json

    # ── Relax ─────────────────────────────────────────────────────
    def _relax(self, args: Dict) -> str:
        return VaspAnalysisDispatcher.dispatch(
            "relax", args["work_dir"],
            get_site_mag=args["get_site_mag"],
        )

    # ── Structure Info ────────────────────────────────────────────
    def _structure_info(self, args: Dict) -> str:
        raw = VaspAnalysisDispatcher.dispatch("structure_info", args["work_dir"])
        try:
            data = json.loads(raw)
            data.get("data", {}).pop("vasp_text", None)
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw

    # ── COHP Summary ──────────────────────────────────────────────
    def _cohp_summary(self, args: Dict) -> str:
        kwargs: Dict[str, Any] = {"n_top_bonds": args["n_top_bonds"]}
        if args.get("filter_type"):
            kwargs["filter_type"] = args["filter_type"]
        if args.get("filter_value"):
            fv = args["filter_value"]
            if args.get("filter_type") == "index":
                kwargs["filter_value"] = [int(v) for v in fv]
            else:
                kwargs["filter_value"] = fv
        return VaspAnalysisDispatcher.dispatch("cohp_summary", args["work_dir"], **kwargs)

    # ── COHP Curves ───────────────────────────────────────────────
    def _cohp_curves(self, args: Dict) -> str:
        kwargs: Dict[str, Any] = {
            "bond_labels":      args["bond_labels"],
            "include_orbitals": args["include_orbitals"],
        }
        if args.get("erange"):
            kwargs["erange"] = args["erange"]
        raw = VaspAnalysisDispatcher.dispatch("cohp_curves", args["work_dir"], **kwargs)
        return self._strip_cohp_arrays(raw)

    @staticmethod
    def _strip_cohp_arrays(raw_json: str) -> str:
        """Replace large cohp_curves list with a compact summary."""
        try:
            data = json.loads(raw_json)
            inner = data.get("data", {})
            curves = inner.pop("cohp_curves", [])
            if isinstance(curves, list) and curves:
                inner["n_datapoints"] = len(curves)
                inner["columns"] = list(curves[0].keys()) if curves else []
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw_json

    # ── COHP Export ───────────────────────────────────────────────
    def _cohp_export(self, args: Dict) -> str:
        import pandas as pd
        from .Analysis import CohpAnalysis

        work_dir = args["work_dir"]
        bond_labels = args["bond_labels"]
        erange = args.get("erange")
        include_orbitals = args.get("include_orbitals", False)
        export_format = args.get("export_format", "csv")
        save_dir = Path(args.get("save_dir", "./cohp_export"))

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            analyzer = CohpAnalysis(work_dir=work_dir)
            df: pd.DataFrame = analyzer.get_cohp_curves(
                bond_labels=bond_labels,
                erange=erange,
                include_orbitals=include_orbitals,
            )

            if df is None or df.empty:
                return json.dumps({
                    "success": False, "code": 404,
                    "message": "No COHP data found for the specified bonds.", "data": {}
                })

            label_str = "_".join(bond_labels[:3])
            fname = f"cohp_bonds_{label_str}.{export_format}"
            out_path = save_dir / fname

            if export_format == "csv":
                df.to_csv(out_path, index=False)
            else:
                df.to_json(out_path, orient="records", indent=2)

            return json.dumps({
                "success": True, "code": 200,
                "message": f"COHP data exported for bonds {bond_labels}",
                "data": {
                    "saved_path": str(out_path),
                    "bonds": bond_labels,
                    "n_datapoints": len(df),
                    "columns": list(df.columns),
                    "format": export_format,
                }
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "success": False, "code": 500,
                "message": f"Export failed: {e}", "data": {}
            })

    async def close(self):
        pass
```

- [ ] **Step 2: Run tests — expect all 6 to pass**

```
pytest Analysis_tool/tests/test_analysis_executor.py -v
```

Expected:
```
PASSED test_tools_list
PASSED test_unknown_tool_returns_error
PASSED test_vasp_structure_info
PASSED test_vasp_relax
PASSED test_vasp_dos
PASSED test_vasp_cohp_summary_no_lobster
```

- [ ] **Step 3: Commit**

```bash
git add Analysis_tool/analysis_tool_executor.py
git commit -m "feat: add AnalysisToolExecutor with 6 VASP analysis tools"
```

---

## Task 4: analysis_tool_use.py (LLM entry point)

**Files:**
- Create: `Analysis_tool/analysis_tool_use.py`

- [ ] **Step 1: Write the entry point**

```python
# Analysis_tool/analysis_tool_use.py
"""
Entry point for the Analysis Tool_use LLM agent.

Usage (from Tool_use/):
    python -m Analysis_tool.analysis_tool_use

Or directly:
    python D:/path/to/Tool_use/Analysis_tool/analysis_tool_use.py

Env vars (loaded from Search_tool/.env or local .env):
    LLM_API_KEY  — required
    MP_SCHEMA_LANG — "en" | "cn" (default: "en")

LLM provider: change llm_provider= in the run() call inside main().
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "Search_tool" / ".env")
load_dotenv()

try:
    from .analysis_tool_executor import AnalysisToolExecutor
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from Analysis_tool.analysis_tool_executor import AnalysisToolExecutor


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
    # DeepSeek thinking mode: reasoning_content must be echoed back to the API
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        d["reasoning_content"] = reasoning
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


async def run(
    user_message: str,
    executor: AnalysisToolExecutor,
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
                "You are a computational chemistry assistant specialising in VASP DFT "
                "post-processing analysis. You have access to tools that can: "
                "inspect structure files (POSCAR/CONTCAR), analyse structural relaxation "
                "convergence (OUTCAR/OSZICAR), extract projected DOS and d-band descriptors "
                "(DOSCAR), and analyse chemical bonding via COHP/ICOHP from LOBSTER output. "
                "All tools accept a work_dir (path to the VASP calculation directory). "
                "For DOS analysis, always specify which elements and orbitals to project. "
                "For COHP analysis, call vasp_cohp_summary first to discover bond labels, "
                "then call vasp_cohp_curves or vasp_cohp_export for detailed data. "
                "Return a concise summary of the analysis results."
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


async def main():
    LLM_KEY = os.environ.get("LLM_API_KEY")
    if not LLM_KEY:
        raise ValueError(
            "LLM_API_KEY not set. Add it to Search_tool/.env or set it in the environment."
        )

    executor = AnalysisToolExecutor()
    print(f"[Tools] {[t['function']['name'] for t in executor.tools]}")

    DOS_DIR   = str(Path(__file__).parent / "Test" / "dos")
    RELAX_DIR = str(Path(__file__).parent / "Test" / "clean-zone")

    QUESTIONS = [
        f"Analyse the VASP calculation in {DOS_DIR}: "
        "first show me the structure info, then calculate the d-band center of Fe.",
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
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
git add Analysis_tool/analysis_tool_use.py
git commit -m "feat: add analysis_tool_use.py LLM agentic loop for VASP analysis"
```

---

## Task 5: CLAUDE.md update + final check

**Files:**
- Modify: `Tool_use/CLAUDE.md`

- [ ] **Step 1: Add Analysis_tool section to CLAUDE.md**

After the "Structure Tool_use (LLM Agent)" section, add:

```markdown
## Analysis_tool Package

A VASP post-processing toolkit with LLM tool-calling interface. Independent of Search_tool and Structure_tool — no MP API key required. Import directly:

```python
from Analysis_tool import VaspAnalysisDispatcher
```

### Classes

| Class | File | Purpose |
|---|---|---|
| `DosAnalysis` | `Analysis.py` | Projected DOS + d-band descriptors from DOSCAR |
| `RelaxAnalysis` | `Analysis.py` | Relaxation convergence from OUTCAR/OSZICAR (single-pass fast parser) |
| `StructureAnalysis` | `Analysis.py` | Structure summary from POSCAR/CONTCAR |
| `CohpAnalysis` | `Analysis.py` | Chemical bonding (COHP/ICOHP) from LOBSTER output |
| `VaspAnalysisDispatcher` | `Analysis.py` | Registry-based dispatcher; single entry point for all analyzers |

`parse.py` provides fast numpy-based parsers: `FastCohpcar` (10-20× faster than pymatgen) and `DoscarParser` (lazy evaluation, gzip support).

### Analysis Tool_use (LLM Agent)

Six tools exposed as OpenAI function-calling tools. All accept `work_dir` (path to VASP calculation directory). Raw numeric arrays are stripped before returning to LLM.

| Tool | Operation | Key args |
|---|---|---|
| `vasp_dos` | DOS + d-band descriptors | `work_dir`, `elements`, `orbitals`, `erange` |
| `vasp_relax` | Relaxation convergence | `work_dir`, `get_site_mag` |
| `vasp_structure_info` | Structure summary | `work_dir` |
| `vasp_cohp_summary` | ICOHP bond table (top N) | `work_dir`, `n_top_bonds`, `filter_type`, `filter_value` |
| `vasp_cohp_curves` | COHP curve summary | `work_dir`, `bond_labels`, `erange`, `include_orbitals` |
| `vasp_cohp_export` | Export COHP to CSV/JSON | `work_dir`, `bond_labels`, `export_format`, `save_dir` |

Run from `Tool_use/`:
```powershell
python -m Analysis_tool.analysis_tool_use
```

LLM provider and API key: set `LLM_API_KEY` in `Search_tool/.env`. Change `llm_provider=` in `main()`.
```

- [ ] **Step 2: Run full test suite**

```
pytest Analysis_tool/tests/ -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document Analysis_tool package and LLM tool use in CLAUDE.md"
```

---

## Self-Review

**Spec coverage:**
- DOS analysis with d-band descriptors → `vasp_dos` tool + `DosArgs` ✓
- Relaxation convergence → `vasp_relax` tool + `RelaxArgs` ✓
- Structure info → `vasp_structure_info` tool + `StructureInfoArgs` ✓
- COHP summary (ICOHP table) → `vasp_cohp_summary` + `CohpSummaryArgs` ✓
- COHP curves → `vasp_cohp_curves` + `CohpCurvesArgs` ✓
- COHP export to file → `vasp_cohp_export` + `CohpExportArgs` ✓
- Token efficiency (strip arrays) → `_strip_dos_arrays`, `_strip_cohp_arrays`, vasp_text removal ✓
- LLM agentic loop → `analysis_tool_use.py` with DeepSeek `reasoning_content` fix ✓
- Windows UTF-8 + direct script execution → `__main__` block matches `structure_tool_use.py` ✓

**Placeholder scan:** No TBD/TODO/placeholder patterns. All code blocks are complete and runnable.

**Type consistency:**
- `CohpSummaryArgs.filter_value: Optional[List[str]]` — executor converts to `List[int]` when `filter_type == "index"` ✓
- `_TOOL_DISPATCH` method names match method definitions in executor ✓
- `get_analysis_tool_schema` matches import in executor `tools` property ✓
