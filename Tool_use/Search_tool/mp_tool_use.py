# ══════════════════════════════════════════════════════════════
# mp_tool_use.py
# 工具：mp_search_formula / mp_search_elements /
#       mp_search_criteria / mp_fetch / mp_download
#
# 执行后端（通过 MP_EXECUTOR_MODE 切换）：
#   local   → LocalToolExecutor  精确参数控制，直连 MP API（默认）
#   mcp_llm → MCPToolExecutor    MP 官方 MCP Server，失败自动降级到 Local
# ══════════════════════════════════════════════════════════════

import os
import json
import asyncio
from abc import ABC, abstractmethod
from monty.json import MontyEncoder
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ──────────────────────────────────────────────
# Schema 语言切换
# ──────────────────────────────────────────────
_SCHEMA_LANG = os.environ.get("MP_SCHEMA_LANG", "en")
if _SCHEMA_LANG == "cn":
    from mp_tool_schema_cn import MP_TOOL_SCHEMA_CN as MP_TOOL_SCHEMA
else:
    from mp_tool_schema_en import MP_TOOL_SCHEMA_EN as MP_TOOL_SCHEMA


# ══════════════════════════════════════════════
# LLM 配置
# ══════════════════════════════════════════════

LLM_CONFIGS: Dict[str, Dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-v4-flash",
        "extra":    {"parallel_tool_calls": False},
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model":    "qwen-max",
        "extra":    {},
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model":    "glm-4-air",
        "extra":    {},
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model":    "gpt-4o",
        "extra":    {},
    },
}


def _get_openai_client(provider: str, llm_api_key: str):
    from openai import OpenAI
    cfg    = LLM_CONFIGS[provider]
    client = OpenAI(api_key=llm_api_key, base_url=cfg["base_url"])
    client._mp_model = cfg["model"]
    client._mp_extra = cfg["extra"]
    return client


def _normalize_tool_call_ids(msg: Any, provider: str) -> Any:
    """修正 GLM tool_call_id 格式差异（切换到 GLM 时启用）。"""
    if provider == "glm" and msg.tool_calls:
        for tc in msg.tool_calls:
            if not tc.id or not tc.id.startswith("call_"):
                tc.id = f"call_{tc.id or id(tc)}"
    return msg


def message_to_dict(msg: Any) -> Dict:
    """
    ChatCompletionMessage → 纯字典。
    - content=None      → ""（DeepSeek 不接受 null）
    - reasoning_content → 原样传回（DeepSeek Thinking Mode）
    """
    d: Dict[str, Any] = {
        "role":    msg.role,
        "content": msg.content if msg.content is not None else "",
    }
    reasoning = getattr(msg, "reasoning_content", None)
    if reasoning:
        d["reasoning_content"] = reasoning
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id":       tc.id,
                "type":     "function",
                "function": {
                    "name":      tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


# ══════════════════════════════════════════════
# 执行器抽象基类
# ══════════════════════════════════════════════

class MPToolExecutor(ABC):

    @abstractmethod
    async def execute(self, tool_name: str, tool_args: Dict) -> str: ...

    @abstractmethod
    async def close(self): ...

    @property
    def tools(self) -> List[Dict]:
        return MP_TOOL_SCHEMA


# ══════════════════════════════════════════════
# 本地执行器
# 直连 MPQueryService，5 个工具全部原生支持
# ══════════════════════════════════════════════

class LocalToolExecutor(MPToolExecutor):
    """
    对应 mp_query_service.py，支持 5 个工具：
      mp_search_formula   → query_by_formula()
      mp_search_elements  → query_by_elements()
      mp_search_criteria  → query_by_criteria()
      mp_fetch            → query_by_material_id()
      mp_download         → query_by_material_id() + save_structure_to_disk()
    """

    def __init__(self, mp_api_key: str):
        from search import MPQueryService
        self._svc = MPQueryService(
            api_key        = mp_api_key,
            max_results    = 20,
            include_angles = True,   # 返回 alpha/beta/gamma
        )

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        return await asyncio.to_thread(self._sync, tool_name, tool_args)

    # ── 工具分发 ──────────────────────────────
    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        return await asyncio.to_thread(self._sync, tool_name, tool_args)

    def _sync(self, tool_name: str, tool_args: Dict) -> str:
        try:
            if   tool_name == "mp_search_formula":   payload = self._search_formula(tool_args)
            elif tool_name == "mp_search_elements":  payload = self._search_elements(tool_args)
            elif tool_name == "mp_search_criteria":  payload = self._search_criteria(tool_args)
            elif tool_name == "mp_fetch":            payload = self._fetch(tool_args)
            elif tool_name == "mp_download":         payload = self._download(tool_args)
            else:                                    payload = {"error": f"unknown tool: {tool_name}"}
        except Exception as e:
            payload = {"error": str(e)}
        return json.dumps(payload, cls=MontyEncoder, ensure_ascii=False, indent=2)
    
    # ── Tool 1: mp_search_formula ─────────────
    def _search_formula(self, args: Dict) -> Dict:
        results = self._svc.query_by_formula(
            formula     = args["formula"],
            only_stable = args.get("only_stable", False),
        )
        n = args.get("max_results", 5)
        return {
            "count":   len(results),
            "results": [self._summary(r) for r in results[:n]],
        }

    # ── Tool 2: mp_search_elements ────────────
    def _search_elements(self, args: Dict) -> Dict:
        num_el = args.get("num_elements")
        results = self._svc.query_by_elements(
            elements     = args["elements"],
            num_elements = num_el,
            only_stable  = args.get("only_stable", False),
        )
        n = args.get("max_results", 5)
        return {
            "count":   len(results),
            "results": [self._summary(r) for r in results[:n]],
        }

    # ── Tool 3: mp_search_criteria ────────────
    def _search_criteria(self, args: Dict) -> Dict:
        criteria: Dict[str, Any] = {}
        n = args.pop("max_results", 5)

        # 直接透传的字段
        _direct = [
            "elements", "exclude_elements", "chemsys", "formula",
            "num_elements", "crystal_system", "spacegroup_symbol",
            "is_stable", "is_metal", "is_magnetic", "theoretical",
        ]
        for key in _direct:
            if args.get(key) is not None:
                criteria[key] = args[key]

        # 范围参数：min/max → tuple
        def _range(mn, mx) -> Optional[Tuple]:
            if mn is None and mx is None:
                return None
            return (mn, mx)

        r = _range(args.get("band_gap_min"), args.get("band_gap_max"))
        if r: criteria["band_gap"] = r

        r = _range(None, args.get("energy_above_hull_max"))
        if r: criteria["energy_above_hull"] = r

        r = _range(args.get("formation_energy_min"), args.get("formation_energy_max"))
        if r: criteria["formation_energy_per_atom"] = r

        r = _range(args.get("density_min"), args.get("density_max"))
        if r: criteria["density"] = r

        if not criteria:
            return {"error": "mp_search_criteria requires at least one filter parameter."}

        results = self._svc.query_by_criteria(**criteria)
        return {
            "count":   len(results),
            "results": [self._summary(r) for r in results[:n]],
        }

    # ── Tool 4: mp_fetch ──────────────────────
    def _fetch(self, args: Dict) -> Dict:
        ids     = args["material_ids"]
        results = self._svc.query_by_material_id(ids)
        if not results:
            return {"error": f"not found: {ids}"}
        # fetch 返回完整字段（含晶格角度和结构统计）
        return {
            "count":   len(results),
            "results": [self._full_summary(r) for r in results],
        }

    # ── Tool 5: mp_download ───────────────────
    def _download(self, args: Dict) -> Dict:

        from search import save_structure_to_disk   # ← 正确导入路径

        mid     = args["material_id"]
        fmt     = args.get("fmt",      "cif")
        save_dir = args.get("save_dir", "./structures")

        # 1. 查询结构
        results = self._svc.query_by_material_id(mid)
        if not results:
            return {"error": f"not found: {mid}"}

        item     = results[0]
        struct   = item["_structure"]          # pymatgen Structure 对象
        filename = args.get("filename") or f"{item['material_id']}_{item['formula']}"

        # 2. 保存文件（调用 mp_query_service 中新增的函数）
        saved = save_structure_to_disk(
            struct   = struct,
            save_dir = save_dir,
            filename = filename,
            fmt      = fmt,
        )

        # 3. 返回结果
        if not saved:
            return {
                "material_id": mid,
                "formula":     item["formula"],
                "fmt":         fmt,
                "success":     False,
                "error":       "文件写入失败，请检查目录权限或日志",
            }

        return {
            "material_id": mid,
            "formula":     item["formula"],
            "fmt":         fmt,
            "saved_files": saved,
            "success":     True,
        }

    # ── 字段过滤工具 ──────────────────────────
    _SEARCH_FIELDS = (
        "material_id", "formula", "space_group", "crystal_system",
        "a", "b", "c",
        "band_gap", "is_metal",
        "formation_energy_per_atom", "energy_above_hull", "is_stable",
        "is_magnetic", "total_magnetization",
        "nsites", "density", "theoretical",
    )
    # fetch 结果：完整字段（含角度）
    _FETCH_FIELDS = _SEARCH_FIELDS + ("alpha", "beta", "gamma", "volume")
    # 始终排除的大字段
    _EXCLUDE = {"_structure", "xyz", "cif", "poscar"}

    @classmethod
    def _summary(cls, r: Dict) -> Dict:
        """search 用：只保留精简字段。"""
        return {k: r[k] for k in cls._SEARCH_FIELDS if k in r}

    @classmethod
    def _full_summary(cls, r: Dict) -> Dict:
        """fetch 用：保留完整字段（含角度/体积）。"""
        return {k: r[k] for k in cls._FETCH_FIELDS if k in r}

    async def close(self): pass


# ══════════════════════════════════════════════
# MCP 执行器
# 设计逻辑：
#   1. start() 启动 MCP Server 子进程
#      └── 成功 → tools 属性返回 MCP 原生 Schema（自动同步）
#      └── 失败 → 降级标志位置 True，tools 返回本地 Schema
#
#   2. execute() 执行工具调用
#      └── MCP 在线 → 直接 call_tool()（透传原生工具名）
#      └── MCP 离线 → 委托给内置的 LocalToolExecutor
#
#   3. mp_download 始终降级到本地执行（MCP 无此工具）
# ══════════════════════════════════════════════

class MCPToolExecutor(MPToolExecutor):

    _DOWNLOAD_TOOL = {
        "type": "function",
        "function": {
            "name": "mp_download",
            "description": (
                "Download a crystal structure file from the Materials Project. "
                "Supports CIF, POSCAR, and XYZ formats. "
                "Use this after finding a material_id with search or fetch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "material_id": {
                        "type": "string",
                        "description": "Materials Project ID, e.g. 'mp-19770'",
                    },
                    "fmt": {
                        "type": "string",
                        "enum": ["cif", "poscar", "xyz"],
                        "description": "File format. Default: cif",
                    },
                    "save_dir": {
                        "type": "string",
                        "description": "Directory to save the file. Default: ./structures",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Custom filename without extension. Optional.",
                    },
                },
                "required": ["material_id"],
            },
        },
    }

    def __init__(self, mp_api_key: str):
        self.mp_api_key          = mp_api_key
        self._client             = None
        self._mcp_tools:         List[str]  = []
        self._mcp_tools_schema:  List[Dict] = []
        self._fallback:          Optional[LocalToolExecutor] = None
        self._use_fallback:      bool = False

    @property
    def tools(self) -> List[Dict]:
        """MCP 在线 → MCP 原生 Schema；离线 → 本地 5 工具 Schema。"""
        if self._mcp_tools_schema and not self._use_fallback:
            return self._mcp_tools_schema + [self._DOWNLOAD_TOOL]
        return MP_TOOL_SCHEMA

    async def start(self) -> bool:
        """启动 MCP Server 子进程。失败时自动激活降级，不抛出异常。"""
        import sys
        try:
            from fastmcp import Client
            from fastmcp.client.transports import StdioTransport

            transport = StdioTransport(
                command = sys.executable,
                args    = ["-m", "mp_api.mcp.server"],
                env     = {**os.environ, "MP_API_KEY": self.mp_api_key},
            )
            self._client = Client(transport=transport)
            await self._client.__aenter__()

            mcp_tools             = await self._client.list_tools()
            self._mcp_tools       = [t.name for t in mcp_tools]
            self._mcp_tools_schema = [
                {
                    "type": "function",
                    "function": {
                        "name":        t.name,
                        "description": t.description,
                        "parameters":  t.inputSchema,
                    }
                }
                for t in mcp_tools
            ]
            print(f"[MCP] ✅ 已连接 | 工具: {self._mcp_tools}")
            return True

        except Exception as e:
            print(f"[MCP] ❌ 启动失败: {e}")
            print(f"[MCP] ⚠️  自动降级到 LocalToolExecutor")
            self._activate_fallback()
            return False

    def _activate_fallback(self):
        self._use_fallback = True
        self._fallback     = LocalToolExecutor(self.mp_api_key)
        print(f"[Fallback] ✅ LocalToolExecutor 已就绪")

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        # 整体降级模式
        if self._use_fallback:
            if self._fallback is None:
                self._activate_fallback()
            return await self._fallback.execute(tool_name, tool_args)

        if self._client is None:
            return json.dumps({"error": "MCP client 未启动"})

        try:
            # mp_download 始终本地执行（MCP 无此工具）
            if tool_name == "mp_download":
                return await self._local_download(tool_args)

            if tool_name in self._mcp_tools:
                result = await self._client.call_tool(tool_name, tool_args)
                return self._extract_text(result)

            return json.dumps({
                "error":           f"unknown tool: {tool_name}",
                "available_tools": self._mcp_tools + ["mp_download"],
            })
        
        except Exception as e:
            print(f"[MCP] ⚠️  {tool_name} 执行失败: {e}，降级重试...")
            if self._fallback is None:
                self._activate_fallback()
            try:
                return await self._fallback.execute(tool_name, tool_args)
            except Exception as e2:
                return json.dumps({"error": f"MCP: {e} | Local: {e2}"})
            
    # ── download 本地降级 ──────────────────────────────────────
    async def _local_download(self, args: Dict) -> str:
        from search import MPQueryService, save_structure_to_disk
        svc     = MPQueryService(api_key=self.mp_api_key)
        mid     = args["material_id"]
        results = svc.query_by_material_id(mid)
        if not results:
            return json.dumps({"error": f"not found: {mid}"})
        item     = results[0]
        filename = args.get("filename") or f"{item['material_id']}_{item['formula']}"
        saved    = save_structure_to_disk(
            struct   = item["_structure"],
            save_dir = args.get("save_dir", "./structures"),
            filename = filename,
            fmt      = args.get("fmt", "cif"),
        )
        return json.dumps({
            "material_id": mid, "formula": item["formula"],
            "fmt":         args.get("fmt", "cif"),
            "saved_files": saved, "success": bool(saved),
        }, ensure_ascii=False)

    # ── MCP 返回值解析 ─────────────────────────────────────────

    @staticmethod
    def _extract_text(result: Any) -> str:
        """兼容 fastmcp CallToolResult 的多种返回格式。"""
        if hasattr(result, "content"):
            content = result.content
            if content and hasattr(content[0], "text"):
                return content[0].text
            return str(content)
        if isinstance(result, list):
            if result and hasattr(result[0], "text"):
                return result[0].text
            return str(result)
        if isinstance(result, str):
            return result
        return json.dumps({"error": f"unexpected result type: {type(result)}"})

    async def close(self):
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None
            print("[MCP] 连接已关闭")

# ══════════════════════════════════════════════
# 统一对话循环
# ══════════════════════════════════════════════

async def run(
    user_message: str,
    executor:     MPToolExecutor,
    llm_provider: str = "deepseek",
    llm_api_key:  str = "",
) -> str:
    client   = _get_openai_client(llm_provider, llm_api_key)
    model    = client._mp_model
    extra    = client._mp_extra
    messages = [
        {"role": "system", "content": (
            "You are a materials science assistant with access to the Materials Project database. "
            "Use the provided tools to answer questions about crystal structures, "
            "electronic properties, stability, and magnetic properties. "
            "Always cite the material_id in your answer."
        )},
        {"role": "user", "content": user_message},
    ]

    while True:
        response = client.chat.completions.create(
            model       = model,
            messages    = messages,
            tools       = executor.tools,
            tool_choice = "auto",
            max_tokens  = 2048,
            temperature = 0.7,
            **extra,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return msg.content

        messages.append(message_to_dict(msg))

        results = await asyncio.gather(*[
            executor.execute(tc.function.name, json.loads(tc.function.arguments))
            for tc in msg.tool_calls
        ])

        for tc, result in zip(msg.tool_calls, results):
            messages.append({
                "role":         "tool",
                "tool_call_id": tc.id,
                "content":      result,
            })


# ══════════════════════════════════════════════
# 入口示例
# ══════════════════════════════════════════════

async def main():
    MP_KEY  = os.environ.get("MP_API_KEY")
    LLM_KEY = os.environ.get("LLM_API_KEY")

    if not MP_KEY:
        raise ValueError("❌ MP_API_KEY 未设置，请检查 .env 文件")
    if not LLM_KEY:
        raise ValueError("❌ LLM_API_KEY 未设置，请检查 .env 文件")
    
    # ── 执行模式选择 ──────────────────────────
    # MP_EXECUTOR_MODE=local    → LocalToolExecutor（默认，精确控制）
    # MP_EXECUTOR_MODE=mcp_llm  → MCPToolExecutor（MCP 优先，失败自动降级）
    MODE = os.environ.get("MP_EXECUTOR_MODE", "local")
    
    QUESTIONS = [
        "Find the most stable Fe2O3 structure and download its CIF file.",
        "Get detailed properties of mp-126 and save it as POSCAR.",
        "Find magnetic insulators containing Fe and O with band gap between 1 and 3 eV.",
        # "我想要获得特殊的金红石型的VO2结构信息并下载为POSCAR文件。",
        # "我想要知道稳定的FeVO4的band_gap是多少，如果它是导体请下载为POSCAR文件，如果不是请告诉我它的band_gap是多少。",
    ]

    if MODE == "local":
        print("🔧 后端：LocalToolExecutor")
        executor = LocalToolExecutor(mp_api_key=MP_KEY)

    elif MODE == "mcp_llm":
        executor = MCPToolExecutor(mp_api_key=MP_KEY)
        print("\n[启动] MCP Server（失败时自动降级到 Local）...")
        await executor.start()
        backend = "LocalToolExecutor（降级）" if executor._use_fallback else "MCP Server"
        print(f"[就绪] 当前后端: {backend}")
        print(f"[工具] {[t['function']['name'] for t in executor.tools]}")

    else:
        raise ValueError(f"未知模式：{MODE}，可选：local / mcp_llm")

    try:
        for q in QUESTIONS:
            print(f"\n{'='*60}\n>>> {q}\n{'='*60}")
            ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
            print(ans)
    finally:
        await executor.close()

if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())