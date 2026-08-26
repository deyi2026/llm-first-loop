"""记忆提取（design.md §2.1.3.6 机制五 / FR-MEM-01）.

边界说明（M11）: 本模块为记忆块解析纯函数（无 LLM 往返），被 loop._remember（即时沉淀）与 memory/extractor.py（独立提取调度器）共同复用;独立提取的触发/预算/异步/审计在 extractor.py。

system prompt 约定结构化记忆块 `[[memory]] {...} [[/memory]]`，
REMEMBER 阶段解析回答中的记忆块生成条目；解析失败如实记录，不丢弃原始回答。
"""

from __future__ import annotations

import json
import re
from typing import Any

from llm_loop.memory.store import MemoryEntry

_MEMORY_BLOCK_RE = re.compile(r"\[\[memory\]\](.*?)\[\[/memory\]\]", re.DOTALL)


def extract_memory_blocks(answer: str) -> list[dict[str, Any]]:
    """从最终回答中解析 `[[memory]] {...} [[/memory]]` 块.

    Returns:
        解析出的记忆块 dict 列表；非法 JSON 块返回 {"_parse_error": 原文}。
    """
    blocks: list[dict[str, Any]] = []
    for m in _MEMORY_BLOCK_RE.finditer(answer):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                blocks.append(data)
            else:
                blocks.append({"_parse_error": f"记忆块必须是 JSON 对象: {raw[:100]}"})
        except json.JSONDecodeError:
            # EVO-20260812-2bd55cf3: 双大括号自动纠错——AI 常照抄 prompt 模板的 {{ }}（Jinja2 转义）
            # 导致 json.loads 失败、记忆静默不落盘。先试单大括号替换；仍失败才如实报错并标注该特征。
            fixed = raw.replace("{{", "{").replace("}}", "}")
            if fixed != raw:
                try:
                    data = json.loads(fixed)
                    if isinstance(data, dict):
                        blocks.append(data)
                        continue
                except json.JSONDecodeError:
                    data = None  # 双大括号纠错仍失败；下方统一返回可见 parse_error
            hint = "（常见错误: 若你写了 {{ }} 双大括号，请改为 { } 单大括号）"
            blocks.append({"_parse_error": f"记忆块 JSON 解析失败: {raw[:100]}{hint}"})
    return blocks


def memory_blocks_to_entries(
    blocks: list[dict[str, Any]],
    *,
    session_id: str,
    message_id: str,
) -> tuple[list[MemoryEntry], list[str]]:
    """记忆块 → MemoryEntry 列表 + 失败记录列表.

    非法块（缺 content 或含 _parse_error）不落盘，如实记录失败原因。
    """
    entries: list[MemoryEntry] = []
    failures: list[str] = []
    for b in blocks:
        if "_parse_error" in b:
            failures.append(b["_parse_error"])
            continue
        content = str(b.get("content", "")).strip()
        if not content:
            failures.append(f"记忆块缺少 content: {json.dumps(b, ensure_ascii=False)[:100]}")
            continue
        mtype = str(b.get("type", "fact"))
        # Phase 2: type 集合扩展 procedure（流程/操作类记忆）
        if mtype not in {"fact", "decision", "convention", "procedure"}:
            mtype = "fact"
        keywords = [str(k) for k in (b.get("keywords") or [])]
        # Phase 2: citations 溯源解析（非法/缺省 → 空列表，不丢弃整块）
        citations: list[dict] = []
        citations_raw = b.get("citations")
        if isinstance(citations_raw, list):
            for c in citations_raw:
                if isinstance(c, dict) and c.get("ref"):
                    citations.append(
                        {
                            "kind": str(c.get("kind", "message")),
                            "ref": str(c["ref"]),
                            "note": str(c.get("note", "")),
                        }
                    )
        entries.append(
            MemoryEntry(
                id="",
                type=mtype,
                content=content,
                keywords=keywords,
                source_session_id=session_id,
                source_message_id=message_id,
                created_at="",
                citations=citations,  # Phase 2 溯源
                scope=_classify_scope(content),  # 2026-08-20 记忆分级（防跨会话污染）
            )
        )
    return entries, failures


# ── 2026-08-20 记忆分级：会话瞬时性识别（防 A 会话调试现场污染 B 会话判断）──
# 保守规则：仅当内容含硬瞬时标记（会话 id/PID/tmp 路径/临时文件产物）才标 scope=session；
# 通用决策/约定/经验即使带时间戳也不降级（时间戳不构成瞬时性）。
_TRANSIENT_SESSION_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|"  # session/事件 id
    r"session-?[0-9a-f]{8}|"
    r"\bPID\s*\d{3,}\b|pid[=:]\s*\d{3,}|"  # 进程号
    r"/private/tmp/|/tmp/|"  # 临时路径
    r"\.sse\b|\.zstd\b|measure_[a-z0-9]+\.sse|"  # 临时产物
    r"已 kill|已终止.*进程|端口.*已释放|残留进程"  # 现场处置
)


def _classify_scope(content: str) -> str:
    """按内容判定记忆作用域: 含硬瞬时标记 → session（仅原会话召回），否则 global."""
    return "session" if _TRANSIENT_SESSION_RE.search(content) else "global"
