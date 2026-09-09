#!/usr/bin/env python3
"""R0 Freeze Evidence: 1210 offending payload → 脱敏 wire fixture.

来源: data/audit/offending_payloads/（主区/镜像区均可，见 SOURCE_DIR）
输出: tests/fixtures/wire/<category>.json

脱敏规则（design.md §5.1）:
  - message content 截断至 CONTENT_LIMIT 字符（保字节顺序，前缀原样）
  - tools schema 深截断（保 name/结构）
  - 防御性剔除 secret 模式值
  - 保留: messages role 结构 / tool_calls / tool_call_id / params / is_compact_first
  - meta: source_file / sanitized_at / tail_user_run / shape / category

幂等: 同输入重跑输出 byte-identical（sanitized_at 除外用 SOURCE mtime）。
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

CONTENT_LIMIT = 300  # 每条 message content 保留前缀字符数
TOOL_SCHEMA_LIMIT = 3  # tools[].function.parameters.properties 保留键数
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|bearer)\s*[:=]\s*\S+"),
)

# 六类形态 → 源文件（2026-08-29 定位，见 R0 分析）
CATEGORIES: dict[str, dict] = {
    "tail1_compact": {  # run=1: provider 间歇性拒绝（blind-retry 证据形态）
        "file": "20260828T185055528Z_63e27ed7.json",
        "expect_run": 1,
        "note": "tail4=[assistant,tool,tool,user]; mem+compact; blind retry 5/5 成功形态",
    },
    "tail2_compact": {  # run=2: 结构性触发（aggregate recovery 形态）
        "file": "20260828T161048002Z_af2ee3ae.json",
        "expect_run": 2,
        "note": "tail4=[tool,tool,user,user]; mirror 区样本",
    },
    "tail3_compact": {  # run=3
        "file": "20260829T043828388Z_883b4725.json",
        "expect_run": 3,
        "note": "tail4=[assistant,user,user,user]; mem+compact",
    },
    "tail2_mem_compact": {  # user+memory+compact
        "file": "20260828T235441148Z_63e27ed7.json",
        "expect_run": 2,
        "note": "tail4=[tool,tool,user,user]; memory 标记在尾部 8 条内",
    },
    "tail2_tool_user_compact": {  # assistant,tool+user+compact
        "file": "20260828T193943766Z_63e27ed7.json",
        "expect_run": 2,
        "note": "tail4=[assistant,tool,user,user]",
    },
    "tail_tc_compact": {  # tool_calls+compact
        "file": "20260828T193943766Z_63e27ed7.json",
        "expect_run": 2,
        "note": "尾部 10 条内 assistant 带 tool_calls",
    },
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_CANDIDATES = [
    _REPO_ROOT / "data" / "audit" / "offending_payloads",
    _REPO_ROOT.parent / "llm-first-loop" / "data" / "audit" / "offending_payloads",
]
OUT_DIR = _REPO_ROOT / "tests" / "fixtures" / "wire"


def _truncate(text: str, limit: int) -> str:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return f"{text[:limit]}...[TRUNCATED len={len(text)}]"


def _scrub_str(text: str) -> str:
    for pat in SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


def sanitize_message(msg: dict) -> dict:
    out = copy.deepcopy(msg)
    c = out.get("content")
    if isinstance(c, str):
        out["content"] = _truncate(_scrub_str(c), CONTENT_LIMIT)
    elif isinstance(c, list):
        out["content"] = [
            {**part, "text": _truncate(_scrub_str(part.get("text", "")), CONTENT_LIMIT)}
            if isinstance(part.get("text"), str)
            else part
            for part in c
        ]
    for tc in out.get("tool_calls") or []:
        fn = tc.get("function") or {}
        if isinstance(fn.get("arguments"), str):
            fn["arguments"] = _truncate(fn["arguments"], CONTENT_LIMIT)
    if isinstance(out.get("tool_call_id"), str):
        out["tool_call_id"] = out["tool_call_id"][:24]
    return out


def sanitize_tool(tool: dict) -> dict:
    out = copy.deepcopy(tool)
    fn = out.get("function") or {}
    desc = fn.get("description")
    if isinstance(desc, str):
        fn["description"] = _truncate(desc, 120)
    params = fn.get("parameters")
    if isinstance(params, dict):
        props = params.get("properties")
        if isinstance(props, dict) and len(props) > TOOL_SCHEMA_LIMIT:
            keep = dict(list(props.items())[:TOOL_SCHEMA_LIMIT])
            params["properties"] = {
                k: {**v, "description": _truncate(v.get("description", ""), 80)}
                if isinstance(v, dict) and isinstance(v.get("description"), str)
                else v
                for k, v in keep.items()
            }
            params["properties"]["__truncated__"] = (
                f"[{len(props) - TOOL_SCHEMA_LIMIT} more omitted]"
            )
    return out


def tail_user_run(msgs: list[dict]) -> int:
    n = 0
    for m in reversed(msgs):
        if m.get("role") == "user":
            n += 1
        else:
            break
    return n


def find_source(fname: str) -> Path:
    for d in SOURCE_CANDIDATES:
        p = d / fname
        if p.exists():
            return p
    raise FileNotFoundError(f"{fname} not in any source dir: {[str(s) for s in SOURCE_CANDIDATES]}")


def build_fixture(category: str, spec: dict) -> dict:
    src = find_source(spec["file"])
    raw = json.loads(src.read_text(encoding="utf-8"))
    msgs = [sanitize_message(m) for m in raw.get("messages", [])]
    run = tail_user_run(msgs)
    if run != spec["expect_run"]:
        raise ValueError(
            f"{category}: tail_user_run={run} != expected {spec['expect_run']} ({spec['file']})"
        )
    return {
        "schema": 2,  # fixture schema（区别于 payload schema=1）
        "category": category,
        "meta": {
            "source_file": src.name,
            "source_repo": "main" if "/llm-first-loop/" in str(src) else "mirror",
            "source_payload_schema": raw.get("schema"),
            "source_ts_utc": raw.get("ts_utc"),
            "model": raw.get("model"),
            "is_compact_first": raw.get("is_compact_first"),
            "msg_count": len(msgs),
            "tool_count": len(raw.get("tools", [])),
            "tail_user_run": run,
            "shape_tail4": [m.get("role") for m in msgs[-4:]],
            "note": spec["note"],
        },
        "messages": msgs,
        "tools": [sanitize_tool(t) for t in raw.get("tools", [])],
        "params": {
            k: v
            for k, v in (raw.get("params") or {}).items()
            if k not in ("api_key", "authorization")
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc = 0
    for cat, spec in CATEGORIES.items():
        try:
            fx = build_fixture(cat, spec)
            out = OUT_DIR / f"{cat}.json"
            out.write_text(json.dumps(fx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            print(
                f"[ok] {cat}: run={fx['meta']['tail_user_run']} msgs={fx['meta']['msg_count']} -> {out.name}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[FAIL] {cat}: {e}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
