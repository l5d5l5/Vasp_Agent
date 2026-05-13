# Analysis_tool/analysis_tool_executor.py
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .analysis_tool_schemas import (
    get_analysis_tool_schema,
    DetectArgs, DosArgs, RelaxArgs, StructureInfoArgs,
    CohpSummaryArgs, CohpCurvesArgs, CohpExportArgs,
)
from .Analysis import VaspAnalysisDispatcher


class AnalysisToolExecutor:
    """
    Async executor for VASP analysis tools.
    Mirrors StructureToolExecutor from Structure_tool/structure_tool_executor.py.
    """

    _TOOL_DISPATCH: Dict[str, tuple] = {
        "vasp_detect":         (DetectArgs,        "_detect"),
        "vasp_dos":            (DosArgs,           "_dos"),
        "vasp_relax":          (RelaxArgs,          "_relax"),
        "vasp_structure_info": (StructureInfoArgs,  "_structure_info"),
        "vasp_cohp_summary":   (CohpSummaryArgs,    "_cohp_summary"),
        "vasp_cohp_curves":    (CohpCurvesArgs,     "_cohp_curves"),
        "vasp_cohp_export":    (CohpExportArgs,     "_cohp_export"),
    }

    @property
    def tools(self) -> List[Dict]:
        lang = os.environ.get("MP_SCHEMA_LANG", "en")
        return get_analysis_tool_schema(lang)

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        return await asyncio.to_thread(self._sync_execute, tool_name, tool_args)

    def _sync_execute(self, tool_name: str, tool_args: Dict) -> str:
        try:
            if tool_name not in self._TOOL_DISPATCH:
                return json.dumps({"error": f"Unknown tool: {tool_name}. "
                                            f"Available: {list(self._TOOL_DISPATCH)}"})
            model_cls, method_name = self._TOOL_DISPATCH[tool_name]
            validated = model_cls.model_validate(tool_args)
            clean = validated.model_dump()
            return getattr(self, method_name)(clean)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ── Detect ───────────────────────────────────────────────────
    def _detect(self, args: Dict) -> str:
        """
        Scan work_dir for characteristic VASP output files and infer calculation type.

        Detection rules (in priority order):
          NEB    — numbered subdirs 00/01/02... each containing POSCAR, OR
                   INCAR contains IMAGES= or ICHAIN=0
          DIMER  — MODECAR present, OR INCAR contains ICHAIN=2
          COHP   — COHPCAR.lobster or ICOHPLIST.lobster present
          DOS    — DOSCAR present and size > 1 KB
          RELAX  — OUTCAR present (catch-all for ground-state calculations)
        """
        import re
        work_dir = Path(args["work_dir"])

        if not work_dir.exists():
            return json.dumps({
                "success": False, "code": 404,
                "message": f"Directory not found: {work_dir}", "data": {}
            })

        detected: list[str] = []
        details: Dict[str, Any] = {}

        # ── Read INCAR once for tag inspection ──────────────────
        incar_tags: Dict[str, str] = {}
        incar_path = work_dir / "INCAR"
        if incar_path.exists():
            try:
                for line in incar_path.read_text(errors="ignore").splitlines():
                    line = line.split("#")[0].strip()
                    if "=" in line:
                        k, _, v = line.partition("=")
                        incar_tags[k.strip().upper()] = v.strip().upper()
            except Exception:
                pass

        # ── NEB: numbered image subdirectories ──────────────────
        image_dirs = sorted(
            d for d in work_dir.iterdir()
            if d.is_dir() and d.name.isdigit() and len(d.name) == 2
        )
        neb_from_dirs = (
            len(image_dirs) >= 3
            and all((d / "POSCAR").exists() for d in image_dirs[:3])
        )
        neb_from_incar = (
            "IMAGES" in incar_tags
            or incar_tags.get("ICHAIN") == "0"
        )
        if neb_from_dirs or neb_from_incar:
            detected.append("neb")
            n_images = len(image_dirs)
            # collect per-image convergence if OUTCAR exists
            image_info = []
            for d in image_dirs:
                outcar = d / "OUTCAR"
                image_info.append({
                    "image": d.name,
                    "has_outcar": outcar.exists(),
                    "outcar_size_MB": round(outcar.stat().st_size / 1e6, 2) if outcar.exists() else 0,
                })
            details["neb"] = {
                "evidence": "image_dirs" if neb_from_dirs else "INCAR:IMAGES/ICHAIN=0",
                "n_images": n_images,
                "images": image_info,
                "incar_images": incar_tags.get("IMAGES", "not set"),
            }

        # ── DIMER: MODECAR or ICHAIN=2 ──────────────────────────
        modecar = work_dir / "MODECAR"
        dimer_from_file = modecar.exists()
        dimer_from_incar = incar_tags.get("ICHAIN") == "2"
        if dimer_from_file or dimer_from_incar:
            detected.append("dimer")
            details["dimer"] = {
                "evidence": ("MODECAR" if dimer_from_file else "") +
                            (" INCAR:ICHAIN=2" if dimer_from_incar else "").strip(),
                "modecar": dimer_from_file,
            }

        # ── COHP/LOBSTER ─────────────────────────────────────────
        cohpcar   = work_dir / "COHPCAR.lobster"
        icohplist = work_dir / "ICOHPLIST.lobster"
        if cohpcar.exists() or icohplist.exists():
            detected.append("cohp")
            details["cohp"] = {
                "cohpcar":   cohpcar.exists(),
                "icohplist": icohplist.exists(),
            }

        # ── DOS: DOSCAR > 1 KB ───────────────────────────────────
        doscar = work_dir / "DOSCAR"
        if doscar.exists() and doscar.stat().st_size > 1024:
            detected.append("dos")
            details["dos"] = {
                "doscar_size_MB": round(doscar.stat().st_size / 1e6, 2),
            }

        # ── RELAX: OUTCAR present (catch-all) ────────────────────
        outcar  = work_dir / "OUTCAR"
        oszicar = work_dir / "OSZICAR"
        if outcar.exists() and "neb" not in detected and "dimer" not in detected:
            detected.append("relax")
            details["relax"] = {
                "outcar_size_MB": round(outcar.stat().st_size / 1e6, 2),
                "oszicar": oszicar.exists(),
            }

        if not detected:
            return json.dumps({
                "success": False, "code": 404,
                "message": "No recognisable VASP calculation files found.",
                "data": {"work_dir": str(work_dir), "detected": []}
            })

        # ── Recommend follow-up tools ─────────────────────────────
        tool_map = {
            "relax": ["vasp_structure_info", "vasp_relax"],
            "dos":   ["vasp_structure_info", "vasp_dos"],
            "cohp":  ["vasp_cohp_summary", "vasp_cohp_curves"],
            "neb":   [],   # no dedicated NEB analysis tool yet
            "dimer": [],   # no dedicated DIMER analysis tool yet
        }
        recommended: list[str] = []
        for t in detected:
            for tool in tool_map.get(t, []):
                if tool not in recommended:
                    recommended.append(tool)

        return json.dumps({
            "success": True, "code": 200,
            "message": f"Detected: {', '.join(detected)}",
            "data": {
                "work_dir":          str(work_dir),
                "detected":          detected,
                "details":           details,
                "recommended_tools": recommended,
            }
        }, ensure_ascii=False)

    # ── DOS ──────────────────────────────────────────────────────
    def _dos(self, args: Dict) -> str:
        elements = args["elements"]
        orbitals = args["orbitals"]
        if len(orbitals) == 1:
            orbitals = orbitals * len(elements)

        curves = [
            {
                "id":      f"{el}_{orb}",
                "label":   f"{el}-{orb}",
                "mode":    "element",
                "element": el,
                "orbital": orb,
                "color":   "#333",
            }
            for el, orb in zip(elements, orbitals)
        ]

        raw = VaspAnalysisDispatcher.dispatch(
            "dos", args["work_dir"],
            curves=curves,
            erange=args["erange"],
            show_tdos=args["show_tdos"],
        )
        return self._strip_dos_arrays(raw)

    @staticmethod
    def _strip_dos_arrays(raw_json: str) -> str:
        """Remove large numeric arrays from DOS result before returning to LLM."""
        try:
            data = json.loads(raw_json)
            inner = data.get("data", {})
            inner.pop("energy", None)
            inner.pop("tdos", None)
            for curve in inner.get("curves", []):
                curve.pop("dos_up", None)
                curve.pop("dos_down", None)
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw_json

    # ── Relax ─────────────────────────────────────────────────────
    def _relax(self, args: Dict) -> str:
        return VaspAnalysisDispatcher.dispatch(
            "relax", args["work_dir"],
            get_site_mag=args["get_site_mag"],
        )

    # ── Structure Info ────────────────────────────────────────────
    def _structure_info(self, args: Dict) -> str:
        raw = VaspAnalysisDispatcher.dispatch("structure_info", args["work_dir"])
        try:
            data = json.loads(raw)
            data.get("data", {}).pop("vasp_text", None)
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw

    # ── COHP Summary ──────────────────────────────────────────────
    def _cohp_summary(self, args: Dict) -> str:
        kwargs: Dict[str, Any] = {"n_top_bonds": args["n_top_bonds"]}
        if args.get("filter_type"):
            kwargs["filter_type"] = args["filter_type"]
        if args.get("filter_value"):
            fv = args["filter_value"]
            if args.get("filter_type") == "index":
                kwargs["filter_value"] = [int(v) for v in fv]
            else:
                kwargs["filter_value"] = fv
        return VaspAnalysisDispatcher.dispatch("cohp_summary", args["work_dir"], **kwargs)

    # ── COHP Curves ───────────────────────────────────────────────
    def _cohp_curves(self, args: Dict) -> str:
        kwargs: Dict[str, Any] = {
            "bond_labels":      args["bond_labels"],
            "include_orbitals": args["include_orbitals"],
        }
        if args.get("erange"):
            kwargs["erange"] = args["erange"]
        raw = VaspAnalysisDispatcher.dispatch("cohp_curves", args["work_dir"], **kwargs)
        return self._strip_cohp_arrays(raw)

    @staticmethod
    def _strip_cohp_arrays(raw_json: str) -> str:
        """Replace large cohp_curves list with a compact summary."""
        try:
            data = json.loads(raw_json)
            inner = data.get("data", {})
            curves = inner.pop("cohp_curves", [])
            if isinstance(curves, list) and curves:
                inner["n_datapoints"] = len(curves)
                inner["columns"] = list(curves[0].keys()) if curves else []
            return json.dumps(data, ensure_ascii=False)
        except Exception:
            return raw_json

    # ── COHP Export ───────────────────────────────────────────────
    def _cohp_export(self, args: Dict) -> str:
        import pandas as pd
        from .Analysis import CohpAnalysis

        work_dir = args["work_dir"]
        bond_labels = args["bond_labels"]
        erange = args.get("erange")
        include_orbitals = args.get("include_orbitals", False)
        export_format = args.get("export_format", "csv")
        save_dir = Path(args.get("save_dir", "./cohp_export"))

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            analyzer = CohpAnalysis(work_dir=work_dir)
            df: pd.DataFrame = analyzer.get_cohp_curves(
                bond_labels=bond_labels,
                erange=erange,
                include_orbitals=include_orbitals,
            )

            if df is None or df.empty:
                return json.dumps({
                    "success": False, "code": 404,
                    "message": "No COHP data found for the specified bonds.", "data": {}
                })

            label_str = "_".join(bond_labels[:3])
            fname = f"cohp_bonds_{label_str}.{export_format}"
            out_path = save_dir / fname

            if export_format == "csv":
                df.to_csv(out_path, index=False)
            else:
                df.to_json(out_path, orient="records", indent=2)

            return json.dumps({
                "success": True, "code": 200,
                "message": f"COHP data exported for bonds {bond_labels}",
                "data": {
                    "saved_path": str(out_path),
                    "bonds": bond_labels,
                    "n_datapoints": len(df),
                    "columns": list(df.columns),
                    "format": export_format,
                }
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "success": False, "code": 500,
                "message": f"Export failed: {e}", "data": {}
            })

    async def close(self):
        pass
