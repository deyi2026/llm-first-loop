"""Unscored provider smoke for Stage S1. Does NOT use P01-P08 fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.calib.screening_runner import _build_client, _chat_once, _provider_profile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("provider", choices=["minimax", "deepseek", "kimi", "glm"])
    args = ap.parse_args()
    p = _provider_profile(args.provider)
    llm = _build_client(args.provider)
    try:
        r1 = _chat_once(
            llm,
            [{"role": "user", "content": "Provider compatibility smoke. Reply with SMOKE_OK."}],
            [],
            f"SMOKE-{args.provider}-plain",
            args.provider,
            p["model"],
        )
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "smoke_echo",
                    "description": "Return a fixed smoke value.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                },
            }
        ]
        messages = [
            {
                "role": "user",
                "content": "Call smoke_echo once with value=PING, then report SMOKE_TOOL_OK.",
            }
        ]
        r2 = _chat_once(
            llm, messages, tools, f"SMOKE-{args.provider}-tool1", args.provider, p["model"]
        )
        tool_ok = False
        if r2.tool_calls:
            tc = r2.tool_calls[0]
            args_json = json.dumps(
                tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments or "{}")
            )
            assistant = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": args_json},
                    }
                ],
            }
            rc = getattr(r2, "reasoning_content", None) or getattr(r2, "reasoning", None)
            if rc:
                assistant["reasoning_content"] = rc
            messages += [assistant, {"role": "tool", "tool_call_id": tc.id, "content": "PONG"}]
            r3 = _chat_once(
                llm, messages, tools, f"SMOKE-{args.provider}-tool2", args.provider, p["model"]
            )
            tool_ok = bool(r3.content)
        result = {
            "provider": args.provider,
            "model": p["model"],
            "plain_ok": bool(r1.content),
            "tool_ok": tool_ok,
            "reasoning_seen": bool(
                getattr(r1, "reasoning_content", None) or getattr(r2, "reasoning_content", None)
            ),
            "prompt_tokens": (getattr(r1, "prompt_tokens", 0) or 0)
            + (getattr(r2, "prompt_tokens", 0) or 0),
        }
        result["passed"] = bool(
            result["plain_ok"]
            and result["tool_ok"]
            and (result["reasoning_seen"] if p["thinking_supported"] else True)
        )
        out = Path("data/calib/smoke_s1")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{args.provider}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["passed"] else 1
    finally:
        llm.close()


if __name__ == "__main__":
    raise SystemExit(main())
