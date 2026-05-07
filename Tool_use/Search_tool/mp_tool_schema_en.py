# ══════════════════════════════════════════════════════════════
# mp_tool_schema_en.py
# Tool Schema for MPQueryService (refactored)
# 5 tools: mp_search_formula / mp_search_elements /
#          mp_search_criteria / mp_fetch / mp_download
# ══════════════════════════════════════════════════════════════

MP_TOOL_SCHEMA_EN: list = [

    # ── Tool 1: Search by formula ──────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_formula",
            "description": (
                "Search Materials Project by chemical formula (e.g. 'Fe2O3', 'LiFePO4'). "
                "Returns a ranked list of matching structures with key properties: "
                "space group, lattice parameters, band gap, formation energy, "
                "energy above hull, stability, magnetic properties, etc. "
                "Use this when the user specifies an exact or reduced formula."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "formula": {
                        "type": "string",
                        "description": (
                            "Chemical formula to search. Accepts reduced formula "
                            "(e.g. 'Fe2O3') or a list encoded as JSON array string "
                            "(e.g. '[\"Fe2O3\",\"FeO\"]')."
                        ),
                    },
                    "only_stable": {
                        "type": "boolean",
                        "description": (
                            "If true, restrict results to thermodynamically stable "
                            "phases (energy_above_hull = 0). Default: false."
                        ),
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1–20). Default: 5.",
                        "default": 5,
                    },
                },
                "required": ["formula"],
            },
        },
    },

    # ── Tool 2: Search by elements ─────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_elements",
            "description": (
                "Search Materials Project for structures containing a specific set of elements. "
                "Useful when the user asks 'find all Fe-O compounds' or "
                "'binary oxides of titanium'. "
                "Can optionally filter by number of distinct elements and stability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of element symbols that must ALL be present "
                            "(e.g. ['Fe', 'O']). Case-insensitive."
                        ),
                    },
                    "num_elements": {
                        "type": "integer",
                        "description": (
                            "Exact number of distinct elements in the formula. "
                            "E.g. 2 for binary compounds. Omit to allow any."
                        ),
                    },
                    "only_stable": {
                        "type": "boolean",
                        "description": "Restrict to stable phases only. Default: false.",
                        "default": False,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1–20). Default: 5.",
                        "default": 5,
                    },
                },
                "required": ["elements"],
            },
        },
    },

    # ── Tool 3: Search by custom criteria ──────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_search_criteria",
            "description": (
                "Advanced search on Materials Project using multiple simultaneous filters. "
                "Use this for complex queries such as: "
                "'magnetic insulators with band gap 1–3 eV containing Fe and O', "
                "'stable cubic perovskites', "
                "'high-density binary oxides'. "
                "All parameters are optional; provide only those needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Elements that must ALL be present (e.g. ['Fe','O']).",
                    },
                    "exclude_elements": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Elements that must NOT be present.",
                    },
                    "chemsys": {
                        "type": "string",
                        "description": (
                            "Chemical system string, e.g. 'Fe-O' (only Fe and O, no others). "
                            "Mutually exclusive with 'elements'."
                        ),
                    },
                    "formula": {
                        "type": "string",
                        "description": "Exact reduced formula filter.",
                    },
                    "num_elements": {
                        "type": "integer",
                        "description": "Exact number of distinct elements.",
                    },
                    "band_gap_min": {
                        "type": "number",
                        "description": "Minimum band gap in eV (inclusive).",
                    },
                    "band_gap_max": {
                        "type": "number",
                        "description": "Maximum band gap in eV (inclusive).",
                    },
                    "energy_above_hull_max": {
                        "type": "number",
                        "description": (
                            "Maximum energy above convex hull in eV/atom. "
                            "Set to 0 to get only stable phases."
                        ),
                    },
                    "formation_energy_min": {
                        "type": "number",
                        "description": "Minimum formation energy per atom in eV/atom.",
                    },
                    "formation_energy_max": {
                        "type": "number",
                        "description": "Maximum formation energy per atom in eV/atom.",
                    },
                    "density_min": {
                        "type": "number",
                        "description": "Minimum density in g/cm³.",
                    },
                    "density_max": {
                        "type": "number",
                        "description": "Maximum density in g/cm³.",
                    },
                    "crystal_system": {
                        "type": "string",
                        "description": (
                            "Crystal system filter. One of: cubic, tetragonal, "
                            "orthorhombic, hexagonal, trigonal, monoclinic, triclinic."
                        ),
                        "enum": [
                            "cubic", "tetragonal", "orthorhombic",
                            "hexagonal", "trigonal", "monoclinic", "triclinic",
                        ],
                    },
                    "spacegroup_symbol": {
                        "type": "string",
                        "description": "Hermann-Mauguin space group symbol, e.g. 'Fm-3m'.",
                    },
                    "is_stable": {
                        "type": "boolean",
                        "description": "Filter by thermodynamic stability flag.",
                    },
                    "is_metal": {
                        "type": "boolean",
                        "description": "True for metals, False for insulators/semiconductors.",
                    },
                    "is_magnetic": {
                        "type": "boolean",
                        "description": "Filter by magnetic ordering.",
                    },
                    "theoretical": {
                        "type": "boolean",
                        "description": "True to include only theoretical structures; False for experimental.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (1–20). Default: 5.",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },

    # ── Tool 4: Fetch by material_id ───────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_fetch",
            "description": (
                "Fetch detailed information for one or more specific materials "
                "by their Materials Project ID (e.g. 'mp-19770', 'mp-126'). "
                "Returns full property set including lattice parameters, "
                "band gap, formation energy, magnetic properties, "
                "and structure statistics. "
                "Use this when the user already knows the material ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "One or more Materials Project IDs "
                            "(e.g. ['mp-19770'] or ['mp-126', 'mp-2'])."
                        ),
                    },
                },
                "required": ["material_ids"],
            },
        },
    },
    # ── Tool 5: Download structure file ────────────────────────
    {
        "type": "function",
        "function": {
            "name": "mp_download",
            "description": (
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
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": (
                            "Materials Project ID of the structure to download "
                            "(e.g. 'mp-19770'). Case-insensitive."
                        ),
                    },
                    "fmt": {
                        "type": "string",
                        "description": (
                            "Output file format:\n"
                            "  'cif'    → <filename>.cif    (default, for VESTA/ICSD)\n"
                            "  'poscar' → POSCAR_<filename> (for VASP/DFT)\n"
                            "  'xyz'    → <filename>.xyz    (for OVITO/ASE/Avogadro)"
                        ),
                        "enum":    ["cif", "poscar", "xyz"],
                        "default": "cif",
                    },
                    "save_dir": {
                        "type": "string",
                        "description": (
                            "Directory path where the file will be saved. "
                            "Will be created automatically if it does not exist. "
                            "Accepts both relative (e.g. './structures') and "
                            "absolute paths (e.g. 'D:/vasp/inputs'). "
                            "Default: './structures'."
                        ),
                        "default": "./structures",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "Custom base filename (without extension). "
                            "If omitted, defaults to '<material_id>_<formula>' "
                            "(e.g. 'mp-19770_Fe2O3'). "
                            "Useful when saving multiple polymorphs to the same directory."
                        ),
                    },
                },
                "required": ["material_id"],
            },
        },
    },
]