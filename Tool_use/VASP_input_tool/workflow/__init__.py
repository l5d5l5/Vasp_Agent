"""
flow.workflow — orchestration layer for the VASP workflow.
flow.workflow — VASP 工作流编排层。

This package sits between params.yaml configuration and the per-stage
VASP input writers.  It owns the manifest-driven task graph, PBS job
submission, marker-file state machine, and result extraction.
本包位于 params.yaml 配置与各 stage VASP 输入写入器之间。
负责基于 manifest 的任务图管理、PBS 作业提交、标记文件状态机
以及结果提取功能。

Key public objects / 关键公共对象:
  load_config(path)             – load params.yaml → WorkflowConfig
                                  / 加载 params.yaml → WorkflowConfig
  expand_manifest(cfg)          – create/refresh manifest.json
                                  / 创建或刷新 manifest.json
  auto_submit_workflow(cfg)     – submit first eligible task
                                  / 提交第一个符合条件的任务
  submit_all_ready(cfg)         – submit all eligible tasks
                                  / 提交所有符合条件的任务
  mark_done_by_workdir(wd, cfg) – write done.ok after OUTCAR check
                                  / OUTCAR 检查通过后写入 done.ok
  STAGE_ORDER                   – canonical stage sequence list
                                  / 规范的 stage 顺序列表
"""
from flow.workflow.config import load_config
from flow.workflow.hook import (
    auto_submit_workflow,
    expand_manifest,
    mark_done_by_workdir,
    submit_all_ready,
)
from flow.workflow.stages import STAGE_ORDER

__all__ = [
    "load_config",
    "expand_manifest",
    "auto_submit_workflow",
    "submit_all_ready",
    "mark_done_by_workdir",
    "STAGE_ORDER",
]
