# VASP 输入文件生成教程

---

## 目录

- [第 1 节 — 环境配置](#第-1-节--环境配置)
- [第 2 节 — 所有计算类型用法](#第-2-节--所有计算类型用法)
- [第 3 节 — 高级用法与 FrontendAdapter](#第-3-节--高级用法与-frontendadapter)

---

# 第 1 节 — 环境配置

## 1.1 Python 版本

需要 Python **3.10 或更高版本**（代码使用 `match`/`case` 结构模式匹配）。

```bash
python --version   # 预期：Python 3.10.x 或更高
```

## 1.2 安装

```bash
conda create -n workflow python=3.11 -y
conda activate workflow
pip install -e .
```

## 1.3 必需环境变量

| 变量名 | 用途 | 何时必需 |
|---|---|---|
| `PMG_VASP_PSP_DIR` | VASP 赝势库路径（含 `potpaw_PBE/` 等子目录） | 写入文件时必须 |
| `FLOW_VDW_KERNEL` | `vdw_kernel.bindat` 的绝对路径 | 仅 `functional="BEEF"` 时必须 |

```bash
export PMG_VASP_PSP_DIR=/path/to/vasp/potentials
export FLOW_VDW_KERNEL=/path/to/vdw_kernel.bindat
```

永久配置（可选）：

```bash
pmg config --add PMG_VASP_PSP_DIR /path/to/vasp/potentials
```

## 1.4 外部软件说明

- **NEB / Dimer**：需要 **VTST 补丁版** VASP。
- **BEEF**：需要 **BEEF 补丁版** VASP；`vdw_kernel.bindat` 会被自动复制到输出目录。
- **LOBSTER**：需要单独安装 LOBSTER 程序；本工具仅生成 `lobsterin` 输入文件。

## 1.5 基本用法模式

所有计算类型统一使用 `WorkflowEngine` + `WorkflowConfig`：

```python
from flow.workflow_engine import WorkflowEngine, WorkflowConfig, CalcType

engine = WorkflowEngine()
engine.run(WorkflowConfig(
    calc_type=CalcType.BULK_RELAX,   # 也可传字符串 "bulk_relax"
    structure="/path/to/POSCAR",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={           # 最高优先级，始终覆盖所有默认值
        "ENCUT": 520,
        "NPAR":  4,
    },
    output_dir="01-bulk_relax/",
))
# 输出：POSCAR  INCAR  KPOINTS  POTCAR  submit.sh
```

`engine.run()` 返回输出目录的绝对路径字符串，并默认自动生成 PBS 脚本。

---

# 第 2 节 — 所有计算类型用法

**统一导入：**

```python
from flow.workflow_engine import WorkflowEngine, WorkflowConfig, CalcType

engine = WorkflowEngine()
```

**`prev_dir` 的自动行为（适用于所有支持它的计算类型）：**
1. 从 `prev_dir/CONTCAR`（优先）或 `prev_dir/POSCAR` 自动提取结构。
2. 通过 `from_prev_calc_ecat()` 继承 `prev_dir/INCAR` 中的 ENCUT、EDIFF 等参数。
3. 自动复制 WAVECAR / CHGCAR，并注入 `ISTART=1` / `ICHARG=1`。

**`user_incar_overrides` 中的参数具有最高优先级，始终覆盖所有默认值。**

---

## 计算类型速览

| `calc_type` | 说明 | 需要 `prev_dir` |
|---|---|---|
| `"bulk_relax"` | 体相弛豫（ISIF=3，晶胞+离子全弛豫） | 否 |
| `"slab_relax"` | slab 弛豫 / 吸附构型弛豫（ISIF=2，仅离子） | 否 |
| `"static_sp"` | 单点能 | 否 |
| `"static_dos"` | 单点 + 投影态密度（LORBIT=11，LCHARG=True） | 可选 |
| `"static_charge"` | 单点 + 全电荷密度（LAECHG=True，Bader 分析用） | 可选 |
| `"static_elf"` | 单点 + 电子局域函数（LELF=True） | 可选 |
| `"freq"` | 振动频率（有限差分，IBRION=5） | 可选 |
| `"freq_ir"` | 振动频率 + IR 强度（DFPT，IBRION=7，LEPSILON=True） | 可选 |
| `"lobster"` | COHP 化学键分析（LWAVE=True，ISYM=0） | 可选 |
| `"nmr_cs"` | NMR 化学位移（LCHIMAG=True） | 否 |
| `"nmr_efg"` | NMR 电场梯度（LEFG=True） | 否 |
| `"nbo"` | 自然键轨道分析 | 可选 |
| `"neb"` | NEB 过渡态搜索（需 VTST VASP） | 必须指定 `start_structure`/`end_structure` |
| `"dimer"` | Dimer 鞍点搜索（需 VTST VASP） | 必须指定 `prev_dir`（NEB 目录） |
| `"md_nvt"` | NVT 分子动力学（Nosé–Hoover） | 否 |
| `"md_npt"` | NPT 分子动力学（Langevin，MDALGO=3） | 否 |

---

## 2.1 `bulk_relax` — 体相结构弛豫

ISIF=3，晶胞形状 / 体积 / 离子位置全部自由弛豫。默认 PBE，ENCUT=520，EDIFFG=-0.02。

```python
engine.run(WorkflowConfig(
    calc_type="bulk_relax",
    structure="Fe2O3/POSCAR",
    functional="PBE",
    kpoints_density=50.0,       # 体相典型值 50 Å⁻¹
    user_incar_overrides={
        "EDIFFG": -0.02,        # 力收敛判据（eV/Å）
        "ENCUT":  520,          # 平面波截断能（eV）
        "ISMEAR": 1,            # Methfessel-Paxton 展宽（金属）
        "SIGMA":  0.2,
        "ISPIN":  2,
        "MAGMOM": {"Fe": 5.0, "O": 0.0},  # per-element；ISPIN=2 由 MAGMOM 自动注入，但显式更安全
        "LMAXMIX": 4,
        "LDAU":    True,
        "LDAUTYPE": 2,
        "LDAUU":   {"Fe": 4.0, "O": 0.0},
        "LDAUL":   {"Fe": 2,   "O": -1},
        "LDAUJ":   {"Fe": 0.0, "O": 0.0},
        "NPAR":   4,
        "KPAR":   2,
    },
    output_dir="01-bulk_relax/",
))
```

**`MAGMOM` 两种格式：**

```python
# per-element dict（推荐；ISPIN=2 由引擎自动注入）
"MAGMOM": {"Fe": 5.0, "O": 0.0}

# per-site list（与 POSCAR 原子顺序一一对应；引擎自动转换并注入 ISPIN=2）
"MAGMOM": [5.0, 5.0, 5.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
```

> **注意**：使用 per-element dict 时，若 MAGMOM 在 merged INCAR 中存在且用户未显式设置
> `ISPIN`，引擎会自动注入 `ISPIN=2`。建议仍然显式写入以避免歧义。

---

## 2.2 `slab_relax` — 表面 slab / 吸附构型弛豫

ISIF=2，仅弛豫离子位置，晶胞固定。

```python
engine.run(WorkflowConfig(
    calc_type="slab_relax",
    structure="Fe3O4_CO_slab/POSCAR",
    functional="PBE",
    kpoints_density=25.0,       # 表面计算典型值 25 Å⁻¹
    user_incar_overrides={
        "EDIFFG": -0.03,
        "ISPIN":  2,
        "MAGMOM": {"Fe": 4.0, "O": 0.0, "C": 0.0},
        "LDAU":   True,
        "LDAUTYPE": 2,
        "LDAUU":  {"Fe": 3.8, "O": 0.0, "C": 0.0},
        "LDAUL":  {"Fe": 2,   "O": -1,  "C": -1},
        "LDAUJ":  {"Fe": 0.0, "O": 0.0, "C": 0.0},
        "LDIPOL": True,         # 偶极校正（用于带有真空层的 slab）
        "IDIPOL": 3,            # 沿 z 轴方向
        "LVHAR":  True,         # 输出静电势（用于计算功函数）
        "NPAR":   4,
    },
    output_dir="02-slab_relax/",
))
```

---

## 2.3 `static_sp` — 单点能

NSW=0，IBRION=-1，固定几何结构计算总能量。

```python
engine.run(WorkflowConfig(
    calc_type="static_sp",
    structure="Fe2O3_relax/CONTCAR",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "EDIFF":  1e-7,         # 更紧的电子收敛判据
        "ENCUT":  520,
        "ISMEAR": -5,           # 四面体方法（绝缘体 / 半导体）
        "SIGMA":  0.05,
        "NPAR":   4,
    },
    output_dir="03-static_sp/",
))
```

---

## 2.4 `static_dos` — 投影态密度

自动设置 LCHARG=True、LORBIT=11、NEDOS=2000。提供 `prev_dir` 时自动继承 INCAR/KPOINTS 并提取结构。

```python
engine.run(WorkflowConfig(
    calc_type="static_dos",
    prev_dir="01-bulk_relax/",      # 自动从 CONTCAR 提取结构；继承 INCAR
    functional="PBE",
    kpoints_density=80.0,           # DOS 积分需要更密的 K 网格
    user_incar_overrides={
        "NEDOS":  4001,             # 更细的能量网格
        "EMIN":   -15.0,
        "EMAX":    15.0,
        "ISMEAR": -5,
        "NPAR":   4,
    },
    output_dir="04-static_dos/",
))
```

---

## 2.5 `static_charge` — 全电荷密度

自动设置 LCHARG=True、LAECHG=True，输出 CHGCAR / AECCAR0 / AECCAR2（Bader 分析所需）。

```python
engine.run(WorkflowConfig(
    calc_type="static_charge",
    prev_dir="01-bulk_relax/",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "ENCUT":  520,
        "EDIFF":  1e-6,
        "NPAR":   4,
    },
    output_dir="05-static_charge/",
))
```

---

## 2.6 `static_elf` — 电子局域函数

自动设置 LELF=True，输出 ELFCAR。

```python
engine.run(WorkflowConfig(
    calc_type="static_elf",
    prev_dir="01-bulk_relax/",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "ENCUT":  520,
        "EDIFF":  1e-6,
        "NPAR":   4,
    },
    output_dir="06-static_elf/",
))
```

---

## 2.7 `freq` / `freq_ir` — 振动频率 / IR 强度

两种计算类型直接通过 `calc_type` 字符串区分：

| `calc_type` | 方法 | 自动注入的 INCAR |
|---|---|---|
| `"freq"` | 有限差分 | `IBRION=5` |
| `"freq_ir"` | DFPT | `IBRION=7`、`LEPSILON=True`、`NWRITE=3` |

提供 `prev_dir` 时继承 INCAR 并从 CONTCAR 读取结构（含选择性动力学标志）。

```python
# 有限差分频率（IBRION=5 自动设置）
engine.run(WorkflowConfig(
    calc_type="freq",
    prev_dir="02-slab_relax/",
    functional="PBE",
    kpoints_density=25.0,
    user_incar_overrides={
        "POTIM": 0.015,     # 有限差分步长（Å）
        "NFREE": 2,         # 每个原子的位移次数（2=±δ）
        "NPAR":  4,
    },
    output_dir="07-freq/",
))

# DFPT 频率 + IR 强度（IBRION=7 / LEPSILON=True / NWRITE=3 自动注入）
engine.run(WorkflowConfig(
    calc_type="freq_ir",
    prev_dir="02-slab_relax/",
    functional="PBE",
    kpoints_density=25.0,
    user_incar_overrides={
        "POTIM": 0.015,
        "NFREE": 2,
        "NPAR":  4,
        # 勿手动设置 IBRION / LEPSILON / NWRITE，由 calc_type 自动注入
    },
    output_dir="07-freq_ir/",
))
```

**精确指定参与振动的原子索引（`vibrate_indices`）：**

```python
engine.run(WorkflowConfig(
    calc_type=CalcType.FREQ,
    prev_dir="02-slab_relax/",
    functional="PBE",
    kpoints_density=25.0,
    vibrate_indices=[12, 13, 14],   # 0-based 索引；None = 使用选择性动力学标志
    user_incar_overrides={"POTIM": 0.015, "NFREE": 2, "NPAR": 4},
    output_dir="07-freq/",
))
```

---

## 2.8 `lobster` — COHP 化学键分析

自动设置 LWAVE=True、ISYM=0、NSW=0。提供 `prev_dir` 时自动复制 WAVECAR（LOBSTER 后处理所需）。

```python
engine.run(WorkflowConfig(
    calc_type="lobster",
    prev_dir="02-slab_relax/",
    functional="PBE",
    kpoints_density=50.0,
    user_incar_overrides={
        "ISPIN":  2,
        "MAGMOM": {"Fe": 5.0, "O": 0.0, "C": 0.0},
        "LDAU":   True,
        "LDAUTYPE": 2,
        "LDAUU":  {"Fe": 4.0, "O": 0.0, "C": 0.0},
        "LDAUL":  {"Fe": 2,   "O": -1,  "C": -1},
        "LDAUJ":  {"Fe": 0.0, "O": 0.0, "C": 0.0},
        "ENCUT":  520,
        "NPAR":   4,
        "KPAR":   2,
    },
    lobster_overwritedict={
        "COHPstartEnergy": -20.0,
        "COHPendEnergy":    20.0,
        "cohpGenerator": "from 1.8 to 2.3 type Fe type O orbitalwise",
    },
    lobster_custom_lines=[
        "cohpGenerator from 1.1 to 1.5 type C type O orbitalwise",
    ],
    output_dir="08-lobster/",
))
```

**`lobster_overwritedict` / `lobster_custom_lines` 说明：**
- `lobster_overwritedict`：覆盖 pymatgen 自动生成的 lobsterin 键值对（第一条 `cohpGenerator` 在此设置）。
- `lobster_custom_lines`：逐字追加到 lobsterin 文件末尾的行列表（用于多条 `cohpGenerator`）。
- 不传两者则 pymatgen 根据结构最短键长自动生成 lobsterin。

---

## 2.9 `nmr_cs` / `nmr_efg` — NMR 计算

`nmr_cs`：设置 LCHIMAG=True（化学位移）。`nmr_efg`：设置 LEFG=True（电场梯度）。  
NMR 需要较密的 K 网格（引擎自动将 kpoints_density 下限设为 100）。

```python
# NMR 化学位移
engine.run(WorkflowConfig(
    calc_type="nmr_cs",
    structure="Li3PO4/POSCAR",
    functional="PBE",
    kpoints_density=100.0,
    user_incar_overrides={
        "ENCUT":   600,
        "EDIFF":   1e-8,
        "NPAR":    4,
    },
    output_dir="09-nmr_cs/",
))

# NMR 电场梯度（指定同位素）
engine.run(WorkflowConfig(
    calc_type="nmr_efg",
    structure="Li3PO4/POSCAR",
    functional="PBE",
    kpoints_density=100.0,
    isotopes=["Li-7", "P-31"],   # 用于四极耦合常数计算
    user_incar_overrides={
        "ENCUT": 600,
        "EDIFF": 1e-8,
        "NPAR":  4,
    },
    output_dir="09-nmr_efg/",
))
```

---

## 2.10 `nbo` — 自然键轨道分析

提供 `prev_dir` 时继承 INCAR / KPOINTS 并从 CONTCAR 提取结构。

```python
engine.run(WorkflowConfig(
    calc_type="nbo",
    prev_dir="01-bulk_relax/",
    functional="PBE",
    kpoints_density=50.0,
    nbo_config={
        "basis_source": "ANO-RCC-MB",   # 默认基组；或 "custom" + custom_basis_path
        "occ_1c": 1.60,
        "occ_2c": 1.85,
    },
    user_incar_overrides={
        "ENCUT":  520,
        "EDIFF":  1e-6,
        "LWAVE":  True,         # NBO 后处理需要 WAVECAR
        "NPAR":   4,
    },
    output_dir="10-nbo/",
))
```

---

## 2.11 `neb` — NEB 过渡态搜索

需要 VTST 补丁版 VASP。通过 `start_structure` / `end_structure` 指定起末态。  
输出结构：`neb_run/00/`、`01/`、…、`NN/`，每个子目录包含一个 image 的 POSCAR / INCAR / KPOINTS / POTCAR。

```python
engine.run(WorkflowConfig(
    calc_type=CalcType.NEB,
    start_structure="IS_relax/CONTCAR",   # 初态结构
    end_structure="FS_relax/CONTCAR",     # 末态结构
    n_images=6,                           # 中间 image 数量
    use_idpp=True,                        # True=IDPP 内插；False=线性内插
    functional="PBE",
    kpoints_density=25.0,
    user_incar_overrides={
        "SPRING": -5,   # NEB 弹簧常数（eV/Å²）
        "NPAR":    4,
    },
    output_dir="11-neb/",
))
```

---

## 2.12 `dimer` — Dimer 鞍点搜索

需要 VTST 补丁版 VASP。`prev_dir` 必须指向一个已完成的 NEB 目录，引擎自动从中提取鞍点几何结构和 MODECAR。

```python
engine.run(WorkflowConfig(
    calc_type=CalcType.DIMER,
    prev_dir="11-neb/",         # 已完成的 NEB 目录，自动提取鞍点 + MODECAR
    functional="PBE",
    kpoints_density=25.0,
    user_incar_overrides={
        "SPRING": -5,
        "NPAR":    4,
    },
    output_dir="12-dimer/",
))
```

---

## 2.13 `md_nvt` / `md_npt` — 分子动力学

`md_nvt`：Nosé–Hoover 恒温器（MDALGO=2）。`md_npt`：Langevin 恒温 + 恒压（MDALGO=3）。

温度、步数、时间步通过 `WorkflowConfig` 的专用字段设置，**不要**通过 `user_incar_overrides` 设置 TEBEG/TEEND/NSW/POTIM（这些由 `MDSetEcat` 内部根据专用参数自动生成）。

```python
# NVT — 恒温分子动力学
engine.run(WorkflowConfig(
    calc_type=CalcType.MD_NVT,
    structure="Fe_bulk/POSCAR",
    functional="PBE",
    kpoints_density=1.0,        # MD 通常用 Gamma 点
    start_temp=1000.0,          # 起始温度（K）→ TEBEG
    end_temp=1000.0,            # 终止温度（K）→ TEEND；等于 start_temp = 等温
    nsteps=10000,               # 总 MD 步数 → NSW
    time_step=2.0,              # 时间步（fs）→ POTIM；含 H 时建议 0.5 fs
                                # None = 自动判断：含 H → 0.5 fs，否则 2.0 fs
    user_incar_overrides={
        "MAGMOM": {"Fe": 2.5},
        "ISPIN":  2,
        "NPAR":   4,
    },
    output_dir="13-md_nvt/",
))

# NPT — 恒温恒压分子动力学
engine.run(WorkflowConfig(
    calc_type=CalcType.MD_NPT,
    structure="Fe_bulk/POSCAR",
    functional="PBE",
    kpoints_density=1.0,
    start_temp=300.0,
    end_temp=300.0,
    nsteps=5000,
    time_step=2.0,
    user_incar_overrides={
        "PSTRESS": 0.0,         # 外压（kB）；0 = 零压 NPT
        "NPAR":    4,
    },
    output_dir="13-md_npt/",
))
```

**NPT 专项说明：**
- `LANGEVIN_GAMMA` 由 `MDSetEcat` 内部自动设置为 `[10.0] * n_elems`（各元素相同）。
- NPT 的 `ENCUT` 在 `write_input()` 后自动从 POTCAR 读取 ENMAX 并乘以 1.5（消除 Pulay 应力），无需手动设置。
- `spin_polarized=True` 效果等同于在 `user_incar_overrides` 中设置 `ISPIN=2`，但直接设置 `ISPIN` 更明确。

运行完成后输出：`XDATCAR`（轨迹）、`OSZICAR`（每步能量）、`OUTCAR`。

---

## 2.14 BEEF 泛函使用说明

`"BEEF"` 与所有 `calc_type` 兼容。使用前需设置 `FLOW_VDW_KERNEL` 环境变量，`vdw_kernel.bindat` 会被自动复制到输出目录。

```python
# BEEF 泛函与任意 calc_type 均可配合使用
engine.run(WorkflowConfig(calc_type="bulk_relax",  structure="Fe/POSCAR",  functional="BEEF", output_dir="out/"))
engine.run(WorkflowConfig(calc_type="slab_relax",  structure="Pt/POSCAR",  functional="BEEF", kpoints_density=25.0, output_dir="out/"))
engine.run(WorkflowConfig(calc_type="static_dos",  prev_dir="relax/",      functional="BEEF", output_dir="out/"))
engine.run(WorkflowConfig(calc_type="lobster",      prev_dir="relax/",      functional="BEEF", output_dir="out/"))
```

---

## 2.15 不生成脚本 / 自定义资源

```python
# 不生成 PBS 脚本（仅写 VASP 输入文件）
engine.run(config, generate_script=False)

# 生成脚本并指定资源
engine.run(config, generate_script=True, cores=72, walltime=200)  # walltime 单位：小时
```

---

# 第 3 节 — 高级用法与 FrontendAdapter

`WorkflowEngine` + `WorkflowConfig` 是面向用户的主要接口。对于需要从非结构化字典（如 Web 前端表单数据）创建配置的场景，可使用 `FrontendAdapter`。

## 3.1 FrontendAdapter — 从前端字典构建参数

`FrontendAdapter.from_frontend_dict(data)` 接受一个扁平字典，解析所有子模块参数，返回 `VaspWorkflowParams`；再调用 `.to_workflow_config()` 转为引擎格式。

```python
from flow.api import FrontendAdapter
from flow.workflow_engine import WorkflowEngine

data = {
    "calc_type": "bulk_relax",
    "xc": "PBE",                          # 或 "functional": "PBE"
    "kpoints": {"density": 50.0},
    "structure": {
        "source": "file",
        "id": "/path/to/POSCAR",
    },
    "settings": {
        # 精度参数（单独提取）
        "ENCUT": 520,
        "EDIFF": 1e-5,
        "EDIFFG": -0.02,
        # MAGMOM（支持 per-element dict / per-site list / VASP 字符串）
        "MAGMOM": {"Fe": 5.0, "O": 0.0},
        # DFT+U
        "LDAUU": {"Fe": 4.0, "O": 0.0},
        "LDAUL": {"Fe": 2,   "O": -1},
        "LDAUJ": {"Fe": 0.0, "O": 0.0},
        # 其他 INCAR 参数（透传为 custom_incar → user_incar_overrides）
        "ISMEAR": 1,
        "SIGMA":  0.2,
        "NPAR":   4,
    },
    "prev_dir": None,
    "output_dir": "/path/to/output",
}

params = FrontendAdapter.from_frontend_dict(data)
config = params.to_workflow_config()
WorkflowEngine().run(config)
```

## 3.2 前端字典与 WorkflowConfig 字段对应关系

| 前端字典键 | 等价的 `WorkflowConfig.user_incar_overrides` 键 |
|---|---|
| `settings["MAGMOM"] = {"Fe": 5.0}` | `"MAGMOM": {"Fe": 5.0}` + 自动注入 `"ISPIN": 2` |
| `settings["MAGMOM"] = [5.0, 5.0, 0.4]` | `"MAGMOM": [5.0, 5.0, 0.4]`（引擎自动转换格式） |
| `settings["LDAUU"] = {"Fe": 4.0}` | `"LDAU": True` + `"LDAUTYPE": 2` + `"LDAUU": {"Fe": 4.0}` + … |
| `settings["ENCUT"] = 520` | `"ENCUT": 520`（通过 PrecisionParams 处理） |
| `settings["NPAR"] = 4` | `"NPAR": 4`（直接并入 custom_incar） |

## 3.3 VaspAPI — 一步运行工作流

`VaspAPI` 封装了 FrontendAdapter → WorkflowEngine 的完整调用链：

```python
from flow.api import FrontendAdapter, VaspAPI

params = FrontendAdapter.from_frontend_dict(data)
params.output_dir = "/path/to/output"

api = VaspAPI()
result = api.run_workflow(params, generate_script=True)
# result: {"success": True, "output_dir": "...", "calc_type": "bulk_relax"}
```

## 3.4 磁矩（MAGMOM）——直接通过 WorkflowConfig

`WorkflowConfig` 中磁矩直接写入 `user_incar_overrides`，引擎内部的 `_apply_magmom_compat` 自动处理格式转换。

支持三种等价写法：

```python
engine.run(WorkflowConfig(
    calc_type="slab_relax",
    structure="Fe110/POSCAR",
    user_incar_overrides={
        # 写法 1（推荐）：per-element dict，键为元素符号
        "MAGMOM": {"Fe": 5.0, "O": 0.4},
        "ISPIN":  2,    # 推荐显式设置

        # 写法 2：per-site list，顺序与 POSCAR 原子顺序一致
        # "MAGMOM": [5.0, 5.0, 5.0, 0.4, 0.4],

        # 写法 3：VASP 字符串格式
        # "MAGMOM": "3*5.0 2*0.4",
    },
    output_dir="slab_relax/",
))
```

## 3.5 DFT+U

```python
engine.run(WorkflowConfig(
    calc_type="slab_relax",
    structure="TiO2/POSCAR",
    functional="SCAN",
    user_incar_overrides={
        "LDAU":     True,
        "LDAUTYPE": 2,                       # Dudarev 方案（常用）
        "LDAUU": {"Ti": 3.0, "O": 0.0},     # Hubbard U（eV）
        "LDAUL": {"Ti": 2,   "O": -1},       # 角量子数（-1 表示该元素不加 U）
        "LDAUJ": {"Ti": 0.0, "O": 0.0},     # 交换 J（eV），Dudarev 方案设为 0
    },
    output_dir="slab_relax_u/",
))
```

## 3.6 磁矩 + DFT+U 同时使用

```python
engine.run(WorkflowConfig(
    calc_type="slab_relax",
    structure="TiO2/POSCAR",
    functional="SCAN",
    kpoints_density=50.0,
    user_incar_overrides={
        "ISPIN":    2,
        "MAGMOM":   {"Ti": 3.0, "O": 0.4},
        "LDAU":     True,
        "LDAUTYPE": 2,
        "LDAUU":    {"Ti": 3.0, "O": 0.0},
        "LDAUL":    {"Ti": 2,   "O": -1},
        "LDAUJ":    {"Ti": 0.0, "O": 0.0},
        "LMAXMIX":  4,
        "NSW":      55,
        "ENCUT":    520,
        "NPAR":     4,
    },
    output_dir="slab_relax/",
))
```
