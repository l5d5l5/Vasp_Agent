# Flow Workflow — 部署手册

> **定位：** 本文档面向首次在集群上部署 `flow.workflow` 的用户，按步骤说明从代码安装到首次提交计算任务的全过程，以及日常运维操作。
>
> **配套文档：**
> - `WORKFLOW_TUTORIAL.md` — params.yaml 完整字段说明、阶段逻辑、CLI 命令、错误排查
> - `../VASP_INPUT_TUTORIAL.md` — VASP 输入文件生成逻辑（flow 核心层）

---

## 目录

1. [系统要求](#1-系统要求)
2. [安装 Python 环境](#2-安装-python-环境)
3. [部署代码](#3-部署代码)
4. [配置集群环境变量](#4-配置集群环境变量)
5. [建立项目目录结构](#5-建立项目目录结构)
6. [编写 params.yaml](#6-编写-paramsyaml)
7. [定制 PBS 模板](#7-定制-pbs-模板-pbs_hookshtpl)
8. [首次运行验证](#8-首次运行验证)
9. [提交计算任务](#9-提交计算任务)
10. [自动推进下游任务](#10-自动推进下游任务)
11. [运维命令速查](#11-运维命令速查)
12. [卸载与迁移](#12-卸载与迁移)

---

## 1. 系统要求

| 组件 | 要求 |
|------|------|
| Python | 3.10+（使用 `match`/`case` 语法） |
| 作业调度器 | PBS/Torque（`qsub`、`qstat` 需在 `$PATH`） |
| VASP | 可从 PBS 节点访问（路径硬编码在 PBS 模板中） |
| 操作系统 | Linux（集群计算节点） |
| 必要 Python 包 | `pymatgen`, `ase`, `jinja2`, `pyyaml`, `scipy`, `numpy` |
| 可选 | LOBSTER 二进制（LOBSTER 阶段需要）、NBO7 二进制（NBO 阶段需要） |

> **重要：** Python 必须 ≥ 3.10，`match`/`case` 在 3.9 及以下会报语法错误。

---

## 2. 安装 Python 环境

推荐使用 Conda 管理独立环境：

```bash
# 若集群已有 Anaconda/Miniconda，直接创建环境
conda create -n workflow python=3.11 -y
conda activate workflow

# 安装依赖（pymatgen 体积较大，约需 5–10 分钟）
pip install pymatgen ase jinja2 pyyaml scipy numpy
```

验证 Python 版本：

```bash
python --version   # 必须 >= 3.10
```

记录完整 Python 路径，后续 params.yaml 和 PBS 模板均需要：

```bash
which python
# 示例输出：/data2/home/luodh/anaconda3/envs/workflow/bin/python
```

---

## 3. 部署代码

```bash
# 克隆代码库到集群家目录（或 /data 分区）
git clone <repo_url> /data2/home/luodh/high-calc-2
cd /data2/home/luodh/high-calc-2

# 以可编辑模式安装（从 flow/ 子目录执行）
cd flow
pip install -e .
cd ..
```

安装后验证模块可导入：

```bash
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
cd /data2/home/luodh/high-calc-2

$PYTHON -c "from flow.workflow import hook; print('hook OK')"
$PYTHON -c "from flow.workflow.stages import STAGE_ORDER; print(STAGE_ORDER)"
$PYTHON -c "from flow.workflow.config import load_config; print('config OK')"
```

全部输出不报错即为成功。

---

## 4. 配置集群环境变量

在 `~/.bashrc`（或集群 module 加载脚本）中添加以下内容：

```bash
# ── LOBSTER 可执行文件路径（启用 *_lobster 阶段时必须设置）
export LOBSTER_BIN=/path/to/lobster

# ── NBO 可执行文件路径（启用 *_nbo 阶段时必须设置）
export NBO_BIN=/path/to/nbo7
```

使改动立即生效：

```bash
source ~/.bashrc
echo $LOBSTER_BIN   # 应显示路径
lobster --version   # 应能正常运行
```

> **说明：** 二进制路径**不在** `params.yaml` 中配置，而是通过 shell 环境变量传递给 PBS 节点。确保 PBS 作业的环境也能继承这些变量（通常在 PBS 模板中 `source ~/.bashrc` 即可）。

---

## 5. 建立项目目录结构

推荐的项目目录布局（按 params.yaml 的命名惯例）：

```
/data2/home/luodh/high-calc-2/          ← project_root
├── flow/                               ← 代码库（pip install -e . 已安装）
│   └── workflow/
│       ├── params.yaml                 ← 工作流配置（你需要编辑此文件）
│       ├── pbs_hook.sh.tpl             ← PBS 模板（你需要定制此文件）
│       ├── WORKFLOW_TUTORIAL.md
│       └── DEPLOYMENT.md              ← 本文件
├── structure/                          ← 输入体相结构文件
│   ├── POSCAR_PtSnCu
│   ├── POSCAR_Fe3O4
│   └── ...
└── runs/                               ← run_root（由工作流自动创建）
    ├── manifest.json
    ├── _generated_slabs/
    ├── _generated_ads/
    ├── bulk_relax/
    ├── slab_relax/
    └── adsorption/
```

创建结构目录并放入 POSCAR：

```bash
mkdir -p /data2/home/luodh/high-calc-2/structure

# 文件命名规则：POSCAR_<id>、CONTCAR_<id>、POSCAR.<id>、CONTCAR.<id>
# <id> 将成为所有计算阶段的目录名
cp my_bulk.vasp /data2/home/luodh/high-calc-2/structure/POSCAR_PtSnCu
```

---

## 6. 编写 params.yaml

`params.yaml` 位于 `flow/workflow/params.yaml`（也可放任意路径，用 `--params` 指定）。

以下是最小可用配置示例，按实际情况替换路径：

```yaml
# ── 项目路径（必填）
project:
  project_root: /data2/home/luodh/high-calc-2
  run_root:     /data2/home/luodh/high-calc-2/runs

# ── PBS 调度器设置
pbs:
  queue:           low
  ppn:             72
  walltime:        "124:00:00"
  job_name_prefix: high_calc
  template_file:   /data2/home/luodh/high-calc-2/flow/workflow/pbs_hook.sh.tpl

# ── Python 运行时（PBS 节点上激活 conda 环境）
python_runtime:
  conda_sh:   /data2/home/luodh/anaconda3/etc/profile.d/conda.sh
  conda_env:  workflow
  python_bin: /data2/home/luodh/anaconda3/envs/workflow/bin/python

# ── 体相结构目录
structure: /data2/home/luodh/high-calc-2/structure

# ── 启用的计算阶段（按需开启）
workflow:
  stages:
    bulk_relax:         true
    bulk_dos:           false
    bulk_lobster:       false
    bulk_nbo:           false
    slab_relax:         true
    slab_dos:           false
    slab_lobster:       false
    slab_nbo:           false
    adsorption:         true
    adsorption_freq:    true
    adsorption_lobster: false
    adsorption_nbo:     false

# ── 体相弛豫 VASP 参数
bulk:
  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 50
    user_incar_settings:
      NPAR: 4

# ── 板面切割参数
slab:
  miller_list: [[1,1,0], [1,1,1]]
  slabgen:
    target_layers: 5
    vacuum_thickness: 15
    fix_bottom_layers: 2
  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 25
    auto_dipole: true

# ── 吸附物放置参数
adsorption:
  build:
    mode: "site"
    molecule_formula: "CO"
    site_type: "ontop"
    height: 1.8
    reorient: true
    find_args:
      positions: ["ontop"]
  vasp:
    functional: "BEEF"
    is_metal: true
    kpoints_density: 25
    auto_dipole: true

# ── 振动频率参数
freq:
  vasp:
    functional: "BEEF"
    kpoints_density: 25
  settings:
    mode: "adsorbate"
    adsorbate_formula: "CO"
    adsorbate_formula_prefer: "tail"
```

> **完整字段说明** 见 `WORKFLOW_TUTORIAL.md` §4。

验证 params.yaml 可以正常加载：

```bash
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
cd /data2/home/luodh/high-calc-2
$PYTHON -c "
from flow.workflow.config import load_config
cfg = load_config('flow/workflow/params.yaml')
print('project_root:', cfg.project.project_root)
print('run_root:    ', cfg.project.run_root)
print('enabled stages:', [s.value for s in __import__('flow.workflow.stages', fromlist=['STAGE_ORDER']).STAGE_ORDER if getattr(cfg.workflow, s.value, False)])
"
```

---

## 7. 定制 PBS 模板（pbs_hook.sh.tpl）

PBS 模板位于 `flow/workflow/pbs_hook.sh.tpl`。其中**硬编码了集群相关参数**，需要按你的集群修改：

```bash
# ── 需要按集群实际情况修改的部分（文件头部硬编码区）──────────────────────────
VER=5.4.4                          # VASP 版本
TYPE2=std                          # VASP 构建类型（std / gam / ncl）
OPT=2                              # 优化等级
COMPILER=2020u2                    # Intel 编译器版本
IMPIVER=2019.8.254                 # Intel MPI 版本
VASPHOME=/data/software/vasp/compile/   # VASP 安装目录
VDW_KERNEL=/data/software/vasp/compile/vdw_kernel.bindat  # vdw_kernel 文件路径
```

`TYPE1` 由 `params.yaml` 中各阶段的 `functional` 字段自动推导，**无需手动修改**：

| `params.yaml` 中填写的 `functional` | `TYPE1` 值 | 说明 |
|---|---|---|
| `BEEF` | `"beef"` | BEEF-vdW 泛函，含色散修正 |
| `PBE`（默认）/ `SCAN` / `PBE0` / `HSE` | `"org"` | 标准 GGA / meta-GGA / 杂化泛函 |

> **关于 BEEFVTST / VTST**：这两者**不是独立的 DFT 泛函**，而是 PBS 脚本的 `TYPE1` 标签，用于选择带 VTST 补丁的 VASP 可执行文件（NEB / DIMER 过渡态计算专用）。`params.yaml` 中只需填写 `BEEF` 或 `PBE`（默认），系统会在脚本层面自动处理，无需用户干预。

其余 Jinja2 占位符（`{{ job_name }}`、`{{ ppn }}`、`{{ conda_sh }}` 等）由 `hook.py` 在运行时自动填充，**不要手动修改**。

修改模板后，建议先用 dry-run 测试模板渲染：

```bash
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
$PYTHON -c "
from flow.workflow.config import load_config
from flow.workflow.pbs import render_template
cfg = load_config('flow/workflow/params.yaml')
# 模拟一个 bulk_relax 任务的模板渲染
ctx = {
    'job_name': 'test_job_abc123',
    'ppn': cfg.pbs.ppn,
    'walltime': cfg.pbs.walltime,
    'queue': cfg.pbs.queue,
    'TYPE1': 'org',
    'stage': 'bulk_relax',
    'workdir': '/tmp/test_workdir',
    'params_file': 'flow/workflow/params.yaml',
    'hook_script': 'flow/workflow/hook.py',
    'conda_sh': cfg.python_runtime.conda_sh or '',
    'conda_env': cfg.python_runtime.conda_env or '',
    'python_bin': cfg.python_runtime.python_bin or '',
}
result = render_template(cfg.pbs.template_file, ctx)
print(result[:500])  # 只打印前500字符检查格式
print('--- template render OK ---')
"
```

---

## 8. 首次运行验证

### 步骤 1 — 展开 manifest（不提交任何作业）

```bash
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python
PARAMS=/data2/home/luodh/high-calc-2/flow/workflow/params.yaml
cd /data2/home/luodh/high-calc-2

$PYTHON -m flow.workflow.hook --params $PARAMS expand
```

检查 manifest：

```bash
# 查看生成了哪些任务
python -m json.tool runs/manifest.json | grep '"stage"' | sort | uniq -c

# 预期输出（假设结构目录有 2 个文件）：
#      2 "stage": "bulk_relax"
# slab_relax / adsorption 此时不会出现（gate 未满足）
```

### 步骤 2 — 生成并检查一个作业的输入文件（不提交）

```bash
# 查看将要写入的输入文件内容
cat runs/bulk_relax/PtSnCu/INCAR
cat runs/bulk_relax/PtSnCu/KPOINTS
head -5 runs/bulk_relax/PtSnCu/POSCAR
```

> **此时输入文件还未存在**，因为 `expand` 只更新 `manifest.json`，实际的 VASP 输入文件在 `auto`/`submit-all` 提交时由 `prepare()` 生成。

### 步骤 3 — 提交第一批作业

```bash
# 提交所有 bulk_relax 任务
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all --stage bulk_relax

# 或者逐个提交（测试时更安全）
$PYTHON -m flow.workflow.hook --params $PARAMS auto --stage bulk_relax
```

提交后检查：

```bash
qstat -u $USER                   # 确认作业出现在 PBS 队列中
ls runs/bulk_relax/PtSnCu/       # 确认 INCAR、KPOINTS、POSCAR、job.pbs、submitted.json 已生成
cat runs/bulk_relax/PtSnCu/submitted.json
```

---

## 9. 提交计算任务

### 标准流程（逐阶段推进）

```bash
PARAMS=/data2/home/luodh/high-calc-2/flow/workflow/params.yaml
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python

# 第 1 轮：提交体相弛豫
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all --stage bulk_relax

# ── 等待 PBS 作业完成 ──────────────────────────────────────────────────────
# 作业完成后，PBS epilogue (pbs_hook.sh.tpl) 自动写入 done.ok
# 也可手动标记：
$PYTHON -m flow.workflow.hook --params $PARAMS mark-done \
    --workdir runs/bulk_relax/PtSnCu

# 第 2 轮：展开 manifest（此时 slab_relax 任务会出现），提交
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all

# ── 重复以上流程直到所有阶段完成 ─────────────────────────────────────────
```

### 一次性提交所有已就绪任务（无 stage 过滤）

```bash
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all
```

### 限制单次提交数量（避免占用过多队列资源）

```bash
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all --limit 10
```

### 重新提交已提交的任务（队列被管理员清空后）

```bash
# submitted.json 已存在但作业已被杀 → 用 --resubmit 跳过已提交检查
$PYTHON -m flow.workflow.hook --params $PARAMS auto --resubmit

# 已标记 done.ok 但需要重跑 → 用 --rerun-done（谨慎使用）
$PYTHON -m flow.workflow.hook --params $PARAMS auto --rerun-done
```

---

## 10. 自动推进下游任务

`pbs_hook.sh.tpl` 的结尾只调用 `mark-done`，不会自动调用 `auto`。
推进下游任务有两种方式：

### 方式 A — cron 定时任务（推荐）

在集群登录节点的 crontab 中添加（每 10 分钟检查一次）：

```bash
crontab -e
```

添加以下行（按实际路径修改）：

```
*/10 * * * * cd /data2/home/luodh/high-calc-2 && \
    /data2/home/luodh/anaconda3/envs/workflow/bin/python \
    -m flow.workflow.hook \
    --params /data2/home/luodh/high-calc-2/flow/workflow/params.yaml \
    submit-all >> ~/workflow_cron.log 2>&1
```

这样每 10 分钟自动展开 manifest 并提交所有就绪任务，无需手动干预。

### 方式 B — 在 PBS epilogue 末尾追加 auto（手动修改模板）

如果希望作业一完成就立即触发后续阶段，可在 `pbs_hook.sh.tpl` 末尾追加：

```bash
# 在 mark-done 调用之后添加：
"${PYTHON}" "${HOOK_SCRIPT}" --params "${PARAMS_FILE}" \
    auto >> "${LOG_FILE}" 2>&1
```

> **注意：** 此模式下多个 PBS epilogue 可能并发触发，但 `DirLock` 机制可防止重复提交。

### 方式 C — 手动运行（适合调试）

```bash
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all
```

---

## 11. 运维命令速查

### 查看任务状态

```bash
# 查看所有已完成任务
find runs/ -name done.ok | sort

# 查看所有已提交但未完成的任务
find runs/ -name submitted.json | sort

# 查看所有失败任务（超过重试上限）
find runs/ -name failed.json | sort

# 按阶段统计进度
python3 -c "
import json, os
from pathlib import Path
m = json.loads(Path('runs/manifest.json').read_text())
from collections import Counter
status = Counter()
for t in m['tasks'].values():
    w = Path(t['workdir'])
    if (w/'done.ok').exists():      status['done']      += 1
    elif (w/'failed.json').exists(): status['failed']    += 1
    elif (w/'submitted.json').exists(): status['running'] += 1
    else:                           status['pending']    += 1
print(dict(status))
"
```

### 提取计算结果（extract）

所有阶段完成后，用 `extract` 子命令解析 OUTCAR 并汇总能量：

```bash
PARAMS=flow/workflow/params.yaml
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python

# 默认以表格形式输出到终端
$PYTHON -m flow.workflow.hook --params $PARAMS extract

# 输出为 CSV 文件
$PYTHON -m flow.workflow.hook --params $PARAMS extract \
    --output results.csv --format csv

# 仅提取指定阶段
$PYTHON -m flow.workflow.hook --params $PARAMS extract \
    --stages bulk_relax,adsorption

# 提供分子参考能量，计算吸附能（可重复多次 --mol-ref）
$PYTHON -m flow.workflow.hook --params $PARAMS extract \
    --mol-ref CO=-14.78 --mol-ref H2=-6.77
```

| 选项 | 说明 |
|---|---|
| `--output FILE` | 输出文件路径；省略则输出到 stdout |
| `--format` | `table`（默认）/ `json` / `csv` |
| `--stages` | 逗号分隔的阶段过滤器；省略则提取所有阶段 |
| `--mol-ref FORMULA=eV` | 分子参考能量（可重复） |

---

### PBS 队列监控

```bash
qstat -u $USER             # 当前用户的作业
qstat -Q                   # 可用队列列表
qdel <job_id>              # 取消作业
```

### 批量标记已完成任务为 done

适用于集群重启或 PBS epilogue 未正常触发的情况：

```bash
PARAMS=flow/workflow/params.yaml
PYTHON=/data2/home/luodh/anaconda3/envs/workflow/bin/python

for stage in bulk_relax slab_relax adsorption; do
    for d in runs/${stage}/*/; do
        if [ -f "${d}OUTCAR" ] && [ ! -f "${d}done.ok" ]; then
            $PYTHON -m flow.workflow.hook --params $PARAMS \
                mark-done --workdir "${d}" 2>&1 | grep -v WARNING
        fi
    done
done

# 批量标记后推进下游
$PYTHON -m flow.workflow.hook --params $PARAMS submit-all
```

### 恢复失败任务

```bash
# 查看失败原因
cat runs/bulk_relax/PtSnCu/failed.json

# 修复问题后恢复（删除 failed.json 和 submitted.json，重新提交）
rm runs/bulk_relax/PtSnCu/failed.json
rm runs/bulk_relax/PtSnCu/submitted.json
$PYTHON -m flow.workflow.hook --params $PARAMS auto --stage bulk_relax
```

### 清除 stale DirLock

当进程崩溃后留下孤立锁目录：

```bash
# 查看锁目录及其持有者 PID
find runs/ -name ".lock" -type d | while read lock; do
    echo "Lock: $lock"
    cat "$lock/meta.json" 2>/dev/null
    echo ""
done

# 检查 PID 是否仍在运行（无输出表示进程已死）
# ps -p <pid>

# 若进程已死，手动删除锁
rm -rf runs/bulk_relax/PtSnCu/.lock
```

### 重置整个工作流（慎用）

```bash
# 只删除 marker 文件（保留 VASP 输入/输出），重新跑 auto 会跳过已收敛的作业
find runs/ -name "submitted.json" -delete
find runs/ -name "done.ok" -delete
find runs/ -name "failed.json" -delete
rm -f runs/manifest.json

$PYTHON -m flow.workflow.hook --params $PARAMS expand
```

---

## 12. 卸载与迁移

### 迁移到新集群

1. 拷贝代码库到新集群：
   ```bash
   rsync -av /data2/home/luodh/high-calc-2/ newcluster:/data2/.../high-calc-2/
   ```

2. 在新集群重新创建 conda 环境（§2）。

3. 更新 `params.yaml` 中的所有路径（`project_root`、`run_root`、`python_runtime.*`、`pbs.template_file`）。

4. 更新 `pbs_hook.sh.tpl` 中的硬编码集群路径（VASP 安装目录、编译器路径等，见 §7）。

5. 更新 `~/.bashrc` 中的 `LOBSTER_BIN`、`NBO_BIN`（如果路径发生变化）。

### 仅迁移数据（runs/ 目录）

`manifest.json` 使用的是绝对路径。迁移后需要更新 `manifest.json` 中的所有路径：

```bash
# 用 sed 批量替换旧路径前缀
OLD_ROOT=/data2/home/luodh/high-calc-2
NEW_ROOT=/data3/users/luodh/project

sed -i "s|${OLD_ROOT}|${NEW_ROOT}|g" runs/manifest.json
find runs/ -name "submitted.json" -o -name "done.ok" -o -name "failed.json" | \
    xargs sed -i "s|${OLD_ROOT}|${NEW_ROOT}|g"
```

---

*若在部署中遇到问题，首先检查 `WORKFLOW_TUTORIAL.md` §9 的错误排查手册。*
