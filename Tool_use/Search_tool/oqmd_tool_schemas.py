# ══════════════════════════════════════════════════════════════
# oqmd_tool_schemas.py
# OQMD 工具 schema（Pydantic 模型 → OpenAI function-calling schema）
#
# 公开接口：
#   get_oqmd_tool_schema(lang="en") -> list[dict]
#   OQMD_TOOL_SCHEMA_EN / OQMD_TOOL_SCHEMA_CN
#   OQMDSearchFormulaArgs / OQMDSearchElementsArgs /
#   OQMDSearchCriteriaArgs / OQMDFetchArgs / OQMDDownloadArgs
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from mp_tool_schemas import _clean_schema_for_openai   # 复用清理逻辑


# ══════════════════════════════════════════════
# §1  Pydantic 参数模型（5 个 OQMD 工具）
# ══════════════════════════════════════════════

class OQMDSearchFormulaArgs(BaseModel):
    model_config = {"extra": "ignore"}

    composition: str = Field(
        description=(
            "Chemical formula to search in OQMD, e.g. 'Fe2O3' or 'Al2O3'. "
            "Use the reduced formula (no spaces)."
        )
    )
    only_stable: bool = Field(
        False,
        description=(
            "If true, restrict results to thermodynamically stable phases "
            "(stability ≤ 0 eV/atom, i.e. on or below the convex hull). "
            "Default: false."
        ),
    )
    max_results: int = Field(
        5,
        description="Maximum number of results to return (1–20). Default: 5.",
    )


class OQMDSearchElementsArgs(BaseModel):
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
            "Exact number of distinct element types (ntypes). "
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


class OQMDSearchCriteriaArgs(BaseModel):
    model_config = {"extra": "ignore"}

    elements: Optional[List[str]] = Field(
        None,
        description="Elements that must ALL be present (e.g. ['Fe', 'O']).",
    )
    composition: Optional[str] = Field(
        None,
        description="Exact reduced formula filter (e.g. 'Fe2O3').",
    )
    num_elements: Optional[int] = Field(
        None,
        description="Exact number of distinct element types.",
    )
    band_gap_min: Optional[float] = Field(
        None,
        description="Minimum band gap in eV (inclusive).",
    )
    band_gap_max: Optional[float] = Field(
        None,
        description=(
            "Maximum band gap in eV (inclusive). "
            "Set band_gap_min=0 and band_gap_max=0 to find metals."
        ),
    )
    stability_max: Optional[float] = Field(
        None,
        description=(
            "Maximum stability (energy above convex hull) in eV/atom. "
            "Set to 0 to restrict to thermodynamically stable phases."
        ),
    )
    formation_energy_min: Optional[float] = Field(
        None,
        description="Minimum formation energy per atom in eV/atom.",
    )
    formation_energy_max: Optional[float] = Field(
        None,
        description="Maximum formation energy per atom in eV/atom.",
    )
    prototype: Optional[str] = Field(
        None,
        description=(
            "Structure prototype name, e.g. 'Cu' for FCC, "
            "'NaCl' for rock salt, 'ZnS' for zinc blende."
        ),
    )
    spacegroup: Optional[str] = Field(
        None,
        description=(
            "Space group filter. Accepts symbol (e.g. 'Fm-3m') "
            "or international number (e.g. '225')."
        ),
    )
    natom_max: Optional[int] = Field(
        None,
        description="Maximum number of atoms per unit cell.",
    )
    max_results: int = Field(
        5,
        description="Maximum number of results to return (1–20). Default: 5.",
    )


class OQMDFetchArgs(BaseModel):
    model_config = {"extra": "ignore"}

    entry_ids: List[int] = Field(
        description=(
            "One or more OQMD entry IDs (integer), e.g. [4061139] or [4061139, 3682726]. "
            "Entry IDs can be found from oqmd_search_formula or oqmd_search_elements results."
        )
    )


class OQMDDownloadArgs(BaseModel):
    model_config = {"extra": "ignore"}

    entry_id: int = Field(
        description=(
            "OQMD entry ID of the structure to download, e.g. 4061139. "
            "Obtain from search results."
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
            "Created automatically if it does not exist. "
            "Default: './structures'."
        ),
    )
    filename: Optional[str] = Field(
        None,
        description=(
            "Custom base filename (without extension). "
            "If omitted, defaults to 'oqmd-<entry_id>_<formula>'."
        ),
    )


# ══════════════════════════════════════════════
# §2  ToolSpec 容器（工具名 + 双语描述 + 参数模型类）
# ══════════════════════════════════════════════

@dataclass
class OQMDToolSpec:
    name:           str
    description_en: str
    description_cn: str
    args_class:     type[BaseModel]


_OQMD_TOOL_SPECS: list[OQMDToolSpec] = [
    OQMDToolSpec(
        name="oqmd_search_formula",
        description_en=(
            "Search the OQMD (Open Quantum Materials Database) by chemical formula "
            "(e.g. 'Fe2O3', 'Al2O3'). "
            "Returns a ranked list of matching structures with key properties: "
            "space group, lattice parameters, band gap, formation energy, "
            "stability (convex hull distance), and structure prototype. "
            "Use this when the user specifies an exact or reduced formula."
        ),
        description_cn=(
            "通过化学式在 OQMD（开放量子材料数据库）中搜索材料（如 'Fe2O3'、'Al2O3'）。"
            "返回匹配结构的排序列表，包含关键属性："
            "空间群、晶格参数、带隙、形成能、"
            "热力学稳定性（凸包距离）和结构原型。"
            "当用户指定了确切或化简化学式时使用此工具。"
        ),
        args_class=OQMDSearchFormulaArgs,
    ),
    OQMDToolSpec(
        name="oqmd_search_elements",
        description_en=(
            "Search OQMD for structures containing a specific set of elements. "
            "Useful for queries like 'find all stable Fe-O binary compounds' or "
            "'ternary oxides containing Ti and Ba'. "
            "Can optionally filter by number of distinct elements and stability."
        ),
        description_cn=(
            "在 OQMD 中搜索包含指定元素集合的结构。"
            "适用于'查找所有稳定的 Fe-O 二元化合物'或"
            "'含 Ti 和 Ba 的三元氧化物'等查询。"
            "可选择按不同元素数量和热力学稳定性进行过滤。"
        ),
        args_class=OQMDSearchElementsArgs,
    ),
    OQMDToolSpec(
        name="oqmd_search_criteria",
        description_en=(
            "Advanced search in OQMD using multiple simultaneous filters. "
            "Use this for complex queries such as: "
            "'stable insulators containing Fe and O with band gap 1–3 eV', "
            "'FCC-prototype materials with formation energy below -1 eV/atom', "
            "'binary rock-salt structures'. "
            "All parameters are optional; provide only those needed."
        ),
        description_cn=(
            "使用多个同时生效的过滤条件在 OQMD 中进行高级搜索。"
            "适用于复杂查询，例如："
            "'含 Fe 和 O、带隙 1–3 eV 的稳定绝缘体'、"
            "'形成能低于 -1 eV/atom 的 FCC 原型材料'、"
            "'二元岩盐结构'等。"
            "所有参数均为可选，仅提供所需条件即可。"
        ),
        args_class=OQMDSearchCriteriaArgs,
    ),
    OQMDToolSpec(
        name="oqmd_fetch",
        description_en=(
            "Fetch detailed information for one or more OQMD entries "
            "by their integer entry ID (e.g. 4061139). "
            "Returns full property set including lattice parameters (a, b, c, α, β, γ), "
            "band gap, formation energy, stability, and structure prototype. "
            "Use this when the user already knows the OQMD entry ID, "
            "or to get full details after a search."
        ),
        description_cn=(
            "通过整数 entry_id（如 4061139）精确获取一个或多个 OQMD 条目的详细信息。"
            "返回完整属性集，包括晶格参数（a、b、c、α、β、γ）、"
            "带隙、形成能、热力学稳定性和结构原型。"
            "当用户已知 OQMD entry ID 时使用此工具，"
            "或在搜索后获取完整详细信息时使用。"
        ),
        args_class=OQMDFetchArgs,
    ),
    OQMDToolSpec(
        name="oqmd_download",
        description_en=(
            "Download and save the crystal structure of a specific OQMD entry "
            "to a local file on disk. "
            "Three output formats are supported:\n"
            "  • cif    — Standard CIF format (for VESTA, ICSD, Mercury). "
            "File saved as '<filename>.cif'.\n"
            "  • poscar — VASP POSCAR format for DFT calculations. "
            "File saved as 'POSCAR_<filename>' (no extension, VASP convention).\n"
            "  • xyz    — Cartesian XYZ format (for OVITO, ASE, Avogadro). "
            "File saved as '<filename>.xyz'.\n"
            "Filename defaults to 'oqmd-<entry_id>_<formula>' unless overridden. "
            "Returns the absolute path(s) of saved file(s) on success."
        ),
        description_cn=(
            "将指定 OQMD 条目的晶体结构下载并保存为本地文件。\n"
            "支持三种输出格式：\n"
            "  • cif    — 标准 CIF 格式（适用于 VESTA、ICSD、Mercury）。"
            "文件保存为 '<文件名>.cif'。\n"
            "  • poscar — VASP POSCAR 格式，用于 DFT 第一性原理计算。"
            "文件保存为 'POSCAR_<文件名>'（无扩展名，符合 VASP 惯例）。\n"
            "  • xyz    — 笛卡尔坐标 XYZ 格式（适用于 OVITO、ASE、Avogadro）。"
            "文件保存为 '<文件名>.xyz'。\n"
            "文件名默认为 'oqmd-<entry_id>_<化学式>'，可通过 filename 参数覆盖。"
            "成功时返回已保存文件的绝对路径列表。"
        ),
        args_class=OQMDDownloadArgs,
    ),
]


# ══════════════════════════════════════════════
# §3  公开函数：get_oqmd_tool_schema
# ══════════════════════════════════════════════

def get_oqmd_tool_schema(lang: str = "en") -> list[Dict[str, Any]]:
    """
    生成 OQMD 工具的 OpenAI function-calling 格式 schema 列表。

    Parameters
    ----------
    lang : "en" | "cn"
        工具级描述的语言，默认英文。

    Returns
    -------
    list[dict]
        可直接传给 openai.chat.completions.create(tools=...) 的列表。
    """
    result = []
    for spec in _OQMD_TOOL_SPECS:
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
# §4  向后兼容变量
# ══════════════════════════════════════════════

OQMD_TOOL_SCHEMA_EN: list = get_oqmd_tool_schema("en")
OQMD_TOOL_SCHEMA_CN: list = get_oqmd_tool_schema("cn")
