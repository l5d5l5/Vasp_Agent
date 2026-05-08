# ══════════════════════════════════════════════════════════════
# mp_tool_schema_cn.py
# MPQueryService 工具调用 Schema（中文版）
# 对应 mp_tool_schema_en.py 最新版本
# 5 个工具：mp_search_formula / mp_search_elements /
#           mp_search_criteria / mp_fetch / mp_download
# ══════════════════════════════════════════════════════════════

MP_TOOL_SCHEMA_CN: list = [

    # ── 工具 1：按化学式搜索 ────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_formula",
            "description": (
                "通过化学式在 Materials Project 数据库中搜索材料（如 'Fe2O3'、'LiFePO4'）。"
                "返回匹配结构的排序列表，包含关键属性："
                "空间群、晶格参数、带隙、形成能、"
                "凸包以上能量、热力学稳定性、磁性等。"
                "当用户指定了确切或化简化学式时使用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "formula": {
                        "type": "string",
                        "description": (
                            "要搜索的化学式。接受化简式（如 'Fe2O3'）"
                            "或 JSON 数组字符串形式的列表"
                            "（如 '[\"Fe2O3\",\"FeO\"]'）。"
                        ),
                    },
                    "only_stable": {
                        "type": "boolean",
                        "description": (
                            "若为 true，则只返回热力学稳定相"
                            "（energy_above_hull = 0）。默认值：false。"
                        ),
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果的最大数量（1–20）。默认值：5。",
                        "default": 5,
                    },
                },
                "required": ["formula"],
            },
        },
    },

    # ── 工具 2：按元素组合搜索 ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_elements",
            "description": (
                "在 Materials Project 中搜索包含指定元素集合的结构。"
                "适用于用户询问'查找所有 Fe-O 化合物'或"
                "'钛的二元氧化物'等场景。"
                "可选择按不同元素数量和热力学稳定性进行过滤。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "必须全部存在的元素符号列表"
                            "（如 ['Fe', 'O']）。不区分大小写。"
                        ),
                    },
                    "num_elements": {
                        "type": "integer",
                        "description": (
                            "化学式中不同元素的确切数量。"
                            "例如：2 表示二元化合物。省略则不限制。"
                        ),
                    },
                    "only_stable": {
                        "type": "boolean",
                        "description": "仅返回稳定相。默认值：false。",
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果的最大数量（1–20）。默认值：5。",
                        "default": 5,
                    },
                },
                "required": ["elements"],
            },
        },
    },

    # ── 工具 3：多条件高级搜索 ──────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_criteria",
            "description": (
                "使用多个同时生效的过滤条件在 Materials Project 中进行高级搜索。"
                "适用于复杂查询，例如："
                "'含 Fe 和 O、带隙 1–3 eV 的磁性绝缘体'、"
                "'稳定的立方钙钛矿'、"
                "'高密度二元氧化物'等。"
                "所有参数均为可选，仅提供所需的条件即可。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "必须全部存在的元素（如 ['Fe','O']）。",
                    },
                    "exclude_elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "必须不存在的元素。",
                    },
                    "chemsys": {
                        "type": "string",
                        "description": (
                            "化学体系字符串，如 'Fe-O'（仅含 Fe 和 O，不含其他元素）。"
                            "与 'elements' 参数互斥。"
                        ),
                    },
                    "formula": {
                        "type": "string",
                        "description": "精确的化简化学式过滤条件。",
                    },
                    "num_elements": {
                        "type": "integer",
                        "description": "不同元素的确切数量。",
                    },
                    "band_gap_min": {
                        "type": "number",
                        "description": "最小带隙（eV，含端点）。",
                    },
                    "band_gap_max": {
                        "type": "number",
                        "description": "最大带隙（eV，含端点）。",
                    },
                    "energy_above_hull_max": {
                        "type": "number",
                        "description": (
                            "凸包以上能量的最大值（eV/atom）。"
                            "设为 0 可仅获取稳定相。"
                        ),
                    },
                    "formation_energy_min": {
                        "type": "number",
                        "description": "每原子形成能的最小值（eV/atom）。",
                    },
                    "formation_energy_max": {
                        "type": "number",
                        "description": "每原子形成能的最大值（eV/atom）。",
                    },
                    "density_min": {
                        "type": "number",
                        "description": "最小密度（g/cm³）。",
                    },
                    "density_max": {
                        "type": "number",
                        "description": "最大密度（g/cm³）。",
                    },
                    "crystal_system": {
                        "type": "string",
                        "description": (
                            "晶系过滤条件，可选值：cubic（立方）、tetragonal（四方）、"
                            "orthorhombic（正交）、hexagonal（六方）、"
                            "trigonal（三方）、monoclinic（单斜）、triclinic（三斜）。"
                        ),
                        "enum": [
                            "cubic", "tetragonal", "orthorhombic",
                            "hexagonal", "trigonal", "monoclinic", "triclinic",
                        ],
                    },
                    "spacegroup_symbol": {
                        "type": "string",
                        "description": "Hermann-Mauguin 空间群符号，如 'Fm-3m'。",
                    },
                    "is_stable": {
                        "type": "boolean",
                        "description": "按热力学稳定性标志过滤。",
                    },
                    "is_metal": {
                        "type": "boolean",
                        "description": "true 表示金属，false 表示绝缘体/半导体。",
                    },
                    "is_magnetic": {
                        "type": "boolean",
                        "description": "按磁有序性过滤。",
                    },
                    "theoretical": {
                        "type": "boolean",
                        "description": (
                            "true 表示仅包含理论预测结构；"
                            "false 表示仅包含实验观测结构。"
                        ),
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果的最大数量（1–20）。默认值：5。",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },

    # ── 工具 4：按 material_id 精确获取 ────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_fetch",
            "description": (
                "通过 Materials Project ID（如 'mp-19770'、'mp-126'）"
                "精确获取一个或多个材料的详细信息。"
                "返回完整属性集，包括晶格参数（a、b、c、α、β、γ）、"
                "晶胞体积、带隙、形成能、磁性属性和结构统计信息。"
                "当用户已知材料 ID 时使用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "一个或多个 Materials Project ID"
                            "（如 ['mp-19770'] 或 ['mp-126', 'mp-2']）。"
                            "ID 不区分大小写。"
                        ),
                    },
                },
                "required": ["material_ids"],
            },
        },
    },

    # ── 工具 5：下载结构文件 ────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_download",
            "description": (
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
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": (
                            "要下载的结构对应的 Materials Project ID"
                            "（如 'mp-19770'）。不区分大小写。"
                        ),
                    },
                    "fmt": {
                        "type": "string",
                        "description": (
                            "输出文件格式：\n"
                            "  'cif'    → <文件名>.cif         （默认，适用于 VESTA/ICSD）\n"
                            "  'poscar' → POSCAR_<文件名>      （适用于 VASP/DFT 计算）\n"
                            "  'xyz'    → <文件名>.xyz         （适用于 OVITO/ASE/Avogadro）"
                        ),
                        "enum":    ["cif", "poscar", "xyz"],
                        "default": "cif",
                    },
                    "save_dir": {
                        "type": "string",
                        "description": (
                            "文件保存的目录路径。"
                            "若目录不存在将自动创建。"
                            "支持相对路径（如 './structures'）和"
                            "绝对路径（如 'D:/vasp/inputs'）。"
                            "默认值：'./structures'。"
                        ),
                        "default": "./structures",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "自定义基础文件名（不含扩展名）。"
                            "若省略，默认使用 '<material_id>_<化学式>'"
                            "（如 'mp-19770_Fe2O3'）。"
                            "在同一目录下保存多个同质异构体时尤为有用。"
                        ),
                    },
                },
                "required": ["material_id"],
            },
        },
    },
]