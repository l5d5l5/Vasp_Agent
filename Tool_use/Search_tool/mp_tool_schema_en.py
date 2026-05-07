# ══════════════════════════════════════════════════════════════
# mp_tool_schema_en.py
# MP Tool Schema — English version (token-efficient)
# Use this in production to reduce LLM context token usage.
# ══════════════════════════════════════════════════════════════

from typing import Dict, List

MP_TOOL_SCHEMA_EN: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "mp_search",
            "description": (
                "Search Materials Project for crystal structure summaries.\n"
                "Auto-detects input format:\n"
                "  - material_id : 'mp-126'\n"
                "  - formula     : 'Fe2O3', 'LiFePO4'\n"
                "  - chemsys     : 'Fe-O', 'Li-Fe-O'\n"
                "  - elements    : 'Fe, O'\n"
                "Returns lattice params, space group, crystal system."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Formula, chemsys, element list, or material_id.",
                    }
                },
                "only_stable": {
                    "type": "boolean",
                    "description": "Return only stable phases (energy_above_hull=0). Default true.",
                    "default": True,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max entries to return. Default 5, max 20.",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
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
                "Fetch detailed structure info for a single material by ID.\n"
                "Returns full lattice, atomic sites, symmetry, volume, composition."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "MP material ID, e.g. 'mp-126'.",
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
                "Download a structure file for a material to local disk.\n"
                "Saves ONE format per call. Returns file path, NOT content.\n"
                "Call multiple times for multiple formats."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "MP material ID, e.g. 'mp-126'.",
                        "pattern": "^mp-\\d+$",
                    },
                    "fmt": {
                        "type": "string",
                        "description": "File format: 'cif' | 'poscar' | 'xyz'. Default 'cif'.",
                        "enum": ["cif", "poscar", "xyz"],
                        "default": "cif",
                    },
                    "save_dir": {
                        "type": "string",
                        "description": "Output directory. Default './structures'.",
                        "default": "./structures",
                    },
                },
                "required": ["material_id"],
            },
        },
    },
]