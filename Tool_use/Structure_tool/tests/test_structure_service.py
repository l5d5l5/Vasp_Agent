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
        assert result["structures"][0]["nsites"] == 2

    def test_saves_files(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pathlib import Path
        path = _make_bcc_fe(tmp_path)
        result = StructureService().vacancy(path, "Fe", num_vacancies=1,
                                            num_structs=1, save_dir=str(tmp_path))
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
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        result = StructureService().slab(
            str(path), miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_slab"
        )
        assert result["success"] is True
        assert result["structure"]["cell_type"] == "slab"

    def test_slab_c_is_large(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        result = StructureService().slab(
            str(path), miller_indices="111", target_layers=4,
            vacuum_thickness=15.0, save_dir=str(tmp_path)
        )
        assert result["structure"]["c"] > 15.0

    def test_slab_saves_file(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from Structure_tool.structure_service import StructureService
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        from pathlib import Path
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        result = StructureService().slab(
            str(path), miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_111"
        )
        assert result["success"] is True
        assert Path(result["saved_files"][0]).exists()

    def test_supercell_2x2_expands_slab(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        result_1x1 = StructureService().slab(
            str(path), miller_indices="111", target_layers=4,
            save_dir=str(tmp_path), filename="POSCAR_1x1"
        )
        result_2x2 = StructureService().slab(
            str(path), miller_indices="111", target_layers=4,
            supercell_matrix="2x2", save_dir=str(tmp_path), filename="POSCAR_2x2"
        )
        assert result_2x2["structure"]["nsites"] == result_1x1["structure"]["nsites"] * 4
