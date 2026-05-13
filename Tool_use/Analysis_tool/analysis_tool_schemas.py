# ══════════════════════════════════════════════════════════════
# analysis_tool_schemas.py
# Pydantic models → OpenAI function-calling schema for 7 VASP analysis tools
#
# Public API:
#   get_analysis_tool_schema(lang="en") -> list[dict]
#   DetectArgs / DosArgs / RelaxArgs / StructureInfoArgs /
#   CohpSummaryArgs / CohpCurvesArgs / CohpExportArgs
# ══════════════════════════════════════════════════════════════
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════
# §1  Pydantic argument models (7 tools)
# ══════════════════════════════════════════════

class DetectArgs(BaseModel):
    model_config = {"extra": "ignore"}

    work_dir: str = Field(
        description=(
            "Path to the VASP calculation directory to inspect. "
            "The tool scans for characteristic files and returns the detected "
            "calculation type(s) and recommended follow-up tools."
        )
    )


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
        name="vasp_detect",
        description_en=(
            "Scan a VASP calculation directory and automatically detect which type(s) "
            "of calculation are present. "
            "Recognised types: relax (geometry optimisation), dos (density of states), "
            "cohp (LOBSTER bonding analysis), neb (nudged elastic band transition state), "
            "dimer (dimer method transition state). "
            "Returns the detected types, key evidence files, and a list of recommended "
            "follow-up tools to use. "
            "Always call this first when the user does not specify the calculation type."
        ),
        description_cn=(
            "扫描 VASP 计算目录并自动识别其中包含哪种类型的计算。"
            "可识别类型：relax（几何优化）、dos（态密度）、"
            "cohp（LOBSTER 成键分析）、neb（微动弹性带过渡态）、"
            "dimer（二聚体方法过渡态）。"
            "返回识别到的计算类型、关键证据文件和推荐的后续工具列表。"
            "当用户未指定计算类型时，始终优先调用此工具。"
        ),
        args_class=DetectArgs,
    ),
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
    Generate the OpenAI function-calling tool schema list for the 7 VASP analysis tools.

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
