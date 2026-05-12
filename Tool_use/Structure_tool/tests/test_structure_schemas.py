import pytest
from pydantic import ValidationError


def test_load_args_requires_file_path():
    from Structure_tool.structure_tool_schemas import LoadArgs
    with pytest.raises(ValidationError):
        LoadArgs()


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
