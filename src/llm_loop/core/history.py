"""上下文构造与压缩另存（design.md §2.2.2.3 / T22 另存提取替代截断）.

- 保序提交（FR-MSG-03）
- **T22: 截断不是目的**——上下文超长时，将被丢弃的旧消息先"另存提取重要信息"
  （原文完整另存 + 关键事实/路径索引）到 ArchiveStore，再注入精简内容 +
  `[上下文压缩]` 标注（含"可查 search_archive"指引），信息零丢失。
- 记忆注入（source=memory 前置消息）
- **EVO-20260817-b6554376: 投影一致性门闸（借鉴 DSH seq 水印）**——stable_digest /
  projection_ver / projection_check 纯函数：以 seq（消息数）+ ver（构建参数指纹）
  精确水印检测"输入未变但输出变化"的非确定性构建/历史被改（防前缀缓存悄悄失效）。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from typing import Any

from llm_loop.core.injection_labels import (
    PROGRAM_APPENDIX_NOTICE,
    PROGRAM_RECOVERY_LABEL,
    REFERENCE_LABEL,
    STATUS_LABEL,
)
from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.core.reference_injection import is_human_user_message


def _wire_size(m: Message, current_turn_ref: int | None = None) -> int:
    """提交视图口径体积（与守卫估算 routing._estimate_request_chars 对齐）.

    content + reasoning_content + tool_calls 参数。history 压缩预算原只看
    content——reasoning_content 可占 40%+（实测 fb8f8987: 287K/598K 全字段），
    压缩器看不见 → 恒不触发（2026-08-26 glm 超限
    死循环根因：守卫按全字段 907K tokens 拦截、压缩按 content 159K<255K 判
    不超）。预算判定一律改用本口径；纯展示/审计统计不变。
    """
    n = len(m.content or "") + len(_capability_boundary_block(m, current_turn_ref))
    if m.role == "assistant":
        replay = (m.metadata or {}).get("provider_replay")
        replay_fields = replay.get("fields") if isinstance(replay, dict) else None
        if isinstance(replay_fields, dict) and replay_fields.get("reasoning_details") is not None:
            n += len(json.dumps(replay_fields["reasoning_details"], ensure_ascii=False))
        else:
            n += len(m.reasoning_content or "")
        for tc in m.tool_calls or []:
            # ToolCall dataclass（扁平 name/arguments）或 OpenAI wire dict（嵌套 function）兼容
            if isinstance(tc, ToolCall):
                n += len(str(tc.arguments or "")) + len(str(tc.name or ""))
            else:
                fn = (tc or {}).get("function") or {}
                n += len(str(fn.get("arguments") or "")) + len(str(fn.get("name") or ""))
    return n


def _dict_wire_size(d: dict) -> int:
    """to_llm_dict 后的提交口径体积（out 列表元素用）."""
    n = len(str(d.get("content") or ""))
    replay = d.get("_provider_replay")
    replay_fields = replay.get("fields") if isinstance(replay, dict) else None
    if isinstance(replay_fields, dict) and replay_fields.get("reasoning_details") is not None:
        n += len(json.dumps(replay_fields["reasoning_details"], ensure_ascii=False))
    else:
        n += len(str(d.get("reasoning_content") or ""))
    for tc in d.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        n += len(str(fn.get("arguments") or "")) + len(str(fn.get("name") or ""))
    return n


def _same_turn_ref(raw: Any, current_turn_ref: int | None) -> bool:
    if raw is None or current_turn_ref is None:
        return False
    try:
        return int(raw) == int(current_turn_ref)
    except (TypeError, ValueError):
        return False


def _capability_boundary_block(m: Message, current_turn_ref: int | None) -> str:
    """Render producer-attached G6-v2 boundary facts for the current human turn only.

    The source Message is never mutated. The block is factual (no imperative next-step
    wording), deterministic, and loses prompt visibility on the next human turn while
    structured metadata remains available for audit/retrieval.
    """
    metadata = m.metadata if isinstance(m.metadata, dict) else {}
    if not _same_turn_ref(metadata.get("capability_boundary_turn_ref"), current_turn_ref):
        return ""
    rows = metadata.get("capability_unavailable")
    if not isinstance(rows, list):
        return ""
    normalized: list[tuple[str, str, tuple[str, ...]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("tool_name", "") or "").strip()
        reason = str(row.get("reason_code", "") or "runtime_unhealthy").strip()
        if not name:
            continue
        raw_repl = row.get("replacement") or ()
        if isinstance(raw_repl, str):
            raw_repl = (raw_repl,)
        repl = tuple(sorted({str(x).strip() for x in raw_repl if str(x).strip()}))
        normalized.append((name, reason, repl))
    if not normalized:
        return ""
    lines = ["[能力边界事实]"]
    for name, reason, repl in sorted(set(normalized)):
        line = f"tool={name}; available=false; reason={reason}"
        if repl:
            line += "; alternatives=" + ",".join(repl)
        lines.append(line)
    return "\n" + "\n".join(lines)


def _provider_message_dict(m: Message, current_turn_ref: int | None) -> dict:
    d = m.to_llm_dict()
    block = _capability_boundary_block(m, current_turn_ref)
    if block:
        d["content"] = str(d.get("content") or "") + block
    return d

# EVO-20260816-380f1c2e: 压缩目标比例（裁到预算×此值，留缓冲降低断点频率）。
# 2026-09-03 P0: 不能在模块 import 时读取 env。Web 入口会先 import factory/history，
# 后在 main() 才 load_env_file；旧常量因此永久固化默认 0.6，磁盘 .env=0.5 实际不生效。
# 默认仍冻结为生产真实行为 0.6；每次进入压缩路径时读取运行态 env，修 SoT 不夹带调参。
_DEFAULT_COMPRESS_TARGET_RATIO = 0.6


def _compress_target_ratio() -> float:
    """Return the runtime compression target ratio without import-order split brain."""
    raw = os.environ.get("COMPRESS_TARGET_RATIO", "").strip()
    if not raw:
        return _DEFAULT_COMPRESS_TARGET_RATIO
    try:
        ratio = float(raw)
    except ValueError:
        return _DEFAULT_COMPRESS_TARGET_RATIO
    if not 0.0 < ratio < 1.0:
        return _DEFAULT_COMPRESS_TARGET_RATIO
    return ratio

_CACHE_COMPACTED_FOR_META = "cache_compacted_for"
_CACHE_COMPACTION_SCOPE_META = "cache_compaction_scope"
_CACHE_COMPACTION_SCOPE_VERSION = 1


def is_cache_compacted_for(
    message: Message,
    provider_id: str,
    *,
    model_ref: str = "",
    effective_budget: int | None = None,
) -> bool:
    """Return whether a provider-scoped compaction marker is valid *now*.

    Legacy markers carried only ``provider_id`` and therefore became permanent:
    a message compacted under an old 80K/100K budget stayed hidden even after the
    same provider moved to a 1M model.  When the current model/budget contract is
    supplied, unversioned legacy markers are deliberately treated as stale and are
    eligible for one deterministic re-projection.  Versioned markers remain valid
    for the same model while the current budget is no more permissive than the
    budget that created the marker.

    Callers that do not supply model/budget retain the historical provider-only
    membership semantics for diagnostics/tests.
    """
    if not provider_id:
        return False
    meta = message.metadata or {}
    raw = meta.get(_CACHE_COMPACTED_FOR_META)
    if isinstance(raw, str):
        marked = raw == provider_id
    elif isinstance(raw, (list, tuple, set)):
        marked = provider_id in raw
    else:
        marked = False
    if not marked:
        return False
    if not model_ref or effective_budget is None:
        return True
    scopes = meta.get(_CACHE_COMPACTION_SCOPE_META)
    scope = scopes.get(provider_id) if isinstance(scopes, dict) else None
    if not isinstance(scope, dict):
        return False  # legacy provider-only marker: stale under a concrete contract
    try:
        version = int(scope.get("version", 0) or 0)
        marker_budget = int(scope.get("effective_budget", 0) or 0)
    except (TypeError, ValueError):
        return False
    if version != _CACHE_COMPACTION_SCOPE_VERSION:
        return False
    if str(scope.get("model") or "") != model_ref:
        return False
    if marker_budget <= 0:
        return False
    # Smaller/equal current budget is at least as restrictive: keeping the old
    # hidden set is safe and the current build may compact further.  A larger
    # budget must re-open candidates so the new model can actually use its window.
    return int(effective_budget) <= marker_budget


def _mark_cache_compacted_for(
    message: Message,
    provider_id: str,
    *,
    model_ref: str = "",
    effective_budget: int | None = None,
) -> bool:
    """Persist/update a provider-scoped prompt-view compaction marker contract."""
    if not provider_id:
        return False
    meta = message.metadata if isinstance(message.metadata, dict) else {}
    raw = meta.get(_CACHE_COMPACTED_FOR_META)
    if isinstance(raw, str):
        providers = [raw]
    elif isinstance(raw, (list, tuple, set)):
        providers = [str(item) for item in raw if item]
    else:
        providers = []
    was_marked = provider_id in providers
    if not was_marked:
        providers.append(provider_id)
    meta[_CACHE_COMPACTED_FOR_META] = providers
    scope_changed = False
    if model_ref and effective_budget is not None:
        scopes_raw = meta.get(_CACHE_COMPACTION_SCOPE_META)
        scopes = dict(scopes_raw) if isinstance(scopes_raw, dict) else {}
        new_scope = {
            "version": _CACHE_COMPACTION_SCOPE_VERSION,
            "model": model_ref,
            "effective_budget": int(effective_budget),
        }
        scope_changed = scopes.get(provider_id) != new_scope
        scopes[provider_id] = new_scope
        meta[_CACHE_COMPACTION_SCOPE_META] = scopes
    message.metadata = meta
    return (not was_marked) or scope_changed


def clear_cache_compacted_for(message: Message, provider_id: str) -> bool:
    """Remove one provider's stale prompt-view marker while preserving other providers."""
    if not provider_id:
        return False
    meta = message.metadata if isinstance(message.metadata, dict) else {}
    raw = meta.get(_CACHE_COMPACTED_FOR_META)
    if isinstance(raw, str):
        providers = [raw]
    elif isinstance(raw, (list, tuple, set)):
        providers = [str(item) for item in raw if item]
    else:
        providers = []
    changed = provider_id in providers
    if changed:
        providers = [item for item in providers if item != provider_id]
        if providers:
            meta[_CACHE_COMPACTED_FOR_META] = providers
        else:
            meta.pop(_CACHE_COMPACTED_FOR_META, None)
    scopes_raw = meta.get(_CACHE_COMPACTION_SCOPE_META)
    if isinstance(scopes_raw, dict) and provider_id in scopes_raw:
        scopes = dict(scopes_raw)
        scopes.pop(provider_id, None)
        if scopes:
            meta[_CACHE_COMPACTION_SCOPE_META] = scopes
        else:
            meta.pop(_CACHE_COMPACTION_SCOPE_META, None)
        changed = True
    message.metadata = meta
    return changed

# EVO-20260818 cache_window_converge 的兼容入口。
# 2026-09-04 agency-first 修正：未配置全局 HISTORY_MAX_CHARS 不再等价于隐藏
# 100K~200K cap。value=None 时只给出按物理窗口估算的诊断预算：90% 输入安全
# 边界 × 0.6 chars/token。真正执行预算由当前路由模型再扣 output reserve/provider
# cap，并由最终 payload guard 校验。显式 operator 值 >=1000 原样保留，不再存在
# 无事实依据的 200K 上限/“显式豁免”语义；非法输入仍保守兜底 100K。
_HISTORY_BUDGET_DEFAULT = 100_000  # 兜底默认值（与 max_chars 形参默认一致）
_HISTORY_BUDGET_CHARS_PER_TOKEN = 0.6
_HISTORY_BUDGET_INPUT_MARGIN = 0.9


def converge_history_budget(
    value: int | None,
    *,
    model_window: int | None,
) -> tuple[int, str | None]:
    """历史预算兼容/诊断收敛。

    Args:
        value: 显式配置值（None=未配置，按窗口自适应）.
        model_window: 模型窗口上限（tokens），None=未知.

    Returns:
        (预算, 告警说明或 None)。value=None 且窗口已知时返回窗口输入安全边界的
        字符估算，不代表独立全局 cap；显式合法配置原样保留；非法输入兜底 100K。
    """
    if value is None:
        if model_window is None:
            return _HISTORY_BUDGET_DEFAULT, "窗口未知兜底 100K"
        try:
            adaptive = int(
                model_window
                * _HISTORY_BUDGET_INPUT_MARGIN
                * _HISTORY_BUDGET_CHARS_PER_TOKEN
            )
        except (TypeError, ValueError):
            return _HISTORY_BUDGET_DEFAULT, "窗口非法兜底 100K"
        if adaptive <= 0:
            return _HISTORY_BUDGET_DEFAULT, "窗口非法兜底 100K"
        return max(1, adaptive), None
    if not isinstance(value, int) or isinstance(value, bool):
        return _HISTORY_BUDGET_DEFAULT, "输入非法兜底 100K"
    if value < 1000:
        return _HISTORY_BUDGET_DEFAULT, f"输入非法兜底 100K（{value} < 1000）"
    return value, None


# archive sink: (session_id, message) -> None（由调用方装配 ArchiveStore）
ArchiveSink = Callable[[str, Message], None]


def _apply_reasoning_tail(
    messages: list[Message], reasoning_tail: int
) -> list[Message]:
    """M66 思考链瘦身: 历史中省略 assistant 思考链（reasoning_content）.

    更早轮次的思考链在**提交给 LLM 时**省略（内容/工具调用完整保留），
    体积显著减小且不影响事实完整性；不修改原消息（仅提交视图瘦身）。

    - reasoning_tail <= 0 → 保留全部（向后兼容，零回归）
    - reasoning_tail == -2 → 全省略档（2026-08-29 镜像本地模型复读修复）：所有
      assistant reasoning_content 一律省略（含 tool_calls 轮）。THK-04 是云端
      provider（deepseek/glm）协议约束（不回传则 400）；本地端点（mlx_lm.server
      等 OpenAI 兼容）无此校验，回传 tool_calls 轮思考链反而强化弱模型自模仿复读
      （实证 68fed5f5 会话：5 轮 tool_calls reasoning 收敛复读不发散）。
    - reasoning_tail == -1 → 方案 A（2026-08-20 从 backup/20260819-after-3am 重新应用，
      思考链 token 治理——占请求 ~60%）：仅【携带 tool_calls 的 assistant 消息】保留
      reasoning_content（协议必需，M20 THK-04: 携带 tool_calls 必须回传否则 400），
      其余思考链一律省略。与"最近 N 轮"不同：N 轮窗口随轮次滚动 → 历史中消息的
      reasoning 从有到无每轮改前缀 → 断点；按属性（是否带 tool_calls）省略 →
      每条消息 reasoning 有无固定不变 → 前缀字节稳定 + 输入最小化。
    - 最近一轮的 reasoning 必须保留（M20 THK-04: 携带 tool_calls 必须回传，
      否则协议 400）——本实现始终保留最近 N 轮，覆盖最近一轮。
    """
    from dataclasses import replace

    if reasoning_tail == -2:
        # 全省略档：含 tool_calls 轮（本地/无 THK-04 约束端点用）
        return [
            replace(m, reasoning_content=None)
            if m.role == "assistant" and m.reasoning_content
            else m
            for m in messages
        ]
    if reasoning_tail == -1:
        out: list[Message] = []
        for m in messages:
            if (
                m.role == "assistant"
                and m.reasoning_content
                and not m.tool_calls
            ):
                out.append(replace(m, reasoning_content=None))  # 仅提交视图省略，不动原消息
            else:
                out.append(m)
        return out
    if reasoning_tail <= 0:
        return messages

    idx = [i for i, m in enumerate(messages) if m.role == "assistant" and m.reasoning_content]
    keep = set(idx[-reasoning_tail:]) if idx else set()
    if not idx:
        return messages
    out: list[Message] = []
    for i, m in enumerate(messages):
        if m.role == "assistant" and m.reasoning_content and i not in keep:
            out.append(replace(m, reasoning_content=None))  # 仅提交视图省略，不动原消息
        else:
            out.append(m)
    return out


# P1-7: 推送式通知内容前缀（存量会话消息无 metadata 标记，按前缀兼容跳过）
_INJECTED_SYSTEM_PREFIXES = (
    "[架构上报]",
    "[预算预警]",
    "[轮数预警]",
    "[声明提醒]",
    "[自我评估提醒]",
)


def _is_injected_system(m: Message) -> bool:
    """P1-7: 是否为推送式 system 注入（架构上报/预警/快照等）.

    双通道判定: ① 新注入带 metadata.injected_system 标记（引擎注入点已打标）;
    ② 存量会话历史消息无标记, 按内容前缀兼容（[架构上报]/[预算预警] 等）。
    这类消息仅"落会话保留记录、不进提交视图"——本地慢模型下让 system 前缀保持
    静态, llama.cpp 引擎前缀缓存每轮命中; 功能性注入（压缩标注/降级通知/overflow
    回注/故障反馈/轮次决策请求）不匹配前缀, 不受影响。
    """
    if m.role != "system":
        return False
    meta = m.metadata or {}
    if meta.get("injected_system"):
        return True
    content = m.content or ""
    return any(content.startswith(p) for p in _INJECTED_SYSTEM_PREFIXES)


# 漂移修复（2026-08-29 会话 68fed5f5 实证）: user 通道注入块前缀——程序注入的
# [上下文注入]/[声明提醒]/[相关记忆] 等块非用户真实指令，任务锚点保护时须排除。
_INJECTED_USER_PREFIXES = (
    PROGRAM_APPENDIX_NOTICE,
    PROGRAM_RECOVERY_LABEL,
    REFERENCE_LABEL,
    STATUS_LABEL,
    "[上下文注入",  # legacy
    "[声明提醒",
    "[声明提示",
    "[声明-回执校验",
    "[相关记忆",
    "[经验提示",
    "[模型切换感知",
    "[架构上报",
    "[预算预警",
    "[搜索空结果提醒",
    "[程序反馈",
    "[程序续跑",
    "[上下文超限",
)


def _is_injected_block(m: Message) -> bool:
    """user 消息是否为程序注入块（漂移修复 2026-08-29）.

    判定依据: 内容前缀（存量会话消息无 metadata 标记，与会话实测注入块标头对齐）。
    """
    if m.role != "user":
        return False
    meta = m.metadata or {}
    if meta.get("program_origin"):
        return True
    content = (m.content or "").lstrip()
    return any(content.startswith(p) for p in _INJECTED_USER_PREFIXES)


def build_history_messages(
    session_messages: list[Message],
    system_prompt: str,
    max_chars: int = 100000,  # EVO-20260818: 默认值 1M→100K（spec §5.1.1-3，与 config 兜底一致）
    *,
    compact_ratio: float = 1.0,  # EVO-20260817: 主动压缩阈值（预算比例; 1.0=现行为超限才压;
    # <1.0 在预算附近提前整理压缩——裁到 COMPRESS_TARGET_RATIO 留缓冲, 避免撞顶被动压缩）
    session_id: str = "",
    archive_sink: ArchiveSink | None = None,
    summarizer: Any | None = None,  # 保留签名向后兼容；压缩路径不再自动调 LLM 摘要（RULE-AI-00，LLM 摘要由 AI 经 search_archive(with_summary=true) 主动触发）
    reasoning_tail: int = 0,  # M66: 历史中仅保留最近 N 轮思考链（默认 0=全保留，T-P0-1-1 capability-first）
    skip_injected_system: bool = False,  # P1-7: 跳过推送式 system 注入（metadata.injected_system）
    # —— 仅落会话不进提交, system 前缀保持静态 → 引擎前缀缓存命中; 功能性注入不受影响
    history_anchor: int = 0,  # P1-10: 历史窗口锚点（相对 session_messages 的索引; 0=无锚现有行为）
    # —— 锚定后起点固定（只追加不挤旧, 超预算优先降级中段）, system+历史前缀稳定 → 前缀缓存命中
    anchor_out: list[int] | None = None,  # P1-10: 输出容器——构建后填充新锚点（相对传入列表）;
    # 正常提交（无归档）不填充（锚点保持不变, engine 沿用旧值）; 超长归档后填充推进值
    compacted_out: list[bool] | None = None,  # 显式报告“本次真实进入归档压缩路径”
    head_keep_chars: int = 0,  # EVO-20260817-9d3e1f2c: 缓存友好压缩——保留锚点头部字符预算
    # （0=关闭/现有行为零回归）。>0 时归档路径保留最旧 head_keep_chars 字符的组（提交前缀
    # 稳定命中），只归档中段；锚点不推进（仅头部被归档兜底时才前移）。
    head_keep_target_ratio: float = 0.5,  # fixed-head 最多占压缩目标水位的比例；默认保持旧 50%
    # provider 中段压缩可调高（DeepSeek 生产建议 0.65），给稳定前缀更多目标预算，同时
    # 至少给最近尾部预留约 35% 水位；避免为了命中把最近语义全部挤出。
    # （默认关=零回归）。启用后归档消息生成固定格式摘要追加提交尾部——任务语义连贯
    # + 前缀稳定（同归档内容→同摘要字节→缓存命中）。
    freeze_compression: bool = False,  # P0 压缩风暴熔断（2026-08-25）: 冻结期禁止
    # 一切程序压缩/归档/分层降级（前缀字节稳定），且锚点不前移（anchor_out 不填充）。
    # 仅用于熔断冻结轮——超预算时由 engine 前置 context_pressure 管控，不在此提交超限载荷。
    cache_archive_provider: str = "",  # provider级提交视图压缩标记；非空时中段只折一次
    cache_archive_model: str = "",  # P4: marker provenance，模型变化可重算旧 provider 折叠
    cache_archive_budget: int | None = None,  # P4: marker provenance，预算扩容可重算旧折叠
    cache_compacted_out: list[Message] | None = None,  # 本轮新写标记的原消息，供事件链同步
    cache_compacted_index_out: list[int] | None = None,  # 对应消息在原始 session_messages/base 中的精确索引
    cache_protected_prefix_messages: int = 0,  # P1: 上轮已确认 cached 的历史消息数（system 后）
    cache_protected_prefix_chars: int = 0,  # P1: 上轮 cached boundary 扣除 system 后的字符近似
    compact_view_stats: list[dict] | None = None,  # EVO-20260825 任务6: 压缩后视图体积验证
    # 输出容器——大裁/折叠发生后填充真实触发/目标/结果参数，供 deterministic replay；
    # 供调用方（build.py）写 breaker 审计事件 view_not_shrinking_after_compact（drop<5% 时）。
    require_archive_success: bool = False,  # ERC enforce: hidden bytes must be durable before shrink
    preserve_last_human_exact: bool = False,  # R6 initial ingress: never replace current human truth with a compact surrogate
    preserve_human_message: Message | None = None,  # exact active-human identity from filtered Session mapping
    current_turn_ref: int | None = None,  # G6-v2: render source-attached boundary facts only in owning human turn
) -> list[dict]:
    """组装提交 LLM 的消息序列（保序 + 超长另存压缩 + 如实标注）.

    Args:
        session_messages: 会话消息序列（保序）.
        system_prompt: 系统提示词.
        max_chars: 上下文注入字符预算.
        session_id: 当前会话（另存归档用）.
        archive_sink: 压缩另存回调（将被丢弃的消息逐条另存，信息零丢失）.

    Returns:
        LLM 协议消息列表（dict）。压缩发生时消息序列含 `[上下文压缩]` 标注。
    """
    out: list[dict] = []
    # P1 replay fidelity: 在任何 slice/filter/layer-trim 前冻结原始 base identity→index。
    # 后续 projection 用 prefix_len + filtered_indices 映射回 Session 真正 msg_seq，
    # message.cache_compacted 不再依赖 role/content/ts fuzzy resolve。
    _source_index_by_id = {id(m): i for i, m in enumerate(session_messages)}
    # Active-human wire invariant: when the caller identifies this build as belonging
    # to a genuine current human turn, freeze that exact persisted Message identity
    # before anchor/marker filtering. Provider compaction may retire surrounding tool
    # groups, but must not erase the human turn that gives those groups protocol
    # context (GLM rejects assistant/tool-only histories with HTTP 1214).
    _preserved_human: Message | None = None
    _preserved_human_source_index: int | None = None
    if (
        preserve_human_message is not None
        and id(preserve_human_message) in _source_index_by_id
        and is_human_user_message(preserve_human_message)
        and not _is_injected_block(preserve_human_message)
    ):
        _preserved_human = preserve_human_message
        _preserved_human_source_index = _source_index_by_id[id(preserve_human_message)]
    elif preserve_last_human_exact:
        for _idx in range(len(session_messages) - 1, -1, -1):
            _candidate = session_messages[_idx]
            if is_human_user_message(_candidate) and not _is_injected_block(_candidate):
                _preserved_human = _candidate
                _preserved_human_source_index = _idx
                break
    if compacted_out is not None:
        compacted_out[:] = [False]
    if cache_compacted_out is not None:
        cache_compacted_out.clear()
    if cache_compacted_index_out is not None:
        cache_compacted_index_out.clear()
    if system_prompt:
        out.append({"role": "system", "content": system_prompt})
    # Cache-First (2026-08-16): system_prompt 静态主体长度——永不截断（前缀缓存锚）。
    # 只对动态追加段（memory/inbox/快照/reminder）设上限，防累积超限（原意图不变）。
    sys_base_len = len(out[0]["content"]) if out else 0

    # P1-FEISHU: 合并后续 system 消息到首个 system（避免连续 system 导致模板 500）。
    # —— qwen3 heretic 模板严格要求 "System message must be at the beginning"。
    # ⚠️ 累积陷阱: 架构上报/validator reminder 每轮注入到 sess.messages,session 长时间累积后
    # 125+ 条 system 消息若全合并 → 单条 system 数十万字符 → LM Studio 超 token 限 / 超时。
    # 修复: 合并时限制动态追加段总字符数(max_sys_merge_chars),保留最新追加、丢弃过期的
    # (state 帧意义在即时性)。静态 system_prompt 主体不参与截断（前缀缓存保持命中）。
    max_sys_merge_chars = 4000  # 动态 system 追加段上限（不含 system_prompt 主体）

    def _append_or_merge(msg_dict: dict, dynamic: bool = False) -> None:
        # EVO-20260817（DSH 修复）: 动态注入（memory/inbox 等每轮变化段）不并入 system 主体——
        # 转独立 user 消息（system 主体字节稳定 → DeepSeek 前缀缓存命中；qwen 单 system 模板兼容）
        if dynamic and msg_dict.get("role") == "system":
            msg_dict = dict(msg_dict)
            msg_dict["role"] = "user"
            out.append(msg_dict)
            return
        if msg_dict.get("role") == "system" and out and out[0].get("role") == "system":
            # 2026-08-18 对齐 DSH（用户反馈'DSH 开始就高'）: 非首个 system 不再合并进主体——
            # 架构上报/警告等每会话数量不同 → 合并后主体跨会话不一致 → 新会话首轮 system 段
            # 不命中（0%）。转独立 user 消息——system 主体纯静态（跨会话字节一致——
            # 首轮命中稳定段；内容仍在上下文中——AI 可见）。
            msg_dict = dict(msg_dict)
            msg_dict["role"] = "user"
            out.append(msg_dict)
            return
            new_content = msg_dict.get("content", "")
            if not new_content:
                return
            cur = out[0]["content"]
            dyn = cur[sys_base_len:]  # 动态追加段（含分隔符）
            # 动态段已超限 → 截动态段、保留最新（system_prompt 主体不动）
            if len(dyn) >= max_sys_merge_chars:
                out[0]["content"] = (
                    cur[:sys_base_len]
                    + "\n\n[…历史系统消息已截断(超 max_sys_merge_chars=4000)…]\n\n"
                    + new_content
                )
            else:
                sep = "\n\n"
                out[0]["content"] = cur + sep + new_content
            # 兜底: 动态段仍超限 → 截动态段尾部（保留最新）
            dyn2 = out[0]["content"][sys_base_len:]
            if len(dyn2) > max_sys_merge_chars * 1.5:
                out[0]["content"] = (
                    cur[:sys_base_len]
                    + "...[已截断]...\n"
                    + dyn2[-(max_sys_merge_chars - 20):]
                )
        else:
            out.append(msg_dict)

    total_chars = sum(_wire_size(m, current_turn_ref) for m in session_messages)

    def _marker_active(m: Message) -> bool:
        # Breaker freeze 的语义是“本轮绝不改写 provider view”。冻结期间继续沿用
        # 既有 marker；待 freeze 解除后再按新 model/budget contract 一次性重投影。
        if freeze_compression:
            return is_cache_compacted_for(m, cache_archive_provider)
        return is_cache_compacted_for(
            m,
            cache_archive_provider,
            model_ref=cache_archive_model,
            effective_budget=cache_archive_budget,
        )

    # P1-10: 窗口锚定——起点固定（锚点前的消息已归档, 不再参与构建/重复归档）
    # A previously bad compaction may already have advanced the persisted anchor past
    # the active human. Re-open only as far as that exact identity; provider markers
    # still suppress every other already-compacted message.
    if (
        _preserved_human_source_index is not None
        and history_anchor > _preserved_human_source_index
    ):
        history_anchor = _preserved_human_source_index
    if history_anchor > 0 and history_anchor < len(session_messages):
        session_messages = session_messages[history_anchor:]
        if cache_archive_provider:
            session_messages = [
                m
                for m in session_messages
                if m is _preserved_human or not _marker_active(m)
            ]
        # 2026-08-16 锚点对齐工具轮边界（现场：tool_call_id is not found 根因）：
        # 锚点落在声明↔回执组内会把声明裁掉、留下孤儿回执（API 拒绝）。
        # 裁后窗口内"无对应声明"的 tool 回执 → 丢弃（如实标注；声明必在回执前，
        # 被裁掉的声明不可伪造，故不回补）。
        declared_ids = {
            str(tc.get("id") or "")
            for m in session_messages
            if m.role == "assistant" and getattr(m, "tool_calls", None)
            for tc in (m.tool_calls or [])
        }
        kept_msgs: list[Message] = []
        dropped_orphans = 0
        for m in session_messages:
            rid = str(getattr(m, "tool_call_id", "") or "")
            if m.role == "tool" and rid and rid not in declared_ids:
                dropped_orphans += 1
                continue
            kept_msgs.append(m)
        if dropped_orphans:
            import logging

            logging.getLogger(__name__).warning(
                "锚点对齐: 丢弃 %d 条无声明孤儿工具回执（防 tool_call_id 协议拒绝）",
                dropped_orphans,
            )
        session_messages = kept_msgs
        total_chars = sum(_wire_size(m, current_turn_ref) for m in session_messages)
    elif cache_archive_provider:
        session_messages = [
            m
            for m in session_messages
            if m is _preserved_human or not _marker_active(m)
        ]
        total_chars = sum(_wire_size(m, current_turn_ref) for m in session_messages)

    # 2026-09-03 P0 projected-wire pressure: 明确不会进入 provider wire 的推送式
    # system 历史必须在压缩阈值判定前退出。旧路径只在正常序列化/锚定超限后跳过，
    # 导致 08:27 实例把 38 条、6527 chars 的 injected_system 算入 255K 阈值，
    # 实际 wire 249413 < 255000 却误触发一次 cache epoch reset。
    if skip_injected_system:
        session_messages = [m for m in session_messages if not _is_injected_system(m)]
    total_chars = sum(_wire_size(m, current_turn_ref) for m in session_messages)

    # Physical history pressure is handled by the single atomic-group compaction path.
    # There is no separate tool-result relevance/age/threshold rewrite policy.
    compact_limit = max(1, int(max_chars * compact_ratio))
    if freeze_compression:
        compact_limit = max(1, total_chars)
    if total_chars <= compact_limit:
        # Agency-first: below the physical history budget, preserve tool-result bytes.
        for m in _apply_reasoning_tail(session_messages, reasoning_tail):
            if skip_injected_system and _is_injected_system(m):
                continue  # P1-7: 推送式注入仅落会话, 不进提交（system 前缀稳定）
            # EVO-20260817-cef296f8 L1b: 已消费的耗尽注入 system（[轮次决策请求]/
            # [已达轮数上限]）跳过——run 内 AI 决策可见，run 后消费，下个 run 不进请求
            # system 区 → 前缀不因耗尽注入持续分叉（缓存 MISS 收敛）
            if skip_injected_system and m.role == "system" and (m.metadata or {}).get("consumed"):
                continue
            _d = _provider_message_dict(m, current_turn_ref)
            _append_or_merge(_d, dynamic=_is_dynamic_inject(m))
        return _repair_tool_call_pairing(out)

    # 兼容既有语义：无 boundary 的超大真实 user 即使 R6 禁止删字节，也要如实标记
    # “进入压缩/压力路径”；P1 boundary 的 no-op 会在归档选择后单独降回 False。
    if compacted_out is not None:
        compacted_out[0] = True

    # ── 超长: 从最新往回保留，最旧的先"另存提取"再精简注入（不静默丢弃）──
    # ── M40 修复（tool_calls 配对原子性）: assistant(tool_calls) 与其紧跟的 tool 响应
    #    组成"配对组"整体保留/归档/精简——否则 LLM 协议报
    #    "assistant with tool_calls must be followed by tool messages"（HTTP 400）──
    atomic_groups: list[list[Message]] = []
    i = 0
    n = len(session_messages)
    while i < n:
        m = session_messages[i]
        if m.role == "assistant" and m.tool_calls:
            # 配对组: assistant(tool_calls) + 其后连续的 tool 响应（保持协议配对原子性）
            group = [m]
            j = i + 1
            while j < n and session_messages[j].role == "tool":
                group.append(session_messages[j])
                j += 1
            atomic_groups.append(group)
            i = j
        else:
            atomic_groups.append([m])
            i += 1

    # 漂移修复（2026-08-29 会话 68fed5f5 实证）: 任务锚点保护——最后一条真实用户
    # 指令（非注入块）所在组起、到最新端的组强制保留，不参与归档。实证机制: 用户
    # 任务指令在会话早段（如第 13 条），预算超载折叠按最老端连续折把任务指令归档，
    # 残余上下文 68% 为注入块（[相关记忆]/[声明提醒] 含身份话题），本地弱模型被
    # 带偏答非所问。保护代价: 锚点组穿透 archive_budget（最多多保留锚点组+其后本
    # 就保留的组），远小于任务锚点丢失的漂移代价；极端场景（锚点组超大仍超限）由
    # engine 侧规则 F BLOCK 兜底，不在此破坏配对原子性。
    _anchor_group_idx: int | None = None
    for _gi in range(len(atomic_groups) - 1, -1, -1):
        if any(mm.role == "user" and not _is_injected_block(mm) for mm in atomic_groups[_gi]):
            _anchor_group_idx = _gi
            break
    # R6: the current ingress human text is a semantic invariant, not a compression source.
    # When requested by LoopEngine initial-ingress build, keep the final real-user atomic group
    # byte-for-byte even if it alone exceeds history budget; routing/context guard may then reject
    # the oversized request explicitly. Silent trim/archive substitution would change the user's task.
    _exact_human_group: list[Message] | None = None
    if _preserved_human is not None:
        for _group in atomic_groups:
            if any(mm is _preserved_human for mm in _group):
                _exact_human_group = _group
                break
    elif preserve_last_human_exact and _anchor_group_idx is not None:
        _exact_human_group = atomic_groups[_anchor_group_idx]

    # 2026-09-03 cache-boundary P1: 上轮 provider 已确认命中的 prefix 是 mandatory head。
    # 双口径（消息数 + chars）都向 atomic-group 末端取整：宁可多保护一组，也不能拆开
    # assistant(tool_calls)↔tool 回执或只保护半条 boundary message。调用侧只会在同 session /
    # 同模型 / 同 human turn / 同 stable-prefix fingerprint 时传非零值；其它情况自动为 0。
    try:
        _reported_cached_messages = max(
            0, int(cache_protected_prefix_messages or 0)
        )
    except (TypeError, ValueError):
        _reported_cached_messages = 0
    try:
        _protect_char_req = max(0, int(cache_protected_prefix_chars or 0))
    except (TypeError, ValueError):
        _protect_char_req = 0
    _protected_group_count = 0
    _protected_message_count = 0
    _protected_chars = 0
    # boundary_msg_index 属于最终 wire 索引，不能直接映射为 history-base 消息数；
    # 08:28 实证把 wire#122 当 history 122 条会把保护区从约50K误放大到108K。
    # 因此 chars 是保护 authority，reported message count 只进审计。
    if _protect_char_req:
        for _pg in atomic_groups:
            if _protected_chars >= _protect_char_req:
                break
            _protected_group_count += 1
            _protected_message_count += len(_pg)
            _protected_chars += sum(_wire_size(mm, current_turn_ref) for mm in _pg)

    kept_groups: list[list[Message]] = []
    archived: list[Message] = []
    # EVO-20260816-380f1c2e（缓存友好压缩）: 归档目标从"裁到预算上限"改为"裁到预算×0.6 留缓冲"。
    # 前缀缓存机制: 追加消息不破坏命中（实证 97%+），但修改已提交序列（压缩）必断点。
    # 裁到 100% 上限 → 下一轮必再超 → 每轮压缩 → 前缀每轮变化 → 永久断点（实测 1% 命中率）。
    # 裁到 60% → 压缩后留 40% 增长空间 → 稳定期从"几轮"延长到"几十轮"（该时段纯追加、高命中）。
    _archive_target_ratio = _compress_target_ratio()
    _archive_target_chars = int(max_chars * _archive_target_ratio)
    archive_budget = _archive_target_chars
    # EVO-20260817-9d3e1f2c（缓存友好压缩 v2）: 保留锚点头部（提交前缀命中）+ 最近尾部（语义），
    # 只归档中段——压缩不再破坏前缀缓存。实证: 锚点前移式压缩后首轮命中 6.8%→次轮起 96%
    # （全量失效后重新锚定）; 保留头部后压缩轮即命中 system+头部（~70%+），次轮 99%，无断崖。
    # 头部保留代价: 每轮多占预算（命中价 ~1/10），换来压缩轮无全量失效; head_keep_chars=0 关闭。
    # mandatory cached-prefix 先占位；普通 fixed-head 只能在它之后追加，不能把它裁掉。
    head_groups: list[list[Message]] = list(atomic_groups[:_protected_group_count])
    head_chars = sum(_wire_size(mm, current_turn_ref) for g in head_groups for mm in g)
    # R3: 真实任务锚点保护只覆盖“真实对话组”，不覆盖锚点后 program-only user
    # 附录。旧实现把后续 [相关记忆]/[声明提醒] 也计入保护区，噪声一多就把
    # _anchor_protect_valid 打成 False，最终真实 user 任务反而被归档；旧
    # 旧自动压缩摘要曾把任务复述回来形成伪 PASS。program-only 组仍可按普通
    # archive/budget 规则淘汰，不能获得与用户任务相同的保护权。
    _anchor_protected_groups: set[int] = set()
    if _anchor_group_idx is not None:
        for _pgi in range(_anchor_group_idx, len(atomic_groups)):
            _pg = atomic_groups[_pgi]
            if not all(_is_injected_block(mm) for mm in _pg):
                _anchor_protected_groups.add(_pgi)
    _anchor_protect_valid = True
    if head_keep_chars > 0:
        acc = 0
        optional_count = 0
        for g in atomic_groups:  # 从最旧端累积普通 fixed-head 候选
            gl = sum(_wire_size(mm, current_turn_ref) for mm in g)
            if acc + gl > head_keep_chars:
                break
            optional_count += 1
            acc += gl
        desired_count = max(_protected_group_count, optional_count)
        head_groups = list(atomic_groups[:desired_count])
        head_chars = sum(_wire_size(mm, current_turn_ref) for g in head_groups for mm in g)
        # 上限保护: 默认仍不超过归档预算一半；provider 中段压缩可显式提高到例如 0.65，
        # 让压缩轮保留更大的、曾作为早期请求端点出现过的 fixed-head。DeepSeek 实测：
        # “长 prompt → 中段分叉”不会自动复用全部共同前缀，但若 fixed-head 边界曾作为
        # 完整请求端点出现，则后续分叉可几乎完整复用该 head。自然增长会产生这些端点。
        try:
            _head_target_ratio = float(head_keep_target_ratio)
        except (TypeError, ValueError):
            _head_target_ratio = 0.5
        _head_target_ratio = max(0.1, min(_head_target_ratio, 0.85))
        _head_cap = int(archive_budget * _head_target_ratio)
        # cap 只允许收缩 optional fixed-head；mandatory cached prefix 永不因 target cap 被裁。
        while len(head_groups) > _protected_group_count and head_chars > _head_cap:
            g = head_groups.pop()
            head_chars -= sum(_wire_size(mm, current_turn_ref) for mm in g)
    head_count = len(head_groups)
    # head 预算确定后再验证真实对话保护区，避免旧实现“注释计 head、实际未计”的
    # 时序漂移。只要真实对话保护区本身能放进整个 max_chars，就允许它穿透
    # 60% archive target；单条超大真实 user 仍走既有 trim+archive 兜底。
    if _anchor_protected_groups:
        _anchor_zone_chars = sum(
            _wire_size(mm, current_turn_ref)
            for _pgi in _anchor_protected_groups
            for mm in atomic_groups[_pgi]
            if _pgi >= head_count
        )
        if len(system_prompt) + head_chars + _anchor_zone_chars > max_chars:
            _anchor_protect_valid = False
    if head_keep_chars > 0 and head_count == 0:
        # EVO-20260825 任务6.3: head 预算过小/首组即超 → 自动降级 head_keep=0 全量归档
        # （与 head_keep_chars=0 行为一致：锚点前移式归档，前缀重建一轮后恢复）。
        import logging

        logging.getLogger(__name__).warning(
            "head_keep 保留组为空（首组已超 head 预算），自动降级为 head_keep=0 全量归档: "
            "head_keep_chars=%d session=%s",
            head_keep_chars,
            session_id,
        )
    # 最新组单条超限兜底仍按全预算判断（不因留缓冲而更激进截断单条消息;
    # 该分支语义=单条消息就超整个预算的极端场景, 保留语义与留缓冲解耦）。
    trim_budget = max_chars
    # Provider compaction is a mechanical contiguous-oldest projection once the
    # effective physical/operator budget is exceeded. It is intentionally independent
    # of the retired per-round K-fold experiment: no semantic relevance decision and
    # no per-round K rewrite. Durable archive + versioned provider markers preserve exact
    # recovery and prevent the same old span from being folded again every round.
    if cache_archive_provider:
        kept_groups = list(atomic_groups[head_count:])
        _kept_group_indices = list(range(head_count, len(atomic_groups)))
        _fold_count = 0
        while kept_groups:
            _kept_chars = sum(
                _wire_size(mm, current_turn_ref) for g in kept_groups for mm in g
            )
            if len(system_prompt) + head_chars + _kept_chars <= archive_budget:
                break
            # Mechanical oldest-first compaction with one non-removable identity:
            # skip the active human group, then continue retiring the oldest atomic
            # tool groups after it. This preserves protocol grounding without pinning
            # the entire current tool trajectory or making relevance judgements.
            _remove_pos: int | None = None
            for _pos, (_group_idx, _group) in enumerate(
                zip(_kept_group_indices, kept_groups, strict=True)
            ):
                if _exact_human_group is not None and _group is _exact_human_group:
                    continue
                if _group_idx in _anchor_protected_groups and _anchor_protect_valid:
                    break
                _remove_pos = _pos
                break
            if _remove_pos is None:
                break
            group = kept_groups.pop(_remove_pos)
            _kept_group_indices.pop(_remove_pos)
            archived.extend(group)
            _fold_count += 1
    else:
        _fold_count = 0
        for _gi in range(len(atomic_groups) - 1, head_count - 1, -1):
            group = atomic_groups[_gi]
            group_len = sum(_wire_size(mm, current_turn_ref) for mm in group)
            if _exact_human_group is not None and group is _exact_human_group:
                kept_groups.insert(0, group)
                archive_budget -= group_len
                continue  # R6: exact human truth may pierce history budget; routing owns hard model limit
            if (
                archive_budget - group_len < 0
                and kept_groups
                and not (
                    _anchor_protect_valid
                    and _gi in _anchor_protected_groups
                )
            ):
                # 漂移修复（2026-08-29）: 保护边界内（锚点组起）不归档——穿透预算
                # 保留任务锚点，锚点丢失代价 > 超限 BLOCK 兜底
                archived.extend(group)  # 整组归档（配对原子性：不拆散）
                _fold_count += 1
                continue
            if group_len > trim_budget and (
                not kept_groups
                or (_anchor_protect_valid and _gi in _anchor_protected_groups)
            ):
                # 最新组单条/整组超限: 另存全文 + 精简注入（组内字段保留，仅 content 截断）
                # 2026-08-29 回归修复（test_search_archive_in_loop_after_compression）:
                # 锚点组自身超 trim_budget 时也走本兜底——原实现 1062 归档分支被锚点
                # 保护排除、本分支又被 not kept_groups 排除 → 单条大锚点（如用户贴长文）
                # 永久穿透预算不归档（提交持续超载 + 档案零命中）。本兜底归档原文
                # （信息零丢失）+ 提交保留截断版（锚点残迹在，防漂移语义保留）。
                archived.extend(group)
                trimmed_group: list[Message] = []
                for mm in group:
                    trimmed = (
                        mm.content[: max(trim_budget - 100, 100)]
                        + "\n…[本消息已压缩，完整内容已另存；检索入口: search_archive]…"
                    )
                    trimmed_group.append(
                        Message(
                            role=mm.role,
                            content=trimmed,
                            source=mm.source,
                            tool_call_id=mm.tool_call_id,
                            status=mm.status,
                            tool_name=mm.tool_name,
                            error_detail=mm.error_detail,
                            tool_calls=mm.tool_calls,
                            reasoning_content=mm.reasoning_content,  # M20 THK-04: 压缩后回传链不因截断断裂
                            metadata=mm.metadata,
                        )
                    )
                    archive_budget -= len(trimmed)
                kept_groups.insert(0, trimmed_group)
                continue
            kept_groups.insert(0, group)
            archive_budget -= group_len

    # EVO-20260818（spec §5.5.1-7，grill-me Q4）: 压缩余量不足降级——head 保留 + 归档目标
    # 后提交仍 >95% 预算（单轮裁不动: 超大消息/头部占比高；head 不占 archive_budget，
    # 压缩后提交 ≈ head(15-20%) + archive(60%)）→ 放弃 head 保留（锚点前移式压缩），
    # 防规则 F 反复 BLOCK 与压缩风暴；head 与最老保留组一并归档（信息零丢失）。
    _downgraded_head = False
    _cache_boundary_mode = "protected" if _protected_group_count > 0 else "inactive"
    if head_groups and kept_groups:
        _kept_total = head_chars + sum(_wire_size(mm, current_turn_ref) for g in kept_groups for mm in g)
        if len(system_prompt) + _kept_total > int(max_chars * 0.95):
            _downgraded_head = True
            if _protected_group_count > 0:
                # suffix 已压到不能再压仍超过安全线：允许一次显式 cache epoch reset，
                # 不能静默声称“保护缓存”同时又把 cached prefix 归档。
                _cache_boundary_mode = "epoch_reset"
            _preserved_head_group: list[Message] | None = None
            for g in head_groups:
                if _exact_human_group is not None and g is _exact_human_group:
                    _preserved_head_group = g
                    continue
                archived.extend(g)
            head_groups = []
            head_count = 0
            head_chars = 0
            if _preserved_head_group is not None:
                kept_groups.insert(0, _preserved_head_group)
            # head 归档后仍超（system 巨大场景）→ 继续从最老端连续归档，保护最新语义尾部。
            while kept_groups:
                _cur = sum(_wire_size(mm, current_turn_ref) for g in kept_groups for mm in g)
                if len(system_prompt) + _cur <= int(max_chars * 0.95):
                    break
                _remove_pos = next(
                    (
                        _pos
                        for _pos, _group in enumerate(kept_groups)
                        if _exact_human_group is None or _group is not _exact_human_group
                    ),
                    None,
                )
                if _remove_pos is None:
                    break  # exact human alone may exceed budget; routing owns the hard model limit
                archived.extend(kept_groups.pop(_remove_pos))

    if compacted_out is not None and _protected_group_count > 0 and not archived:
        # P1: confirmed cache boundary 把本轮所有可归档 suffix 都保护/锚定住，
        # wire 实际未改变——不能把 soft-pressure no-op 记成 cache compaction。
        compacted_out[0] = False

    # 另存被丢弃消息（信息零丢失）
    if archive_sink is not None and session_id and archived:
        for m in archived:
            try:
                archive_sink(session_id, m)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("archive sink 异常（fail-open）", exc_info=True)
                if require_archive_success:
                    raise

    # provider级提交视图压缩：原文仍保留在 Session/事件链/归档，只让后续该 provider
    # build 跳过本轮已经折叠的中段，解决 head_keep + fold 重复归档。
    if cache_archive_provider and archived:
        for m in archived:
            if _mark_cache_compacted_for(
                m,
                cache_archive_provider,
                model_ref=cache_archive_model,
                effective_budget=cache_archive_budget,
            ):
                if cache_compacted_out is not None:
                    cache_compacted_out.append(m)
                if cache_compacted_index_out is not None:
                    _src_idx = _source_index_by_id.get(id(m))
                    if _src_idx is not None:
                        cache_compacted_index_out.append(_src_idx)

    # EVO-20260818 修复基线 bug（仿真测试暴露）: kept_flat 原实现从不包含 head_groups——
    # 头部消息既不在提交也不在归档（静默丢失）→ "缓存友好压缩保留锚点头部"从未真正生效，
    # 压缩轮命中率仅 system 占比（spec §5.3.1-3b ≥70% 不可达）。head 组并入提交最前。
    kept_flat = [m for g in head_groups for m in g] + [m for g in kept_groups for m in g]
    kept_flat = _apply_reasoning_tail(kept_flat, reasoning_tail)
    # P1-10: 超长归档后锚点推进 = 旧锚点 + 窗口内被丢弃消息数
    # （kept_flat 中不删消息；差值即整组丢弃数；reasoning 瘦身只改提交视图）
    # "最新组超限精简注入"分支的消息仍在 kept → 不计入推进）
    # EVO-20260817-9d3e1f2c: 缓存友好压缩——头部保留（head_count>0）时锚点不动
    # （提交前缀稳定命中，只归档中段）；仅头部也被归档（head_count=0）才前移。
    if anchor_out is not None:
        if _preserved_human is not None and any(m is _preserved_human for m in kept_flat):
            # Provider markers represent non-contiguous retired groups after the current
            # human; advancing the contiguous anchor by archived-count would skip that
            # human on the next round and recreate the 1214 state.
            anchor_out.append(history_anchor)
        elif head_count > 0:
            anchor_out.append(history_anchor)
        else:
            # EVO-20260825 任务6.3: 锚点推进边界安全防护——越界 clamp + WARN
            # （防御：归档计数理论上 ≤ 窗口内消息数，但保留组含 head 并入的极端场景
            #  下差值不得越过窗口上界，防锚点漂移到未知位置）
            _adv_raw = history_anchor + (len(session_messages) - len(kept_flat))
            _adv_cap = len(session_messages)
            _adv = min(_adv_raw, _adv_cap)
            if _adv != _adv_raw:
                import logging

                logging.getLogger(__name__).warning(
                    "锚点推进越界，已安全截断: target=%d cap=%d session=%s",
                    _adv_raw,
                    _adv_cap,
                    session_id,
                )
            anchor_out.append(_adv)
    for m in kept_flat:
        if skip_injected_system and _is_injected_system(m):
            continue  # P1-7: 推送式注入仅落会话, 不进提交（system 前缀稳定）
        # EVO-20260817-cef296f8 L1b: 已消费的耗尽注入 system（[轮次决策请求]/
        # [已达轮数上限]）跳过——run 内 AI 决策可见，run 后消费，下个 run 不进请求
        # system 区 → 前缀不因耗尽注入持续分叉（缓存 MISS 收敛）
        if skip_injected_system and m.role == "system" and (m.metadata or {}).get("consumed"):
            continue
        # P1-QWEN-FIX: 压缩裁剪后的 system 消息必须并入开头 system，
        # 否则 system 落在消息中间 → qwen 系模板(9B/27B) 报
        # "System message must be at the beginning" (HTTP 400/500)。
        if m.role == "system":
            _append_or_merge(_provider_message_dict(m, current_turn_ref), dynamic=_is_dynamic_inject(m))
        else:
            _d = _provider_message_dict(m, current_turn_ref)
            out.append(_d)
    # Compaction is representation-only: archived source bytes remain durable and
    # recoverable through explicit search/read paths. The runtime does not synthesize
    # Goal/checkpoint decisions, key-fact summaries, or compression prose into provider
    # context.
    # EVO-20260825 任务6.2: 压缩后视图体积验证——pre vs post 对比（drop<5% → WARN +
    # 审计事件由调用方写 breaker）。pre 口径 = 压缩前完整载荷（system + 窗口历史）；
    # post 口径 = 实际提交协议视图（含 head/kept/extras）。
    if compact_view_stats is not None and archived:
        try:
            _pre_chars = len(system_prompt) + total_chars
            _post_chars = sum(_dict_wire_size(m) for m in out)
            _drop_pct = (
                (max(1, _pre_chars) - _post_chars) / max(1, _pre_chars) * 100.0
            )
            _archived_ids = {id(m) for m in archived}
            _archived_group_count = sum(
                1
                for _g in atomic_groups
                if any(id(_m) in _archived_ids for _m in _g)
            )
            compact_view_stats.append(
                {
                    "trigger": "projected_history_over_compact_limit",
                    "pre_history_chars": total_chars,
                    "pre_chars": _pre_chars,
                    "post_chars": _post_chars,
                    "drop_pct": round(_drop_pct, 1),
                    "effective_budget_chars": max_chars,
                    "compact_ratio": compact_ratio,
                    "trigger_limit_chars": compact_limit,
                    "trigger_excess_chars": max(0, total_chars - compact_limit),
                    "archive_target_ratio": _archive_target_ratio,
                    "archive_target_chars": _archive_target_chars,
                    "archived_count": len(archived),
                    "archived_group_count": _archived_group_count,
                    "atomic_group_count": len(atomic_groups),
                    "compaction_mode": (
                        "provider_contiguous_oldest" if cache_archive_provider else "budget_recent_tail"
                    ),
                    "head_keep_chars": head_keep_chars,
                    "head_keep_target_ratio": head_keep_target_ratio,
                    "cache_boundary_mode": _cache_boundary_mode,
                    "cache_boundary_reported_messages": _reported_cached_messages,
                    "cache_protected_messages": _protected_message_count,
                    "cache_protected_chars": _protected_chars,
                }
            )
            if _drop_pct < 5:
                import logging

                logging.getLogger(__name__).warning(
                    "head_keep 大裁后视图未缩小: pre=%d post=%d drop=%.1f%% "
                    "archived=%d session=%s",
                    _pre_chars,
                    _post_chars,
                    _drop_pct,
                    len(archived),
                    session_id,
                )
            else:
                import logging

                logging.getLogger(__name__).debug(
                    "压缩视图验证: pre=%d post=%d drop=%.1f%% archived=%d session=%s",
                    _pre_chars,
                    _post_chars,
                    _drop_pct,
                    len(archived),
                    session_id,
                )
        except Exception:  # noqa: BLE001 — fail-open
            import logging

            logging.getLogger(__name__).debug(
                "压缩视图统计失败（fail-open）", exc_info=True
            )
    return _repair_tool_call_pairing(out)



def _exact_tool_group(messages: list[dict], start: int) -> tuple[int, str] | None:
    """Return (exclusive_end, canonical_fp) for one complete tool protocol group.

    Canonicalization ignores generated call IDs only. Assistant content/reasoning,
    function names/arguments, receipt association/order, and every other provider-
    visible tool field remain part of the fingerprint. Therefore only byte-equivalent
    action+observation episodes are eligible for exact duplicate projection.
    """
    if start >= len(messages):
        return None
    assistant = messages[start]
    if not isinstance(assistant, dict) or assistant.get("role") != "assistant":
        return None
    raw_calls = assistant.get("tool_calls")
    if not isinstance(raw_calls, list) or not raw_calls:
        return None

    call_index: dict[str, int] = {}
    canonical_calls: list[dict] = []
    for idx, raw_call in enumerate(raw_calls):
        if not isinstance(raw_call, dict):
            return None
        call = dict(raw_call)
        call_id = str(call.pop("id", "") or "")
        if call_id:
            call_index[call_id] = idx
        call["_call_index"] = idx
        canonical_calls.append(call)

    end = start + 1
    receipts: list[dict] = []
    answered: set[int] = set()
    while end < len(messages):
        receipt = messages[end]
        if not isinstance(receipt, dict) or receipt.get("role") != "tool":
            break
        item = dict(receipt)
        receipt_id = str(item.pop("tool_call_id", "") or "")
        if receipt_id and receipt_id in call_index:
            idx = call_index[receipt_id]
        else:
            remaining = [i for i in range(len(canonical_calls)) if i not in answered]
            if not remaining:
                break
            idx = remaining[0]
        item["_call_index"] = idx
        answered.add(idx)
        receipts.append(item)
        end += 1
        if len(answered) >= len(canonical_calls):
            break

    if len(answered) != len(canonical_calls):
        return None

    assistant_rest = {
        key: value
        for key, value in assistant.items()
        if key != "tool_calls"
    }
    canonical = {
        "assistant": assistant_rest,
        "tool_calls": canonical_calls,
        "receipts": receipts,
    }
    digest = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return end, digest


def project_exact_duplicate_tool_groups(
    messages: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """Mechanically collapse runs of >=3 contiguous exact tool groups, keeping first.

    This is representation-only and intentionally has no semantic stop/retry logic:
    - only immediately adjacent complete assistant(tool_calls)->tool receipt groups;
    - two identical groups remain visible; folding begins only once the run reaches three;
    - generated call IDs are normalized, every other provider-visible byte matters;
    - the first group is kept for stable-prefix friendliness;
    - no summary, warning, "do not retry" hint, or completion judgement is injected.
    The caller retains the unmodified Session/EventLog as durable truth.
    """
    if not messages:
        return [], {"folded_groups": 0, "removed_messages": 0}

    units: list[tuple[str, str | None, list[dict]]] = []
    cursor = 0
    while cursor < len(messages):
        group = _exact_tool_group(messages, cursor)
        if group is None:
            units.append(("other", None, [messages[cursor]]))
            cursor += 1
            continue
        end, digest = group
        units.append(("group", digest, messages[cursor:end]))
        cursor = end

    projected: list[dict] = []
    folded_groups = 0
    removed_messages = 0
    i = 0
    while i < len(units):
        kind, digest, chunk = units[i]
        if kind != "group":
            projected.extend(chunk)
            i += 1
            continue
        j = i + 1
        while j < len(units) and units[j][0] == "group" and units[j][1] == digest:
            j += 1
        run_len = j - i
        if run_len < 3:
            for unit in units[i:j]:
                projected.extend(unit[2])
        else:
            projected.extend(chunk)  # keep first exact observation for prefix stability
            for duplicate in units[i + 1 : j]:
                folded_groups += 1
                removed_messages += len(duplicate[2])
        i = j

    return projected, {
        "folded_groups": folded_groups,
        "removed_messages": removed_messages,
    }

def compute_breakdown(
    session_messages: list[Message],
    system_prompt: str,
    memory_msgs: list[Message] | None = None,
    *,
    tool_schema_chars: int = 0,
    budget: int = 0,
) -> dict:
    """组件级上下文占用分解（R1: 纯只读，无副作用，供 architecture_status 注入）.

    Returns:
        {system, memory, history, tool_results, tool_schema, total, budget, ratio}
        每项含 {chars, est_tokens, pct}；budget<=0 时 ratio 为 None。
    """
    sys_chars = len(system_prompt or "")
    mem_chars = sum(len(m.content) for m in (memory_msgs or []))
    hist_chars = sum(len(m.content) for m in session_messages if m.role != "tool")
    tool_chars = sum(len(m.content) for m in session_messages if m.role == "tool")
    reasoning_chars = sum(
        len(m.reasoning_content or "")
        for m in session_messages
        if m.role == "assistant" and getattr(m, "reasoning_content", None)
    )
    total = sys_chars + mem_chars + hist_chars + tool_chars + tool_schema_chars + reasoning_chars

    def _item(c: int) -> dict:
        return {"chars": c, "est_tokens": c // 2, "pct": round(c / max(1, total) * 100, 1)}

    return {
        "system": _item(sys_chars),
        "memory": _item(mem_chars),
        "history": _item(hist_chars),
        "tool_results": _item(tool_chars),
        "tool_schema": _item(tool_schema_chars),
        "reasoning": _item(reasoning_chars),
        "total": {"chars": total, "est_tokens": total // 2},
        "budget": budget,
        "ratio": round(total / max(1, budget), 3) if budget > 0 else None,
    }


def compute_breakdown_from_dicts(
    messages: list[dict],
    tool_schema_chars: int = 0,
    budget: int = 0,
) -> dict:
    """基于**实际发送载荷**（LLM 协议 dict 列表）的组件级占用分解.

    与 compute_breakdown（基于原始会话消息）同构，但口径为构建后真正发给
    LLM 的内容——已压缩归档的历史不再计入占用（旧口径把原始会话全量算进
    "当前上下文占用"，本地慢模型收紧预算后会虚高数十倍，误导 AI 压缩决策）。

    Returns:
        {system, memory, history, tool_results, tool_schema, reasoning,
         total, budget, ratio}；memory 恒 0（记忆消息已并入 system/history，
        协议层不可区分）；budget<=0 时 ratio 为 None。
    """
    sys_chars = sum(
        len(str(m.get("content") or "")) for m in messages if m.get("role") == "system"
    )
    hist_chars = sum(
        len(str(m.get("content") or ""))
        for m in messages
        if m.get("role") not in ("system", "tool")
    )
    tool_chars = sum(
        len(str(m.get("content") or "")) for m in messages if m.get("role") == "tool"
    )
    reasoning_chars = sum(
        len(str(m.get("reasoning_content") or "")) for m in messages
    )
    total = sys_chars + hist_chars + tool_chars + tool_schema_chars + reasoning_chars

    def _item(c: int) -> dict:
        return {"chars": c, "est_tokens": c // 2, "pct": round(c / max(1, total) * 100, 1)}

    return {
        "system": _item(sys_chars),
        "memory": _item(0),
        "history": _item(hist_chars),
        "tool_results": _item(tool_chars),
        "tool_schema": _item(tool_schema_chars),
        "reasoning": _item(reasoning_chars),
        "total": {"chars": total, "est_tokens": total // 2},
        "budget": budget,
        "ratio": round(total / max(1, budget), 3) if budget > 0 else None,
    }


def _pairing_gap(messages: list[dict], i: int) -> tuple[list[str], list[str], int]:
    """assistant(i) 声明的 tool_calls 与紧随 tool 回执的配对缺口.

    P1-6(2026-08-15，审计发现 #16)：按 id 精确配对；空 id 声明/回执按位置兜底——
    存量会话存在空 tool_call_id 回执，旧实现按"回执 id 非空"计数会漏计 → 多补占位
    （额外 tool 消息无对应声明 → API 400）。

    Returns: (declared_ids, missing_declared_ids, next_index)
        missing 为空 = 配对完整；next_index = 紧随回执段之后的位置。
    """
    calls = messages[i].get("tool_calls") or []
    declared: list[str] = []
    for c in calls:
        declared.append(str(c.get("id") or "") if isinstance(c, dict) else "")
    n = len(messages)
    receipt_ids: list[str] = []
    j = i + 1
    while j < n and isinstance(messages[j], dict) and messages[j].get("role") == "tool":
        receipt_ids.append(str(messages[j].get("tool_call_id") or ""))
        j += 1
    # id 精确配对
    remaining = list(receipt_ids)
    answered: set[int] = set()
    for di, did in enumerate(declared):
        if did and did in remaining:
            remaining.remove(did)
            answered.add(di)
    # 仅空 id 参与位置兜底（存量兼容）。两个不同的非空 id 绝不能按位置视为
    # 已配对，否则 provider 仍会因 tool_call_id not found 拒绝请求。
    unanswered = [di for di in range(len(declared)) if di not in answered]
    for di in unanswered:
        did = declared[di]
        for ri, rid in enumerate(remaining):
            if not did or not rid:
                remaining.pop(ri)
                answered.add(di)
                break
    missing = [declared[di] for di in range(len(declared)) if di not in answered]
    return declared, missing, j


def _pairing_direction_b_orphans(messages: list[dict]) -> set[int]:
    """方向 B（2026-08-24 主区故障: "Messages with role 'tool' must be a
    response to a preceding message with 'tool_calls'"）: 孤立/多余 tool 回执下标集合.

    - 孤立: tool 消息前向最近的声明不是 assistant(tool_calls)（含首条即 tool /
      前一条为 user / 声明已被裁剪）——协议要求 tool 必须紧跟 assistant(tool_calls)。
    - 多余: tool 回执的 tool_call_id 未在最近声明的 id 集合中被消费（声明数量
      不足 / id 不匹配）——同样触发协议 400（tool_call_id not found 类）。

    配对语义与 _pairing_gap 一致（id 精确优先 + 空 id 位置兜底兼容存量）。
    纯函数无副作用；调用方（validate/repair）据此报违规或丢弃提交视图条目。
    """
    orphans: set[int] = set()
    n = len(messages)
    i = 0
    while i < n:
        m = messages[i]
        if not isinstance(m, dict):
            i += 1
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            declared = [
                str(c.get("id") or "") for c in (m.get("tool_calls") or []) if isinstance(c, dict)
            ]
            consumed = [False] * len(declared)
            j = i + 1
            while j < n and isinstance(messages[j], dict) and messages[j].get("role") == "tool":
                rid = str(messages[j].get("tool_call_id") or "")
                matched = False
                for di, did in enumerate(declared):
                    if consumed[di]:
                        continue
                    if did and did == rid:
                        consumed[di] = True
                        matched = True
                        break
                if not matched:
                    # 存量兼容只允许“声明 id 为空”或“回执 id 为空”时按位置兜底；
                    # 两个不同的非空 id 必须判为孤儿/错配。
                    for di, did in enumerate(declared):
                        if not consumed[di] and (not did or not rid):
                            consumed[di] = True
                            matched = True
                            break
                if not matched:
                    orphans.add(j)  # 声明已全部消费 / 无匹配 → 多余回执
                j += 1
            i = j
        else:
            if m.get("role") == "tool":
                orphans.add(i)  # 前无声明 → 孤立
            i += 1
    return orphans


def validate_tool_call_pairing(messages: list[dict]) -> list[str]:
    """S2/A2: LLM 消息序列 tool_calls↔tool 消息配对自检（纯函数，无副作用）.

    对每条 `role == "assistant"` 且含 `tool_calls` 的消息，校验其后连续
    tool 消息数量 ≥ 声明数量（tool_calls 列表中每项按 `id`/`index` 计数）；
    不足 → 返回违规描述列表（缺几条/缺哪轮）；空列表 = 通过。
    遍历/结构异常 → 返回 `["配对自检异常: <原因>"]`（如实标注，不静默）。

    Args:
        messages: LLM 协议消息列表（dict，含 role/content/tool_calls/tool_call_id 等）.

    Returns:
        违规描述列表；空列表表示序列配对完整（fail-open：异常同样以列表如实返回）。
    """
    try:
        violations: list[str] = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "assistant":
                continue
            calls = msg.get("tool_calls")
            if not calls:
                continue
            declared, missing, _j = _pairing_gap(messages, i)
            if missing:
                violations.append(
                    f"第 {i} 轮 assistant(tool_calls) 声明 {len(declared)} 个工具调用，"
                    f"其后仅 {len(declared) - len(missing)} 条 tool 回执，缺 {len(missing)} 条"
                )
        # 方向 B（2026-08-24 主区故障: "Messages with role 'tool' must be a
        # response to a preceding message with 'tool_calls'"）: 孤立/多余 tool 回执
        # ——统一判定见 _pairing_direction_b_orphans（id 精确 + 段首回溯），报违规供 repair。
        for idx in sorted(_pairing_direction_b_orphans(messages)):
            violations.append(
                f"第 {idx} 条 tool 回执孤立/多余（前无匹配的 assistant(tool_calls) 声明），"
                f"tool_call_id={messages[idx].get('tool_call_id')!r}"
            )
        return violations
    except Exception as exc:  # noqa: BLE001 — 自检异常如实标注，不静默不阻断
        return [f"配对自检异常: {type(exc).__name__}: {exc}"]


def _repair_tool_call_pairing(messages: list[dict]) -> list[dict]:
    """S2/A2: 协议配对自检 + 补齐占位（fail-open，不阻断不伪装真实回执）.

    对 assistant(tool_calls) 后缺失的 tool 回执按声明顺序补齐占位消息：
    content 为 `[程序异常] 工具回执缺失（协议配对自检）`，tool_call_id 沿用
    assistant 声明的 id（缺失 id 时用占位 id），日志如实标注违规明细；
    无违规 → 返回原列表（零改动）。

    Args:
        messages: LLM 协议消息列表（dict）.

    Returns:
        补齐后的消息列表（无违规时原样返回）.
    """
    violations = validate_tool_call_pairing(messages)
    if not violations:
        return messages
    import logging

    logging.getLogger(__name__).warning(
        "tool_calls↔tool 配对自检发现违规，已补齐占位（协议配对自检）: %s",
        "; ".join(violations),
    )
    # 方向 B（2026-08-24 主区故障）: 孤立/多余 tool 回执统一判定（id 精确 + 段首回溯）
    orphans = _pairing_direction_b_orphans(messages)
    out: list[dict] = []
    n = len(messages)
    i = 0
    while i < n:
        m = messages[i]
        # 方向 B: 孤立/多余 tool 回执——提交视图丢弃（原始会话数据不动、零丢失）并
        # 如实标注日志；协议要求 tool 必须响应某条 assistant(tool_calls) 声明，否则
        # DeepSeek/OpenAI 报 400 "Messages with role 'tool' must be a response to a
        # preceding message with 'tool_calls'"（或 tool_call_id not found）。
        # 不伪造声明、不静默丢弃。
        if i in orphans:
            logging.getLogger(__name__).warning(
                "丢弃孤立/多余 tool 回执（协议配对自检，提交视图处理）: tool_call_id=%s",
                m.get("tool_call_id"),
            )
            i += 1
            continue
        out.append(m)
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            # P1-6: id 精确配对 + 空 id 位置兜底（审计 #16，缺口语义与自检一致）
            _declared, missing, j = _pairing_gap(messages, i)
            # 既有 tool 回执原序追加（跳过方向 B 孤儿；占位补在真实回执之后）
            for t in range(i + 1, j):
                if t not in orphans:
                    out.append(messages[t])
            # 按声明顺序补齐缺失占位（沿用缺口声明 id；空 id 用占位 id）
            for k, did in enumerate(missing):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": did or f"pairing-placeholder-{i}-{k}",
                        "content": "[程序异常] 工具回执缺失（协议配对自检）",
                    }
                )
            i = j
            continue
        i += 1
    return out


# ── EVO-20260817-b6554376: 投影一致性门闸（借鉴 DSH seq 水印）──
def _is_dynamic_inject(m: Message) -> bool:
    """EVO-20260817（DSH 修复）: 每轮变化的动态注入（memory 检索/inbox 临时消息）→ 不并入
    system 主体（转独立 user 消息，system 主体字节稳定 → 前缀缓存命中）."""
    if getattr(m, "source", None) == MessageSource.MEMORY:
        return True
    meta = getattr(m, "metadata", None) or {}
    return bool(meta.get("_dynamic"))


def stable_digest(obj: Any) -> str:
    """稳定序列化哈希（sort_keys + ensure_ascii=False）——同输入必同输出.

    Message 对象转 (role, content) 对；dict/list 稳定 JSON；其余 str() 兜底。
    """
    def _norm(o: Any):
        if isinstance(o, Message):
            return {"role": o.role, "content": o.content, "metadata": o.metadata}
        if isinstance(o, dict):
            return {k: _norm(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_norm(v) for v in o]
        return o

    raw = json.dumps(_norm(obj), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def projection_ver(*, model: str, budget: int, anchor: int, memory_fp: str,
                   interop_fp: str, system_fp: str, settings_fp: str) -> str:
    """构建参数指纹（ver）——任何影响构建输出的参数变化 → ver 变化 → 缓存行自然过期.

    seq（消息数）负责"历史追加"水印；ver 负责"参数/动态输入（记忆/协调/system/开关）"水印。
    """
    return stable_digest({
        "model": model, "budget": budget, "anchor": anchor,
        "memory_fp": memory_fp, "interop_fp": interop_fp,
        "system_fp": system_fp, "settings_fp": settings_fp,
    })


def projection_check(prev: dict | None, *, ver: str, seq: int, built_hash: str) -> str:
    """投影一致性校验——纯函数，返回状态字符串.

    - "miss":  无前序缓存行 / ver 或 seq 不匹配（正常：新会话/参数变化/新消息追加）→ 应更新缓存行
    - "ok":    ver+seq 匹配且输出哈希一致（稳定期，前缀应命中）
    - "mismatch": ver+seq 匹配但输出哈希不同 → **非确定性构建或历史被改**（追加式保证被破坏）→ 告警
    """
    if prev is None:
        return "miss"
    if prev.get("ver") != ver or prev.get("seq") != seq:
        return "miss"
    if prev.get("built_hash") == built_hash:
        return "ok"
    return "mismatch"
