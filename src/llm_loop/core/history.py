"""上下文构造与压缩另存（design.md §2.2.2.3 / T22 另存提取替代截断）.

- 保序提交（FR-MSG-03）
- **T22: 截断不是目的**——上下文超长时，将被丢弃的旧消息先"另存提取重要信息"
  （原文完整另存 + 关键事实/路径索引）到 ArchiveStore，再注入精简内容 +
  `[上下文压缩]` 标注（含"可查 search_archive"指引），信息零丢失。
- 记忆注入（source=memory 前置消息）
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from llm_loop.core.message import Message, MessageSource

# EVO-20260816-380f1c2e: 压缩目标比例（裁到预算×此值，留缓冲降低断点频率）。
# 实证: 前缀缓存下压缩轮必断点；裁到 100% → 每轮压缩 → 永久断点（命中率 ~1%）；
# 裁到 60% → 留 40% 增长空间 → 稳定期纯追加高命中（97%+）。可经环境变量覆盖（缓存纪律: 配置低频改）。
_COMPRESS_TARGET_RATIO = float(os.environ.get("COMPRESS_TARGET_RATIO", "0.6"))


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
    tools = Counter(m.tool_name for m in messages if m.tool_name)
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


def _layer_trim(
    messages: list[Message],
    *,
    enabled: bool,
    threshold: int,
    age: int,
    session_id: str,
    archive_sink: ArchiveSink | None,
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
    """M66 思考链瘦身: 历史中仅保留最近 N 轮 assistant 思考链（reasoning_content）.

    更早轮次的思考链在**提交给 LLM 时**省略（内容/工具调用完整保留），
    体积显著减小且不影响事实完整性；不修改原消息（仅提交视图瘦身）。

    - reasoning_tail <= 0 → 保留全部（向后兼容，零回归）
    - 最近一轮的 reasoning 必须保留（M20 THK-04: 携带 tool_calls 必须回传，
      否则协议 400）——本实现始终保留最近 N 轮，覆盖最近一轮。
    """
    if reasoning_tail <= 0:
        return messages
    from dataclasses import replace

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
    max_chars: int = 1000000,
    *,
    session_id: str = "",
    archive_sink: ArchiveSink | None = None,
    summarizer: Any | None = None,  # 保留签名向后兼容；压缩路径不再自动调 LLM 摘要（RULE-AI-00，LLM 摘要由 AI 经 search_archive(with_summary=true) 主动触发）
    layer_tool_trim: bool = False,  # EVO-20260811-7baa2737: 历史分层降级（默认关=零回归，loop 装配时按 settings 启用）
    tool_trim_threshold: int = 8000,  # tool 消息 content 超此长度才降级（默认 8000，EVO-20260815 调大减少折叠触发）
    tool_trim_age: int = 0,  # R3: 0=自适应（按占用率自动调）；>0=固定值禁用自适应
    reasoning_tail: int = 2,  # M66: 历史中仅保留最近 N 轮 assistant 思考链（0=全部保留）
    skip_injected_system: bool = False,  # P1-7: 跳过推送式 system 注入（metadata.injected_system）
    # —— 仅落会话不进提交, system 前缀保持静态 → 引擎前缀缓存命中; 功能性注入不受影响
    history_anchor: int = 0,  # P1-10: 历史窗口锚点（相对 session_messages 的索引; 0=无锚现有行为）
    # —— 锚定后起点固定（只追加不挤旧, 超预算优先降级中段）, system+历史前缀稳定 → 前缀缓存命中
    anchor_out: list[int] | None = None,  # P1-10: 输出容器——构建后填充新锚点（相对传入列表）;
    # 正常提交（无归档）不填充（锚点保持不变, engine 沿用旧值）; 超长归档后填充推进值
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

    def _append_or_merge(msg_dict: dict) -> None:
        if msg_dict.get("role") == "system" and out and out[0].get("role") == "system":
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

    total_chars = sum(len(m.content) for m in session_messages)
    # P1-10: 窗口锚定——起点固定（锚点前的消息已归档, 不再参与构建/重复归档）
    if history_anchor > 0 and history_anchor < len(session_messages):
        session_messages = session_messages[history_anchor:]
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
        total_chars = sum(len(m.content) for m in session_messages)
    # R3: tool_trim_age=0 时按占用率自适应（AI 无感零配置）
    if tool_trim_age <= 0:
        tool_trim_age = _adaptive_tool_trim_age(total_chars, max_chars)
    # P1-10: 锚定模式超预算 → 依次: ①剔除注入消息（推送式 system 不进提交, 剔除对提交
    # 零影响且不产生归档/extras——提交前缀完全稳定）; ②分层降级中段旧 tool 消息（不移动锚点）;
    # 仍超才走归档路径（锚点前移, 前缀断一次后重新锚定）
    if history_anchor > 0 and total_chars > max_chars:
        if skip_injected_system:
            filtered = [m for m in session_messages if not _is_injected_system(m)]
            if len(filtered) != len(session_messages):
                session_messages = filtered
                total_chars = sum(len(m.content) for m in session_messages)
        if total_chars > max_chars and layer_tool_trim:
            session_messages = _layer_trim(
                session_messages,
                enabled=True,
                threshold=tool_trim_threshold,
                age=tool_trim_age,
                session_id=session_id,
                archive_sink=archive_sink,
            )
            total_chars = sum(len(m.content) for m in session_messages)
    if total_chars <= max_chars:
        for m in _apply_reasoning_tail(
            _layer_trim(
                session_messages,
                enabled=layer_tool_trim,
                threshold=tool_trim_threshold,
                age=tool_trim_age,
                session_id=session_id,
                archive_sink=archive_sink,
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
            _append_or_merge(m.to_llm_dict())
        return _repair_tool_call_pairing(out)

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
    # 最新组单条超限兜底仍按全预算判断（不因留缓冲而更激进截断单条消息;
    # 该分支语义=单条消息就超整个预算的极端场景, 保留语义与留缓冲解耦）。
    trim_budget = max_chars
    for group in reversed(atomic_groups):
        group_len = sum(len(mm.content) for mm in group)
        if archive_budget - group_len < 0 and kept_groups:
            archived.extend(group)  # 整组归档（配对原子性：不拆散）
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

    # 另存被丢弃消息（信息零丢失）
    if archive_sink is not None and session_id and archived:
        for m in archived:
            try:
                archive_sink(session_id, m)
            except Exception:
                import logging

                logging.getLogger(__name__).warning("archive sink 异常（fail-open）", exc_info=True)

    kept_flat = [m for g in kept_groups for m in g]
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
    if anchor_out is not None:
        anchor_out.append(history_anchor + (len(session_messages) - len(kept_flat)))
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
            _append_or_merge(m.to_llm_dict())
        else:
            out.append(m.to_llm_dict())
    if archived:
        # EVO-9794797e: 主动压缩——对被丢弃的旧消息做"另存 + 可见标注"
        # （原文已完整另存至压缩档案保信息零丢失，fail-open）
        # AI 优先（RULE-AI-00）: 压缩路径不自动调 LLM 摘要（程序不知道哪些信息重要、
        # 自动摘要可能误导 + 增计费）；LLM 语义摘要由 AI 主动触发（search_archive with_summary=true）。
        # EVO-20260811-1e68f400: 附加压缩档案目录（主动检索意识，fail-open）
        extras: list[Message] = []

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
        # P1-QWEN-SYS-SINGLE: extras（压缩关键事实/档案目录/压缩标注，均为 system）
        # 必须并入开头唯一 system —— qwen 系模板(9B/27B) 只允许 1 条 system 消息，
        # 多条 system（即便都在开头）也会触发 "System message must be at the beginning"。
        # 原实现 out.insert(1+i) 绕过 _append_or_merge → 产生多条独立 system → 400。
        for em in extras:
            _append_or_merge(em.to_llm_dict())
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
    # 空 id 声明/回执按位置兜底（存量兼容，不丢弃真实回执）
    unanswered = [di for di in range(len(declared)) if di not in answered]
    for di, _rid in zip(unanswered, remaining, strict=False):
        answered.add(di)
    missing = [declared[di] for di in range(len(declared)) if di not in answered]
    return declared, missing, j


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
    out: list[dict] = []
    n = len(messages)
    i = 0
    while i < n:
        m = messages[i]
        out.append(m)
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls"):
            # P1-6: id 精确配对 + 空 id 位置兜底（审计 #16，缺口语义与自检一致）
            _declared, missing, j = _pairing_gap(messages, i)
            # 既有 tool 回执原序追加（占位补在真实回执之后）
            for t in range(i + 1, j):
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
