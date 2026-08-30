"""M4.3 认知缓存标记编码（研究线 M1/M2 落地，2026-08-29）.

背景（docs/local/ANALYSIS-20260828-freetoken-semantic-caching.md §4-5）：
    缓存复用的敌人不是上下文变长，而是前缀变更；两层的正确做法相同——
    识别语义上不变的段，把变更严格推后到不变段之后。
    LFL 的锚是"程序治理出来的"：本模块在 wire 组装点把 LFL 的认知分级
    编码为 cache_tag，供认知引擎侧（mlx-lm CognitivePromptCache，
    PIN_TAGS = goal/evidence/identity/rules）做认知优先 KV 驱逐。

设计约束：
    - 纯函数、无 IO、无全局态；仅在显式启用的端点上生效（默认关，零回归）；
    - 云端 provider 零接触——cache_tag 是非标字段，GLM 曾对参数敏感（1210），
      绝不给未启用端点的请求加任何字段；
    - 规则与认知 server PIN_TAGS 对齐，勿单侧漂移。

打标规则（按消息特征 + 结构位置，保守优先）：
    - system 消息 → "rules"     （LFL 身份/规则，pin 级）
    - 尾部最后一条 user → "goal" （当前任务指令，pin 级；轮次推进自动降级）
    - 含 "[上下文压缩]" 的 user 段 → "summary" （可再生投影，驱逐优先）
    - 含 "evidence://" 引用的段 → "evidence" （观察身份，pin 级）
    - 其余消息不打标（引擎侧按默认桶 LRU）
"""

from __future__ import annotations

import fnmatch
import os

from llm_loop.core.injection_labels import (
    PROGRAM_APPENDIX_NOTICE,
    PROGRAM_RECOVERY_LABEL,
    REFERENCE_LABEL,
    STATUS_LABEL,
)

# 认知 server PIN_TAGS 对齐（mlx-lm cognitive_cache.py:57）
PIN_TAGS = frozenset({"goal", "evidence", "identity", "rules"})

_COMPACT_MARKERS = (
    "[上下文压缩]",
    "[context compression]",
    "[上下文注入·非新指令]",  # legacy program appendix
    PROGRAM_APPENDIX_NOTICE,
    REFERENCE_LABEL,
    STATUS_LABEL,
    PROGRAM_RECOVERY_LABEL,
)
_EVIDENCE_MARKER = "evidence://"


def tagging_enabled_for(base_url: str | None, *, env: dict[str, str] | None = None) -> bool:
    """判定端点是否启用认知打标.

    开关: COGNITIVE_TAG_ENDPOINTS（逗号分隔 base_url 通配，如 "http://localhost:8901*"）。
    默认空 → 全关（零回归）。env 参数供测试注入。
    """
    if not base_url:
        return False
    env = env if env is not None else dict(os.environ)
    patterns = [p.strip() for p in env.get("COGNITIVE_TAG_ENDPOINTS", "").split(",") if p.strip()]
    return any(fnmatch.fnmatch(base_url, pat) for pat in patterns)


def _classify_message(msg: dict, *, is_tail_user: bool) -> str | None:
    role = msg.get("role")
    content = msg.get("content") or ""
    if not isinstance(content, str):
        return None
    if role == "system":
        return "rules"
    if role == "user":
        # R1/L1: program-origin user-wire messages must never be pinned as the
        # human goal merely because they are last. Source semantics precede position.
        if any(m in content for m in _COMPACT_MARKERS):
            return "summary"
        if is_tail_user:
            return "goal"
        if _EVIDENCE_MARKER in content:
            return "evidence"
    elif role == "assistant" and _EVIDENCE_MARKER in content:
        return "evidence"
    return None


def apply_cognitive_cache_tags(messages: list[dict]) -> list[dict]:
    """返回打标后的新消息列表（浅拷贝被改消息，原列表不动）. 幂等：已有 cache_tag 不覆盖."""
    tail_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            tail_user_idx = i
            break
    out: list[dict] = []
    changed = 0
    for i, msg in enumerate(messages):
        tag = _classify_message(msg, is_tail_user=(i == tail_user_idx))
        if tag and "cache_tag" not in msg:
            out.append({**msg, "cache_tag": tag})
            changed += 1
        else:
            out.append(msg)
    if changed:
        import logging

        logging.getLogger(__name__).debug(
            "cognitive.cache_tags: tagged %d/%d messages", changed, len(messages)
        )
    return out
