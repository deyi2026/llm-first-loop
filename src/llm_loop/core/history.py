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
from datetime import UTC
from typing import Any

from llm_loop.core.message import Message, MessageSource, ToolCall


def _wire_size(m: Message) -> int:
    """提交视图口径体积（与守卫估算 routing._estimate_request_chars 对齐）.

    content + reasoning_content + tool_calls 参数。history 压缩预算原只看
    content——reasoning_content 可占 40%+（实测 fb8f8987: 287K/598K 全字段），
    压缩器看不见 → 恒不触发 → emergency_compact 空转（2026-08-26 glm 超限
    死循环根因：守卫按全字段 907K tokens 拦截、压缩按 content 159K<255K 判
    不超）。预算判定一律改用本口径；纯展示/审计统计不变。
    """
    n = len(m.content or "")
    if m.role == "assistant":
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
    n += len(str(d.get("reasoning_content") or ""))
    for tc in d.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        n += len(str(fn.get("arguments") or "")) + len(str(fn.get("name") or ""))
    return n

# EVO-20260816-380f1c2e: 压缩目标比例（裁到预算×此值，留缓冲降低断点频率）。
# 实证: 前缀缓存下压缩轮必断点；裁到 100% → 每轮压缩 → 永久断点（命中率 ~1%）；
# 裁到 60% → 留 40% 增长空间 → 稳定期纯追加高命中（97%+）。可经环境变量覆盖（缓存纪律: 配置低频改）。
_COMPRESS_TARGET_RATIO = float(os.environ.get("COMPRESS_TARGET_RATIO", "0.6"))

_CACHE_COMPACTED_FOR_META = "cache_compacted_for"

# 任务7（§5.7）: progressive_fold 要求 cache_archive_provider（provider 级折叠标记）
# 缺失时的降级 head 预算——降级后 head_keep_chars 原值 ≤0 时使用（env 可配，默认 2000）。
_DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE = int(
    os.environ.get("DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE", "2000")
)


def is_cache_compacted_for(message: Message, provider_id: str) -> bool:
    """Return whether a message is hidden from one provider's prompt view."""
    if not provider_id:
        return False
    raw = (message.metadata or {}).get(_CACHE_COMPACTED_FOR_META)
    if isinstance(raw, str):
        return raw == provider_id
    if isinstance(raw, (list, tuple, set)):
        return provider_id in raw
    return False


def _mark_cache_compacted_for(message: Message, provider_id: str) -> bool:
    """Persist a provider-scoped prompt-view compaction marker."""
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
    if provider_id in providers:
        return False
    providers.append(provider_id)
    meta[_CACHE_COMPACTED_FOR_META] = providers
    message.metadata = meta
    return True

# EVO-20260818 cache_window_converge（spec §5.1.1-1/2/4/5）: 窗口收敛上限守卫。
# - value=None → 按模型窗口自适应 min(200000, max(100000, int(window*2*0.08)))（×2 字符/token 估算，
#   1M=1,000,000 十进制；自适应仅对窗口 ≥625K tokens 生效，其余取兜底 100K）; 窗口未知 → 100K 兜底。
# - 显式 ∈ [1000, 200000] → 原值生效 (value, None)。
# - 显式 > 200K → 显式豁免保留原值 + 告警 note（2026-08-18 用户拍板: 兼容"方案A"大预算实践）。
# - 非法（<1000 / 非整数 / 负数）→ 兜底 100K + note。
# 纯函数: 无副作用、不抛异常、不读 env/不写日志; 供 factory.py 装配期与 runtime.py 运行期同源复用。
_HISTORY_BUDGET_MAX = 200_000  # 收敛上限（默认/自适应路径强制; 显式配置豁免）
_HISTORY_BUDGET_DEFAULT = 100_000  # 兜底默认值（与 max_chars 形参默认一致）


def converge_history_budget(
    value: int | None,
    *,
    model_window: int | None,
) -> tuple[int, str | None]:
    """窗口收敛上限守卫（spec §5.1.1-1/2/4/5）.

    Args:
        value: 显式配置值（None=未配置，按窗口自适应）.
        model_window: 模型窗口上限（tokens），None=未知.

    Returns:
        (收敛后预算, 告警说明或 None). 默认/自适应路径预算 ∈ [100000, 200000];
        显式配置 >200K 豁免保留原值（note 含"显式豁免"）; 非法输入兜底 100K.
    """
    if value is None:
        if model_window is None:
            return _HISTORY_BUDGET_DEFAULT, "窗口未知兜底 100K"
        try:
            adaptive = int(model_window * 2 * 0.08)
        except (TypeError, ValueError):
            return _HISTORY_BUDGET_DEFAULT, "窗口非法兜底 100K"
        if adaptive <= 0:
            return _HISTORY_BUDGET_DEFAULT, "窗口非法兜底 100K"
        return min(_HISTORY_BUDGET_MAX, max(_HISTORY_BUDGET_DEFAULT, adaptive)), None
    if not isinstance(value, int) or isinstance(value, bool):
        return _HISTORY_BUDGET_DEFAULT, "输入非法兜底 100K"
    if value < 1000:
        return _HISTORY_BUDGET_DEFAULT, f"输入非法兜底 100K（{value} < 1000）"
    if value > _HISTORY_BUDGET_MAX:
        return value, (
            f"显式配置 {value} 超收敛上限 200K（显式豁免，已保留）；"
            "如需收敛请配置 ≤200K"
        )
    return value, None


def _top_keywords(messages: list[Message], top: int = 5) -> list[str]:
    """从消息内容抽取高频词作为检索建议词（极简词频，fail-open 由调用方包裹）."""
    import re
    from collections import Counter

    stop = {
        "的", "了", "是", "在", "我", "你", "他", "她", "它", "这", "那", "个", "与", "和",
        "及", "对", "为", "从", "到", "把", "被", "也", "都", "就", "而", "但", "并", "或",
        "the", "a", "an", "is", "are", "was", "to", "of", "for", "and", "or", "in", "on",
        "with", "as", "at", "by", "from", "that", "this", "it", "we", "you", "i",
    }
    counter: Counter = Counter()
    for m in messages:
        if not m.content:
            continue
        for tok in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_]{2,}", m.content):
            t = tok.lower()
            if t not in stop and len(t) >= 2:
                counter[t] += 1
    return [w for w, _ in counter.most_common(top)]


_REASON_WORDS = (
    "因为", "所以", "决定", "选择", "由于", "为了", "判断", "推断",
    "结论", "理由", "依据", "优先", "采用", "建议", "认为", "考虑",
)


def _extract_reasoning_facts(messages: list[Message], max_facts: int = 6) -> list[str]:
    """EVO-3b39134f（OpenAI harness 借鉴）: 提取"决策点+理由"信号行.

    压缩保留推理（为什么这样做）而非仅动作/结果——被压缩的推理链丢失后，
    AI 检索归档只见动作不见动机，易重复分析。规则提取零 LLM：
    含决策/推理连接词的行（因为/所以/决定/选择/由于/为了/判断/推断/结论/理由/
    依据/优先/采用/建议/认为/考虑）且长度 <=200 视为推理结论候选。
    """
    facts: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if not m.content:
            continue
        for line in m.content.splitlines():
            line = line.strip()
            if not line or line in seen:
                continue
            if len(line) > 200:
                continue
            if any(w in line for w in _REASON_WORDS):
                seen.add(line)
                facts.append(line)
            if len(facts) >= max_facts:
                return facts
    return facts


def _cog_anchor_mode() -> str:
    """读 COG_RUNTIME_ANCHOR_MODE（对齐 config._env_cog_anchor_mode 语义；模块级 env 惯例）."""
    import os

    raw = os.environ.get("COG_RUNTIME_ANCHOR_MODE", "").strip().lower()
    return raw if raw in ("semantic", "anchor", "auto") else "auto"


def _persist_semantic_state(session_id: str = "") -> bool:
    """压缩黄金窗口: 从 GoalStore 派生语义状态并原子落盘（Cognitive Runtime tasks 2.4）.

    决策线（T2 [当前决策]+[下一步] 独立注入帧）升级演进为 SemanticTaskState 投影——
    压缩时把决策指针持久化（rebuild+save），build 每轮从状态文件投影为决策包 HOT 首行
    （尾部聚合条内），代码演进不并存（spec 5.1.1-3b）。
    fail-open: GoalStore 不可用/无活跃 goal/损坏 → False（不阻断压缩主流程）。
    audit 路径 = LFL_DATA_DIR（镜像/跨区隔离锚点）或 data/（主区默认）。
    CR-R1（tasks 2.2）: COG_RUNTIME_MODE=off 时短路——连 store 写也不做（纯旧行为）。
    """
    import os as _os_mod
    if _os_mod.environ.get("COG_RUNTIME_MODE", "shadow").strip().lower() == "off":
        return False
    try:
        import os
        from datetime import datetime
        from pathlib import Path as _Path

        from llm_loop.cognitive.state import (
            SemanticStateStore,
            StateEnvelope,
            StateIdentity,
            Tombstone,
            rebuild_state,
        )
        from llm_loop.introspection.goal import GoalStore

        base = os.environ.get("LFL_DATA_DIR", "data")
        audit = _Path(base) / "audit"
        goal = GoalStore(audit).get(prefer_session_id=session_id)
        store = SemanticStateStore(audit)
        state = rebuild_state(goal)
        if state is None:
            # spec 4.1-3 墓碑：goal 终态（complete/blocked）→ 对现存分片打 tombstone，
            # 不删除（供审计）；无 goal 时保留旧分片不覆盖（原语义）。
            if goal and str(goal.get("status", "")) in ("complete", "blocked"):
                old = store.load(session_id)
                if isinstance(old, StateEnvelope) and old.tombstone is None:
                    old.tombstone = Tombstone(
                        reason=f"goal_{str(goal.get('status', ''))}",
                        ts=datetime.now(UTC).isoformat(),
                    )
                    store.save(session_id, old)
            return False  # 无活跃 goal：不覆盖既有状态文件（保留旧指针）
        if goal is None:
            # CR-R1.1（审查项10 pyright 归零）: 有 state 无 goal——identity 无从派生
            # （宁缺勿错，同上语义不覆盖）；显式收窄 Optional，替代原先 .get 隐式
            # AttributeError→except 兜底（行为等价：均 return False）。
            return False
        cps = goal.get("checkpoints") or []
        identity = StateIdentity(
            session_id=session_id or "_",
            goal_id=str(goal.get("id", "")),
            goal_updated_at=str(goal.get("updated_at", "")),
            checkpoint_ts=str((cps[-1] or {}).get("ts", "")) if cps else "",
        )
        old = store.load(session_id)
        if isinstance(old, StateEnvelope):
            # revision 语义：源未变（identity matches）保留；源变更 +1（design §2.1）
            identity.state_revision = (
                old.identity.state_revision
                if old.identity.matches(goal)
                else old.identity.state_revision + 1
            )
        store.save(session_id, StateEnvelope(identity=identity, state=state))
        return True
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "语义状态持久化失败（fail-open）", exc_info=True
        )
        return False


def _decision_line_frame(session_id: str = "") -> str:
    """能力 B 决策线（injection_hygiene 5.2）: 活跃 goal + 最近 checkpoint 两行指针.

    注入位置 = 压缩产物帧首行（[压缩关键事实] 之前）——压缩后恢复从「检索式」变
    「指针式」（AI 不必 search 重建上下文，直接知道当前在做什么/下一步）。
    内容 ≤400 字符（spec 5.2-2）；只带 goal_id 指针不带 evidence 全文（5.2-4）。
    全路径 fail-open: GoalStore 不可用/无活跃 goal → 空串省略（禁阻塞压缩主流程）。
    audit 路径 = LFL_DATA_DIR（镜像/跨区隔离锚点）或 data/（主区默认）。
    """
    try:
        import os
        from pathlib import Path as _Path

        from llm_loop.introspection.goal import GoalStore

        base = os.environ.get("LFL_DATA_DIR", "data")
        g = GoalStore(_Path(base) / "audit").get(prefer_session_id=session_id)
        if not g or g.get("status") != "active":
            return ""
        obj = str(g.get("objective", ""))
        cps = g.get("checkpoints") or []
        nxt = str((cps[-1] or {}).get("next", "")) if cps else ""
        line1 = f"[当前决策] goal={str(g.get('id', ''))[:12]} | {obj}"
        line2 = f"[下一步] {nxt}" if nxt else "[下一步] （无 checkpoint；见 objective）"
        return (line1 + "\n" + line2)[:400]
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "决策线读取失败（fail-open 省略）", exc_info=True
        )
        return ""


def _archive_key_facts(messages: list[Message], max_facts: int = 8) -> str:
    """RULE-AI-00 增强: 压缩注入"确定性关键事实清单"（规则提取零 LLM）.

    对被压缩消息逐条用 extract_key_info 提取含动作/结果信号的行，
    汇总去重后注入——AI 快速感知旧内容要点，再决定是否主动检索原文。
    不调 LLM（程序只提供客观要点，不替 AI 理解）。
    """
    from llm_loop.memory.archive import extract_key_info

    facts: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if not m.content:
            continue
        try:
            f, _p, _s = extract_key_info(m.content, max_facts=3)
        except Exception:
            continue
        for item in f:
            item = item.strip()
            if item and len(item) >= 4 and item not in seen:
                seen.add(item)
                facts.append(item)
            if len(facts) >= max_facts:
                break
        if len(facts) >= max_facts:
            break
    # EVO-3b39134f: 动作/结果 + 推理结论（决策+理由）并列注入。
    # 推理结论独立于动作/结果——归档消息若只有决策理由（无动作结果信号词），
    # facts 为空也应注入推理段（否则推理结论丢失，OpenAI 实验痛点复现）。
    reasoning = _extract_reasoning_facts(messages, max_facts=6)
    if not facts and not reasoning:
        return ""
    parts: list[str] = []
    if facts:
        parts.append(
            "[压缩关键事实] 被压缩旧消息中的关键动作/结果（规则提取，非语义总结；细节以原文为准）：\n- "
            + "\n- ".join(facts)
        )
    if reasoning:
        parts.append(
            "[压缩推理结论] 关键决策与理由（规则提取，供追溯决策动机、避免重复推理；"
            "细节以原文为准）：\n- " + "\n- ".join(reasoning)
        )
    return "\n".join(parts)

def _archive_index_dir(messages: list[Message]) -> str:
    """生成压缩档案索引目录（数行，供 AI 主动检索；原文已另存至档案）."""
    from collections import Counter

    roles = Counter(m.role for m in messages if m.content)
    # DSH 借鉴（2026-08-18 拷问产出）: 归档目录【去动态计数】——N/角色/工具计数每轮变
    # → 前缀持续漂移。改为固定文本（字节稳定——压缩断点后前缀稳定）；检索词由 search_archive
    # 自行索引（AI 需要时主动检索——RULE-AI-00）。
    from collections import Counter as _Counter

    roles = _Counter(m.role for m in messages if m.content)
    tools = _Counter(m.tool_name for m in messages if m.tool_name)
    n = len(messages)
    chars = sum(len(m.content) for m in messages)
    lines = [
        f"[压缩档案目录] 本次归档 {n} 条消息（约 {chars} 字符），原文已完整另存，"
        "可用 search_archive 按关键词检索："
    ]
    if roles:
        lines.append("- 消息构成: " + ", ".join(f"{r}×{c}" for r, c in roles.most_common()))
    if tools:
        lines.append("- 工具结果: " + ", ".join(f"{t}×{c}" for t, c in tools.most_common(6)))
    words = _top_keywords(messages)
    if words:
        lines.append("- 建议检索词: " + ", ".join(words))
    return "\n".join(lines)




def _adaptive_tool_trim_age(total_chars: int, max_chars: int) -> int:
    """R3: 按上下文占用率自适应 tool_trim_age（AI 无感零配置）.

    - < 40% → 20（保守，保护最近上下文完整）
    - 40-70% → 10（中等）
    - > 70% → 5（激进，更早降级旧 tool 结果）
    """
    if max_chars <= 0:
        return 20
    ratio = total_chars / max_chars
    if ratio < 0.4:
        return 20
    if ratio < 0.7:
        return 10
    return 5


def _prune_oversized_tool_result(content: str, limit: int = 200_000) -> str:
    """DSH 借鉴（2026-08-18 拷问产出）: 超长工具结果【中间剪枝标记】（保留头尾）.

    与归档不同——不触发归档目录变化（前缀稳定）；保留头尾（AI 可见关键信息）。
    仅提交视图剪枝（不动原消息）。超过 limit 的单条 tool 结果在此截断。
    """
    if content is None or len(content) <= limit:
        return content
    head = content[: limit // 2]
    tail = content[-limit // 2 :]
    return (
        head
        + f"\n\n[... 工具结果中间已剪枝（{len(content) - limit:,} 字符）——原文可 search_archive 检索 ...]\n\n"
        + tail
    )


def _layer_trim(
    messages: list[Message],
    *,
    enabled: bool,
    threshold: int,
    age: int,
    session_id: str,
    archive_sink: ArchiveSink | None,
    require_archive_success: bool = False,
) -> list[Message]:
    """历史分层降级（EVO-20260811-7baa2737）: 旧的长 tool 消息降级为首尾摘要.

    规则: role=tool 且 content 超 threshold 且距最新消息 >= age 条 → 降级。
    原文经 archive_sink 归档（信息零丢失），消息本身保留（role/tool_name/status 不变），
    仅 content 替换为摘要 + 检索指引。返回新消息列表（无副作用，不动原消息）。
    """
    if not enabled:
        return list(messages)
    out: list[Message] = []
    n = len(messages)
    for idx, m in enumerate(messages):
        is_old_tool = (
            m.role == "tool" and m.content and len(m.content) > threshold and (n - 1 - idx) >= age
        )
        if not is_old_tool:
            out.append(m)
            continue
        full = m.content
        archived = False
        if archive_sink is not None and session_id:
            try:
                archive_sink(session_id, m)
                archived = True
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "分层降级原文归档失败（fail-open，标注如实声明）", exc_info=True
                )
                if require_archive_success:
                    raise
        # 审查中危修复: sink 失败时标注如实声明"未能归档"——原实现失败仍写
        # "原文已另存"（信息零丢失承诺失实，AI 检索必空手而归）。
        if archived:
            _hint = (
                f'查看完整原文请直接调用 search_archive(tool_name="{m.tool_name}")'
                "（可再加 query= 关键词精确定位；一次取回，勿换命令重复执行同一工具）"
                if m.tool_name
                else "可用 search_archive(query=<关键词>) 检索找回"
            )
            archived_note = "原文已另存压缩档案"
        else:
            _hint = ""
            archived_note = "原文归档失败（未另存，仅保留以下摘要）"
        # 摘要优先（EVO-20260815）: 折叠时先提取关键事实+关键路径/URL（复用 extract_key_info，
        # 规则提取零 LLM），避免机械首尾截断把中间关键信息丢给 AI 迫使二次检索浪费 token；
        # 提取不到任何内容（无路径/URL/动作信号词）时回退首尾截断兜底（背景+结论）。
        digest = ""
        try:
            from llm_loop.memory.archive import extract_key_info

            facts, paths, _s = extract_key_info(full, max_facts=5)
            parts: list[str] = []
            if facts:
                # 清洗: facts 可能保留原文行前缀（"- "等），避免 join 后出现 "- - xxx" 重复噪音
                cleaned = [f.strip().lstrip("-").strip() for f in facts if f.strip()]
                cleaned = [f for f in cleaned if f]
                if cleaned:
                    parts.append(
                        "关键事实（规则提取，非语义总结；细节以原文为准）：\n- "
                        + "\n- ".join(cleaned)
                    )
            if paths:
                parts.append("关键路径/URL：\n- " + "\n- ".join(paths[:8]))
            digest = "\n\n".join(parts)
        except Exception:
            digest = ""
        if not digest:
            digest = f"── 首部 ──\n{full[:400]}\n── 尾部 ──\n{full[-400:]}"
        out.append(
            Message(
                role=m.role,
                content=(
                    f"[工具输出已分层] 共 {len(full)} 字符（触发阈值: {threshold} 字符），{archived_note}"
                    + (f"（{_hint}）：\n" if _hint else "：\n")
                    + f"{digest}"
                ),
                source=m.source,
                tool_call_id=m.tool_call_id,
                status=m.status,
                tool_name=m.tool_name,
                error_detail=m.error_detail,
                tool_calls=m.tool_calls,
                reasoning_content=m.reasoning_content,
                metadata=m.metadata,
            )
        )
    return out



# archive sink: (session_id, message) -> None（由调用方装配 ArchiveStore）
ArchiveSink = Callable[[str, Message], None]


def _apply_reasoning_tail(
    messages: list[Message], reasoning_tail: int
) -> list[Message]:
    """M66 思考链瘦身: 历史中省略 assistant 思考链（reasoning_content）.

    更早轮次的思考链在**提交给 LLM 时**省略（内容/工具调用完整保留），
    体积显著减小且不影响事实完整性；不修改原消息（仅提交视图瘦身）。

    - reasoning_tail <= 0 → 保留全部（向后兼容，零回归）
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
    layer_tool_trim: bool = False,  # EVO-20260811-7baa2737: 历史分层降级（默认关=零回归，loop 装配时按 settings 启用）
    tool_trim_threshold: int = 8000,  # tool 消息 content 超此长度才降级（默认 8000，EVO-20260815 调大减少折叠触发）
    tool_trim_age: int = 0,  # R3: 0=自适应（按占用率自动调）；>0=固定值禁用自适应
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
    _append_summary_enabled: bool = False,  # 2026-08-21 追加式压缩: 归档后追加确定性摘要
    # （默认关=零回归）。启用后归档消息生成固定格式摘要追加提交尾部——任务语义连贯
    # + 前缀稳定（同归档内容→同摘要字节→缓存命中）。
    progressive_fold: int = 0,  # EVO-20260824-54d46549（billion-context 拷问产出）: 渐进折叠 K 值。
    # >0 时压缩改为"每次最多归档最老 K 个配对组"（K 小, 默认建议 3-5），不一次裁到预算×0.6；
    # 0=一次性大裁（现有行为, 零回归）。诚实定位（字节级前缀缓存下"前缀保持"不存在——
    # billion README 宣传已被推翻）: 渐进价值是命中率曲线平滑 + cache_guard 不 BLOCK
    # + 智力无断崖（每次只丢几组, AI 可逐步适应/检索），而非省 token（单次 miss 范围不变）。
    # 折叠后注入折叠标注（AI 有感知, 减少"刚引用的内容已被折掉"的落空）。
    freeze_compression: bool = False,  # P0 压缩风暴熔断（2026-08-25）: 冻结期禁止
    # 一切程序压缩/归档/分层降级（前缀字节稳定），且锚点不前移（anchor_out 不填充）。
    # 仅用于熔断冻结轮——超预算时由 engine 前置 context_pressure 管控，不在此提交超限载荷。
    cache_archive_provider: str = "",  # provider级提交视图压缩标记；非空时中段只折一次
    cache_compacted_out: list[Message] | None = None,  # 本轮新写标记的原消息，供事件链同步
    compact_view_stats: list[dict] | None = None,  # EVO-20260825 任务6: 压缩后视图体积验证
    # 输出容器——大裁/折叠发生后填充 [{pre_chars, post_chars, drop_pct, archived_count}]，
    # 供调用方（build.py）写 breaker 审计事件 view_not_shrinking_after_compact（drop<5% 时）。
    degrade_out: list[dict] | None = None,  # EVO-20260825 任务7（§5.7）: 渐进折叠降级输出容器
    # ——progressive_fold>0 但 cache_archive_provider 缺失时填充
    # [{kind: "degraded", reason, head_keep_chars}]，供调用方写 metadata.cache_health。
    require_archive_success: bool = False,  # ERC enforce: hidden bytes must be durable before shrink
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
    if compacted_out is not None:
        compacted_out[:] = [False]
    if cache_compacted_out is not None:
        cache_compacted_out.clear()
    if degrade_out is not None:
        degrade_out.clear()
    # 直接调用者若没有 provider 级折叠标记，仍保持旧防御：fold+head_keep 会重复
    # 归档同一中段。LoopEngine 会传 cache_archive_provider，因此可安全保留固定头部。
    if progressive_fold > 0 and not cache_archive_provider:
        # 任务7（§5.7）: archive_provider 缺失——无法写入 provider 级 cache_compacted_for
        # 标记，"固定头部 + 渐进折叠"会重复归档同一中段。降级：强制关闭渐进折叠
        # （回一次性大裁），head_keep_chars 恢复原值（不得因降级而错误置 0）；
        # 原值 ≤0 时用 DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE（env 可配，默认 2000）。
        import logging

        _deg_log = logging.getLogger(__name__)
        _deg_log.warning(
            "渐进折叠降级: progressive_fold=%d 要求 cache_archive_provider（当前缺省）"
            "——强制关闭渐进折叠，head_keep_chars 恢复原值 %d（session=%s）",
            progressive_fold,
            head_keep_chars,
            session_id,
        )
        if head_keep_chars <= 0:
            head_keep_chars = _DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE
            _deg_log.error(
                "渐进折叠降级后 head_keep_chars 仍 ≤0，使用默认 %d（session=%s）",
                _DEFAULT_HEAD_KEEP_CHARS_ON_DEGRADE,
                session_id,
            )
        progressive_fold = 0
        if degrade_out is not None:
            degrade_out[:] = [
                {
                    "kind": "degraded",
                    "reason": "progressive_fold 要求 cache_archive_provider（缺省）",
                    "head_keep_chars": head_keep_chars,
                }
            ]
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

    total_chars = sum(_wire_size(m) for m in session_messages)
    # P1-10: 窗口锚定——起点固定（锚点前的消息已归档, 不再参与构建/重复归档）
    if history_anchor > 0 and history_anchor < len(session_messages):
        session_messages = session_messages[history_anchor:]
        if cache_archive_provider:
            session_messages = [
                m
                for m in session_messages
                if not is_cache_compacted_for(m, cache_archive_provider)
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
        total_chars = sum(_wire_size(m) for m in session_messages)
    elif cache_archive_provider:
        session_messages = [
            m
            for m in session_messages
            if not is_cache_compacted_for(m, cache_archive_provider)
        ]
        total_chars = sum(_wire_size(m) for m in session_messages)
    # R3: tool_trim_age=0 时按占用率自适应（AI 无感零配置）
    if tool_trim_age <= 0:
        tool_trim_age = _adaptive_tool_trim_age(total_chars, max_chars)
    # EVO-20260817: 主动压缩阈值（预算×compact_ratio; 1.0=现行为超限才压,
    # <1.0 预算附近提前整理——用户决策: 长任务大几率撞顶, 提前平滑压缩优于被动撞顶）
    compact_limit = max(1, int(max_chars * compact_ratio))
    # P0 压缩风暴熔断冻结: 冻结期不走任何归档/压缩/分层降级路径（提交前缀字节稳定），
    # 且锚点不前移（正常路径不填充 anchor_out）。超限载荷由 engine 前置 context_pressure
    # 管控，不在此硬提交。
    if freeze_compression:
        compact_limit = max(1, total_chars)  # 恒走正常路径（只序列化，不改写）
        layer_tool_trim = False  # 分层降级改写中段 → 冻结期一并禁用
    # P1-10: 锚定模式超预算 → 依次: ①剔除注入消息（推送式 system 不进提交, 剔除对提交
    # 零影响且不产生归档/extras——提交前缀完全稳定）; ②分层降级中段旧 tool 消息（不移动锚点）;
    # 仍超才走归档路径（锚点前移, 前缀断一次后重新锚定）
    if history_anchor > 0 and total_chars > compact_limit:
        if skip_injected_system:
            filtered = [m for m in session_messages if not _is_injected_system(m)]
            if len(filtered) != len(session_messages):
                session_messages = filtered
                total_chars = sum(_wire_size(m) for m in session_messages)
        if total_chars > compact_limit and layer_tool_trim:
            session_messages = _layer_trim(
                session_messages,
                enabled=True,
                threshold=tool_trim_threshold,
                age=tool_trim_age,
                session_id=session_id,
                archive_sink=archive_sink,
                require_archive_success=require_archive_success,
            )
            total_chars = sum(_wire_size(m) for m in session_messages)
    if total_chars <= compact_limit:
        for m in _apply_reasoning_tail(
            _layer_trim(
                session_messages,
                enabled=layer_tool_trim,
                threshold=tool_trim_threshold,
                age=tool_trim_age,
                session_id=session_id,
                archive_sink=archive_sink,
                require_archive_success=require_archive_success,
            ),
            reasoning_tail,
        ):
            if skip_injected_system and _is_injected_system(m):
                continue  # P1-7: 推送式注入仅落会话, 不进提交（system 前缀稳定）
            # EVO-20260817-cef296f8 L1b: 已消费的耗尽注入 system（[轮次决策请求]/
            # [已达轮数上限]）跳过——run 内 AI 决策可见，run 后消费，下个 run 不进请求
            # system 区 → 前缀不因耗尽注入持续分叉（缓存 MISS 收敛）
            if skip_injected_system and m.role == "system" and (m.metadata or {}).get("consumed"):
                continue
            _d = m.to_llm_dict()
            if _d.get("role") == "tool" and _d.get("content"):
                _d["content"] = _prune_oversized_tool_result(_d["content"])
            _append_or_merge(_d, dynamic=_is_dynamic_inject(m))
        return _repair_tool_call_pairing(out)

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

    kept_groups: list[list[Message]] = []
    archived: list[Message] = []
    # EVO-20260816-380f1c2e（缓存友好压缩）: 归档目标从"裁到预算上限"改为"裁到预算×0.6 留缓冲"。
    # 前缀缓存机制: 追加消息不破坏命中（实证 97%+），但修改已提交序列（压缩）必断点。
    # 裁到 100% 上限 → 下一轮必再超 → 每轮压缩 → 前缀每轮变化 → 永久断点（实测 1% 命中率）。
    # 裁到 60% → 压缩后留 40% 增长空间 → 稳定期从"几轮"延长到"几十轮"（该时段纯追加、高命中）。
    archive_budget = int(max_chars * _COMPRESS_TARGET_RATIO)
    # EVO-20260817-9d3e1f2c（缓存友好压缩 v2）: 保留锚点头部（提交前缀命中）+ 最近尾部（语义），
    # 只归档中段——压缩不再破坏前缀缓存。实证: 锚点前移式压缩后首轮命中 6.8%→次轮起 96%
    # （全量失效后重新锚定）; 保留头部后压缩轮即命中 system+头部（~70%+），次轮 99%，无断崖。
    # 头部保留代价: 每轮多占预算（命中价 ~1/10），换来压缩轮无全量失效; head_keep_chars=0 关闭。
    head_groups: list[list[Message]] = []
    head_chars = 0  # 兜底初始化: head_keep_chars=0 时无头部保留, 渐进折叠分支引用不炸（2026-08-24 镜像实证 UnboundLocalError）
    if head_keep_chars > 0:
        acc = 0
        for g in atomic_groups:  # 从最旧端累积头部保留组（前缀核心）
            gl = sum(_wire_size(mm) for mm in g)
            if acc + gl > head_keep_chars:
                break
            head_groups.append(g)
            acc += gl
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
        head_chars = acc
        while head_groups and head_chars > _head_cap:
            g = head_groups.pop()  # 收缩时去掉最新头部组（靠近中段，前缀核心不变）
            head_chars -= sum(_wire_size(mm) for mm in g)
    head_count = len(head_groups)
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
    # EVO-20260824-54d46549 渐进折叠: 每次最多归档最老 K 个配对组（K 小, 平滑曲线）——
    # 常规超限只折 K 组即停（guard 不 BLOCK + 智力无断崖）; 若折满 K 组后提交仍
    # >预算×0.95（guard 规则 F BLOCK 阈值）→ 突破 K 上限继续归档（保命兜底）。
    # P0 修复（2026-08-25 实测）: fold 必须【从最老端连续折】——原实现混用"从最新
    # 保留预算"逻辑，预算边界拆散消息对 → 归档区/保留区交错 → 锚点无法推进到
    # 归档边界 → 同一批消息每轮重复归档（archive_ref ×N）→ 提交永不缩小 →
    # guard 规则 F 永久 BLOCK。fold 语义 = 最老 K 组连续折 + 锚点同步前移。
    if progressive_fold > 0:
        kept_groups = list(atomic_groups[head_count:])
        _fold_left = progressive_fold
        _fold_count = 0
        while kept_groups:
            _kept_chars = sum(_wire_size(mm) for g in kept_groups for mm in g)
            _total_now = len(system_prompt) + head_chars + _kept_chars
            if cache_archive_provider:
                # provider中段压缩已有稳定head + 持久化隐藏标记，不再需要靠K小步保护
                # 前缀。一次压到目标水位，换取更长纯追加区间，避免90-95%附近每轮压缩。
                if _total_now <= archive_budget:
                    break
            else:
                if _fold_left <= 0:
                    # 兼容旧渐进语义: 折满K后≤95%即可停；否则突破K继续折（保命）
                    if _total_now <= int(max_chars * 0.95):
                        break
                elif _total_now <= archive_budget:
                    break
            g = kept_groups.pop(0)  # 最老组（连续折——归档区=视图头部连续段）
            archived.extend(g)
            _fold_count += 1
            if _fold_left > 0:
                _fold_left -= 1
    else:
        _fold_cap = 0
        _fold_count = 0
        for group in reversed(atomic_groups[head_count:]):
            group_len = sum(_wire_size(mm) for mm in group)
            if _fold_cap > 0 and _fold_count >= _fold_cap:
                # 已达渐进折叠上限: 评估保留后是否 ≤95% 预算——是则保留（平滑停折）;
                # 否则突破上限继续归档（保命, 防 guard 规则 F BLOCK / 提交超限 400）。
                _cur_kept = head_chars + sum(_wire_size(mm) for g in kept_groups for mm in g)
                if len(system_prompt) + _cur_kept + group_len <= int(max_chars * 0.95):
                    kept_groups.insert(0, group)
                    archive_budget -= group_len
                    continue
                # 超限兜底: 落入下方归档分支（不因 K 上限而拒绝归档）
            if archive_budget - group_len < 0 and kept_groups:
                archived.extend(group)  # 整组归档（配对原子性：不拆散）
                if _fold_cap > 0:
                    _fold_count += 1
                continue
            if group_len > trim_budget and not kept_groups:
                # 最新组单条/整组超限: 另存全文 + 精简注入（组内字段保留，仅 content 截断）
                archived.extend(group)
                trimmed_group: list[Message] = []
                for mm in group:
                    trimmed = (
                        mm.content[: max(trim_budget - 100, 100)]
                        + "\n…[本消息已压缩，完整内容已另存，可用 search_archive 检索]…"
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
    if head_keep_chars > 0 and head_groups and kept_groups:
        _kept_total = head_chars + sum(_wire_size(mm) for g in kept_groups for mm in g)
        if len(system_prompt) + _kept_total > int(max_chars * 0.95):
            _downgraded_head = True
            for g in head_groups:
                archived.extend(g)
            head_groups = []
            head_count = 0
            head_chars = 0
            # head 归档后仍超（system 巨大场景）→ 继续从最老端连续归档，保护最新语义尾部。
            while kept_groups:
                _cur = sum(_wire_size(mm) for g in kept_groups for mm in g)
                if len(system_prompt) + _cur <= int(max_chars * 0.95):
                    break
                archived.extend(kept_groups.pop(0))

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
            if _mark_cache_compacted_for(m, cache_archive_provider) and cache_compacted_out is not None:
                cache_compacted_out.append(m)

    # 2026-08-21 (追加式压缩, APPEND_COMPRESSION=1 启用): 归档后追加确定性摘要——
    # 被归档的旧历史用"固定格式摘要"追加到提交尾部（转 user 消息），AI 保留任务语义
    # 连贯（知道做过什么），同时摘要字节确定性（同归档内容→同摘要）→ 前缀稳定缓存命中。
    # 与 slim-first（归档即删, 只能 search_archive 检索）不同: 追加摘要保持上下文连贯。
    #
    # 重要: 此处只能【生成】摘要，不能立刻 append 到 out。out 当前仅含 system；真正的
    # fixed-head/kept history 尚在下方序列化。若这里先 append，会把压缩轮序列变成
    # `system -> archive-summary -> fixed-head...`，使服务端缓存恰好在 system 后断裂；
    # 线上 DeepSeek 实测表现就是压缩后 tokens_hit 固定回落到 8,960。摘要必须等
    # kept_flat 写完后再追加，才能保持 `system -> fixed-head` 的共同字节前缀。
    _archive_summary_dict: dict | None = None
    if (
        _append_summary_enabled
        and archived
        and not _downgraded_head  # 降级 head 场景（已放弃前缀稳定）不追加（语义回归现状）
    ):
        try:
            import logging

            _total_archived = sum(_wire_size(mm) for mm in archived)
            _summary_text = " | ".join(
                (mm.content or "")[:60].replace("\n", " ")
                for mm in archived[:3]
                if mm.content
            )[:400]
            _summary_msg = (
                f"[上下文归档摘要] 已归档 {len(archived)} 条消息（约 {_total_archived} 字符）。"
                f"归档内容概要: {_summary_text}"
                f"{'…' if len(archived) > 3 else ''}"
                f"[归档可检索: search_archive]"
            )
            _archive_summary_dict = {
                "role": "user",
                "content": _summary_msg,
                "metadata": {"archived_summary": True, "archived_count": len(archived)},
            }
        except Exception:  # noqa: BLE001 — 摘要追加失败 fail-open
            import logging

            logging.getLogger(__name__).debug("归档摘要追加失败（fail-open）")

    # EVO-20260818 修复基线 bug（仿真测试暴露）: kept_flat 原实现从不包含 head_groups——
    # 头部消息既不在提交也不在归档（静默丢失）→ "缓存友好压缩保留锚点头部"从未真正生效，
    # 压缩轮命中率仅 system 占比（spec §5.3.1-3b ≥70% 不可达）。head 组并入提交最前。
    kept_flat = [m for g in head_groups for m in g] + [m for g in kept_groups for m in g]
    kept_flat = _apply_reasoning_tail(
        _layer_trim(
            kept_flat,
            enabled=layer_tool_trim,
            threshold=tool_trim_threshold,
            age=tool_trim_age,
            session_id=session_id,
            archive_sink=archive_sink,
        ),
        reasoning_tail,
    )
    # P1-10: 超长归档后锚点推进 = 旧锚点 + 窗口内被丢弃消息数
    # （kept_flat 消息数不变（_layer_trim/思考链瘦身不删消息）, 差值即整组丢弃数;
    # "最新组超限精简注入"分支的消息仍在 kept → 不计入推进）
    # EVO-20260817-9d3e1f2c: 缓存友好压缩——头部保留（head_count>0）时锚点不动
    # （提交前缀稳定命中，只归档中段）；仅头部也被归档（head_count=0）才前移。
    if anchor_out is not None:
        if head_count > 0:
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
            _append_or_merge(m.to_llm_dict(), dynamic=_is_dynamic_inject(m))
        else:
            _d = m.to_llm_dict()
            if _d.get("role") == "tool" and _d.get("content"):
                _d["content"] = _prune_oversized_tool_result(_d["content"])
            out.append(_d)
    # APPEND_COMPRESSION 的摘要必须位于 kept history【之后】。这既符合“追加式”语义，
    # 也保证压缩前/后的共同前缀至少延伸到 fixed-head 末端；后续动态 extras 同样只在尾部。
    # P1 压缩帧聚合（err1210 9.1 方案A / 8.4 Verdict=STRUCTURE_TRIGGER）: 归档摘要与
    # extras 不再逐条独立 append——统一合并为单条动态 system（各帧自带 [xxx] 标题、
    # 内容逐字保留），提交视图转 user 后尾部连续 user 条数不随压缩帧数线性增长
    # （merge-tail-user 9→1 变体生产验证恢复 200；16:01 聚合重试成功同源）。
    _compact_frames: list[Message] = []
    if _archive_summary_dict is not None:
        _compact_frames.append(
            Message(
                role="system",
                content=str(_archive_summary_dict.get("content") or ""),
                source=MessageSource.SYSTEM,
                # P1 聚合适配: archived_summary 标记透传（测试/探测方按标记定位归档
                # 摘要——test_append_summary_deterministic / cache_round_sim 依赖）
                # pyright 修复: Message.metadata 类型为 dict（非 dict|None），空标记用 {}
                metadata={"archived_summary": True}
                if (_archive_summary_dict.get("metadata") or {}).get("archived_summary")
                else {},
            )
        )
    if archived:
        # EVO-9794797e: 主动压缩——对被丢弃的旧消息做"另存 + 可见标注"
        # （原文已完整另存至压缩档案保信息零丢失，fail-open）
        # AI 优先（RULE-AI-00）: 压缩路径不自动调 LLM 摘要（程序不知道哪些信息重要、
        # 自动摘要可能误导 + 增计费）；LLM 语义摘要由 AI 主动触发（search_archive with_summary=true）。
        # EVO-20260811-1e68f400: 附加压缩档案目录（主动检索意识，fail-open）
        extras: list[Message] = []

        # 能力 B 决策线（injection_hygiene 5.2）→ Cognitive Runtime tasks 2.4 升级演进:
        # semantic/auto: 压缩黄金窗口持久化语义状态（决策指针两行，_persist_semantic_state），
        #   build 每轮从状态文件投影为决策包 HOT 首行（尾部聚合条内）；不再注入独立
        #   决策线帧（代码演进不并存，spec 5.1.1-3b）。
        # anchor（过渡回退态，design 2.1.3.4 冻结点④）: 保留旧决策线帧（零回归）。
        # 两套路径同轮互斥（spec 4.2-3 单管线）。
        try:
            if _cog_anchor_mode() == "anchor":
                _dl = _decision_line_frame(session_id)
                if _dl:
                    extras.append(
                        Message(role="system", content=_dl, source=MessageSource.SYSTEM)
                    )
            else:
                _persist_semantic_state(session_id)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "决策线注入失败（fail-open）", exc_info=True
            )

        # RULE-AI-00 增强: 确定性关键事实清单（规则提取零 LLM，AI 快速感知旧内容要点）
        try:
            key_facts = _archive_key_facts(archived)
            if key_facts:
                extras.append(
                    Message(role="system", content=key_facts, source=MessageSource.SYSTEM)
                )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "压缩关键事实提取失败（fail-open）", exc_info=True
            )

        # 档案目录（保证"有什么可找"可见）
        try:
            idx_dir = _archive_index_dir(archived)
            if idx_dir:
                extras.append(
                    Message(role="system", content=idx_dir, source=MessageSource.SYSTEM)
                )
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "压缩档案目录生成失败（fail-open）", exc_info=True
            )

        from llm_loop.feedback.honesty import compression_message

        extras.append(
            compression_message(len(archived), sum(len(a.content) for a in archived))
        )
        # EVO-20260824-54d46549 渐进折叠知情标注: 渐进模式（progressive_fold>0）下折叠发生 →
        # 明确告知 AI"本轮只折了最老 K 组, 其余保留, 可检索"——减少"刚引用的内容已被
        # 折掉"的推理落空; 固定文本含 K 值（折叠组数即 _fold_count, 便于归因）。
        if progressive_fold > 0 and _fold_count > 0:
            _fold_note = (
                f"[中段折叠] 本轮折叠 {_fold_count} 个最老中段配对组并回落到目标水位；"
                "固定头部保持不变，被折叠原文可经 search_archive 检索；"
                if cache_archive_provider
                else f"[渐进折叠] 本轮仅折叠最老 {_fold_count} 个配对组（其余历史保留, "
                "未一次性大裁）——命中率曲线平滑, 被折叠原文可经 search_archive 检索；"
            )
            extras.append(
                Message(
                    role="system",
                    content=_fold_note + "若需引用已折叠内容, 先检索再作答。",
                    source=MessageSource.SYSTEM,
                )
            )
        # EVO-20260818（spec §5.5.1-7）: 压缩余量不足降级知情标注（固定文本，便于检索归因）
        if _downgraded_head:
            extras.append(
                Message(
                    role="system",
                    content=(
                        "[缓存降级] 压缩余量不足已降级（锚点前移）——头部保留被放弃，"
                        "本轮起前缀重建；被归档原文（含头部）均可经 search_archive 检索"
                    ),
                    source=MessageSource.SYSTEM,
                )
            )
        # P1-QWEN-SYS-SINGLE: extras（压缩关键事实/档案目录/压缩标注，均为 system）
        # 必须并入开头唯一 system —— qwen 系模板(9B/27B) 只允许 1 条 system 消息，
        # 多条 system（即便都在开头）也会触发 "System message must be at the beginning"。
        # 原实现 out.insert(1+i) 绕过 _append_or_merge → 产生多条独立 system → 400。
        # P1 压缩帧聚合（err1210 9.1 方案A）: extras 并入 _compact_frames → 合并单条
        # 动态 system append。_dynamic 语义保留（每轮归档内容变化不进 system 主体 →
        # system 主体字节稳定 → 前缀缓存命中；qwen 单 system 模板兼容）；
        # 唯一变化 = 逐条 append 改单条合并（各帧 [xxx] 标题天然分段、内容逐字保留），
        # 提交视图尾部连续 user 条数从 1+N 降为恒 1（1210 结构性消除）。
        _compact_frames.extend(extras)
        if _compact_frames:
            _merged = Message(
                role="system",
                content="\n\n".join(str(f.content or "") for f in _compact_frames),
                source=MessageSource.SYSTEM,
            )
            _merged.metadata["_dynamic"] = True
            # P1 聚合适配: archived_summary 标记透传到合并条（探测方定位归档摘要依赖）
            if any(
                (f.metadata or {}).get("archived_summary") for f in _compact_frames
            ):
                _merged.metadata["archived_summary"] = True
            _merged_d = _merged.to_llm_dict()
            if _merged.metadata:
                # to_llm_dict 只输出 {role, content}——metadata 显式补进 dict
                # （探测方按 m["metadata"]["archived_summary"] 定位归档摘要）
                _merged_d["metadata"] = dict(_merged.metadata)
            _append_or_merge(
                _merged_d, dynamic=_is_dynamic_inject(_merged)
            )
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
            compact_view_stats.append(
                {
                    "pre_chars": _pre_chars,
                    "post_chars": _post_chars,
                    "drop_pct": round(_drop_pct, 1),
                    "archived_count": len(archived),
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
