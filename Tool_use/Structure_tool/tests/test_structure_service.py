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

    def test_missing_file_returns_error(self):
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
        assert abs(result["structure"]["c"] - 3.615) < 0.01
