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
    """Executor exposes a list of 7 OpenAI-format tool dicts."""
    tools = executor.tools
    assert isinstance(tools, list)
    assert len(tools) == 7
    names = {t["function"]["name"] for t in tools}
    assert names == {
        "vasp_detect",
        "vasp_dos",
        "vasp_relax",
        "vasp_structure_info",
        "vasp_cohp_summary",
        "vasp_cohp_curves",
        "vasp_cohp_export",
    }


@pytest.mark.asyncio
async def test_vasp_detect_dos_dir(executor):
    """Detect correctly identifies DOS + RELAX in the dos test directory."""
    result = await executor.execute("vasp_detect", {"work_dir": DOS_DIR})
    data = json.loads(result)
    assert data.get("success") is True
    detected = data["data"]["detected"]
    # dos/ has DOSCAR — should be labelled dos only, NOT relax
    # (DOS calcs produce OUTCAR/OSZICAR too, but that doesn't make them relax)
    assert "dos" in detected
    assert "relax" not in detected
    # NEB and DIMER should NOT appear
    assert "neb" not in detected
    assert "dimer" not in detected
    # recommended tools should include vasp_dos
    assert "vasp_dos" in data["data"]["recommended_tools"]


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
            "elements": ["Pd"],
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
