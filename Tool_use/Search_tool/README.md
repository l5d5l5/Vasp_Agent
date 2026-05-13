# Materials Database 智能查询助手

基于 LLM + Tool Call 的材料数据库查询工具，支持 **Materials Project** 和 **OQMD** 两个数据库，可进行晶体结构搜索、属性查询与结构文件下载。

---

## 功能概览

### Materials Project 工具

| 工具 | 功能 |
|---|---|
| `mp_search_formula` | 按化学式搜索（如 Fe2O3） |
| `mp_search_elements` | 按元素组合搜索（如 Fe-O 二元体系） |
| `mp_search_criteria` | 多条件筛选（带隙、磁性、晶系、稳定性等） |
| `mp_fetch` | 按 material_id 精确获取完整属性 |
| `mp_download` | 下载结构文件（CIF / POSCAR / XYZ） |

### OQMD 工具

| 工具 | 功能 |
|---|---|
| `oqmd_search_formula` | 按化学式搜索（如 Fe2O3） |
| `oqmd_search_elements` | 按元素组合搜索 |
| `oqmd_search_criteria` | 多条件筛选（带隙、稳定性、原型结构等） |
| `oqmd_fetch` | 按 entry_id 精确获取完整属性 |
| `oqmd_download` | 下载结构文件（CIF / POSCAR / XYZ） |

---

## 环境要求

```
Python      >= 3.10
mp-api      >= 0.41.0
fastmcp     >= 0.1.0
openai      >= 1.0.0
pymatgen    >= 2024.0.0
pydantic    >= 2.0.0
monty
requests
python-dotenv
```

安装依赖：

```powershell
pip install mp-api fastmcp openai pymatgen pydantic monty requests python-dotenv
```

---

## 快速开始

### 配置 `.env` 文件

在 `Search_tool/` 目录下创建 `.env` 文件（OQMD 模式无需任何 Key）：

```env
MP_API_KEY  = 你的_Materials_Project_API_Key
LLM_API_KEY = 你的_LLM_API_Key
```

> 获取 MP API Key：https://next.materialsproject.org/api

---

## 数据库选择

通过环境变量 `DB_BACKEND` 切换数据库（默认 MP）：

| `DB_BACKEND` | 数据库 | 是否需要 API Key | 支持 MCP |
|---|---|---|---|
| `mp`（默认） | Materials Project | 是（`MP_API_KEY`） | 是 |
| `oqmd` | OQMD | **否** | **否**（始终本地） |

---

## 运行模式

### MP 模式 A：Local（默认，推荐）

直接调用本地 `MPQueryService`，精确参数控制。

```powershell
python mp_tool_use.py
```

### MP 模式 B：MCP

通过 MP 官方 MCP Server 调用，工具自动同步官方最新能力。
MCP 启动失败时自动降级到 Local 模式。

```powershell
# MCP 模式下必须在 PowerShell 中显式设置 Key（子进程无法继承 .env）
$env:MP_API_KEY       = "你的_MP_Key"
$env:LLM_API_KEY      = "你的_LLM_Key"
$env:MP_EXECUTOR_MODE = "mcp_llm"
python mp_tool_use.py
Remove-Item Env:MP_EXECUTOR_MODE
Remove-Item Env:MP_API_KEY
Remove-Item Env:LLM_API_KEY
```

**MCP 模式工具列表：**

| MCP 原生工具 | 说明 |
|---|---|
| `search` | 自然语言搜索材料 |
| `fetch` | 按单个 material_id 获取 |
| `fetch_many` | 按多个 ID 获取（逗号分隔） |
| `get_phase_diagram_from_elements` | 相图查询 |
| `mp_download` | 下载结构文件（本地执行，MCP 无此工具） |

### OQMD 模式（无需 API Key）

直接调用 OQMD REST API，无需任何 Key，无 MCP 支持。

```powershell
$env:DB_BACKEND = "oqmd"
python mp_tool_use.py
Remove-Item Env:DB_BACKEND
```

---

## 数据库字段对比

| 属性 | Materials Project | OQMD |
|---|---|---|
| 主键 | `material_id`（如 `mp-19770`） | `entry_id`（整数，如 `353416`） |
| 形成能 | `formation_energy_per_atom` (eV/atom) | `formation_energy_per_atom` (eV/atom) |
| 凸包距离 | `energy_above_hull` (≥0，0为稳定) | `stability` (≤0为稳定) |
| 带隙 | `band_gap` (eV) | `band_gap` (eV) |
| 结构原型 | — | `prototype`（如 `Cu`、`NaCl`） |
| 空间群 | `space_group` | `space_group` |

---

## 切换 LLM 提供商

在 `mp_tool_use.py` 的 `main()` 函数中修改 `llm_provider` 参数：

```python
ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
#                                          ↑ 可选：deepseek / qwen / glm / openai
```

| 提供商 | 模型 | API Key 来源 |
|---|---|---|
| `deepseek` | deepseek-v4-flash | platform.deepseek.com |
| `qwen` | qwen-max | dashscope.aliyuncs.com |
| `glm` | glm-4-air | open.bigmodel.cn |
| `openai` | gpt-4o | platform.openai.com |

---

## 切换 Schema 语言

工具描述支持中英文切换（影响 LLM 理解工具的语言），对两个数据库均生效：

```powershell
$env:MP_SCHEMA_LANG = "cn"
python mp_tool_use.py
Remove-Item Env:MP_SCHEMA_LANG
```

---

## 自定义查询问题

修改 `mp_tool_use.py` 中 `main()` 函数的 `QUESTIONS` 列表（MP 和 OQMD 各有独立列表）：

```python
# MP 模式示例
QUESTIONS = [
    "Find the most stable Fe2O3 structure and download its CIF file.",
    "Get detailed properties of mp-126 and save it as POSCAR.",
    "Find magnetic insulators containing Fe and O with band gap between 1 and 3 eV.",
]

# OQMD 模式示例
QUESTIONS = [
    "Find the most stable Fe2O3 structures in OQMD and show their properties.",
    "Search OQMD for binary compounds containing Fe and O with band gap between 1 and 3 eV.",
]
```

---

## 下载文件说明

结构文件默认保存到 `./structures/` 目录：

| 数据库 | 文件名格式 | 示例 |
|---|---|---|
| MP | `{material_id}_{formula}.{fmt}` | `mp-19770_Fe2O3.cif` |
| OQMD | `oqmd-{entry_id}_{formula}.{fmt}` | `oqmd-353416_Fe2O3.cif` |

POSCAR 格式文件名为 `POSCAR_{文件名}`（无扩展名，VASP 惯例）。

| 格式 | 说明 | 适用软件 |
|---|---|---|
| `cif` | 晶体信息文件（默认） | VESTA, Materials Studio |
| `poscar` | VASP 输入格式 | VASP, ASE |
| `xyz` | 原子坐标格式 | OVITO, ASE |

---

## 项目文件结构

```
Search_tool/
├── .env                     # API Key 配置（不要提交到 Git）
├── mp_tool_use.py           # 主程序：LLM 循环 + 执行器选择
├── search.py                # MPQueryService：MP API 封装 + TTL 缓存
├── oqmd_search.py           # OQMDQueryService：OQMD REST API 封装
├── mp_tool_schemas.py       # MP 工具 Pydantic 模型 → OpenAI Schema
├── oqmd_tool_schemas.py     # OQMD 工具 Pydantic 模型 → OpenAI Schema
├── mp_tool_schema_en.py     # 向后兼容壳（1 行 import）
├── mp_tool_schema_cn.py     # 向后兼容壳（1 行 import）
└── structures/              # 下载的结构文件（自动创建）
```

---

## 常见问题

**Q：OQMD 查询很慢？**

OQMD REST API 为公共服务，响应时间受网络影响（通常 2–10 秒）。已内置 TTL 缓存（300 秒），相同查询第二次即时返回。

**Q：MCP 模式卡在 `[启动] MCP Server...` 不动？**

原因：子进程读不到 `MP_API_KEY`。解决方法：在 PowerShell 中显式设置：
```powershell
$env:MP_API_KEY = "你的Key"
```

**Q：MCP 模式自动降级到 Local 模式了？**

这是正常保护机制，功能不受影响。查看终端中 `[MCP] ❌ 启动失败` 的具体报错。

**Q：下载的 POSCAR 文件乱码？**

POSCAR 是纯文本，用 VS Code / Notepad++ 打开，不要用 Word。

**Q：如何只查询不下载？**

在问题中不提及"下载"或"save"，LLM 会只调用搜索工具返回文字结果。

---

## 快速命令参考

```powershell
# MP Local 模式（默认）
python mp_tool_use.py

# MP MCP 模式
$env:MP_API_KEY       = "your_mp_key"
$env:LLM_API_KEY      = "your_llm_key"
$env:MP_EXECUTOR_MODE = "mcp_llm"
python mp_tool_use.py
Remove-Item Env:MP_EXECUTOR_MODE

# OQMD 模式（无需 Key）
$env:DB_BACKEND = "oqmd"
python mp_tool_use.py
Remove-Item Env:DB_BACKEND

# 中文 Schema
$env:MP_SCHEMA_LANG = "cn"
python mp_tool_use.py
Remove-Item Env:MP_SCHEMA_LANG
```
