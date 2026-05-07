# ══════════════════════════════════════════════════════════════
# mp_tool_use.py  —  重新设计：对应 mp_query_service.py 重构版
# 工具：mp_search_formula / mp_search_elements /
#       mp_search_criteria / mp_fetch / mp_download
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
    将 OpenAI SDK ChatCompletionMessage 转为 DeepSeek 接受的纯字典。

    修复要点（DeepSeek Thinking Mode）：
      - content=None        → ""（DeepSeek 不接受 null）
      - reasoning_content   → 必须原样传回，否则第二轮请求报 400
      - tool_calls          → 转为标准列表格式
    """
    d: Dict[str, Any] = {
        "role":    msg.role,
        "content": msg.content if msg.content is not None else "",
    }

    # 保留 reasoning_content（DeepSeek Thinking Mode 必须传回）
    # getattr 兼容不支持 thinking mode 的其他模型（返回 None 时跳过）
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
# 本地执行器（对应新 MPQueryService）
# ══════════════════════════════════════════════

class LocalToolExecutor(MPToolExecutor):
    """
    对应 mp_query_service.py 重构版，支持 5 个工具：
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
    def _sync(self, tool_name: str, tool_args: Dict) -> str:
        try:
            if tool_name == "mp_search_formula":
                payload = self._search_formula(tool_args)

            elif tool_name == "mp_search_elements":
                payload = self._search_elements(tool_args)

            elif tool_name == "mp_search_criteria":
                payload = self._search_criteria(tool_args)

            elif tool_name == "mp_fetch":
                payload = self._fetch(tool_args)

            elif tool_name == "mp_download":
                payload = self._download(tool_args)

            else:
                payload = {"error": f"unknown tool: {tool_name}"}

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
        """
        将 LLM 传来的扁平参数（band_gap_min/max 等）
        转换为 MPQueryService.query_by_criteria() 接受的格式。
        """
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
    # search 结果：精简字段，节省 token
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
# MCP 执行器（方案 A，保留备用）
# ══════════════════════════════════════════════

class MCPToolExecutor(MPToolExecutor):
    """官方 mp_api MCP Server（方案 A）。"""

    SERVER_PATH = Path("./mp_api/mcp/server.py")

    def __init__(self, mp_api_key: str):
        self.mp_api_key = mp_api_key
        self._client    = None

    async def start(self):
        from fastmcp import Client
        from fastmcp.client.transports import PythonStdioTransport
        transport    = PythonStdioTransport(
            script_path = str(self.SERVER_PATH),
            env         = {"MP_API_KEY": self.mp_api_key},
        )
        self._client = Client(transport=transport)
        await self._client.__aenter__()
        mcp_tools = await self._client.list_tools()
        print(f"[MCP] tools: {[t.name for t in mcp_tools]}")

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        # MCP 方案暂只映射 search/fetch，download 降级到本地
        if tool_name in ("mp_search_formula", "mp_search_elements", "mp_search_criteria"):
            result = await self._client.call_tool("search", {"query": str(tool_args)})
            return self._text(result)
        elif tool_name == "mp_fetch":
            mid    = tool_args["material_ids"][0]
            result = await self._client.call_tool("fetch", {"query": mid})
            return self._text(result)
        elif tool_name == "mp_download":
            return await self._local_download(tool_args)
        return json.dumps({"error": f"unknown tool: {tool_name}"})

    async def _local_download(self, args: Dict) -> str:
        from search import MPQueryService, save_structure_to_disk
        svc     = MPQueryService(api_key=self.mp_api_key)
        results = svc.query_by_material_id(args["material_id"])
        if not results:
            return json.dumps({"error": f"not found: {args['material_id']}"})
        item  = results[0]
        saved = save_structure_to_disk(
            struct   = item["_structure"],
            save_dir = args.get("save_dir", "./structures"),
            filename = f"{item['material_id']}_{item['formula']}",
            fmt      = args.get("fmt", "cif"),
        )
        return json.dumps({"material_id": args["material_id"],
                           "saved_files": saved, "success": bool(saved)})

    @staticmethod
    def _text(result: Any) -> str:
        if result and hasattr(result[0], "text"):
            return result[0].text
        return json.dumps({"error": "empty response"})

    async def close(self):
        if self._client:
            await self._client.__aexit__(None, None, None)


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

    executor = LocalToolExecutor(mp_api_key=MP_KEY)

    questions = [
        # 化学式查询
        "Find the most stable Fe2O3 structure and download its CIF file.",
        # 按 ID 精确获取
        "Get detailed properties of mp-126 and save it as POSCAR.",
        # 多条件筛选
        "Find magnetic insulators containing Fe and O with band gap between 1 and 3 eV.",
        # 元素组合查询
        "我想要获得特殊的金红石型的VO2结构信息并下载为POSCAR文件。",
        #特殊查询
        "我想要知道稳定的FeVO4的band_gap是多少，如果它是导体请下载为POSCAR文件，如果不是请告诉我它的band_gap是多少。",
    ]

    for q in questions:
        print(f"\n{'='*60}")
        print(f">>> {q}")
        print('='*60)
        ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
        print(ans)

    await executor.close()


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())