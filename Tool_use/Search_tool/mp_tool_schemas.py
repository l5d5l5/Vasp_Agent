# ══════════════════════════════════════════════════════════════
# mp_tool_schemas.py
# 唯一的 schema 来源：Pydantic 模型 → OpenAI function-calling schema
#
# 公开接口：
#   get_tool_schema(lang="en") -> list[dict]
#   MP_TOOL_SCHEMA_EN            (向后兼容)
#   MP_TOOL_SCHEMA_CN            (向后兼容)
#   FormulaArgs / ElementsArgs / CriteriaArgs / FetchArgs / DownloadArgs
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# §1  Pydantic 参数模型（5 个工具）
# ══════════════════════════════════════════════

class FormulaArgs(BaseModel):
    model_config = {"extra": "ignore"}

    formula: str = Field(
        description=(
            "Chemical formula to search. Accepts reduced formula "
            "(e.g. 'Fe2O3') or a list encoded as JSON array string "
            "(e.g. '[\"Fe2O3\",\"FeO\"]')."
        )
    )
    only_stable: bool = Field(
        False,
        description=(
            "If true, restrict results to thermodynamically stable "
            "phases (energy_above_hull = 0). Default: false."
        ),
    )
    max_results: int = Field(
        5,
        description="Maximum number of results to return (1–20). Default: 5.",
    )


class ElementsArgs(BaseModel):
    model_config = {"extra": "ignore"}

    elements: List[str] = Field(
        description=(
            "List of element symbols that must ALL be present "
            "(e.g. ['Fe', 'O']). Case-insensitive."
        )
    )
    num_elements: Optional[int] = Field(
        None,
        description=(
            "Exact number of distinct elements in the formula. "
            "E.g. 2 for binary compounds. Omit to allow any."
        ),
    )
    only_stable: bool = Field(
        False,
        description="Restrict to stable phases only. Default: false.",
    )
    max_results: int = Field(
        5,
        description="Maximum number of results to return (1–20). Default: 5.",
    )


class CriteriaArgs(BaseModel):
    model_config = {"extra": "ignore"}

    elements: Optional[List[str]] = Field(
        None, description="Elements that must ALL be present (e.g. ['Fe','O'])."
    )
    exclude_elements: Optional[List[str]] = Field(
        None, description="Elements that must NOT be present."
    )
    chemsys: Optional[str] = Field(
        None,
        description=(
            "Chemical system string, e.g. 'Fe-O' (only Fe and O, no others). "
            "Mutually exclusive with 'elements'."
        ),
    )
    formula: Optional[str] = Field(
        None, description="Exact reduced formula filter."
    )
    num_elements: Optional[int] = Field(
        None, description="Exact number of distinct elements."
    )
    band_gap_min: Optional[float] = Field(
        None, description="Minimum band gap in eV (inclusive)."
    )
    band_gap_max: Optional[float] = Field(
        None, description="Maximum band gap in eV (inclusive)."
    )
    energy_above_hull_max: Optional[float] = Field(
        None,
        description=(
            "Maximum energy above convex hull in eV/atom. "
            "Set to 0 to get only stable phases."
        ),
    )
    formation_energy_min: Optional[float] = Field(
        None, description="Minimum formation energy per atom in eV/atom."
    )
    formation_energy_max: Optional[float] = Field(
        None, description="Maximum formation energy per atom in eV/atom."
    )
    density_min: Optional[float] = Field(
        None, description="Minimum density in g/cm³."
    )
    density_max: Optional[float] = Field(
        None, description="Maximum density in g/cm³."
    )
    crystal_system: Optional[
        Literal[
            "cubic", "tetragonal", "orthorhombic",
            "hexagonal", "trigonal", "monoclinic", "triclinic",
        ]
    ] = Field(
        None,
        description=(
            "Crystal system filter. One of: cubic, tetragonal, "
            "orthorhombic, hexagonal, trigonal, monoclinic, triclinic."
        ),
    )
    spacegroup_symbol: Optional[str] = Field(
        None, description="Hermann-Mauguin space group symbol, e.g. 'Fm-3m'."
    )
    is_stable: Optional[bool] = Field(
        None, description="Filter by thermodynamic stability flag."
    )
    is_metal: Optional[bool] = Field(
        None, description="True for metals, False for insulators/semiconductors."
    )
    is_magnetic: Optional[bool] = Field(
        None, description="Filter by magnetic ordering."
    )
    theoretical: Optional[bool] = Field(
        None,
        description=(
            "True to include only theoretical structures; "
            "False for experimental."
        ),
    )
    max_results: int = Field(
        5, description="Maximum number of results to return (1–20). Default: 5."
    )


class FetchArgs(BaseModel):
    model_config = {"extra": "ignore"}

    material_ids: List[str] = Field(
        description=(
            "One or more Materials Project IDs "
            "(e.g. ['mp-19770'] or ['mp-126', 'mp-2'])."
        )
    )


class DownloadArgs(BaseModel):
    model_config = {"extra": "ignore"}

    material_id: str = Field(
        description=(
            "Materials Project ID of the structure to download "
            "(e.g. 'mp-19770'). Case-insensitive."
        )
    )
    fmt: Literal["cif", "poscar", "xyz"] = Field(
        "cif",
        description=(
            "Output file format:\n"
            "  'cif'    → <filename>.cif    (default, for VESTA/ICSD)\n"
            "  'poscar' → POSCAR_<filename> (for VASP/DFT)\n"
            "  'xyz'    → <filename>.xyz    (for OVITO/ASE/Avogadro)"
        ),
    )
    save_dir: str = Field(
        "./structures",
        description=(
            "Directory path where the file will be saved. "
            "Will be created automatically if it does not exist. "
            "Accepts both relative (e.g. './structures') and "
            "absolute paths (e.g. 'D:/vasp/inputs'). "
            "Default: './structures'."
        ),
    )
    filename: Optional[str] = Field(
        None,
        description=(
            "Custom base filename (without extension). "
            "If omitted, defaults to '<material_id>_<formula>' "
            "(e.g. 'mp-19770_Fe2O3'). "
            "Useful when saving multiple polymorphs to the same directory."
        ),
    )


# ══════════════════════════════════════════════
# §2  ToolSpec 容器（工具名 + 双语描述 + 参数模型类）
# ══════════════════════════════════════════════

@dataclass
class ToolSpec:
    name:           str
    description_en: str
    description_cn: str
    args_class:     type[BaseModel]


_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="mp_search_formula",
        description_en=(
            "Search Materials Project by chemical formula (e.g. 'Fe2O3', 'LiFePO4'). "
            "Returns a ranked list of matching structures with key properties: "
            "space group, lattice parameters, band gap, formation energy, "
            "energy above hull, stability, magnetic properties, etc. "
            "Use this when the user specifies an exact or reduced formula."
        ),
        description_cn=(
            "通过化学式在 Materials Project 数据库中搜索材料（如 'Fe2O3'、'LiFePO4'）。"
            "返回匹配结构的排序列表，包含关键属性："
            "空间群、晶格参数、带隙、形成能、"
            "凸包以上能量、热力学稳定性、磁性等。"
            "当用户指定了确切或化简化学式时使用此工具。"
        ),
        args_class=FormulaArgs,
    ),
    ToolSpec(
        name="mp_search_elements",
        description_en=(
            "Search Materials Project for structures containing a specific set of elements. "
            "Useful when the user asks 'find all Fe-O compounds' or "
            "'binary oxides of titanium'. "
            "Can optionally filter by number of distinct elements and stability."
        ),
        description_cn=(
            "在 Materials Project 中搜索包含指定元素集合的结构。"
            "适用于用户询问'查找所有 Fe-O 化合物'或"
            "'钛的二元氧化物'等场景。"
            "可选择按不同元素数量和热力学稳定性进行过滤。"
        ),
        args_class=ElementsArgs,
    ),
    ToolSpec(
        name="mp_search_criteria",
        description_en=(
            "Advanced search on Materials Project using multiple simultaneous filters. "
            "Use this for complex queries such as: "
            "'magnetic insulators with band gap 1–3 eV containing Fe and O', "
            "'stable cubic perovskites', "
            "'high-density binary oxides'. "
            "All parameters are optional; provide only those needed."
        ),
        description_cn=(
            "使用多个同时生效的过滤条件在 Materials Project 中进行高级搜索。"
            "适用于复杂查询，例如："
            "'含 Fe 和 O、带隙 1–3 eV 的磁性绝缘体'、"
            "'稳定的立方钙钛矿'、"
            "'高密度二元氧化物'等。"
            "所有参数均为可选，仅提供所需的条件即可。"
        ),
        args_class=CriteriaArgs,
    ),
    ToolSpec(
        name="mp_fetch",
        description_en=(
            "Fetch detailed information for one or more specific materials "
            "by their Materials Project ID (e.g. 'mp-19770', 'mp-126'). "
            "Returns full property set including lattice parameters, "
            "band gap, formation energy, magnetic properties, "
            "and structure statistics. "
            "Use this when the user already knows the material ID."
        ),
        description_cn=(
            "通过 Materials Project ID（如 'mp-19770'、'mp-126'）"
            "精确获取一个或多个材料的详细信息。"
            "返回完整属性集，包括晶格参数（a、b、c、α、β、γ）、"
            "晶胞体积、带隙、形成能、磁性属性和结构统计信息。"
            "当用户已知材料 ID 时使用此工具。"
        ),
        args_class=FetchArgs,
    ),
    ToolSpec(
        name="mp_download",
        description_en=(
            "Download and save the crystal structure of a specific material "
            "to a local file on disk. "
            "Three output formats are supported:\n"
            "  • cif    — Standard CIF format, readable by VESTA, ICSD, "
            "Mercury, etc. File saved as '<filename>.cif'.\n"
            "  • poscar — VASP POSCAR format for DFT calculations. "
            "File saved as 'POSCAR_<filename>' (no extension, VASP convention).\n"
            "  • xyz    — Cartesian XYZ format, readable by OVITO, ASE, "
            "Avogadro, etc. File saved as '<filename>.xyz'.\n"
            "The filename is auto-generated as '<material_id>_<formula>' "
            "unless overridden by the 'filename' parameter. "
            "Returns the absolute path(s) of saved file(s) on success. "
            "Use mp_fetch first if you need to confirm the material exists."
        ),
        description_cn=(
            "将指定材料的晶体结构下载并保存为本地文件。\n"
            "支持三种输出格式：\n"
            "  • cif    — 标准 CIF 格式，可由 VESTA、ICSD、Mercury 等软件读取。"
            "文件保存为 '<文件名>.cif'。\n"
            "  • poscar — VASP POSCAR 格式，用于 DFT 第一性原理计算。"
            "文件保存为 'POSCAR_<文件名>'（无扩展名，符合 VASP 惯例）。\n"
            "  • xyz    — 笛卡尔坐标 XYZ 格式，可由 OVITO、ASE、Avogadro 等读取。"
            "文件保存为 '<文件名>.xyz'。\n"
            "文件名默认自动生成为 '<material_id>_<化学式>'，"
            "可通过 'filename' 参数自定义覆盖。"
            "成功时返回已保存文件的绝对路径列表。"
            "若需确认材料是否存在，建议先调用 mp_fetch。"
        ),
        args_class=DownloadArgs,
    ),
]


# ══════════════════════════════════════════════
# §3  Schema 清理：Pydantic v2 → OpenAI 兼容格式
# ══════════════════════════════════════════════

def _clean_schema_for_openai(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 Pydantic v2 生成的 JSON Schema 清理为 OpenAI function-calling 兼容格式。

    处理：
    - 去掉顶层 title（模型类名）和 $defs（嵌套模型引用，防御性）
    - 去掉字段级 title（字段名 Title Case）
    - 展开 anyOf:[T, null] → T（Optional[T]=None 的 v2 写法；DeepSeek/Qwen 不支持 anyOf）
    - 去掉 default: null（None 默认值对 OpenAI 无意义，保留 false/5/"cif" 等有效默认值）
    - 当所有字段可选时，Pydantic 不生成 required 键，补充 required: []
    """
    schema = dict(schema)
    schema.pop("title", None)
    schema.pop("$defs", None)

    if "properties" in schema:
        cleaned: Dict[str, Any] = {}
        for field_name, prop in schema["properties"].items():
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

            cleaned[field_name] = prop
        schema["properties"] = cleaned

    if "required" not in schema:
        schema["required"] = []

    return schema


# ══════════════════════════════════════════════
# §4  公开函数：get_tool_schema
# ══════════════════════════════════════════════

def get_tool_schema(lang: str = "en") -> list[Dict[str, Any]]:
    """
    生成 OpenAI function-calling 格式的工具 schema 列表。

    Parameters
    ----------
    lang : "en" | "cn"
        工具级描述的语言，默认英文。

    Returns
    -------
    list[dict]
        可直接传给 openai.chat.completions.create(tools=...) 的列表。

    Examples
    --------
    >>> schema = get_tool_schema("en")
    >>> schema[0]["function"]["name"]
    'mp_search_formula'
    """
    result = []
    for spec in _TOOL_SPECS:
        description = (
            spec.description_cn if lang == "cn" else spec.description_en
        )
        parameters = _clean_schema_for_openai(spec.args_class.model_json_schema())
        result.append({
            "type": "function",
            "function": {
                "name":        spec.name,
                "description": description,
                "parameters":  parameters,
            },
        })
    return result


# ══════════════════════════════════════════════
# §5  向后兼容变量
# ══════════════════════════════════════════════

MP_TOOL_SCHEMA_EN: list = get_tool_schema("en")
MP_TOOL_SCHEMA_CN: list = get_tool_schema("cn")
