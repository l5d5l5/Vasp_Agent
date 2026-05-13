# -*- coding: utf-8 -*-
"""
llm_tool_schema.py — Universal LLM function-call schema for flow.api.generate_inputs
======================================================================================

Defines one tool/function that exposes ``generate_inputs()`` to LLMs.
Pre-built wrappers for OpenAI (tools), Anthropic (tool_use), and Google Gemini
(function_declarations) are provided at the bottom of this file.

Usage::

    # OpenAI / Azure OpenAI
    from flow.llm_tool_schema import OPENAI_TOOL
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[...],
        tools=[OPENAI_TOOL],
        tool_choice="auto",
    )

    # Anthropic Claude
    from flow.llm_tool_schema import ANTHROPIC_TOOL
    response = client.messages.create(
        model="claude-opus-4-7-20251101",
        messages=[...],
        tools=[ANTHROPIC_TOOL],
    )

    # Google Gemini
    from flow.llm_tool_schema import GEMINI_FUNCTION_DECLARATION
    from google.generativeai.types import Tool
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        tools=[Tool(function_declarations=[GEMINI_FUNCTION_DECLARATION])],
    )

Dispatching the tool call back to Python::

    from flow.llm_tool_schema import dispatch
    result = dispatch(tool_call_arguments_dict)
"""
from __future__ import annotations

from typing import Any, Dict

# ---------------------------------------------------------------------------
# Core parameter schema (JSON Schema draft-07 compatible)
# ---------------------------------------------------------------------------

#: Full parameter schema shared by all providers.  Providers that do not
#: support ``oneOf`` (e.g. older Gemini versions) should use the Gemini
#: wrapper at the bottom, which substitutes compatible alternatives.
_PARAMETERS: Dict[str, Any] = {
    "type": "object",
    "required": ["calc_type"],
    "additionalProperties": False,
    "properties": {

        # ── Core ────────────────────────────────────────────────────────────

        "calc_type": {
            "type": "string",
            "description": (
                "Calculation type. Controls VASP input template and INCAR defaults. "
                "Accepted values:\n"
                "  Structure optimisation: 'bulk_relax' (ISIF=3), 'slab_relax' (ISIF=2)\n"
                "  Electronic structure:   'static_sp', 'static_dos', 'static_charge', 'static_elf'\n"
                "  Vibrational:            'freq' (finite diff, IBRION=5), 'freq_ir' (DFPT, IBRION=7)\n"
                "  Spectroscopy:           'lobster' (COHP), 'nmr_cs', 'nmr_efg', 'nbo'\n"
                "  Transition state:       'neb' (requires VTST VASP), 'dimer' (requires VTST VASP)\n"
                "  Molecular dynamics:     'md_nvt', 'md_npt'"
            ),
            "enum": [
                "bulk_relax", "slab_relax",
                "static_sp", "static_dos", "static_charge", "static_elf",
                "freq", "freq_ir",
                "lobster", "nmr_cs", "nmr_efg", "nbo",
                "neb", "dimer",
                "md_nvt", "md_npt",
            ],
        },

        "structure": {
            "type": "string",
            "description": (
                "Path to the input structure file (POSCAR, CONTCAR, or CIF), "
                "or path to a directory that contains a CONTCAR. "
                "Defaults to 'POSCAR' in the current working directory. "
                "Ignored when prev_dir is supplied and the file does not exist — "
                "the engine falls back to prev_dir/CONTCAR then prev_dir/POSCAR."
            ),
        },

        "functional": {
            "type": "string",
            "description": (
                "Exchange-correlation functional. Controls both the pymatgen InputSet "
                "and the INCAR patches applied on top of the type defaults.\n"
                "  'PBE'    — standard GGA (default)\n"
                "  'RPBE'   — revised PBE, better surface adsorption energies\n"
                "  'BEEF'   — BEEF-vdW non-local van-der-Waals (requires vdw_kernel.bindat)\n"
                "  'SCAN'   — SCAN meta-GGA\n"
                "  'r2SCAN' — r²SCAN meta-GGA\n"
                "  'HSE'    — HSE06 hybrid (accurate band gaps, ~10× more expensive)\n"
                "  'PBE0'   — PBE0 hybrid\n"
                "  'LDA'    — local density approximation\n"
                "  'PBEsol' — PBE revised for solids"
            ),
            "enum": ["PBE", "RPBE", "BEEF", "SCAN", "r2SCAN", "HSE", "PBE0", "LDA", "PBEsol"],
            "default": "PBE",
        },

        "kpoints_density": {
            "type": "number",
            "description": (
                "Reciprocal-space k-point density in Å⁻¹ (points per reciprocal-lattice length). "
                "The Monkhorst-Pack mesh is auto-generated from this density. "
                "Typical values: 50 for bulk, 25 for slabs/surfaces. Default: 50."
            ),
            "default": 50.0,
            "exclusiveMinimum": 0,
        },

        "output_dir": {
            "type": "string",
            "description": (
                "Directory where VASP input files (INCAR, POSCAR, KPOINTS, POTCAR, …) "
                "are written. When omitted, a name is auto-generated under the current "
                "working directory based on calc_type."
            ),
        },

        "prev_dir": {
            "type": "string",
            "description": (
                "Path to a preceding calculation's output directory. Enables three "
                "automatic behaviours:\n"
                "  1. Structure: engine reads prev_dir/CONTCAR (preferred) or POSCAR "
                "when the structure file is absent.\n"
                "  2. INCAR inheritance: settings from prev_dir/INCAR become the base; "
                "ENCUT, EDIFF, etc. carry over automatically.\n"
                "  3. WAVECAR/CHGCAR copy-in with automatic ISTART/ICHARG.\n"
                "Required for: 'static_dos', 'static_charge', 'static_elf', "
                "'lobster', 'nbo', 'dimer'."
            ),
        },

        # ── INCAR overrides ─────────────────────────────────────────────────

        "incar": {
            "type": "object",
            "description": (
                "Any VASP INCAR tag as {'TAG': value}. Merged on top of ALL other "
                "settings (type defaults, functional patches, DFT+U, MAGMOM) — "
                "always wins. No whitelist; every standard VASP tag is accepted.\n"
                "Common examples:\n"
                "  {'EDIFFG': -0.01}           — tighter ionic convergence (eV/Å)\n"
                "  {'ENCUT': 600}              — raise plane-wave cutoff (eV)\n"
                "  {'ISMEAR': 0, 'SIGMA': 0.05}— Gaussian smearing\n"
                "  {'NPAR': 4, 'KPAR': 2}      — parallelisation flags\n"
                "  {'NSW': 300, 'POTIM': 0.3}  — relax steps / ionic step size\n"
                "  {'LORBIT': 11, 'NEDOS': 3001}— projected DOS resolution\n"
                "  {'LREAL': False}             — reciprocal-space projectors"
            ),
            "additionalProperties": True,
        },

        # ── Magnetism ────────────────────────────────────────────────────────

        "magmom": {
            "description": (
                "Initial magnetic moments for spin-polarised (ISPIN=2) calculations. "
                "Two formats:\n"
                "  Per-atom list  — [5.0, 5.0, 3.0, 3.0]  (same atom order as structure)\n"
                "  Per-element dict — {'Fe': 5.0, 'Co': 3.0, 'O': 0.0}  "
                "(pymatgen expands against site order automatically)\n"
                "Omit to let pymatgen use its own defaults."
            ),
            "oneOf": [
                {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Per-atom magnetic moments in structure site order.",
                },
                {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                    "description": "Per-element magnetic moments; pymatgen expands to per-site.",
                },
            ],
        },

        # ── DFT+U ───────────────────────────────────────────────────────────

        "dft_u": {
            "type": "object",
            "description": (
                "DFT+U (Hubbard U) parameters per element. LDAUTYPE=2 (Dudarev, "
                "U_eff = U − J) is set automatically. Three equivalent formats:\n"
                "  Short keys:   {'Fe': {'U': 4.0, 'l': 2, 'J': 0.0}, 'Co': {'U': 3.0, 'l': 2}}\n"
                "  VASP tags:    {'Fe': {'LDAUU': 4.0, 'LDAUL': 2, 'LDAUJ': 0.0}}\n"
                "  Scalar (U only, l=2, J=0 assumed):  {'Fe': 4.0, 'Co': 3.0}\n"
                "Key meanings: 'U'/'LDAUU' — Coulomb U (eV); 'l'/'LDAUL' — angular "
                "momentum (0=s,1=p,2=d,3=f); 'J'/'LDAUJ' — exchange J (eV)."
            ),
            "additionalProperties": {
                "oneOf": [
                    {"type": "number", "description": "Scalar shorthand: U value in eV; l=2, J=0 assumed."},
                    {
                        "type": "object",
                        "properties": {
                            "U":     {"type": "number", "description": "Coulomb U in eV (alias: LDAUU)."},
                            "LDAUU": {"type": "number"},
                            "l":     {"type": "integer", "description": "Angular momentum quantum number (alias: LDAUL)."},
                            "L":     {"type": "integer"},
                            "LDAUL": {"type": "integer"},
                            "J":     {"type": "number", "description": "Exchange J in eV (alias: LDAUJ). Usually 0 for Dudarev."},
                            "LDAUJ": {"type": "number"},
                        },
                        "additionalProperties": False,
                    },
                ]
            },
        },

        # ── LOBSTER ─────────────────────────────────────────────────────────

        "cohp_generator": {
            "description": (
                "COHP bond-length range specification for lobsterin. "
                "Only used when calc_type='lobster'.\n"
                "  str   — single entry: 'from 1.5 to 1.9 orbitalwise'\n"
                "  list  — multiple entries: first replaces pymatgen's default "
                "cohpGenerator; remaining entries are appended verbatim.\n"
                "Omit to let pymatgen generate a default from the structure's shortest bonds."
            ),
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}, "minItems": 1},
            ],
        },

        "lobsterin": {
            "type": "object",
            "description": (
                "Additional key-value pairs written to the lobsterin overwrite dict. "
                "Only used when calc_type='lobster'. "
                "Example: {'COHPstartEnergy': -20.0, 'COHPendEnergy': 20.0}."
            ),
            "additionalProperties": True,
        },

        # ── NBO ─────────────────────────────────────────────────────────────

        "nbo_config": {
            "type": "object",
            "description": (
                "NBO analysis configuration. Only used when calc_type='nbo'."
            ),
            "properties": {
                "occ_1c": {
                    "type": "number",
                    "description": "One-centre occupancy threshold for bond detection. Default: 1.60.",
                    "default": 1.60,
                },
                "occ_2c": {
                    "type": "number",
                    "description": "Two-centre occupancy threshold for bond detection. Default: 1.85.",
                    "default": 1.85,
                },
                "basis_source": {
                    "type": "string",
                    "description": "Basis set identifier or path. Default: 'ANO-RCC-MB'.",
                    "default": "ANO-RCC-MB",
                },
                "print_cube": {
                    "type": "string",
                    "enum": ["T", "F"],
                    "description": "Write orbital cube files. Default: 'F'.",
                    "default": "F",
                },
                "density": {
                    "type": "string",
                    "enum": ["T", "F"],
                    "description": "Write density cube file. Default: 'F'.",
                    "default": "F",
                },
                "vis_start": {
                    "type": "integer",
                    "description": "First orbital index for cube visualisation. Default: 0.",
                    "default": 0,
                },
                "vis_end": {
                    "type": "integer",
                    "description": "Last orbital index for cube visualisation (-1 = last orbital). Default: -1.",
                    "default": -1,
                },
                "mesh": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Cube-file grid dimensions [nx, ny, nz]. Default: [0, 0, 0].",
                },
                "box_int": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                    "description": "Integer box extension factors [bx, by, bz]. Default: [1, 1, 1].",
                },
                "origin_fact": {
                    "type": "number",
                    "description": "Fractional origin offset factor. Default: 0.0.",
                    "default": 0.0,
                },
            },
            "additionalProperties": False,
        },

        # ── Compute resources ────────────────────────────────────────────────

        "walltime": {
            "type": "string",
            "description": (
                "Wall-clock time limit for the PBS job script in 'HH:MM:SS' format, "
                "e.g. '48:00:00'. Omit to let the engine choose a default per calc_type "
                "(relaxations: '124:00:00'; statics: '48:00:00')."
            ),
            "pattern": r"^\d+:[0-5]\d:[0-5]\d$",
        },

        "ncores": {
            "type": "integer",
            "description": (
                "Number of CPU cores (MPI ranks) for the PBS job script. "
                "Omit to use the calc_type default (72)."
            ),
            "exclusiveMinimum": 0,
        },

        # ── Dry run ──────────────────────────────────────────────────────────

        "dry_run": {
            "type": "boolean",
            "description": (
                "When true, return a configuration preview dict without writing any files. "
                "Safe to call with a non-existent structure path. "
                "The returned dict contains: 'incar', 'calc_type', 'functional', "
                "'kpoints_density', and optionally 'lobsterin'/'lobsterin_custom_lines'."
            ),
            "default": False,
        },
    },
}


# ---------------------------------------------------------------------------
# Provider-specific wrappers
# ---------------------------------------------------------------------------

#: OpenAI / Azure OpenAI — ``tools`` list entry.
#: Pass directly: ``client.chat.completions.create(tools=[OPENAI_TOOL], ...)``
OPENAI_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "generate_vasp_inputs",
        "description": (
            "Generate VASP ab-initio calculation input files (INCAR, POSCAR, KPOINTS, POTCAR, "
            "and type-specific files such as lobsterin or NBO input) for a given structure and "
            "calculation type. Supports 16 calculation types across 9 DFT functionals. "
            "Returns the absolute path to the output directory, or a configuration preview dict "
            "when dry_run=true."
        ),
        "parameters": _PARAMETERS,
        "strict": False,
    },
}

#: Anthropic Claude — ``tools`` list entry.
#: Pass directly: ``client.messages.create(tools=[ANTHROPIC_TOOL], ...)``
ANTHROPIC_TOOL: Dict[str, Any] = {
    "name": "generate_vasp_inputs",
    "description": (
        "Generate VASP ab-initio calculation input files (INCAR, POSCAR, KPOINTS, POTCAR, "
        "and type-specific files such as lobsterin or NBO input) for a given structure and "
        "calculation type. Supports 16 calculation types across 9 DFT functionals. "
        "Returns the absolute path to the output directory, or a configuration preview dict "
        "when dry_run=true."
    ),
    "input_schema": _PARAMETERS,
}

# Google Gemini does not support oneOf / additionalProperties in the same way.
# The Gemini schema below uses TYPE_UNSPECIFIED for flexible-typed fields and
# avoids unsupported keywords.  For the full schema, use OPENAI_TOOL or ANTHROPIC_TOOL.
_GEMINI_PARAMETERS: Dict[str, Any] = {
    "type": "OBJECT",
    "required": ["calc_type"],
    "properties": {
        "calc_type": {
            "type": "STRING",
            "description": (
                "Calculation type. One of: bulk_relax, slab_relax, static_sp, static_dos, "
                "static_charge, static_elf, freq, freq_ir, lobster, nmr_cs, nmr_efg, nbo, "
                "neb, dimer, md_nvt, md_npt."
            ),
            "enum": [
                "bulk_relax", "slab_relax",
                "static_sp", "static_dos", "static_charge", "static_elf",
                "freq", "freq_ir",
                "lobster", "nmr_cs", "nmr_efg", "nbo",
                "neb", "dimer",
                "md_nvt", "md_npt",
            ],
        },
        "structure": {
            "type": "STRING",
            "description": "Path to input structure file (POSCAR, CONTCAR, or CIF). Default: 'POSCAR'.",
        },
        "functional": {
            "type": "STRING",
            "description": (
                "XC functional. One of: PBE (default), RPBE, BEEF, SCAN, r2SCAN, HSE, PBE0, LDA, PBEsol."
            ),
            "enum": ["PBE", "RPBE", "BEEF", "SCAN", "r2SCAN", "HSE", "PBE0", "LDA", "PBEsol"],
        },
        "kpoints_density": {
            "type": "NUMBER",
            "description": "K-point density in Å⁻¹. Typical: 50 bulk, 25 surface. Default: 50.",
        },
        "output_dir": {
            "type": "STRING",
            "description": "Output directory for VASP input files. Auto-generated when omitted.",
        },
        "prev_dir": {
            "type": "STRING",
            "description": (
                "Previous calculation directory for INCAR/WAVECAR/CHGCAR inheritance. "
                "Required for: static_dos, static_charge, static_elf, lobster, nbo, dimer."
            ),
        },
        "incar": {
            "type": "OBJECT",
            "description": (
                "VASP INCAR tag overrides as {'TAG': value}. Highest priority; any VASP tag accepted. "
                "Examples: {'EDIFFG': -0.01, 'ENCUT': 600, 'ISMEAR': 0, 'SIGMA': 0.05}."
            ),
        },
        "magmom": {
            "type": "OBJECT",
            "description": (
                "Magnetic moments. Supply either a list-style object with integer keys "
                "{'0': 5.0, '1': 3.0} for per-atom order, or element-keyed {'Fe': 5.0, 'Co': 3.0}. "
                "Gemini note: per-atom list must be encoded as an index-keyed object."
            ),
        },
        "dft_u": {
            "type": "OBJECT",
            "description": (
                "DFT+U per element. Scalar shorthand {'Fe': 4.0} or full "
                "{'Fe': {'U': 4.0, 'l': 2, 'J': 0.0}, 'Co': {'U': 3.0, 'l': 2}}."
            ),
        },
        "cohp_generator": {
            "type": "STRING",
            "description": (
                "COHP bond-length range for lobsterin (lobster only). "
                "Single string: 'from 1.5 to 1.9 orbitalwise'. "
                "Multiple ranges: pass as comma-separated string and the dispatch function splits them."
            ),
        },
        "lobsterin": {
            "type": "OBJECT",
            "description": "Extra lobsterin key-value pairs (lobster only). E.g. {'COHPstartEnergy': -20.0}.",
        },
        "nbo_config": {
            "type": "OBJECT",
            "description": (
                "NBO analysis config (nbo only). Keys: occ_1c (float), occ_2c (float), "
                "basis_source (str), print_cube ('T'/'F'), density ('T'/'F'), "
                "vis_start (int), vis_end (int), mesh ([nx,ny,nz]), box_int ([bx,by,bz])."
            ),
        },
        "walltime": {
            "type": "STRING",
            "description": "PBS walltime in 'HH:MM:SS' format. E.g. '48:00:00'. Auto-chosen when omitted.",
        },
        "ncores": {
            "type": "INTEGER",
            "description": "CPU cores for PBS script. Default: 72.",
        },
        "dry_run": {
            "type": "BOOLEAN",
            "description": "Return config preview dict without writing files. Default: false.",
        },
    },
}

#: Google Gemini — ``function_declarations`` list entry.
#: Pass as: ``Tool(function_declarations=[GEMINI_FUNCTION_DECLARATION])``
GEMINI_FUNCTION_DECLARATION: Dict[str, Any] = {
    "name": "generate_vasp_inputs",
    "description": (
        "Generate VASP ab-initio calculation input files (INCAR, POSCAR, KPOINTS, POTCAR, "
        "and type-specific files such as lobsterin or NBO input) for a given structure and "
        "calculation type. Supports 16 calculation types across 9 DFT functionals."
    ),
    "parameters": _GEMINI_PARAMETERS,
}


# ---------------------------------------------------------------------------
# Dispatch helper — convert LLM tool-call arguments back to generate_inputs()
# ---------------------------------------------------------------------------

def dispatch(arguments: Dict[str, Any]) -> Any:
    """Call ``generate_inputs()`` from a raw LLM tool-call arguments dict.

    Handles provider-specific quirks:
    - Gemini encodes per-atom ``magmom`` as ``{"0": 5.0, "1": 3.0}`` (index-keyed
      object); this function detects that and converts it back to a list.
    - ``cohp_generator`` sent as a comma-separated string is split into a list.

    Args:
        arguments: The ``arguments`` dict from the tool call (already JSON-decoded).

    Returns:
        str | dict: The output directory path, or a config preview dict (dry_run=True).

    Example::

        # After receiving a tool_call from any LLM provider:
        import json
        args = json.loads(tool_call.function.arguments)   # OpenAI
        result = dispatch(args)
    """
    from flow.api import generate_inputs

    args = dict(arguments)

    # Normalise Gemini-style per-atom magmom: {"0": 5.0, "1": 3.0} → [5.0, 3.0]
    magmom = args.get("magmom")
    if isinstance(magmom, dict) and magmom:
        keys = list(magmom.keys())
        if all(k.isdigit() for k in keys):
            args["magmom"] = [magmom[str(i)] for i in range(len(keys))]

    # Normalise Gemini-style cohp_generator: comma-separated string → list
    cohp = args.get("cohp_generator")
    if isinstance(cohp, str) and "," in cohp:
        args["cohp_generator"] = [s.strip() for s in cohp.split(",")]

    return generate_inputs(**args)


# ---------------------------------------------------------------------------
# Convenience getter
# ---------------------------------------------------------------------------

def get_tool(provider: str) -> Dict[str, Any]:
    """Return the tool definition for the given LLM provider.

    Args:
        provider: One of ``"openai"``, ``"azure"``, ``"anthropic"``,
            ``"claude"``, ``"gemini"``, ``"google"``.

    Returns:
        The provider-specific tool / function-declaration dict.

    Raises:
        ValueError: If the provider string is not recognised.
    """
    p = provider.lower().strip()
    if p in ("openai", "azure", "azure_openai"):
        return OPENAI_TOOL
    if p in ("anthropic", "claude"):
        return ANTHROPIC_TOOL
    if p in ("gemini", "google", "google_gemini"):
        return GEMINI_FUNCTION_DECLARATION
    raise ValueError(
        f"Unknown provider '{provider}'. "
        "Supported: 'openai', 'azure', 'anthropic', 'claude', 'gemini', 'google'."
    )
