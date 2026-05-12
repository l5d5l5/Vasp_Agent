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


def _make_cu_slab_file(tmp_path):
    """Build a Cu(111) slab and save it to tmp_path/POSCAR_slab."""
    from pymatgen.core import Structure, Lattice
    from pymatgen.io.vasp import Poscar
    from Structure_tool.bulk_to_slab import BulkToSlabGenerator
    lat = Lattice.cubic(3.615)
    struct = Structure(lat, ["Cu"] * 4,
                       [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
    gen = BulkToSlabGenerator(struct, save_dir=str(tmp_path))
    gen.generate(miller_indices="111", target_layers=4, vacuum_thickness=15.0)
    slabs = gen.get_slabs()
    slab_path = tmp_path / "POSCAR_slab"
    with open(slab_path, "wt", encoding="utf-8") as f:
        f.write(Poscar(slabs[0]).get_str())
    return str(slab_path)


class TestAdsorption:
    def test_analyze_returns_site_counts(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab_file(tmp_path)
        result = StructureService().adsorption(path, mode="analyze",
                                               save_dir=str(tmp_path))
        assert result["success"] is True
        assert "site_counts" in result
        total = sum(result["site_counts"].values())
        assert total > 0

    def test_generate_creates_structures(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab_file(tmp_path)
        result = StructureService().adsorption(
            path, mode="generate", molecule_formula="CO",
            save_dir=str(tmp_path)
        )
        assert result["success"] is True
        assert result["num_generated"] > 0

    def test_generate_saves_files(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        from pathlib import Path
        path = _make_cu_slab_file(tmp_path)
        result = StructureService().adsorption(
            path, mode="generate", molecule_formula="CO",
            save_dir=str(tmp_path)
        )
        for saved in result["saved_files"]:
            assert Path(saved).exists()

    def test_generate_without_molecule_returns_error(self, tmp_path):
        from Structure_tool.structure_service import StructureService
        path = _make_cu_slab_file(tmp_path)
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


import asyncio
import json as _json


class TestStructureToolExecutor:
    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_execute_struct_load(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_load", {"file_path": str(path)}))
        result = _json.loads(raw)
        assert result["formula"] == "Cu4"
        assert result["nsites"] == 4

    def test_execute_struct_supercell(self, tmp_path):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        from pymatgen.core import Structure, Lattice
        from pymatgen.io.vasp import Poscar
        lat = Lattice.cubic(3.615)
        struct = Structure(lat, ["Cu"] * 4,
                           [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]])
        path = tmp_path / "POSCAR"
        Poscar(struct).write_file(str(path))
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_supercell", {
            "file_path": str(path),
            "supercell_matrix": "2x2x1",
            "save_dir": str(tmp_path),
            "filename": "POSCAR_221",
        }))
        result = _json.loads(raw)
        assert result["structure"]["nsites"] == 16

    def test_execute_unknown_tool_returns_error(self):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("nonexistent_tool", {}))
        result = _json.loads(raw)
        assert "error" in result

    def test_tools_property_returns_6_entries(self):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        assert len(executor.tools) == 6

    def test_execute_bad_args_returns_error_json(self):
        from Structure_tool.structure_tool_executor import StructureToolExecutor
        executor = StructureToolExecutor()
        raw = self._run(executor.execute("struct_load", {}))  # missing file_path
        result = _json.loads(raw)
        assert "error" in result
