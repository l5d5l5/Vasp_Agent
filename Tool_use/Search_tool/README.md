# MP Tool Use — Materials Project 智能查询助手

基于 LLM + Tool Call 的 Materials Project 数据库查询工具，支持晶体结构搜索、属性查询与结构文件下载。

---

## 功能概览

| 工具 | 功能 |
|---|---|
| `mp_search_formula` | 按化学式搜索（如 Fe2O3） |
| `mp_search_elements` | 按元素组合搜索（如 Fe-O 二元体系） |
| `mp_search_criteria` | 多条件筛选（带隙、磁性、晶系等） |
| `mp_fetch` | 按 material_id 精确获取完整属性 |
| `mp_download` | 下载结构文件（CIF / POSCAR / XYZ） |

---

## 环境要求

```
Python      >= 3.10
mp-api      >= 0.41.0
fastmcp     >= 0.1.0
openai      >= 1.0.0
pymatgen    >= 2024.0.0
monty
python-dotenv
```

安装依赖：

```powershell
pip install mp-api fastmcp openai pymatgen monty python-dotenv
```

---

## 快速开始

### 第一步：配置 `.env` 文件

在项目根目录创建 `.env` 文件，填入以下内容：

```env
MP_API_KEY  = 你的_Materials_Project_API_Key
LLM_API_KEY = 你的_LLM_API_Key
```

> 获取 MP API Key：https://next.materialsproject.org/api
> 获取 DeepSeek API Key：https://platform.deepseek.com

### 第二步：选择运行模式

本工具支持两种后端模式，通过环境变量 `MP_EXECUTOR_MODE` 切换。

---

## 运行模式

### 模式 A：Local 模式（默认，推荐）

直接调用本地 `MPQueryService`，精确参数控制，无需额外服务。

```powershell
# 方式 1：直接运行（默认即为 local 模式）
python mp_tool_use.py

# 方式 2：显式指定
$env:MP_EXECUTOR_MODE = "local"
python mp_tool_use.py

# 运行完毕后清除环境变量
Remove-Item Env:MP_EXECUTOR_MODE
```

**适用场景：**
- 日常使用，稳定优先
- 需要精确数值过滤（带隙范围、能量范围等）
- 需要结构文件下载

---

### 模式 B：MCP 模式

通过 MP 官方 MCP Server 调用，工具自动同步官方最新能力。
**MCP 启动失败时自动降级到 Local 模式，无需手动干预。**

```powershell
# 第一步：在 PowerShell 中设置 API Key（确保子进程能读取）
$env:MP_API_KEY  = "你的_Materials_Project_API_Key"
$env:LLM_API_KEY = "你的_LLM_API_Key"

# 第二步：运行 MCP 模式
$env:MP_EXECUTOR_MODE = "mcp_llm"
python mp_tool_use.py

# 第三步：运行完毕后清除环境变量
Remove-Item Env:MP_EXECUTOR_MODE
Remove-Item Env:MP_API_KEY
Remove-Item Env:MP_LLM_KEY
```

> ⚠️ **注意**：MCP 模式下必须在 PowerShell 中显式设置 `$env:MP_API_KEY`，
> 仅靠 `.env` 文件不够，因为 MCP Server 是独立子进程，无法继承 Python 的 `load_dotenv()`。

**MCP 模式工具列表：**

| MCP 原生工具 | 参数 | 说明 |
|---|---|---|
| `search` | `query: str` | 自然语言搜索材料 |
| `fetch` | `idx: str` | 按单个 material_id 获取 |
| `fetch_many` | `str_idxs: str` | 按多个 ID 获取（逗号分隔） |
| `fetch_all` | — | 获取全部 |
| `get_phase_diagram_from_elements` | `elements: str` | 相图查询 |
| `mp_download` | `material_id, fmt, save_dir` | 下载结构文件（本地执行） |

---

## 切换 LLM 提供商

在 `mp_tool_use.py` 的 `main()` 函数中修改 `llm_provider` 参数：

```python
ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
#                                          ↑ 可选：deepseek / qwen / glm / openai
```

各提供商对应的模型：

| 提供商 | 模型 | API Key 来源 |
|---|---|---|
| `deepseek` | deepseek-chat | platform.deepseek.com |
| `qwen` | qwen-max | dashscope.aliyuncs.com |
| `glm` | glm-4-air | open.bigmodel.cn |
| `openai` | gpt-4o | platform.openai.com |

---

## 切换 Schema 语言

工具描述支持中英文切换（影响 LLM 理解工具的语言）：

```powershell
# 中文 Schema
$env:MP_SCHEMA_LANG = "cn"
python mp_tool_use.py
Remove-Item Env:MP_SCHEMA_LANG

# 英文 Schema（默认）
python mp_tool_use.py
```

---

## 自定义查询问题

修改 `mp_tool_use.py` 中 `main()` 函数的 `QUESTIONS` 列表：

```python
QUESTIONS = [
    # 按化学式查询并下载
    "Find the most stable Fe2O3 structure and download its CIF file.",

    # 按 material_id 精确获取并下载
    "Get detailed properties of mp-126 and save it as POSCAR.",

    # 多条件筛选
    "Find magnetic insulators containing Fe and O with band gap between 1 and 3 eV.",

    # 中文查询
    "我想要获得金红石型的VO2结构信息并下载为POSCAR文件。",

    # 条件判断型查询
    "我想要知道稳定的FeVO4的band_gap是多少，如果它是导体请下载为POSCAR文件，如果不是请告诉我它的band_gap是多少。",
]
```

---

## 下载文件说明

结构文件默认保存到 `./structures/` 目录，文件名格式为：

```
{material_id}_{formula}.{fmt}
# 示例：mp-19770_Fe2O3.cif
```

支持格式：

| 格式 | 说明 | 适用软件 |
|---|---|---|
| `cif` | 晶体信息文件（默认） | VESTA, Materials Studio |
| `poscar` | VASP 输入格式 | VASP, ASE |
| `xyz` | 原子坐标格式 | OVITO, ASE |

---

## 项目文件结构

```
Search_tool/
├── .env                    # API Key 配置（不要提交到 Git）
├── mp_tool_use.py          # 主程序（本文件）
├── mp_query_service.py     # MP API 查询服务层
├── mp_tool_schema_en.py    # 英文工具 Schema
├── mp_tool_schema_cn.py    # 中文工具 Schema
└── structures/             # 下载的结构文件（自动创建）
    └── mp-19770_Fe2O3.cif
```

---

## 常见问题

**Q：MCP 模式卡在 `[启动] MCP Server...` 不动？**

原因：子进程读不到 `MP_API_KEY`。解决方法：在 PowerShell 中显式设置：
```powershell
$env:MP_API_KEY = "你的Key"
```

**Q：MCP 模式自动降级到 Local 模式了？**

这是正常的保护机制。降级后功能完全正常，只是后端切换为本地直连。
查看终端输出中是否有 `[MCP] ❌ 启动失败` 的具体报错信息。

**Q：下载的 POSCAR 文件乱码？**

POSCAR 是纯文本格式，用文本编辑器（VS Code / Notepad++）打开即可，
不要用 Word 打开。

**Q：如何只查询不下载？**

在问题中不提及"下载"或"save"，LLM 会自动只调用搜索工具返回文字结果。

---

## 快速命令参考

```powershell
# Local 模式（默认）
python mp_tool_use.py

# MCP 模式
$env:MP_API_KEY       = "your_mp_key"
$env:LLM_API_KEY      = "your_llm_key"
$env:MP_EXECUTOR_MODE = "mcp_llm"
python mp_tool_use.py
Remove-Item Env:MP_EXECUTOR_MODE

# 中文 Schema
$env:MP_SCHEMA_LANG = "cn"
python mp_tool_use.py
Remove-Item Env:MP_SCHEMA_LANG
```
