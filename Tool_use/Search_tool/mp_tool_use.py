# ══════════════════════════════════════════════════════════════
# mp_tool_use.py  —  更新：Schema 按语言动态导入
# ══════════════════════════════════════════════════════════════

import os
import json
import asyncio
from abc import ABC, abstractmethod
from monty.json import MontyEncoder
from typing import Any, Dict, List, Optional
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

# ──────────────────────────────────────────────
# Schema 选择：通过环境变量或直接修改此行切换
#   "en" → mp_tool_schema_en  (生产推荐，省 token)
#   "cn" → mp_tool_schema_cn  (开发调试 / 中文文档)
# ──────────────────────────────────────────────
_SCHEMA_LANG = os.environ.get("MP_SCHEMA_LANG", "en")

if _SCHEMA_LANG == "cn":
    from mp_tool_schema_cn import MP_TOOL_SCHEMA_CN as MP_TOOL_SCHEMA
else:
    from mp_tool_schema_en import MP_TOOL_SCHEMA_EN as MP_TOOL_SCHEMA


LLM_CONFIGS: Dict[str, Dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-chat",
        # DeepSeek 不支持并行 tool call
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


def message_to_dict(msg: Any) -> Dict:
    """
    将 OpenAI SDK 的 ChatCompletionMessage 对象转为
    DeepSeek 接受的纯字典格式。
    - content=None 时改为 ""（DeepSeek 不接受 null）
    - tool_calls 转为标准列表格式
    """
    d: Dict[str, Any] = {
        "role":    msg.role,
        "content": msg.content if msg.content is not None else "",
    }

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
# 方案 A：MCP 执行器
# ══════════════════════════════════════════════

class MCPToolExecutor(MPToolExecutor):
    """官方 mp_api v0.46.0 MCP Server。"""

    SERVER_PATH = Path("./mp_api/mcp/server.py")

    def __init__(self, mp_api_key: str):
        self.mp_api_key = mp_api_key
        self._client    = None

    async def start(self):
        from fastmcp import Client
        from fastmcp.client.transports import PythonStdioTransport
        transport    = PythonStdioTransport(
            script_path=str(self.SERVER_PATH),
            env={"MP_API_KEY": self.mp_api_key},
        )
        self._client = Client(transport=transport)
        await self._client.__aenter__()
        mcp_tools = await self._client.list_tools()
        print(f"[MCP] tools: {[t.name for t in mcp_tools]}")

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        if tool_name == "mp_search":
            result = await self._client.call_tool("search", {"query": tool_args["query"]})
            return self._text(result)

        elif tool_name == "mp_fetch":
            result = await self._client.call_tool("fetch", {"query": tool_args["material_id"]})
            return self._text(result)

        elif tool_name == "mp_download":
            # 官方 MCP 暂无 download 工具，降级到本地 MPQueryService
            return await self._local_download(tool_args)

        return json.dumps({"error": f"unknown tool: {tool_name}"})

    async def _local_download(self, args: Dict) -> str:
        from search import MPQueryService, save_structure_to_disk
        svc     = MPQueryService(api_key=self.mp_api_key)
        results = svc.query(args["material_id"])
        if not results:
            return json.dumps({"error": f"not found: {args['material_id']}"})

        item     = results[0]
        struct   = item["_structure"]
        filename = f"{item['material_id']}_{item['formula']}"

        saved = save_structure_to_disk(
            struct   = struct,
            save_dir = args.get("save_dir", "./structures"),
            filename = filename,
            fmt      = args.get("fmt", "cif"),
        )
        return json.dumps({
            "material_id": args["material_id"],
            "saved_files": saved,
            "success":     bool(saved),
        }, ensure_ascii=False)

    @staticmethod
    def _text(result: Any) -> str:
        if result and hasattr(result[0], "text"):
            return result[0].text
        return json.dumps({"error": "empty response"})

    async def close(self):
        if self._client:
            await self._client.__aexit__(None, None, None)


# ══════════════════════════════════════════════
# 方案 B：本地执行器（search.py）
# ══════════════════════════════════════════════

class LocalToolExecutor(MPToolExecutor):
    """直接调用本地 MPQueryService（search.py）。"""

    def __init__(self, mp_api_key: str):
        from search import MPQueryService
        self._svc = MPQueryService(api_key=mp_api_key, only_stable=True, max_results=20)

    async def execute(self, tool_name: str, tool_args: Dict) -> str:
        return await asyncio.to_thread(self._sync, tool_name, tool_args)

    def _sync(self, tool_name: str, tool_args: Dict) -> str:
        try:
            if tool_name == "mp_search":
                results = self._svc.query(tool_args["query"])
                n       = tool_args.get("max_results", 5)
                payload = {
                    "count":   len(results),
                    "results": [self._summary(r) for r in results[:n]],
                }

            elif tool_name == "mp_fetch":
                results = self._svc.query(tool_args["material_id"])
                if not results:
                    return json.dumps({"error": f"not found: {tool_args['material_id']}"})
                r       = results[0]
                struct  = r["_structure"]
                payload = {
                    **self._summary(r),
                    "num_sites":   len(struct),
                    "volume":      round(struct.volume, 4),
                    "composition": str(struct.composition),
                }

            elif tool_name == "mp_download":
                from search import save_structure_to_disk
                results = self._svc.query(tool_args["material_id"])
                if not results:
                    return json.dumps({"error": f"not found: {tool_args['material_id']}"})

                item     = results[0]
                struct   = item["_structure"]
                filename = f"{item['material_id']}_{item['formula']}"

                saved = save_structure_to_disk(
                    struct   = struct,
                    save_dir = tool_args.get("save_dir", "./structures"),
                    filename = filename,
                    fmt      = tool_args.get("fmt", "cif"),
                )
                payload = {
                    "material_id": tool_args["material_id"],
                    "saved_files": saved,
                    "success":     bool(saved),
                }

            else:
                payload = {"error": f"unknown tool: {tool_name}"}

        except Exception as e:
            payload = {"error": str(e)}

        # ✅ 修复1：补上 return，否则函数返回 None 导致后续崩溃
        return json.dumps(payload, cls=MontyEncoder, ensure_ascii=False, indent=2)

    @staticmethod
    def _summary(r: Dict) -> Dict:
        """排除大文本字段和 pymatgen 对象，避免超出 LLM context。"""
        return {k: v for k, v in r.items()
                if k not in ("_structure", "xyz", "cif", "poscar")}

    async def close(self): pass


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
        {"role": "system", "content": "You are a materials science assistant. "
                                      "Use the provided tools to query Materials Project."},
        {"role": "user",   "content": user_message},
    ]

    while True:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=executor.tools,
            tool_choice="auto",
            max_tokens=1024,
            temperature=0.7,
            **extra,
        )
        msg = response.choices[0].message

        # 无 tool_call：返回最终答案
        if not msg.tool_calls:
            return msg.content

        # 转为标准字典再 append，避免 DeepSeek 400 错误
        messages.append(message_to_dict(msg))

        # 并发执行所有工具调用
        results = await asyncio.gather(*[
            executor.execute(tc.function.name, json.loads(tc.function.arguments))
            for tc in msg.tool_calls
        ])

        # 将工具结果逐条追加
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
    # ✅ 修复2：默认值改为 None，确保空值检测正常触发
    MP_KEY  = os.environ.get("MP_API_KEY")
    LLM_KEY = os.environ.get("LLM_API_KEY")

    if not MP_KEY:
        raise ValueError("❌ MP_API_KEY 未设置，请检查 .env 文件")
    if not LLM_KEY:
        raise ValueError("❌ LLM_API_KEY 未设置，请检查 .env 文件")

    # Q1 = "Find the most stable Fe2O3 structure and download its CIF file."
    # Q2 = "Get mp-126 and save it as POSCAR for VASP calculation."
    Q1 = "我想要获得特殊的金红石型的VO2结构信息并下载为POSCAR文件, 不一定非得是stable的。"
    Q2 = "我想要知道稳定的FeV2O4的band_gap是多少，如果它是导体请下载为POSCAR文件，如果不是请告诉我它的band_gap是多少。"
    executor = LocalToolExecutor(mp_api_key=MP_KEY)
    for q in (Q1, Q2):
        print(f"\n>>> {q}")
        ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
        print(ans)

    await executor.close()


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())