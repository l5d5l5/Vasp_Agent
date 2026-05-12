# ══════════════════════════════════════════════════════════════
# structure_tool_schemas.py
# Pydantic models → OpenAI function-calling schema for 6 structure tools
#
# Public API:
#   get_structure_tool_schema(lang="en") -> list[dict]
#   LoadArgs / SupercellArgs / VacancyArgs / SlabArgs / AdsorptionArgs / ParticleArgs
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# §1  Pydantic argument models (6 tools)
# ══════════════════════════════════════════════

class LoadArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description=(
            "Path to the input structure file. Accepts CIF, POSCAR/CONTCAR, "
            "XYZ, or any format supported by pymatgen's Structure.from_file(). "
            "Can be relative (e.g. './POSCAR') or absolute."
        )
    )


class SupercellArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description="Path to the input structure file (CIF, POSCAR, XYZ, etc.)."
    )
    supercell_matrix: str = Field(
        description=(
            "Supercell expansion expressed as 'AxBxC' (e.g. '2x2x1' doubles "
            "a and b, keeps c). Each integer scales the corresponding lattice vector."
        )
    )
    save_dir: str = Field(
        "./structures",
        description=(
            "Directory where the supercell structure file will be saved. "
            "Created automatically if it does not exist. Default: './structures'."
        ),
    )
    filename: Optional[str] = Field(
        None,
        description=(
            "Output filename (without extension). If omitted, a name is "
            "auto-generated from the input filename and supercell matrix."
        ),
    )


class VacancyArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description="Path to the input structure file (CIF, POSCAR, XYZ, etc.)."
    )
    element: str = Field(
        description=(
            "Chemical symbol of the atom to remove to create the vacancy "
            "(e.g. 'Fe', 'O'). Must be present in the structure."
        )
    )
    dopant: Optional[str] = Field(
        None,
        description=(
            "If provided, the vacancy site is filled with this element symbol, "
            "creating a substitutional dopant instead of a bare vacancy."
        ),
    )
    num_vacancies: int = Field(
        1,
        description="Number of vacancy sites to create per structure. Default: 1.",
    )
    num_structs: int = Field(
        1,
        description=(
            "Number of symmetry-inequivalent structures to generate. "
            "Default: 1 (return the lowest-index inequivalent defect site)."
        ),
    )
    top_layers: Optional[int] = Field(
        None,
        description=(
            "If set, restrict vacancy creation to atoms within the top N "
            "atomic layers (useful for slab models)."
        ),
    )
    random_seed: Optional[int] = Field(
        None,
        description="Random seed for reproducible site selection. Default: None.",
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where vacancy structure files will be saved. Default: './structures'.",
    )
    filename_prefix: str = Field(
        "POSCAR_vac",
        description=(
            "Prefix for output filenames. Files are named "
            "'<prefix>_<index>' (no extension, VASP convention). Default: 'POSCAR_vac'."
        ),
    )


class SlabArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description="Path to the bulk structure file (CIF, POSCAR, XYZ, etc.)."
    )
    miller_indices: str = Field(
        description=(
            "Miller indices of the surface as a string without spaces or separators, "
            "e.g. '111' for (1,1,1), '110' for (1,1,0), '210' for (2,1,0)."
        )
    )
    target_layers: int = Field(
        description="Target number of atomic layers in the slab (excluding vacuum)."
    )
    vacuum_thickness: float = Field(
        15.0,
        description="Vacuum region thickness in Angstroms added above the slab. Default: 15.0 Å.",
    )
    supercell_matrix: Optional[str] = Field(
        None,
        description=(
            "Optional in-plane supercell expansion as 'AxB' (e.g. '2x2'). "
            "Applied after slab generation."
        ),
    )
    fix_bottom_layers: int = Field(
        0,
        description=(
            "Number of bottom atomic layers to fix (selective dynamics = F F F). "
            "Default: 0 (no fixed layers)."
        ),
    )
    fix_top_layers: int = Field(
        0,
        description=(
            "Number of top atomic layers to fix (selective dynamics = F F F). "
            "Default: 0."
        ),
    )
    termination_index: int = Field(
        0,
        description=(
            "Index into the list of symmetry-distinct terminations for this "
            "Miller surface. 0 = first (default) termination."
        ),
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where the slab POSCAR will be saved. Default: './structures'.",
    )
    filename: str = Field(
        "POSCAR",
        description="Output filename. Default: 'POSCAR' (VASP convention, no extension).",
    )


class AdsorptionArgs(BaseModel):
    model_config = {"extra": "ignore"}

    file_path: str = Field(
        description=(
            "Path to the slab structure file (CIF, POSCAR, XYZ). "
            "Must be a surface slab (periodic in x/y, vacuum in z)."
        )
    )
    mode: Literal["analyze", "generate"] = Field(
        description=(
            "Operation mode:\n"
            "  'analyze'  — identify and report available adsorption sites "
            "(hollow, bridge, top) without placing any adsorbate.\n"
            "  'generate' — place the molecule specified by molecule_formula "
            "at one or more adsorption sites and write output POSCARs."
        )
    )
    molecule_formula: Optional[str] = Field(
        None,
        description=(
            "Chemical formula of the adsorbate molecule (e.g. 'CO', 'OH', 'H2O'). "
            "Required when mode='generate'; ignored in 'analyze' mode."
        ),
    )
    positions: Optional[List[str]] = Field(
        None,
        description=(
            "List of adsorption site types to populate, e.g. ['hollow', 'bridge', 'top']. "
            "If omitted, all symmetry-inequivalent sites are used."
        ),
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where adsorption structure files will be saved. Default: './structures'.",
    )


class ParticleArgs(BaseModel):
    model_config = {"extra": "ignore"}

    element: str = Field(
        description=(
            "Chemical symbol of the element for the nanoparticle "
            "(e.g. 'Pt', 'Au', 'Fe'). Must be a monatomic FCC/BCC/HCP metal."
        )
    )
    mode: Literal[
        "wulff", "sphere", "octahedron", "decahedron",
        "icosahedron", "fcc_cube", "rod"
    ] = Field(
        description=(
            "Nanoparticle shape:\n"
            "  'wulff'       — Wulff construction from surface energies (requires surface_energies + particle_size)\n"
            "  'sphere'      — Spherical cluster (requires particle_size)\n"
            "  'octahedron'  — Regular octahedron (requires layers)\n"
            "  'decahedron'  — Marks decahedron (requires p, q, r)\n"
            "  'icosahedron' — Icosahedral cluster (requires n_shells)\n"
            "  'fcc_cube'    — Cubic FCC cluster (requires layers)\n"
            "  'rod'         — Nanorod along [001] (requires rod_radius + rod_length)"
        )
    )
    lattice_constant: Optional[float] = Field(
        None,
        description=(
            "Lattice constant in Angstroms. If omitted, the experimental "
            "value for the element is used automatically."
        ),
    )
    lattice_type: Optional[str] = Field(
        None,
        description=(
            "Crystal structure type ('fcc', 'bcc', 'hcp'). "
            "Auto-detected from the element if omitted."
        ),
    )
    surface_energies: Optional[Dict[str, float]] = Field(
        None,
        description=(
            "Surface energy mapping for Wulff construction, keyed by Miller index string. "
            "Example: {'111': 0.05, '100': 0.07} (units: eV/Å²). "
            "Required for mode='wulff'."
        ),
    )
    particle_size: Optional[float] = Field(
        None,
        description=(
            "Target particle diameter in Angstroms. "
            "Used by modes: 'wulff', 'sphere'."
        ),
    )
    layers: Optional[int] = Field(
        None,
        description=(
            "Number of layers (shells) for polyhedral shapes. "
            "Used by modes: 'octahedron', 'fcc_cube'."
        ),
    )
    surfaces: Optional[List[List[int]]] = Field(
        None,
        description=(
            "List of surface Miller index vectors, e.g. [[1,1,1],[1,0,0]]. "
            "Used when specifying custom facets for Wulff or other modes."
        ),
    )
    p: Optional[int] = Field(
        None,
        description="Marks decahedron parameter p (number of atoms on edge). Used for mode='decahedron'.",
    )
    q: Optional[int] = Field(
        None,
        description="Marks decahedron parameter q (notch depth). Used for mode='decahedron'.",
    )
    r: Optional[int] = Field(
        None,
        description="Marks decahedron parameter r (re-entrant). Used for mode='decahedron'.",
    )
    n_shells: Optional[int] = Field(
        None,
        description="Number of shells for icosahedral cluster. Used for mode='icosahedron'.",
    )
    rod_radius: Optional[float] = Field(
        None,
        description="Nanorod cross-section radius in Angstroms. Used for mode='rod'.",
    )
    rod_length: Optional[float] = Field(
        None,
        description="Nanorod length in Angstroms along [001]. Used for mode='rod'.",
    )
    vacuum: float = Field(
        15.0,
        description="Vacuum padding in Angstroms added around the nanoparticle on all sides. Default: 15.0 Å.",
    )
    save_dir: str = Field(
        "./structures",
        description="Directory where the nanoparticle POSCAR will be saved. Default: './structures'.",
    )
    filename: str = Field(
        "POSCAR",
        description="Output filename. Default: 'POSCAR'.",
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
        name="struct_load",
        description_en=(
            "Load a crystal structure file from disk and return its key properties: "
            "formula, space group, lattice parameters (a, b, c, α, β, γ), volume, "
            "number of sites, and element list. "
            "Accepts CIF, POSCAR/CONTCAR, XYZ, and other pymatgen-supported formats. "
            "Use this as the first step to inspect a structure before further manipulation."
        ),
        description_cn=(
            "从磁盘加载晶体结构文件并返回关键属性："
            "化学式、空间群、晶格参数（a, b, c, α, β, γ）、体积、"
            "位点数量和元素列表。"
            "支持 CIF、POSCAR/CONTCAR、XYZ 及其他 pymatgen 支持的格式。"
            "在进行进一步操作前，用此工具检查结构。"
        ),
        args_class=LoadArgs,
    ),
    ToolSpec(
        name="struct_supercell",
        description_en=(
            "Build a supercell from a bulk structure by repeating the unit cell "
            "along the a, b, c directions. "
            "Specify the expansion as 'AxBxC' (e.g. '2x2x1' doubles a and b, keeps c). "
            "The output is saved as a POSCAR file. "
            "Use this to prepare large simulation cells for MD or defect calculations."
        ),
        description_cn=(
            "通过沿 a、b、c 方向重复晶胞来构建超胞。"
            "以 'AxBxC' 格式指定扩展倍数（例如 '2x2x1' 表示 a、b 方向各扩大 2 倍，c 方向不变）。"
            "输出保存为 POSCAR 文件。"
            "用于为分子动力学或缺陷计算准备大型模拟晶胞。"
        ),
        args_class=SupercellArgs,
    ),
    ToolSpec(
        name="struct_vacancy",
        description_en=(
            "Create vacancy or substitutional dopant defect structures from a bulk or slab model. "
            "Removes one or more atoms of the specified element; optionally replaces them with a dopant. "
            "Can generate multiple symmetry-inequivalent defect configurations. "
            "Output files follow the VASP POSCAR naming convention."
        ),
        description_cn=(
            "在体相或表面模型中创建空位或替代掺杂缺陷结构。"
            "移除指定元素的一个或多个原子；可选择用掺杂元素替换。"
            "可生成多个对称性不等价的缺陷构型。"
            "输出文件遵循 VASP POSCAR 命名规范。"
        ),
        args_class=VacancyArgs,
    ),
    ToolSpec(
        name="struct_slab",
        description_en=(
            "Generate a surface slab model from a bulk crystal for a given set of Miller indices. "
            "Controls slab thickness (by layer count), vacuum region, optional in-plane supercell, "
            "and selective dynamics constraints on bottom/top layers. "
            "Supports multiple terminations for polar or asymmetric surfaces. "
            "Output is saved as a POSCAR file."
        ),
        description_cn=(
            "从体相晶体按指定密勒指数生成表面板层模型。"
            "可控制板层厚度（按层数）、真空区域、可选的面内超胞扩展，"
            "以及底部/顶部层的选择性动力学约束。"
            "支持极性或非对称表面的多种终止类型。"
            "输出保存为 POSCAR 文件。"
        ),
        args_class=SlabArgs,
    ),
    ToolSpec(
        name="struct_adsorption",
        description_en=(
            "Analyze or generate adsorption configurations on a surface slab. "
            "In 'analyze' mode: identify and report symmetry-inequivalent adsorption sites "
            "(hollow, bridge, top) without modifying the structure. "
            "In 'generate' mode: place the specified molecule at adsorption sites "
            "and save one POSCAR per configuration. "
            "Useful for catalysis and surface science calculations."
        ),
        description_cn=(
            "分析或生成表面板层上的吸附构型。"
            "'analyze' 模式：识别并报告对称性不等价的吸附位点（空心位、桥位、顶位），不修改结构。"
            "'generate' 模式：将指定分子放置于吸附位点，并为每个构型保存一个 POSCAR 文件。"
            "适用于催化和表面科学计算。"
        ),
        args_class=AdsorptionArgs,
    ),
    ToolSpec(
        name="struct_particle",
        description_en=(
            "Generate a nanoparticle structure in a vacuum box. "
            "Supports multiple shape modes: Wulff construction (thermodynamic shape from surface energies), "
            "sphere, octahedron, Marks decahedron, icosahedron, FCC cube, and nanorod. "
            "The output is a POSCAR file with the nanoparticle centered in a vacuum supercell. "
            "Use this to prepare nanoparticle models for DFT or force-field simulations."
        ),
        description_cn=(
            "在真空盒中生成纳米颗粒结构。"
            "支持多种形状模式：Wulff 构型（由表面能决定的热力学平衡形状）、"
            "球形、八面体、Marks 十面体、二十面体、FCC 立方体和纳米棒。"
            "输出为 POSCAR 文件，纳米颗粒居中于真空超胞中。"
            "用于为 DFT 或力场模拟准备纳米颗粒模型。"
        ),
        args_class=ParticleArgs,
    ),
]


# ══════════════════════════════════════════════
# §3  Schema conversion: Pydantic v2 → OpenAI compatible
# ══════════════════════════════════════════════

def _model_to_openai_schema(model_cls: type[BaseModel]) -> Dict[str, Any]:
    """
    Convert a Pydantic model class to an OpenAI function parameters dict.

    Returns a dict with keys: type, properties, required.
    Handles Pydantic v2 quirks: strips title fields, expands anyOf:[T, null]
    for Optional fields, and removes null defaults.
    """
    schema: Dict[str, Any] = dict(model_cls.model_json_schema())
    schema.pop("title", None)
    schema.pop("$defs", None)

    cleaned_props: Dict[str, Any] = {}
    for field_name, prop in schema.get("properties", {}).items():
        prop = dict(prop)
        prop.pop("title", None)

        # Expand anyOf:[T, null] (Pydantic v2 encoding of Optional[T])
        if "anyOf" in prop:
            non_null = [t for t in prop["anyOf"] if t != {"type": "null"}]
            if len(non_null) == 1:
                inner = dict(non_null[0])
                prop.pop("anyOf")
                prop.update(inner)

        # Drop null defaults (meaningless for OpenAI)
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
# §4  Public function: get_structure_tool_schema
# ══════════════════════════════════════════════

def get_structure_tool_schema(lang: str = "en") -> list[Dict[str, Any]]:
    """
    Generate the OpenAI function-calling tool schema list for the 6 structure tools.

    Parameters
    ----------
    lang : "en" | "cn"
        Language for tool-level descriptions. Default: "en".

    Returns
    -------
    list[dict]
        Ready to pass as tools=[...] to openai.chat.completions.create().

    Examples
    --------
    >>> schema = get_structure_tool_schema("en")
    >>> schema[0]["function"]["name"]
    'struct_load'
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
