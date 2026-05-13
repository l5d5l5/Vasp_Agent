"""
stages/base.py
==============
BaseStage – abstract contract every stage class must implement.

Every concrete stage must declare ``stage_name`` and ``calc_type`` class
attributes and implement ``prepare()`` and ``check_success()``.  Shared
helpers (``outcar_ok``, ``get_workdir``, ``_write_vasp_inputs``) live here
so all subclasses inherit them without repetition.

BaseStage – 每个阶段类必须实现的抽象契约。

每个具体阶段必须声明 ``stage_name`` 和 ``calc_type`` 类属性，并实现
``prepare()`` 与 ``check_success()``。共享辅助方法（``outcar_ok``、
``get_workdir``、``_write_vasp_inputs``）定义于此，供所有子类继承复用。
"""
from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flow.workflow.config import WorkflowConfig

logger = logging.getLogger(__name__)


class Stage(str, Enum):
    """Canonical workflow stage names — single source of truth for all stage strings.

    Inherits from ``str`` so that ``Stage.BULK_RELAX == "bulk_relax"`` is True,
    keeping full JSON/manifest round-trip compatibility without data migration.

    工作流阶段名称的唯一权威来源。
    继承自 ``str``，使得 ``Stage.BULK_RELAX == "bulk_relax"`` 为 True，
    与 JSON/manifest 完全兼容，无需数据迁移。
    """
    BULK_RELAX         = "bulk_relax"
    BULK_DOS           = "bulk_dos"
    BULK_LOBSTER       = "bulk_lobster"
    BULK_NBO           = "bulk_nbo"
    SLAB_RELAX         = "slab_relax"
    SLAB_DOS           = "slab_dos"
    SLAB_LOBSTER       = "slab_lobster"
    SLAB_NBO           = "slab_nbo"
    ADSORPTION         = "adsorption"
    ADSORPTION_FREQ    = "adsorption_freq"
    ADSORPTION_LOBSTER = "adsorption_lobster"
    ADSORPTION_NBO     = "adsorption_nbo"


class BaseStage(ABC):
    """Abstract base for all workflow stages.

    Subclass contract:
      stage_name  – matches the key used in STAGE_ORDER and manifest tasks
      calc_type   – passed to FrontendAdapter ("bulk_relax", "slab_relax", …)

    所有工作流阶段的抽象基类。

    子类约定：
      stage_name  – 与 STAGE_ORDER 及清单任务中使用的键一致
      calc_type   – 传递给 FrontendAdapter 的字符串（如 "bulk_relax"、"slab_relax" 等）
    """

    # Class-level attribute: unique string key identifying this stage.
    # 类级属性：唯一标识本阶段的字符串键。
    stage_name: Stage

    # Class-level attribute: calculation type string forwarded to FrontendAdapter.
    # 类级属性：转发给 FrontendAdapter 的计算类型字符串。
    calc_type: str

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def prepare(
        self,
        workdir: Path,
        prev_dir: Optional[Path],
        cfg: "WorkflowConfig",
        task_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP inputs into *workdir*.

        Args:
            workdir:   Pre-created working directory for this task.
            prev_dir:  Working directory of the prerequisite stage (may be None).
            cfg:       Full typed workflow configuration.
            task_meta: Raw metadata dict from the manifest task entry.

        将 VASP 输入文件写入 *workdir*。

        Args:
            workdir:   已预先创建的本任务工作目录。
            prev_dir:  前置阶段的工作目录（可为 None）。
            cfg:       完整的带类型工作流配置。
            task_meta: 来自清单任务条目的原始元数据字典。
        """

    def check_success(
        self,
        workdir: Path,
        cfg: "WorkflowConfig",
    ) -> bool:
        """Return True if this stage completed successfully.

        Default implementation checks OUTCAR for normal VASP termination.
        Override in subclasses that require additional output files (e.g.
        LOBSTER, NBO).

        Args:
            workdir: Working directory to inspect.
            cfg:     Full typed workflow configuration.

        Returns:
            True if the stage output files indicate successful completion.

        若本阶段已成功完成则返回 True。

        默认实现检查 OUTCAR 是否正常结束。需要检查额外输出文件的子类
        （如 LOBSTER、NBO）应覆盖此方法。

        Args:
            workdir: 待检查的工作目录。
            cfg:     完整的带类型工作流配置。

        Returns:
            若阶段输出文件表明成功完成则为 True。
        """
        return self.outcar_ok(workdir)

    # ------------------------------------------------------------------
    # Concrete helper
    # ------------------------------------------------------------------

    def get_workdir(self, run_root: Path, bulk_id: str) -> Path:
        """Default workdir layout: run_root / stage_name / bulk_id.

        Args:
            run_root: Root directory for the current workflow run.
            bulk_id:  Identifier string for the bulk system being processed.

        Returns:
            Path object pointing to the stage-specific working directory.

        默认工作目录布局：run_root / stage_name / bulk_id。

        Args:
            run_root: 当前工作流运行的根目录。
            bulk_id:  正在处理的体相系统的标识符字符串。

        Returns:
            指向阶段专属工作目录的 Path 对象。
        """
        return run_root / self.stage_name / bulk_id

    # ------------------------------------------------------------------
    # Shared OUTCAR checker (used by most stages)
    # ------------------------------------------------------------------

    @staticmethod
    def outcar_ok(workdir: Path) -> bool:
        """Return True if OUTCAR shows normal VASP termination.

        Reads the last 20 000 characters of OUTCAR and searches for
        any of three termination patterns that VASP writes on clean exit.

        Args:
            workdir: Directory that should contain an OUTCAR file.

        Returns:
            True if a termination pattern is found; False otherwise
            (file missing, unreadable, or terminated abnormally).

        若 OUTCAR 显示 VASP 正常结束则返回 True。

        读取 OUTCAR 末尾 20 000 个字符，搜索 VASP 正常退出时写入的三种结束模式之一。

        Args:
            workdir: 应包含 OUTCAR 文件的目录。

        Returns:
            找到结束模式时返回 True；否则（文件缺失、不可读或异常终止）返回 False。
        """
        outcar = workdir / "OUTCAR"
        if not outcar.exists():
            return False
        try:
            # Binary seek to tail: avoids loading multi-GB OUTCAR files into memory.
            # read_text()[-N:] would read the entire file first then slice.
            # 二进制尾部读取：避免先将整个数 GB OUTCAR 加载入内存再切片。
            with outcar.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(size - 20_000, 0))
                tail = f.read().decode("utf-8", errors="ignore")
        except OSError:
            return False
        # Patterns that appear in every cleanly terminated VASP run.
        # 每次 VASP 正常终止时都会出现的模式字符串。
        patterns = [
            r"total cpu time used",
            r"voluntary context switches",
            r"General timing and accounting informations",
        ]
        return any(re.search(p, tail, flags=re.IGNORECASE) for p in patterns)

    # ------------------------------------------------------------------
    # Shared VASP input writer
    # ------------------------------------------------------------------

    @staticmethod
    def _write_vasp_inputs(
        calc_type: str,
        workdir: Path,
        structure_path: Optional[Path],
        prev_dir: Optional[Path],
        vasp_cfg: Any,                      # StageVaspConfig
        extra_settings: Optional[Dict[str, Any]] = None,
        lobsterin_settings: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write VASP input files for one task workdir.

        This is the **top of the write pipeline** inside the workflow layer.
        Call chain from here::

            _write_vasp_inputs()
                └─ FrontendAdapter.from_frontend_dict()   (flow/api.py)
                         └─ VaspWorkflowParams.to_workflow_config()
                                  └─ WorkflowEngine.run()  (flow/workflow_engine.py)
                                           └─ _write_*(config, incar_params, output_dir)
                                                    └─ InputSet.write_input()  (flow/input_sets/)

        Args:
            calc_type:          String name passed to FrontendAdapter
                                (e.g. ``"bulk_relax"``, ``"lobster"``).
            workdir:            Target directory; inputs are written here.
            structure_path:     Explicit path to a POSCAR/CONTCAR/CIF file.
                                Pass ``None`` to let the engine read from *prev_dir*.
            prev_dir:           Previous stage directory; used for WAVECAR/CHGCAR
                                copy-in and as fallback structure source.
            vasp_cfg:           ``StageVaspConfig`` instance carrying functional,
                                k-point density, and user INCAR overrides.
            extra_settings:     Additional INCAR key-value pairs merged on top of
                                ``vasp_cfg.user_incar_settings``.
            lobsterin_settings: Keys written to lobsterin, NOT INCAR.
                                ``cohpGenerator`` list is split into
                                overwritedict (first entry) + custom lines (rest).

        为单个任务工作目录写入 VASP 输入文件。

        这是工作流层写入流水线的**入口**。从此处开始的调用链::

            _write_vasp_inputs()
                └─ FrontendAdapter.from_frontend_dict()   (flow/api.py)
                         └─ VaspWorkflowParams.to_workflow_config()
                                  └─ WorkflowEngine.run()  (flow/workflow_engine.py)
                                           └─ _write_*(config, incar_params, output_dir)
                                                    └─ InputSet.write_input()  (flow/input_sets/)

        Args:
            calc_type:          传递给 FrontendAdapter 的字符串名称
                                （如 ``"bulk_relax"``、``"lobster"``）。
            workdir:            目标目录；输入文件将写入此处。
            structure_path:     POSCAR/CONTCAR/CIF 文件的显式路径。
                                传 ``None`` 让计算引擎从 *prev_dir* 读取结构。
            prev_dir:           前一阶段目录；用于复制 WAVECAR/CHGCAR 以及
                                作为备用结构来源。
            vasp_cfg:           携带泛函、k 点密度及用户 INCAR 覆盖项的
                                ``StageVaspConfig`` 实例。
            extra_settings:     合并到 ``vasp_cfg.user_incar_settings`` 之上的
                                额外 INCAR 键值对。
            lobsterin_settings: 写入 lobsterin 而非 INCAR 的键值对。
                                ``cohpGenerator`` 列表会被拆分为覆盖默认值的第一条
                                与作为原始行追加的其余条目。
        """
        from flow.api import FrontendAdapter
        from flow.workflow_engine import WorkflowEngine

        # Start with INCAR settings from config, then apply overrides.
        # 先取配置中的 INCAR 设置，再叠加覆盖项。
        settings: Dict[str, Any] = dict(vasp_cfg.user_incar_settings or {})
        if extra_settings:
            settings.update(extra_settings)

        # Build the frontend dict that FrontendAdapter understands.
        # 构建 FrontendAdapter 所识别的前端字典。
        frontend_dict: Dict[str, Any] = {
            "calc_type": calc_type,
            "xc": vasp_cfg.functional,
            "kpoints": {"density": vasp_cfg.kpoints_density},
            "settings": settings,
        }

        # Resolve structure source: explicit file takes priority over prev_dir.
        # 解析结构来源：显式文件优先于 prev_dir。
        if structure_path is not None:
            frontend_dict["structure"] = {"source": "file", "id": str(structure_path)}
        elif prev_dir is not None:
            frontend_dict["structure"] = {"source": "file", "id": str(prev_dir)}

        if prev_dir is not None:
            frontend_dict["prev_dir"] = str(prev_dir)

        # Thread lobsterin customisation through to FrontendAdapter / WorkflowEngine.
        # 将 lobsterin 自定义项传递给 FrontendAdapter / WorkflowEngine。
        ls = dict(lobsterin_settings or getattr(vasp_cfg, "lobsterin_settings", None) or {})
        if ls:
            cohp_gen = ls.pop("cohpGenerator", None)
            if ls:
                frontend_dict["lobsterin"] = ls
            if cohp_gen:
                # First entry replaces pymatgen-generated default; extras appended as raw lines.
                # 第一条替换 pymatgen 生成的默认值；其余条目作为原始行追加。
                if isinstance(cohp_gen, list) and cohp_gen:
                    frontend_dict["lobsterin"] = dict(frontend_dict.get("lobsterin") or {})
                    frontend_dict["lobsterin"]["cohpGenerator"] = cohp_gen[0]
                    if len(cohp_gen) > 1:
                        frontend_dict["lobsterin_custom_lines"] = [
                            f"cohpGenerator {g}" for g in cohp_gen[1:]
                        ]
                else:
                    frontend_dict["lobsterin"] = dict(frontend_dict.get("lobsterin") or {})
                    frontend_dict["lobsterin"]["cohpGenerator"] = str(cohp_gen)

        params = FrontendAdapter.from_frontend_dict(frontend_dict)
        # Redirect output to the task-specific workdir.
        # 将输出重定向到任务专属工作目录。
        params.output_dir = workdir
        # Disable script generation here: the workflow layer uses its own
        # PBS template (pbs_hook.sh.tpl) rendered by pbs.py, not Script class.
        # 此处禁用脚本生成：工作流层使用自己的 PBS 模板（pbs_hook.sh.tpl），
        # 由 pbs.py 渲染，与 Script 类无关。
        WorkflowEngine().run(params.to_workflow_config(), generate_script=False)
        logger.debug("Wrote %s inputs to %s", calc_type, workdir)
