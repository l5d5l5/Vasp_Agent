# Analysis_tool/analysis_tool_use.py
"""
Entry point for the Analysis Tool_use LLM agent.

Usage (from Tool_use/):
    python -m Analysis_tool.analysis_tool_use

Or directly:
    python D:/path/to/Tool_use/Analysis_tool/analysis_tool_use.py

Env vars (loaded from Search_tool/.env or local .env):
    LLM_API_KEY  — required
    MP_SCHEMA_LANG — "en" | "cn" (default: "en")

LLM provider: change llm_provider= in the run() call inside main().
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / "Search_tool" / ".env")
load_dotenv()

try:
    from .analysis_tool_executor import AnalysisToolExecutor
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from Analysis_tool.analysis_tool_executor import AnalysisToolExecutor


LLM_CONFIGS: Dict[str, Dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-chat",
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
    cfg = LLM_CONFIGS[provider]
    client = OpenAI(api_key=llm_api_key, base_url=cfg["base_url"])
    client._mp_model = cfg["model"]
    client._mp_extra = cfg["extra"]
    return client


def message_to_dict(msg: Any) -> Dict:
    d: Dict[str, Any] = {
        "role":    msg.role,
        "content": msg.content if msg.content is not None else "",
    }
    # DeepSeek thinking mode: reasoning_content must be echoed back to the API
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


async def run(
    user_message: str,
    executor: AnalysisToolExecutor,
    llm_provider: str = "deepseek",
    llm_api_key: str = "",
) -> str:
    client  = _get_openai_client(llm_provider, llm_api_key)
    model   = client._mp_model
    extra   = client._mp_extra
    messages: List[Dict] = [
        {
            "role": "system",
            "content": (
                "You are a computational chemistry assistant specialising in VASP DFT "
                "post-processing analysis. You have access to tools that can: "
                "inspect structure files (POSCAR/CONTCAR), analyse structural relaxation "
                "convergence (OUTCAR/OSZICAR), extract projected DOS and d-band descriptors "
                "(DOSCAR), and analyse chemical bonding via COHP/ICOHP from LOBSTER output. "
                "All tools accept a work_dir (path to the VASP calculation directory). "
                "For DOS analysis, always specify which elements and orbitals to project. "
                "For COHP analysis, call vasp_cohp_summary first to discover bond labels, "
                "then call vasp_cohp_curves or vasp_cohp_export for detailed data. "
                "Return a concise summary of the analysis results."
            ),
        },
        {"role": "user", "content": user_message},
    ]

    while True:
        response = client.chat.completions.create(
            model       = model,
            messages    = messages,
            tools       = executor.tools,
            tool_choice = "auto",
            max_tokens  = 2048,
            temperature = 0.3,
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


async def main():
    LLM_KEY = os.environ.get("LLM_API_KEY")
    if not LLM_KEY:
        raise ValueError(
            "LLM_API_KEY not set. Add it to Search_tool/.env or set it in the environment."
        )

    executor = AnalysisToolExecutor()
    print(f"[Tools] {[t['function']['name'] for t in executor.tools]}")

    DOS_DIR   = str(Path(__file__).parent / "Test" / "dos")
    RELAX_DIR = str(Path(__file__).parent / "Test" / "clean-zone")

    QUESTIONS = [
        f"Analyse the VASP calculation in {DOS_DIR}: "
        "first show me the structure info, then calculate the d-band center of Pd.",
    ]

    try:
        for q in QUESTIONS:
            print(f"\n{'='*60}\n>>> {q}\n{'='*60}")
            ans = await run(q, executor, llm_provider="deepseek", llm_api_key=LLM_KEY)
            print(ans)
    finally:
        await executor.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(main())
