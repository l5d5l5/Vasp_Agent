# Structure_tool/structure_tool_executor.py
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List

from .structure_tool_schemas import (
    get_structure_tool_schema,
    LoadArgs, SupercellArgs, VacancyArgs, SlabArgs, AdsorptionArgs, ParticleArgs,
)
from .structure_service import StructureService


class StructureToolExecutor:
    """
    Async executor for structure manipulation tools.
    Mirrors LocalToolExecutor from Search_tool/mp_tool_use.py.
    """

    _TOOL_DISPATCH: Dict[str, tuple] = {
        "struct_load":       (LoadArgs,       "_load"),
        "struct_supercell":  (SupercellArgs,  "_supercell"),
        "struct_vacancy":    (VacancyArgs,    "_vacancy"),
        "struct_slab":       (SlabArgs,       "_slab"),
        "struct_adsorption": (AdsorptionArgs, "_adsorption"),
        "struct_particle":   (ParticleArgs,   "_particle"),
    }

    def __init__(self):
        self._svc = StructureService()

    @property
    def tools(self) -> List[Dict]:
        lang = os.environ.get("MP_SCHEMA_LANG", "en")
        return get_structure_tool_schema(lang)

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
            payload = getattr(self, method_name)(clean)
        except Exception as e:
            payload = {"error": str(e)}
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _load(self, args: Dict) -> Dict:
        return self._svc.load(args["file_path"])

    def _supercell(self, args: Dict) -> Dict:
        return self._svc.supercell(
            file_path=args["file_path"],
            supercell_matrix=args["supercell_matrix"],
            save_dir=args["save_dir"],
            filename=args.get("filename"),
        )

    def _vacancy(self, args: Dict) -> Dict:
        return self._svc.vacancy(
            file_path=args["file_path"],
            element=args["element"],
            dopant=args.get("dopant"),
            num_vacancies=args.get("num_vacancies", 1),
            num_structs=args.get("num_structs", 1),
            top_layers=args.get("top_layers"),
            random_seed=args.get("random_seed"),
            save_dir=args.get("save_dir", "./structures"),
            filename_prefix=args.get("filename_prefix", "POSCAR_vac"),
        )

    def _slab(self, args: Dict) -> Dict:
        return self._svc.slab(
            file_path=args["file_path"],
            miller_indices=args["miller_indices"],
            target_layers=args["target_layers"],
            vacuum_thickness=args.get("vacuum_thickness", 15.0),
            supercell_matrix=args.get("supercell_matrix"),
            fix_bottom_layers=args.get("fix_bottom_layers", 0),
            fix_top_layers=args.get("fix_top_layers", 0),
            termination_index=args.get("termination_index", 0),
            save_dir=args.get("save_dir", "./structures"),
            filename=args.get("filename", "POSCAR"),
        )

    def _adsorption(self, args: Dict) -> Dict:
        return self._svc.adsorption(
            file_path=args["file_path"],
            mode=args["mode"],
            molecule_formula=args.get("molecule_formula"),
            positions=args.get("positions"),
            save_dir=args.get("save_dir", "./structures"),
        )

    def _particle(self, args: Dict) -> Dict:
        return self._svc.particle(
            element=args["element"],
            mode=args["mode"],
            lattice_constant=args.get("lattice_constant"),
            lattice_type=args.get("lattice_type"),
            surface_energies=args.get("surface_energies"),
            particle_size=args.get("particle_size"),
            layers=args.get("layers"),
            surfaces=args.get("surfaces"),
            p=args.get("p"),
            q=args.get("q"),
            r=args.get("r"),
            n_shells=args.get("n_shells"),
            rod_radius=args.get("rod_radius"),
            rod_length=args.get("rod_length"),
            vacuum=args.get("vacuum", 15.0),
            save_dir=args.get("save_dir", "./structures"),
            filename=args.get("filename", "POSCAR"),
        )

    async def close(self):
        pass
