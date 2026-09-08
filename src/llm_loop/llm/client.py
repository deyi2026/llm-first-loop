"""LLM 流式客户端（多协议：OpenAI 兼容 / Anthropic Messages / Google Gemini）.

`wire_protocol`（ModelSpec 元数据，providers.json 模型条目可配）:
- openai（默认，零回归）：POST {base}/chat/completions，SSE choices[].delta
- anthropic：POST {base}/v1/messages，x-api-key + anthropic-version 头，
  SSE content_block_* 事件（text_delta / thinking_delta / input_json_delta / tool_use）
- google：POST {base}/v1beta/models/{model}:streamGenerateContent?alt=sse，
  x-goog-api-key 头，SSE candidates[0].content.parts（text / functionCall）

异常分类/思考分片/工具聚合/用量/截断语义三协议统一（LLMError 体系不变）。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from llm_loop.cache_guard.guard import (
    PromptGuard,  # EVO-20260818: 顶层 import（guard 无内部依赖，无循环）——guard property 类型标注
)
from llm_loop.core.message import ToolCall
from llm_loop.core.run_context import current_reasoning_effort
from llm_loop.llm.errors import (
    LLMEmptyResponseError,
    LLMError,
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)
from llm_loop.llm.schemas import ToolCallDeltaAggregator

logger = logging.getLogger(__name__)
  # finish() 含 json.loads 归一（约束 C5）


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall]
    provider: str = "openai-compat"
    truncated: bool = False
    reasoning_content: str | None = None  # M20 THK-02/03
    prompt_tokens: int = 0  # M52: 缺失保持 0 = 未提供，不伪造
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0  # M58: provider 前缀缓存命中 token（省钱可观测）


@dataclass
class ToolRoundInfo:
    """单轮工具调用摘要（引擎回执 + 事件日志）."""

    tool_name: str
    round_index: int
    args_summary: str = ""
    tool_call_id: str = ""


@dataclass
class StreamDelta:
    text: str = ""
    reasoning: str | None = None
    tool_round: ToolRoundInfo | None = None


@dataclass(frozen=True)
class GuardRequestContext:
    """单次 LLM 请求的 cache_guard 元数据；不可变且绝不存放在共享 client 状态。"""

    session_id: str = ""
    system_text: str | None = None
    compress_count_this_run: int = 0
    history_budget: int = 0
    run_round: int | None = None
    provider: str = ""
    model: str = ""
    breaker_active: bool = False  # P0（2026-08-25）: 压缩风暴熔断冻结期（规则 F 降级协调）


@dataclass
class _StreamAcc:
    """协议无关的流式聚合状态."""

    content_parts: list[str] = field(default_factory=list)
    reasoning_parts: list[str] = field(default_factory=list)
    truncated: bool = False
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    prompt_cache_hit_tokens: int = 0


_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


@dataclass
class _ThinkTagStreamParser:
    """请求局部的 `<think>` 增量状态机，支持标签跨任意 SSE delta 分片."""

    buffer: str = ""
    in_think: bool = False

    @staticmethod
    def _partial_marker_suffix(text: str, marker: str) -> int:
        """返回 text 尾部与 marker 前缀重合长度，完整 marker 留给 find 处理."""
        for size in range(min(len(text), len(marker) - 1), 0, -1):
            if marker.startswith(text[-size:]):
                return size
        return 0

    def feed(self, content: str) -> list[tuple[str, str]]:
        self.buffer += content
        out: list[tuple[str, str]] = []
        while self.buffer:
            marker = _THINK_CLOSE if self.in_think else _THINK_OPEN
            kind = "reasoning" if self.in_think else "content"
            idx = self.buffer.find(marker)
            if idx >= 0:
                before = self.buffer[:idx]
                self.buffer = self.buffer[idx + len(marker):]
                if before:
                    out.append((kind, before))
                self.in_think = not self.in_think
                continue

            keep = self._partial_marker_suffix(self.buffer, marker)
            safe_end = len(self.buffer) - keep
            if safe_end > 0:
                out.append((kind, self.buffer[:safe_end]))
            self.buffer = self.buffer[safe_end:]
            break
        return out

    def flush(self) -> list[tuple[str, str]]:
        """正常流结束时排空残片并重置；状态绝不跨请求存活."""
        text = self.buffer
        kind = "reasoning" if self.in_think else "content"
        self.buffer = ""
        self.in_think = False
        return [(kind, text)] if text else []


def _finish_response(
    acc: _StreamAcc,
    agg: ToolCallDeltaAggregator,
    provider: str,
    client: LLMClient | None = None,
    guard_context: GuardRequestContext | None = None,
) -> LLMResponse:
    raw_calls = agg.finish()
    tool_calls: list[ToolCall] = [
        ToolCall(id=c["id"], name=c["name"], arguments=c["arguments"]) for c in raw_calls
    ]
    # cache_guard 规则 G 回馈必须使用本请求快照，不能在长 stream 结束时再读取
    # provider 级共享 client.guard_session_id（跨会话并发会串台）。无显式上下文时
    # 仅为旧直接调用方保留 legacy 字段回退。
    try:
        if client is not None:
            _pg = getattr(client, "_pg", None)
            _sid = (guard_context.session_id if guard_context is not None else client.guard_session_id)
            if _pg is not None and _sid:
                _pg.record_result(
                    _sid,
                    acc.prompt_tokens,
                    acc.prompt_cache_hit_tokens,
                    provider=(
                        guard_context.provider
                        if guard_context is not None and guard_context.provider
                        else client.provider
                    ),
                    model=(
                        guard_context.model
                        if guard_context is not None and guard_context.model
                        else client.model
                    ),
                )
    except Exception:  # noqa: BLE001 — cache telemetry fail-open，不影响主响应
        logger.debug("cache guard response feedback failed (fail-open)", exc_info=True)
    return LLMResponse(
        content="".join(acc.content_parts) or None,
        tool_calls=tool_calls,
        provider=provider,
        truncated=acc.truncated,
        reasoning_content="".join(acc.reasoning_parts) or None,
        prompt_tokens=acc.prompt_tokens,
        completion_tokens=acc.completion_tokens,
        prompt_cache_hit_tokens=acc.prompt_cache_hit_tokens,
    )


# err1210 任务组 1（spec 4.4-1）: trace 按日轮转——进程内节流时间戳（每小时至多一次实际 stat）
_TRACE_ROTATE_LAST_CHECK = 0.0


def _cleanup_trace_shards(active: Path) -> None:
    """删除超过保留期的历史分片（LLM_PAYLOAD_TRACE_RETAIN_DAYS，默认 7 天；≤0 禁用）."""
    try:
        retain_days = int(os.environ.get("LLM_PAYLOAD_TRACE_RETAIN_DAYS", "7") or "7")
    except ValueError:
        retain_days = 7
    if retain_days <= 0:
        return
    cutoff = time.time() - retain_days * 86400
    try:
        for shard in active.parent.glob(f"{active.stem}-*{active.suffix}"):
            try:
                if shard.stat().st_mtime < cutoff:
                    shard.unlink()
            except OSError:
                pass  # 分片刚被并发移除/暂不可访问——跳过，继续清理其余分片
    except Exception:  # noqa: BLE001 — 清理失败 fail-open
        logger.debug("payload_trace 过期分片清理失败（fail-open）", exc_info=True)


def _maybe_rotate_trace_file(path: str) -> str:
    """[err1210 T1.1/T1.2] 写入前节流轮转检查: trace 文件 mtime 跨日 → 切分为历史分片.

    - 节流: 进程内模块级时间戳，每小时至多触发一次实际 stat（写入热路径零负担）。
    - 轮转: 活跃文件 mtime 所在日 ≠ 今日 → os.replace 为 payload_trace-YYYYMMDD.jsonl，
      当日请求继续写活跃文件（open "a" 自动新建）。
    - 同名分片已存在（时钟回拨/手动复制）→ 追加合并防丢后移除活跃文件。
    - 顺带执行过期分片清理（_cleanup_trace_shards）。
    - 全路径 fail-open: 任何异常返回原路径，不影响主请求写入。
    """
    global _TRACE_ROTATE_LAST_CHECK
    now = time.time()
    if now - _TRACE_ROTATE_LAST_CHECK < 3600.0:
        return path
    _TRACE_ROTATE_LAST_CHECK = now
    try:
        from datetime import datetime

        active = Path(path)
        if not active.exists():
            return path
        mtime_day = datetime.fromtimestamp(active.stat().st_mtime).strftime("%Y%m%d")
        today = datetime.now().strftime("%Y%m%d")
        if mtime_day != today:
            archived = active.with_name(f"{active.stem}-{mtime_day}{active.suffix}")
            if archived.exists():
                with open(archived, "ab") as dst, open(active, "rb") as src:
                    shutil.copyfileobj(src, dst)
                active.unlink()
            else:
                os.replace(active, archived)
        _cleanup_trace_shards(active)
    except Exception:  # noqa: BLE001 — 轮转失败 fail-open（写入继续走活跃文件）
        logger.debug("payload_trace 轮转检查失败（fail-open）", exc_info=True)
    return path


def _trace_payload_fingerprint(
    payload: dict[str, Any], messages: list[dict], *, session_id: str, provider: str, model: str
) -> None:
    """[临时诊断 2026-08-27] 请求分段指纹追踪——定位轮间前缀漂移段（缓存命中暴跌排查）.

    背景: 上游裸调健康、生产请求参数恒定，但轮间命中钉死在工具块头部——怀疑
    messages/tools 之外或极靠前位置存在轮间漂移元素，且对规则 A（system）与
    cache.window（消息）均不可见。本函数在发送前对请求体做确定性分段哈希：
    - tools 整块哈希 + 数量（工具 schema 轮间漂移 → 一眼可见）
    - 除 messages/tools 外的顶层参数哈希（thinking/effort/tool_choice 等）
    - 逐消息 sha256（canonical JSON：含 role/content/tool_calls 全字段）
    逐请求一行 JSON 追加 data/audit/payload_trace.jsonl（可用 env 改路径）。
    只读不改 payload；任何异常吞掉 fail-open，绝不影响主请求。
    env LLM_PAYLOAD_TRACE=0 关闭（默认开，根因定位后建议关闭）。
    """
    if os.environ.get("LLM_PAYLOAD_TRACE", "1") != "1":
        return
    try:
        import hashlib

        def _h(obj: Any) -> str:
            canon = json.dumps(obj, ensure_ascii=False, sort_keys=True)
            return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

        def _hw(obj: Any) -> str:
            """wire 级哈希：不排序、ensure_ascii=True——与 httpx json= 实际发出的字节一致.

            键插入序漂移（canonical sort_keys 哈希会掩盖）在此层现形。
            """
            wire = json.dumps(obj)  # httpx 默认序列化行为（插入序 + ASCII 转义）
            return hashlib.sha256(wire.encode("utf-8")).hexdigest()[:16]

        def _type_tag(a: Any) -> str:
            if isinstance(a, str):
                return "str"
            if isinstance(a, dict):
                return "dict"
            if a is None:
                return "None"
            return f"other_{type(a).__name__}"

        def _arg_type(tc: Any) -> str:
            """单个 tool_call 的 arguments 形态标记（1210 归因：区分 str/dict/缺失/扁平）."""
            if not isinstance(tc, dict):
                return "tc_non_dict"
            fn = tc.get("function")
            if isinstance(fn, dict):
                if "arguments" not in fn:
                    return "missing"
                return _type_tag(fn["arguments"])
            if "arguments" in tc:
                return "flat_" + _type_tag(tc["arguments"])
            return "flat_no_args"

        top = {k: v for k, v in payload.items() if k not in ("messages", "tools")}
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session_id": session_id,
            "provider": provider,
            "model": model,
            "tools_hash": _h(payload.get("tools") or []),
            "tools_wire": _hw(payload.get("tools") or []),
            "tools_n": len(payload.get("tools") or []),
            "params": {
                k: (_h(v) if isinstance(v, dict | list) else v) for k, v in sorted(top.items())
            },
            "msgs": [
                {
                    "i": i,
                    "role": m.get("role"),
                    "chars": len(m.get("content") or "") if isinstance(m.get("content"), str) else -1,
                    "h": _h(m),
                    "w": _hw(m),
                    "args": [_arg_type(tc) for tc in m.get("tool_calls") or []] or None,
                }
                for i, m in enumerate(messages)
            ],
        }
        # GPT 审计批次3: 默认路径跟 LFL_DATA_DIR（测试隔离不再污染生产 data/audit）
        path = os.environ.get(
            "LLM_PAYLOAD_TRACE_PATH",
            os.path.join(os.environ.get("LFL_DATA_DIR", "data"), "audit", "payload_trace.jsonl"),
        )
        path = _maybe_rotate_trace_file(path)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — 纯诊断，失败静默
        logger.debug("payload 指纹追踪写入失败", exc_info=True)


@dataclass
class LLMClient:
    """多协议流式客户端（OpenAI 兼容 / Anthropic / Google；wire_protocol 分发）.

    通过 `LLMClient.chat(messages, tools)` 发起请求；
    测试用 FakeLLM 需实现相同接口（Duck typing）。
    """

    api_key: str
    base_url: str
    model: str
    timeout_s: float = 120.0
    max_tokens: int | None = None  # 2026-08-15: 显式输出预算（None=不发字段，模型默认）
    max_retries: int = 0
    wire_protocol: str = "openai"  # P3-5: openai / anthropic / google（ModelSpec 元数据）

    # 兼容构造: settings 装配（保留字段注入）
    provider: str = "openai-compat"
    # M20 THK-01/CFG-03: DeepSeek V4 思考模式（默认开启；非 DeepSeek 不发）
    thinking_mode: bool = True
    reasoning_effort: str = "high"
    reasoning_effort_map: dict[str, str] | None = None

    # M47（design §5.5）: 思考参数泛化 - 显式传入时以此为准（消除硬编码 deepseek.com）;
    # None 时保持原 _thinking_supported() 行为（向后兼容，零回归）.
    thinking_supported: bool | None = None
    # 2026-08-18 cache_guard（MCP 出入口）: 请求前规则校验开关（默认开；CACHE_GUARD=0 关闭）
    guard_enabled: bool = True
    # legacy guard 字段：仅兼容直接调用方。主 engine 使用 GuardRequestContext，
    # 不再把 per-request 元数据写进 provider 级共享 LLMClient。
    guard_system: str | None = None
    guard_session_id: str = ""
    guard_compress_count: int = 0
    guard_history_budget: int = 0
    # 模型切换检测（拷问②）: 记录上次模型——切换时重置 guard 窗口（防旧模型低命中误拦）
    guard_last_model: str = ""
    def __post_init__(self) -> None:
        # 2026-08-20 (Sub2API Grok 兼容): Connection: close 关闭连接复用——
        # 复用的 httpx 连接池对 ai.mxnook.com 网关的 keepalive 不兼容（流式请求挂起/HTTP 400）；
        # 每次新连接对 DeepSeek/MiniMax/本地 provider 实测零功能影响（仅少一次连接复用）。
        # 2026-08-21 修复（本地模型 400 根因，见 EXPERIENCE-20260821-urllib-sse-lm-studio-400）:
        #   Connection: close 与 LM Studio 本地 SSE 冲突——实测连续请求交替 200/400
        #   （LM Studio 判定客户端提前断开，server 日志 "Client disconnected. Stopping generation"）。
        #   本地 provider（localhost/127.0.0.1）豁免该头；远程 provider 保留原行为（零回归）。
        # 2026-08-24 本地直连忽略系统代理（根因修复）: httpx 默认 trust_env=True 经 urllib
        # 读取 macOS 系统代理（Surge 等代理工具把 127.0.0.1:6152 设为系统代理）→ 回环 LLM
        # 请求被转给代理 → Surge 无法代理自身回环 → 503 Connection Closed（SGErrorDomain）
        # → 表现即"本地模型出错"。本地推理必须直连（llama-server KV 前缀缓存依赖同 slot
        # 直连; 见 EXPERIENCE-local-model-config）；远程 provider 保持默认（需代理访问
        # API 的场景零回归）。env LLM_TRUST_ENV 显式覆盖（1=启用系统代理, 0=禁用）。
        base = (self.base_url or "").lower()
        _is_local_base = any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0"))
        self._is_local_base = _is_local_base  # 2026-08-24: 供 _stream_openai 判本地关 thinking
        if _is_local_base:
            headers: dict[str, str] = {}
        else:
            headers = {"Connection": "close"}
        _trust_override = os.environ.get("LLM_TRUST_ENV")
        if _trust_override is not None:
            trust_env = _trust_override.strip().lower() in ("1", "true", "yes", "on")
        else:
            trust_env = not _is_local_base
        self._client = httpx.Client(timeout=self.timeout_s, headers=headers, trust_env=trust_env)

    def _thinking_supported(self) -> bool:
        """思考参数发送判定（M20 CFG-03 + M47 §5.5）.

        - thinking_supported 显式传入（非 None）→ 以传入值为准（注册表元数据驱动）
        - thinking_supported=None → 原行为: provider 为 deepseek 或 base_url 含 deepseek.com
        """
        if self.thinking_supported is not None:
            return self.thinking_supported
        return self.provider == "deepseek" or "deepseek.com" in self.base_url

    @property
    def guard(self) -> PromptGuard | None:
        """cache_guard 实例（懒创建，chat_stream 内初始化；供 architecture_status 注入快照）."""
        return getattr(self, "_pg", None)

    def ensure_guard(self) -> PromptGuard:
        """预创建 cache_guard（幂等；EVO-20260818: factory 装配后调用使
        architecture_status 快照进程启动即可用——懒创建会让 web 端点在首个请求前无数据）."""
        _guard = getattr(self, "_pg", None)
        if _guard is None:
            # EVO-20260818（spec §6.2-6，grill-me 2.2）: 命中回执开关——
            # lms-chat 等本地推理无命中回执（三字段兜底后仍恒 0）→ 规则 G 停用
            # 防恒 0 误拦；env CACHE_GUARD_HIT_TELEMETRY 显式覆盖
            _hit_tel = os.environ.get("CACHE_GUARD_HIT_TELEMETRY")
            if _hit_tel is not None:
                _tel = _hit_tel not in ("0", "false", "False")
            else:
                _tel = self.wire_protocol != "lms-chat"
            _guard = PromptGuard(hit_telemetry=_tel)
            self._pg = _guard
        return _guard

    def close(self) -> None:
        self._client.close()

    # ── 统一入口（协议分发） ──
    @staticmethod
    def _normalize_tool_call_args(messages: list[dict]) -> tuple[list[dict], dict | None]:
        """EVO-20260827 V3: tool_call.function.arguments 非 str → 强制串化（智谱 1210 唯一探明触发器）.

        取证（6485b02b 会话排查 + 智谱 coding 端点二分探测）:
        - 15 个请求变体中仅「arguments 缺失(D4)/为 dict(D5)」复现 HTTP 400
          {"code":"1210","API 调用参数有误"}；孤儿配对/null content/额外键等全过。
        - ToolCall dataclass 标注 arguments: dict（core/message.py:54），存在隐式
          dict 构建分支——任何未经 json.dumps 的 wire 重建都会整轮 400，且 provider
          只回笼统 1210 无定位信息。
        两遍扫描 + copy-on-write（不改调用方消息）；fail-open 不阻断；
        返回 (新消息列表, 首个修复项诊断 {msg_idx, call_idx, tool}) 供异常归因。
        """
        needs = False
        for m in messages:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if isinstance(fn, dict) and not isinstance(fn.get("arguments"), str):
                    needs = True
                    break
            if needs:
                break
        if not needs:
            return messages, None

        out: list[dict] = []
        first_fixed: dict | None = None
        fixed_count = 0
        for mi, m in enumerate(messages):
            tcs = m.get("tool_calls")
            if not tcs:
                out.append(m)
                continue
            new_tcs: list[dict] = []
            changed = False
            for ti, tc in enumerate(tcs):
                fn = tc.get("function") if isinstance(tc, dict) else None
                args = fn.get("arguments") if isinstance(fn, dict) else None
                if isinstance(args, str):
                    new_tcs.append(tc)
                    continue
                fn2 = dict(fn or {})
                fn2["arguments"] = json.dumps(args if args is not None else {}, ensure_ascii=False)
                tc2 = dict(tc) if isinstance(tc, dict) else {}
                tc2["function"] = fn2
                new_tcs.append(tc2)
                changed = True
                fixed_count += 1
                if first_fixed is None:
                    first_fixed = {
                        "msg_idx": mi,
                        "call_idx": ti,
                        "tool": (fn2.get("name") if isinstance(fn2.get("name"), str) else "") or "?",
                    }
            if changed:
                m2 = dict(m)
                m2["tool_calls"] = new_tcs
                out.append(m2)
            else:
                out.append(m)
        logger.warning(
            "提交视图修复(V3): %d 处 tool_call.arguments 非 str 已强制串化"
            "（首个 msg#%d call#%d %s）——智谱 1210 触发器防御",
            fixed_count,
            (first_fixed or {}).get("msg_idx", -1),
            (first_fixed or {}).get("call_idx", -1),
            (first_fixed or {}).get("tool", "?"),
        )
        return out, first_fixed

    @staticmethod
    def _sanitize_openai_tool_pairs(messages: list[dict]) -> list[dict]:
        """EVO-20260827 V2: OpenAI 路径 tool_calls↔tool 配对双向清洗（连续 400 根因修复）.

        取证（eb5c2686/6485b02b 等 5+ 会话，跨 provider 复现）:
        "An assistant message with 'tool_calls' must be followed by tool messages
        responding to each 'tool_call_id'" —— 反向孤儿（声明在、应答被
        cache_compacted_for 过滤/锚点裁剪切断）是主签名；正向孤儿（tool 无声明）
        为次签名。上游 history.py 过滤不校验配对（689-695），此处为客户端最后防线。
        双向修复（copy-on-write，不改调用方消息对象）:
        - 正向: 孤儿 tool（无在案声明/重复应答）→ 删该 tool 消息
        - 反向: assistant tool_call 无应答（含被 user/system 插队截断、序列末尾悬空）
          → 从 tool_calls 剔除该 id；剔空后无文本则整条删
        fail-open + warning 如实记录两个方向的修复量。
        """
        has_tool = any(m.get("role") == "tool" for m in messages)
        has_tc = any(m.get("tool_calls") for m in messages)
        if not (has_tool or has_tc):
            return messages  # 快速路径：无配对结构原样返回（零开销）

        out: list[dict | None] = []
        pending: dict[str, int] = {}  # tool_call_id -> 其 assistant 在 out 中的下标
        removed_tool = 0
        stripped_ids = 0
        dropped_assistant = 0

        def _strip_pending() -> None:
            # pending 中剩余的 id 即"无应答孤儿"（主签名），从 assistant 剔除之
            nonlocal stripped_ids, dropped_assistant
            if not pending:
                return
            by_idx: dict[int, list[str]] = {}
            for tid, i in pending.items():
                by_idx.setdefault(i, []).append(tid)
            for i, orphan_tids in by_idx.items():
                orphan_set = set(orphan_tids)
                m_i = out[i]
                if m_i is None:
                    continue  # 理论不可达: pending 下标指向 append 后未被压缩的条目
                tcs = m_i.get("tool_calls") or []
                keep = [tc for tc in tcs if (tc or {}).get("id") not in orphan_set]
                stripped_ids += len(tcs) - len(keep)
                if keep:
                    m_i["tool_calls"] = keep
                else:
                    m_i.pop("tool_calls", None)
                    if not m_i.get("content"):  # 无文本且无 tool_calls → 整条删
                        out[i] = None  # 占位，尾部统一压缩
                        dropped_assistant += 1
            pending.clear()

        for m in messages:
            role = m.get("role")
            if role == "assistant":
                if pending:  # 新 assistant 前仍有悬空声明 → 反向孤儿
                    _strip_pending()
                    pending.clear()
                tcs = m.get("tool_calls") or []
                if tcs:
                    m2 = dict(m)  # copy-on-write
                    out.append(m2)
                    for tc in tcs:
                        tid = (tc or {}).get("id")
                        if tid:
                            pending[tid] = len(out) - 1
                else:
                    out.append(m)
            elif role == "tool":
                tid = m.get("tool_call_id") or ""
                if tid and tid in pending:
                    out.append(m)
                    del pending[tid]  # 首个应答有效；重复应答按孤儿删
                else:
                    removed_tool += 1
            else:  # user/system：插队即截断悬空声明
                if pending:
                    _strip_pending()
                    pending.clear()
                out.append(m)
        if pending:  # 序列末尾悬空
            _strip_pending()
        compacted: list[dict] = [m for m in out if m is not None]
        if removed_tool:
            logger.warning(
                "提交视图修复: 删除 %d 条孤儿 tool 消息（无在案声明/重复应答）", removed_tool
            )
        if stripped_ids or dropped_assistant:
            logger.warning(
                "提交视图修复: 剔除 %d 个无应答 tool_call_id，删除 %d 条空 assistant"
                "（反向孤儿——连续 400 主签名，EVO-20260827 V2）",
                stripped_ids,
                dropped_assistant,
            )
        return compacted

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,  # PARAM-01: 每次调用可覆盖超时（None 用构造值）
        model: str | None = None,  # WEB: 每次调用可覆盖模型（None 用构造值，供 Web 模型切换）
        guard_context: GuardRequestContext | None = None,
    ) -> Iterator[StreamDelta]:
        """流式请求，逐 content delta yield；generator 结束返回完整 LLMResponse.

        异常按类型抛出 LLMError 子类，由循环如实反馈。
        """
        protocol = self.wire_protocol
        actual_model = self.model if model is None else model
        # 每请求 guard 快照：显式上下文优先；legacy 直接调用仍从兼容字段构造一次
        # 局部快照，后续整个流（含终态 telemetry）都不再读取共享 per-request 字段。
        _guard_ctx = guard_context or GuardRequestContext(
            session_id=self.guard_session_id or "__global__",
            system_text=(
                self.guard_system
                if self.guard_system is not None
                else (
                    messages[0].get("content", "")
                    if messages and messages[0].get("role") == "system"
                    else ""
                )
            ),
            compress_count_this_run=self.guard_compress_count,
            history_budget=self.guard_history_budget,
            provider=self.provider,
            model=actual_model,
        )
        # cache_guard（MCP 出入口——唯一出入口）: 发送前规则校验（fail-open）
        self._guard_start_ts = 0
        if self.guard_enabled:
            try:
                _guard = self.ensure_guard()
                _d = _guard.check(
                    session_id=_guard_ctx.session_id or "__global__",
                    system_text=_guard_ctx.system_text or "",
                    messages=messages,
                    tools=tools,
                    run_round=_guard_ctx.run_round,
                    compress_count_this_run=_guard_ctx.compress_count_this_run,
                    history_budget=_guard_ctx.history_budget,
                    provider=_guard_ctx.provider or self.provider,
                    model=_guard_ctx.model or actual_model,
                    breaker_active=_guard_ctx.breaker_active,
                )
                if _d.rule == "submit_ratio" and _d.verdict == "WARN":
                    # 规则 F WARN 升级：注入提示（AI 可见——接近超限提前处理）
                    self.guard_warn_injected = getattr(self, "guard_warn_injected", False)
                if _d.verdict == "BLOCK":
                    from llm_loop.cache_guard.guard import CacheGuardBlockedError

                    raise CacheGuardBlockedError(f"cache_guard 拦截: {_d.detail}")
                if _d.verdict == "WARN":
                    logger.warning("cache_guard: %s（%s）", _d.rule, _d.detail)
            except LLMError:
                raise
            except Exception:  # noqa: BLE001 — fail-open 不阻断
                logger.debug("cache_guard 校验异常（fail-open）", exc_info=True)
        # 注意：Python 3.11+ 裸 `yield from` 会丢弃子生成器 return 值（StopIteration.value=None），
        # 必须显式捕获后 return 才能把终态 LLMResponse 传给消费者（engine 经 StopIteration.value 取终态）。
        # EVO-20260827: OpenAI 兼容路径孤儿 tool 清洗（anthropic 在 _to_anthropic_messages
        # 内已有对称清洗；google 的 functionCall 结构不同不适用）——防压缩切配对/注入
        # 插队产生的孤儿 tool 消息被 provider 拒收（连续 400 根因，跨 provider 取证）
        _v3_diag: dict | None = None  # EVO-20260827 V3: arguments 串化诊断（1210 归因用）
        if protocol not in ("anthropic", "google"):
            messages = self._sanitize_openai_tool_pairs(messages)
            messages, _v3_diag = self._normalize_tool_call_args(messages)
        try:
            if protocol == "anthropic":
                result = yield from self._stream_anthropic(
                    messages, tools, timeout_s=timeout_s, model=model, guard_context=_guard_ctx
                )
            elif protocol == "google":
                result = yield from self._stream_google(
                    messages, tools, timeout_s=timeout_s, model=model, guard_context=_guard_ctx
                )
            elif protocol == "lms-chat":
                result = yield from self._stream_lms_chat(messages, tools, timeout_s=timeout_s, model=model)
            else:
                result = yield from self._stream_openai(
                    messages, tools, timeout_s=timeout_s, model=model, guard_context=_guard_ctx
                )
        except LLMHTTPError:
            # EVO-20260827 V3: 参数类 400（如智谱 1210 笼统无定位）携带本轮 arguments
            # 串化诊断，异常侧日志可直接归因到消息位置/工具名。
            if _v3_diag:
                logger.error(
                    "LLM HTTP 错误伴随 V3 诊断: 本请求有 %d 处非串 arguments 已强制串化"
                    "（首个 msg#%s call#%s %s）——若仍 400 属其他结构残留",
                    _v3_diag.get("fixed_total", 0),
                    _v3_diag.get("msg_idx"),
                    _v3_diag.get("call_idx"),
                    _v3_diag.get("tool"),
                )
            raise
        # EVO-20260818-92bd97d6: 空响应兜底——流正常结束但无任何内容/工具调用
        # 视为异常（流被截断/模型异常），抛异常走如实反馈，不再静默记为 content=(空)
        if result is not None and not result.content and not result.tool_calls:
            raise LLMEmptyResponseError(
                f"模型返回空响应（无内容且无工具调用，provider={self.provider}，model={self.model}）",
                provider=self.provider,
            )
        return result

    # ── OpenAI 兼容（既有行为，零回归） ──
    def _stream_openai(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
        guard_context: GuardRequestContext | None = None,
    ) -> Iterator[StreamDelta]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        # 2026-08-20 (Sub2API Grok 兼容): 对第三方网关（base_url 含 mxnook.com 等），
        # tools 为空数组时省略 tools/tool_choice——该网关对 `tools: []` + thinking 字段
        # 组合返回 HTTP 400（单独都正常）。OpenAI 规范允许省略空 tools；
        # 其余 provider 保持原行为（M21 AUX-03: 空数组原样携带，协议边界锁定）。
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"  # 约束 C6
        elif "mxnook.com" in self.base_url:
            pass  # 第三方网关: 省略空 tools/tool_choice
        else:
            payload["tools"] = []
            payload["tool_choice"] = "auto"  # 约束 C6
        # 2026-08-15: 显式输出预算（None=不发字段，模型默认——思考链模型默认 4096 时
        # 思考占大半、最终分析被截断，用户现场反馈"回答被截断"根因）
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        # M20 THK-01: DeepSeek V4 思考模式显式声明（thinking_mode AND provider 支持才发送）
        # P1-FEISHU: 本地 provider (LM Studio) 不发 OpenAI 的 `thinking` 字段
        if self.thinking_mode and self._thinking_supported() and self.api_key:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = current_reasoning_effort.get() or self.reasoning_effort
        # 2026-08-24 本地 thinking 开关（SWE 对照实验定论, 见 docs/swe_ab_report.md）:
        # A 臂（关思考, 4 次独立尝试）0/4 通过 F2P, 全漏第二修复点; B 臂（开思考）通过。
        # → 本地默认【开启】thinking（能力优先）; env LOCAL_ENABLE_THINKING=0 显式关闭
        # （纯速度场景, 如交互闲聊）。llama.cpp qwen 模板默认思考开启, OpenAI 协议
        # thinking 字段不被尊重, 故用 chat_template_kwargs 显式控制。
        if getattr(self, "_is_local_base", False):
            _local_thinking = os.environ.get("LOCAL_ENABLE_THINKING", "1") != "0"
            _template_kwargs: dict[str, Any] = {"enable_thinking": _local_thinking}
            if _local_thinking and self.reasoning_effort_map:
                _requested_effort = (current_reasoning_effort.get() or self.reasoning_effort).strip().lower()
                _mapped_effort = self.reasoning_effort_map.get(_requested_effort)
                if _mapped_effort:
                    _template_kwargs["reasoning_effort"] = _mapped_effort
            # Preserve legacy wire when thinking is enabled but no model-owned mapping exists.
            if not _local_thinking or self.reasoning_effort_map:
                payload["chat_template_kwargs"] = _template_kwargs
        # 本地 provider（api_key 为空）不发 Authorization 头
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # [临时诊断 2026-08-27] 分段指纹落盘（见 _trace_payload_fingerprint docstring）——
        # 放在 payload 完整组装后、发送前；BLOCK 的请求在 chat_stream 层已被拦，不会到达这里。
        _trace_payload_fingerprint(
            payload,
            messages,
            session_id=(guard_context.session_id if guard_context else "") or "__global__",
            provider=self.provider,
            model=payload.get("model", "") or self.model,
        )

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
        # EVO-20260824: 大上下文流式断连重试（默认 1 次，env LLM_RETRY_DISCONNECT 可调/关）——
        # 观测: 150K+ 字符上下文下 deepseek 流式偶发 peer closed connection
        # （incomplete chunked read），同请求重试因前缀缓存命中率高、代价极低；
        # 仅在「尚无任何输出已产出」时重试（已有 content/reasoning/tool delta
        # 产出则重试会造成 UI 重复/工具重复执行，故不重试）。
        try:
            _retry_disconnect = int(os.environ.get("LLM_RETRY_DISCONNECT", "1"))
        except ValueError:  # 非法 env 兜底 1
            _retry_disconnect = 1
        _tc_seen = False

        def _openai_stream_once() -> Iterator[StreamDelta]:
            """单次流式请求（yield delta；传输异常向上抛，由外层重试判定）."""
            nonlocal _tc_seen
            think_parser = _ThinkTagStreamParser()
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    self._check_sse_error(chunk)
                    usage = chunk.get("usage")
                    if isinstance(usage, dict):
                        # M58 修复（审查中危）: 缺失不覆盖——部分 provider 在中间 chunk
                        # 带 usage 但缺字段（或全 0），覆盖式赋值会把已累计值清零。
                        pt = usage.get("prompt_tokens")
                        if pt:
                            acc.prompt_tokens = int(pt)
                        ct = usage.get("completion_tokens")
                        if ct:
                            acc.completion_tokens = int(ct)
                        # M58: 前缀缓存命中（DeepSeek prompt_cache_hit_tokens；Kimi 兜底 cached_tokens；
                        # 2026-08-18 MiniMax-M3: prompt_tokens_details.cached_tokens（嵌套——实测 128 命中）
                        hit = usage.get("prompt_cache_hit_tokens")
                        if hit is None:
                            hit = usage.get("cached_tokens")
                        if hit is None:
                            hit = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                        if hit:
                            acc.prompt_cache_hit_tokens = int(hit)
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        # MiniMax-M3 等 provider 可能把思考链放 content 的 <think> 标签；
                        # parser 必须请求局部且保留潜在 marker 前缀，避免分片泄漏/跨会话污染。
                        for kind, text in think_parser.feed(content):
                            if kind == "reasoning":
                                acc.reasoning_parts.append(text)
                                yield StreamDelta(text="", reasoning=text)
                            else:
                                acc.content_parts.append(text)
                                yield StreamDelta(text=text)
                    rc = delta.get("reasoning_content")
                    if rc:
                        acc.reasoning_parts.append(rc)
                        yield StreamDelta(text="", reasoning=rc)
                    if delta.get("tool_calls"):
                        _tc_seen = True
                        for tc in delta["tool_calls"]:
                            agg.add_delta(tc)
                    fr = choice.get("finish_reason")
                    if fr:
                        acc.finish_reason = fr
                    if acc.finish_reason == "length":
                        acc.truncated = True
                for kind, text in think_parser.flush():
                    if kind == "reasoning":
                        acc.reasoning_parts.append(text)
                        yield StreamDelta(text="", reasoning=text)
                    else:
                        acc.content_parts.append(text)
                        yield StreamDelta(text=text)
        _attempt = 0
        while True:
            _attempt += 1
            try:
                yield from _openai_stream_once()
                break  # 流完整结束（含 [DONE]）
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
            except (httpx.NetworkError, httpx.ProtocolError) as exc:
                # 传输级断连（peer closed / 连接重置 / 协议中断）→ 无输出已产出时重试一次
                _output_seen = bool(acc.content_parts or acc.reasoning_parts) or _tc_seen
                if _attempt <= _retry_disconnect and not _output_seen:
                    logger.warning(
                        "LLM 流式传输中断（尚无输出已产出），重试 %d/%d: %s",
                        _attempt, _retry_disconnect, exc,
                    )
                    continue
                raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
            except LLMHTTPError:
                raise
            except httpx.HTTPError as exc:
                raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider, client=self, guard_context=guard_context)

    # ── Anthropic Messages API（wire_protocol=anthropic，P3-5） ──
    def _anthropic_cache_enabled(self) -> bool:
        """prompt caching 开关（EVO-20260817）: env ANTHROPIC_CACHE_CONTROL 显式覆盖；
        未配置时 localhost/127.0.0.1 自动启用（本地模型省 token 主场景），远端默认关
        （官方 API 兼容但默认零回归，避免第三方端点对 cache_control 报错）。"""
        v = os.environ.get("ANTHROPIC_CACHE_CONTROL")
        if v is not None:
            return v.strip().lower() in {"1", "true", "yes", "on"}
        base = (self.base_url or "").lower()
        return "localhost" in base or "127.0.0.1" in base

    def _stream_anthropic(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
        guard_context: GuardRequestContext | None = None,
    ) -> Iterator[StreamDelta]:
        # EVO-20260817: base_url 已含 /v1 时（如 LM Studio http://localhost:1234/v1）
        # 避免拼出 /v1/v1/messages 404——归一化后两种配置均正确，官方 API 零回归
        _base = self.base_url.rstrip("/")
        if _base.endswith("/v1"):
            _base = _base[:-3]
        url = f"{_base}/v1/messages"
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        msgs = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "model": self.model if model is None else model,
            "messages": self._to_anthropic_messages(msgs),
            "stream": True,
            "max_tokens": self.max_tokens or 4096,
        }
        # EVO-20260817: 无工具时不发 tools 字段（LM Studio 拒绝 null；官方 API 亦兼容省略）
        _atools = self._to_anthropic_tools(tools)
        if _atools:
            payload["tools"] = _atools
        if system_parts:
            # EVO-20260817 prompt caching（本地模型省 token，用户需求）:
            # system+tools 为"固化固定信息"（每轮不变），打 cache_control 标记 →
            # 首次全量计费、后续轮 cache hit 只计费追加的 messages（实测 LM Studio
            # cache_read_input_tokens 命中，81% 前缀省 token）；messages 尾部追加最新。
            # 默认 localhost 自动启用；官方 API 亦兼容（可 env 覆盖）。
            if self._anthropic_cache_enabled():
                payload["system"] = [
                    {
                        "type": "text",
                        "text": "\n\n".join(str(p) for p in system_parts),
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
                if payload.get("tools"):
                    payload["tools"][-1]["cache_control"] = {"type": "ephemeral"}
            else:
                payload["system"] = "\n\n".join(str(p) for p in system_parts)
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        evt = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    evt_type = evt.get("type")
                    if evt_type == "message_start":
                        usage = (evt.get("message") or {}).get("usage") or {}
                        acc.prompt_tokens = int(usage.get("input_tokens") or 0)
                        acc.completion_tokens = int(usage.get("output_tokens") or 0)
                        # M58: Anthropic 缓存命中（cache_read_input_tokens）
                        acc.prompt_cache_hit_tokens = int(usage.get("cache_read_input_tokens") or 0)
                    elif evt_type == "content_block_start":
                        block = evt.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            # 流式语义：start 时 input 恒为空 dict——不并入 arguments，
                            # 参数由随后的 input_json_delta 分片拼装（并入 "{}" 会破坏 JSON）
                            start_input = block.get("input") or {}
                            start_args = (
                                json.dumps(start_input, ensure_ascii=False)
                                if start_input
                                else ""
                            )
                            agg.add_delta(
                                {
                                    "index": evt.get("index", 0),
                                    "id": block.get("id", ""),
                                    "function": {"name": block.get("name", ""), "arguments": start_args},
                                }
                            )
                    elif evt_type == "content_block_delta":
                        delta = evt.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta" and delta.get("text"):
                            acc.content_parts.append(delta["text"])
                            yield StreamDelta(text=delta["text"])
                        elif dtype == "thinking_delta" and delta.get("thinking"):
                            acc.reasoning_parts.append(delta["thinking"])
                            yield StreamDelta(text="", reasoning=delta["thinking"])
                        elif dtype == "input_json_delta":
                            agg.add_delta(
                                {
                                    "index": evt.get("index", 0),
                                    "function": {"arguments": delta.get("partial_json") or ""},
                                }
                            )
                    elif evt_type == "message_delta":
                        stop = ((evt.get("delta") or {}).get("stop_reason")) or ""
                        if stop:
                            acc.finish_reason = stop
                        if acc.finish_reason in ("max_tokens", "length"):
                            acc.truncated = True
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider, client=self, guard_context=guard_context)

    # ── Google Gemini API（wire_protocol=google，P3-5） ──
    def _stream_google(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
        guard_context: GuardRequestContext | None = None,
    ) -> Iterator[StreamDelta]:
        model_id = self.model if model is None else model
        url = (
            f"{self.base_url.rstrip('/')}/v1beta/models/{model_id}:streamGenerateContent?alt=sse"
        )
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        msgs = [m for m in messages if m.get("role") != "system"]
        payload: dict[str, Any] = {
            "contents": self._to_google_contents(msgs),
            "generationConfig": {"maxOutputTokens": self.max_tokens or 4096},
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(str(p) for p in system_parts)}]
            }
        gtools = self._to_google_tools(tools)
        if gtools:
            payload["tools"] = gtools
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

        acc = _StreamAcc()
        agg = ToolCallDeltaAggregator()
        google_fc_index = 0  # Google functionCall 每次独立工具调用（index 递增）
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if not data:
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    usage = chunk.get("usageMetadata") or {}
                    if usage:
                        # M58 修复（审查中危）: 缺失不覆盖（与 openai 路径一致）
                        pt = usage.get("promptTokenCount")
                        if pt:
                            acc.prompt_tokens = int(pt)
                        ct = usage.get("candidatesTokenCount")
                        if ct:
                            acc.completion_tokens = int(ct)
                    finish = chunk.get("candidates", [{}])[0].get("finishReason", "") if chunk.get("candidates") else ""
                    if finish:
                        acc.finish_reason = finish
                        if finish in ("MAX_TOKENS", "LENGTH"):
                            acc.truncated = True
                    parts = ((chunk.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                    for part in parts:
                        if part.get("text"):
                            acc.content_parts.append(part["text"])
                            yield StreamDelta(text=part["text"])
                        if part.get("functionCall"):
                            fc = part["functionCall"]
                            agg.add_delta(
                                {
                                    "index": google_fc_index,
                                    "id": f"fc_{int(time.time() * 1000)}",
                                    "function": {
                                        "name": fc.get("name", ""),
                                        "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False),
                                    },
                                }
                            )
                            google_fc_index += 1
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        return _finish_response(acc, agg, self.provider, client=self, guard_context=guard_context)

    # ── LM Studio /api/v1/chat（wire_protocol=lms-chat，EVO-20260817 用户需求） ──
    def _stream_lms_chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None,
        model: str | None,
    ) -> Iterator[StreamDelta]:
        """LM Studio 新版 /api/v1/chat 端点适配.

        端点特征（实测 2026-08-17）:
        - input: 模态数组 [{type: text, content: str}]（无 role/system/tools 键——极简接口）
        - SSE 流式: reasoning.delta / message.delta / chat.end 事件（无原生工具事件）
        - 无原生工具调用 → 文本工具协议: 工具描述注入文本, 模型输出
          JSON {"tool": name, "args": {...}}，此处解析为 ToolCall 交给循环执行
        - 工具轮上下文精简（用户需求）: 只保留最近 LMS_CHAT_TAIL 条消息文本化
          （默认 16），不发送全部历史——端点无角色字段天然拼接, 早期历史经压缩
          归档可检索（信息零丢失）
        """
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/api/v1/chat"
        model_id = self.model if model is None else model
        payload: dict[str, Any] = {
            "model": model_id,
            "input": self._to_lms_input(messages, tools),
            "stream": True,
        }
        headers = {"Content-Type": "application/json"}
        acc = _StreamAcc()
        try:
            effective_timeout = timeout_s if timeout_s is not None else self.timeout_s
            with self._client.stream(
                "POST", url, json=payload, headers=headers, timeout=effective_timeout
            ) as resp:
                if resp.status_code >= 400:
                    self._raise_for_status(resp)
                for line in resp.iter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                    except ValueError:
                        continue
                    etype = chunk.get("type")
                    if etype == "reasoning.delta":
                        rc = chunk.get("content") or ""
                        if rc:
                            acc.reasoning_parts.append(rc)
                            yield StreamDelta(text="", reasoning=rc)
                    elif etype == "message.delta":
                        c = chunk.get("content") or ""
                        if c:
                            acc.content_parts.append(c)
                            yield StreamDelta(text=c)
                    elif etype == "chat.end":
                        # 2026-08-22 补 usage 解析: lms-chat 的 chat.end.result.stats 含
                        # input_tokens/total_output_tokens（此前 acc 恒 0, 本地模型用量统计失真）。
                        # 注: stats 不含 cached_tokens（lms-chat 协议限制, KV 命中不可观测——
                        # 需走 OpenAI 协议直连 llama-server 才能拿 prompt_tokens_details）。
                        try:
                            _stats = (chunk.get("result") or {}).get("stats") or {}
                            _it = _stats.get("input_tokens")
                            _ot = _stats.get("total_output_tokens")
                            if _it:
                                acc.prompt_tokens = int(_it)
                            if _ot:
                                acc.completion_tokens = int(_ot)
                        except Exception:  # noqa: BLE001 — 解析失败 fail-open（不影响输出）
                            pass
                        break
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM 请求超时（{effective_timeout}s）") from exc
        except httpx.NetworkError as exc:
            raise LLMNetworkError(f"LLM 网络不可达: {exc}") from exc
        except LLMHTTPError:
            raise
        except httpx.HTTPError as exc:
            raise LLMNetworkError(f"LLM HTTP 异常: {exc}") from exc
        content = "".join(acc.content_parts) or None
        reasoning = "".join(acc.reasoning_parts) or None
        tool_calls: list[ToolCall] = []
        if content:
            for i, tc in enumerate(self._parse_text_tool_calls(content)):
                tool_calls.append(ToolCall(id=f"lms-{i}", name=tc["name"], arguments=tc["arguments"]))
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.provider,
            reasoning_content=reasoning,
            prompt_tokens=acc.prompt_tokens,
            completion_tokens=acc.completion_tokens,
        )

    # ── lms-chat 文本工具协议 ──
    _LMS_CHAT_TAIL = int(os.environ.get("LMS_CHAT_TAIL", "16"))  # 工具轮只保留最近 N 条（上下文精简）

    def _to_lms_input(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """消息 → input 模态数组（system + 工具描述 + 最近 N 条历史，文本化）."""
        parts: list[str] = []
        for m in messages:
            if m.get("role") == "system" and m.get("content"):
                parts.append("[系统] " + str(m["content"]))
        if tools:
            parts.append(self._lms_tools_text(tools))
        tail = [m for m in messages if m.get("role") != "system"][-self._LMS_CHAT_TAIL:]
        for m in tail:
            parts.append(self._lms_msg_text(m))
        return [{"type": "text", "content": "\n\n".join(parts)}]

    @staticmethod
    def _lms_msg_text(m: dict) -> str:
        """单条消息文本化（角色前缀标记；工具结果/调用 JSON 化）."""
        role = m.get("role", "user")
        content = m.get("content")
        c = content if isinstance(content, str) else (
            json.dumps(content, ensure_ascii=False) if content else ""
        )
        if role == "tool":
            name = m.get("name") or "tool"
            return f"[工具结果 {name}] {c}"
        if role == "assistant":
            tcs = m.get("tool_calls") or []
            extra = ""
            if tcs:
                bits = []
                for tc in tcs:
                    fn = tc.get("function") or tc
                    bits.append(
                        f'[调用工具 {fn.get("name")} 参数 {json.dumps(fn.get("arguments") or {}, ensure_ascii=False)}]'
                    )
                extra = " " + " ".join(bits)
            return f"[助手] {c}{extra}"
        return f"[用户] {c}"

    @staticmethod
    def _lms_tools_text(tools: list[dict]) -> str:
        """工具描述 → 文本注入（文本工具协议）.

        EVO-20260817 本地模型精简（用户需求）: 本地模型 prefill 随输入线性增长，
        全量 40+ 工具完整 JSON 每轮重发 = token 大头。这里固化精简:
        - 仅 name + description 首句（≤120 字符）+ 参数骨架（字段名+类型+required）
        - 固定不变 → 前缀稳定；尾部追加最新消息（LMS_CHAT_TAIL 已限 16 条）
        - 省 token 但不影响推理: 模型只需知道"有哪些工具/干什么/参数骨架"，
          完整 schema 按需经 get_tool_schema 读取
        """
        lines = ["[可用工具]"]
        for t in tools:
            fn = t.get("function") or t
            desc = (fn.get("description") or "").strip().split("\n")[0][:120]
            params = fn.get("parameters") or {}
            props = (params.get("properties") or {})
            skeleton = {
                k: {"type": v.get("type", "string")}
                for k, v in props.items()
            }
            lines.append(
                json.dumps(
                    {
                        "name": fn.get("name", ""),
                        "description": desc,
                        "parameters": {
                            "type": "object",
                            "properties": skeleton,
                            "required": params.get("required", []),
                        },
                    },
                    ensure_ascii=False,
                )
            )
        lines.append(
            '需要调用工具时，仅输出一行 JSON: {"tool": "工具名", "args": {...}}；'
            "多个调用用换行分隔，不要输出其他内容。"
        )
        return "\n".join(lines)

    @staticmethod
    def _parse_text_tool_calls(text: str) -> list[dict]:
        """从消息文本解析文本协议工具调用 → [{name, arguments(dict)}].

        容错: ```json 围栏、前后杂文本、args 嵌套空对象/数组；
        解析失败返回空（fail-open 当普通回答）。
        实现: 定位 "tool" 键 → 向前找对象起点 → 平衡括号找对象终点 → json.loads。
        """
        import re

        out: list[dict] = []
        s = text.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
        if m:
            s = m.group(1).strip()
        for tm in re.finditer(r'"tool"\s*:\s*"[^"]+"', s):
            i = tm.start()
            while i > 0 and s[i] != "{":
                i -= 1
            if s[i] != "{":
                continue
            depth = 0
            in_str = False
            esc = False
            j = i
            while j < len(s):
                ch = s[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            break
                j += 1
            if j >= len(s):
                continue
            try:
                d = json.loads(s[i : j + 1])
            except ValueError:
                continue
            name = d.get("tool")
            if not name:
                continue
            args = d.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            out.append({"name": name, "arguments": args if isinstance(args, dict) else {}})
        return out

    # ── 共享工具方法 ──
    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            body = resp.read().decode("utf-8", errors="replace")[:2000]
            raise LLMHTTPError(
                f"HTTP {resp.status_code}: {resp.reason_phrase} | {body}",
                status_code=resp.status_code,
                body=body,
                provider=self.provider,
            )

    def _check_sse_error(self, chunk: dict[str, Any]) -> None:
        """P1-FEISHU: LM Studio SSE 错误事件检测（HTTP 200 + data: {error:...}）."""
        err_obj = chunk.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or err_obj.get("code") or "未知 SSE 错误"
            code = err_obj.get("code") or 500
            try:
                code_i = int(code)
            except Exception:
                code_i = 500
            raise LLMHTTPError(
                f"SSE provider error: {msg[:500]}",
                status_code=code_i,
                body=msg[:2000],
                provider=self.provider,
            )

    # ── 消息/工具协议转换 ──
    @staticmethod
    def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
        """OpenAI 历史 → Anthropic messages（tool_use/tool_result 配对清洗）.

        2026-08-17 修复: 历史可能含"声明了 tool_calls 但回执缺失"的 assistant 消息
        （LLM 调用失败中断/上下文压缩裁剪导致）。Anthropic API 硬约束: tool_use 必须
        紧跟对应 tool_result。清洗策略: 未消费的孤立 tool_use 删除其块（含整条空消息
        剔除）；孤立 tool_result（无对应 tool_use）删除该 user 消息。避免 400 拒绝。
        """
        # 第一遍: 转换 + 记录 tool_use 消费情况
        out: list[dict] = []
        pending_use_ids: list[str] = []   # 已发出但未消费的 tool_use id
        consumed: set[str] = set()        # 已被 tool_result 消费的 id
        # (输出索引, 该条 assistant 的 tool_use id 列表)
        assistant_blocks: list[tuple[int, list[str]]] = []
        # 2026-08-17 修复2: 连续 tool 回执合并为单条 user（含多个 tool_result 块）。
        # Anthropic 硬约束: 每个 tool_use 必须"immediately after"紧跟其 tool_result；
        # 若一条 assistant 声明多个 tool_use、回执拆成多条独立 user → 仅第一个 tool_use
        # 满足紧跟，后续 tool_use 被前一条 user 隔开 → 400（现场: id 360355894）。
        # 合并后: assistant[text, tool_use A, tool_use B] → user[tool_result A, tool_result B]。
        tool_buffer: list[dict] = []
        for m in messages:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "tool":
                tid = str(m.get("tool_call_id") or "")
                if tid and tid not in pending_use_ids:
                    # 孤立 tool_result（无对应 tool_use）→ 跳过该消息
                    continue
                tool_buffer.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": str(content),
                    }
                )
                consumed.add(tid)
                continue
            # 非 tool 消息: 先 flush 缓冲的 tool_result（合并为单条 user）
            if tool_buffer:
                out.append({"role": "user", "content": tool_buffer})
                tool_buffer = []
            if role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": str(content)})
                ids: list[str] = []
                for tc in m.get("tool_calls") or []:
                    tid = str(tc.get("id") or "")
                    ids.append(tid)
                    pending_use_ids.append(tid)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tid,
                            "name": str(tc.get("name") or ""),
                            "input": tc.get("arguments") or {},
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
                assistant_blocks.append((len(out) - 1, ids))
                continue
            out.append({"role": role, "content": str(content)})
        if tool_buffer:  # 循环尾部 flush
            out.append({"role": "user", "content": tool_buffer})
        # 第二遍: 剔除未消费的孤立 tool_use 块（整条消息无文本且全孤立 → 删消息）
        orphan_ids = [tid for tid in pending_use_ids if tid not in consumed]
        if orphan_ids:
            orphan_set = set(orphan_ids)
            remove_indices: set[int] = set()
            for idx, _ids in assistant_blocks:
                msgs = out[idx]
                blocks = msgs.get("content") or []
                keep = [b for b in blocks if not (b.get("type") == "tool_use" and b.get("id") in orphan_set)]
                if keep:
                    out[idx]["content"] = keep
                else:
                    # 该 assistant 消息只剩孤立 tool_use → 整条删除
                    remove_indices.add(idx)
            if remove_indices:
                out = [m for idx, m in enumerate(out) if idx not in remove_indices]
        return out

    @staticmethod
    def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
        out = []
        for t in tools:
            fn = t.get("function") or t
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return out

    @staticmethod
    def _to_google_contents(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                out.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": str(m.get("tool_name") or ""),
                                    "response": {"result": str(m.get("content") or "")},
                                }
                            }
                        ],
                    }
                )
                continue
            if role == "assistant" and m.get("tool_calls"):
                parts: list[dict] = []
                if m.get("content"):
                    parts.append({"text": str(m["content"])})
                for tc in m.get("tool_calls") or []:
                    parts.append({"functionCall": {"name": str(tc.get("name") or ""), "args": tc.get("arguments") or {}}})
                out.append({"role": "model", "parts": parts})
                continue
            out.append({"role": "user" if role == "user" else "model", "parts": [{"text": str(m.get("content") or "")}]})
        return out

    @staticmethod
    def _to_google_tools(tools: list[dict]) -> list[dict]:
        decls = []
        for t in tools:
            fn = t.get("function") or t
            decls.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                }
            )
        return [{"functionDeclarations": decls}] if decls else []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_s: float | None = None,  # PARAM-01: 每次调用可覆盖超时（None 用构造值）
        model: str | None = None,
        guard_context: GuardRequestContext | None = None,
    ) -> LLMResponse:
        """非流式：内部走流式聚合（终态与流式一致，含思考链/截断/用量）."""
        it = self.chat_stream(
            messages, tools, timeout_s=timeout_s, model=model, guard_context=guard_context
        )
        result: LLMResponse | None = None
        while True:  # 消费全部 delta；终态 LLMResponse 经 StopIteration.value 捕获
            try:
                next(it)
            except StopIteration as exc:
                result = exc.value
                break
        return result if result is not None else LLMResponse(content=None, tool_calls=[], provider=self.provider)


if __name__ == "__main__":  # pragma: no cover
    pass
