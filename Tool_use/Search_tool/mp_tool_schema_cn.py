# ══════════════════════════════════════════════════════════════
# mp_tool_schema_cn.py
# MP Tool Schema — 中文版（便于开发调试 / 中文用户文档）
# 生产环境建议使用 mp_tool_schema_en.py 以节省 token。
# ══════════════════════════════════════════════════════════════

from typing import Dict, List

MP_TOOL_SCHEMA_CN: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "mp_search",
            "description": (
                "从 Materials Project 数据库检索材料结构信息。\n"
                "支持四种输入格式（自动识别）：\n"
                "  - material_id：'mp-126'\n"
                "  - 化学式：'Fe2O3'、'LiFePO4'\n"
                "  - 化学体系：'Fe-O'、'Li-Fe-O'（连字符分隔）\n"
                "  - 元素列表：'Fe, O'（逗号分隔）\n"
                "返回材料的晶格参数、空间群、晶系等摘要信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容，如 'Fe2O3'、'Fe-O'、'mp-126'。",
                    },
                    "only_stable": {
                        "type": "boolean",
                        "description": "是否只返回稳定结构（energy_above_hull=0），默认 true。",
                        "default": True,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最多返回数量，默认 5，最大 20。",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mp_fetch",
            "description": (
                "根据 material_id 获取单个材料的完整结构信息。\n"
                "返回晶格参数、原子坐标、空间群、体积、组成等详细数据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "材料 ID，格式 'mp-{数字}'，如 'mp-126'。",
                        "pattern": "^mp-\\d+$",
                    },
                },
                "required": ["material_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mp_download",
            "description": (
                "下载指定材料的结构文件到本地磁盘。\n"
                "每次调用保存单一格式，返回保存路径而非文件内容。\n"
                "需要多种格式时请多次调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "材料 ID，格式 'mp-{数字}'，如 'mp-126'。",
                        "pattern": "^mp-\\d+$",
                    },
                    "fmt": {
                        "type": "string",
                        "description": "文件格式：'cif' / 'poscar' / 'xyz'，默认 'cif'。",
                        "enum": ["cif", "poscar", "xyz"],
                        "default": "cif",
                    },
                    "save_dir": {
                        "type": "string",
                        "description": "保存目录，默认 './structures'。",
                        "default": "./structures",
                    },
                },
                "required": ["material_id"],
            },
        },
    },
]