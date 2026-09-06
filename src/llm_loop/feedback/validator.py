"""声明-回执校验 DeclarationValidator（design.md §2.1.3.4 机制三 / FR-FBK-01）.

识别 LLM 最终回答中的"完成声明"（如"已写入文件"），对照本轮真实工具回执；
不一致时如实反馈差异（声明 vs 事实），交由 LLM 更正（最多 1 次，不阻断循环）。
"""

from __future__ import annotations

import json
import re
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import Message, ToolResultStatus
from llm_loop.core.run_context import current_session_id as _current_session_id

# 声明动词表（写入/创建/删除/保存/修改/执行/更新/安装/下载…）
_DECLARE_VERBS = [
    "写入",
    "创建",
    "删除",
    "保存",
    "修改",
    "执行",
    "更新",
    "安装",
    "下载",
    "写到",
    "写入了",
    "已写",
    "已创建",
    "已删除",
    "已保存",
    "已修改",
    "已执行",
    "已更新",
    "已安装",
    "已下载",
    "wrote",
    "created",
    "deleted",
    "saved",
    "modified",
    "executed",
    "installed",
    "downloaded",
    "written",
]

# 每类声明对应的工具回执关键词映射（宾语匹配）
_TOOL_RECEIPT_KEYWORDS = {
    "read_file": ["读取"],
    "write_file": ["写入", "创建", "保存", "written", "created"],
    "execute_command": ["执行", "executed"],
    "web_fetch": ["抓取", "获取", "下载", "fetched"],
}


# EVO-20260810-50816b30: 能力陈述 vs 行为声明语义区分
# 情态/能力标志（表"能力/意愿"，非"已完成"）
_ABILITY_MARKERS = [
    "可以", "能够", "能", "可", "会", "具备", "支持",
    "can ", "could ", "may ", "might ",
]
# 完成标志（表"已完成/已发生"）
_COMPLETION_MARKERS = ["已", "了", "成功", "完成", "did", "has ", "have ", "done"]

# EVO-20260815-640fc96a: B2 计划陈述豁免标记（未来时态/规划句非完成声明）
# 仅当句子不含完成标志时豁免（"已执行计划中的迁移"仍保留校验）
_PLAN_MARKERS = ["下一步", "建议执行", "优先级", "计划", "待办", "接下来", "后续将", "即将"]

# Agency-first: negative action statements are facts about *non-execution*, not completion
# claims that require a success receipt. Keep the matcher local to the matched action verb;
# a mixed sentence containing a separate positive claim (e.g. "未修改，但已执行") must
# still be checked rather than blanket-exempted because it contains "未".
_NEGATION_PREFIXES = ("未", "并未", "没有", "从未", "未曾", "不曾", "不", "无需")

# B3 markdown 结构行（代码 fence/表格行/引用块）为引用内容，不进入声明抽取
_MARKDOWN_STRUCT_PREFIXES = ("|", ">")


@dataclass
class DeclarationCheckResult:
    """一次声明-回执校验结果."""

    consistent: bool
    declarations: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)  # 声明了什么 vs 实际事实
    receipt_summary: list[str] = field(default_factory=list)
    cross_round_hits: list[str] = field(default_factory=list)  # EVO-20260820-409f3f60: 近 N 轮回执命中（跨轮引用）


class DeclarationValidator:
    """声明-回执校验（FR-FBK-01 / P1 OPT-01 语义匹配）."""

    def __init__(
        self,
        audit_dir: str | Path | None = None,
        *,
        semantic_matcher: Callable[[str, str], float] | None = None,
        semantic_threshold: float = 0.75,
        recent_window: int = 3,
    ) -> None:
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._semantic_matcher = semantic_matcher  # P1: 轻量语义匹配（默认 None → 纯关键词/路径）
        self._semantic_threshold = semantic_threshold
        # EVO-20260820-409f3f60: 近 N 轮回执窗口（按会话隔离）——压缩/归档移出内存的
        # 早期轮次成功回执，从历史缓存补证，区分"跨轮引用"与"真实不诚实"。
        self._recent_window = max(1, int(recent_window))
        self._recent_by_session: dict[str, deque[list[str]]] = {}

    def _session_buf(self) -> deque[list[str]]:
        """当前会话的近 N 轮回执缓存（deque maxlen=recent_window）."""
        sid = _current_session_id.get() or ""
        buf = self._recent_by_session.get(sid)
        if buf is None:
            buf = deque(maxlen=self._recent_window)
            self._recent_by_session[sid] = buf
        return buf

    def check(
        self,
        final_answer: str,
        tool_messages: list[Message],
    ) -> DeclarationCheckResult:
        """比对最终回答的完成声明与本轮工具回执.

        Args:
            final_answer: LLM 最终回答文本.
            tool_messages: 本轮全部 tool 消息（含状态）.

        Returns:
            DeclarationCheckResult: consistent=True 一致；否则 discrepancies 含差异说明。
        """
        # 收集成功回执摘要（EVO-20260820-be72efb1: 截断回执标注高亮——声明匹配截断数据时
        # 提醒 LLM 该结论基于未核验摘要，抑制"截断幻觉"声明）
        receipts: list[str] = []
        for m in tool_messages:
            if m.status == ToolResultStatus.SUCCESS:
                _tag = "（⚠️截断: 部分数据未核验）" if "[输出已截断]" in (m.content or "") else ""
                receipts.append(f"{m.tool_name}{_tag}: {m.content[:120]}")
                # 组合工具可携带真实嵌套 SUCCESS 证据；metadata 不进模型 wire，
                # 这里只扩展校验事实面，避免 subagent_result 外层摘要截断导致假阴性。
                for nested in (m.metadata or {}).get("verification_receipts", ()) or ():
                    nested_text = str(nested or "")
                    if nested_text.endswith(":success"):
                        receipts.append(f"nested:{nested_text}")
            elif m.status == ToolResultStatus.BLOCKED:
                receipts.append(f"{m.tool_name}（已阻断）: {m.content[:120]}")

        # 提取完成声明
        declarations = self._extract_declarations(final_answer)

        # EVO-20260820-409f3f60: 近 N 轮历史回执（跨轮引用补证）——压缩/归档可能已把
        # 更早轮次 tool 消息移出会话消息，从本校验器维护的滚动窗口补证。
        buf = self._session_buf()
        history: list[str] = [r for past in buf for r in past]

        discrepancies: list[str] = []
        matched_by: list[str] = []
        cross_round_hits: list[str] = []
        for decl in declarations:
            matched = self._declaration_matches_receipt(decl, receipts)
            if matched:
                matched_by.append(matched)
            else:
                # 跨轮引用判定: 近 N 轮历史回执命中 → 标记跨轮引用（非真实不诚实）
                cross = self._declaration_matches_receipt(decl, history)
                if cross:
                    cross_round_hits.append(
                        f"声明: {decl}（近 {self._recent_window} 轮回执命中: {cross}）"
                    )
                else:
                    # 漂移修复（2026-08-29 会话 68fed5f5 实证）: 回执样本就近取样——
                    # 原 receipts[:3] 取最早回执（本轮首个工具），漂移轮被最早轮的
                    # model_catalog（身份话题）样本直接诱导复读"系统状态"。取最新
                    # 3 条（[-3:]）让提醒贴近当前动作，旧话题文本引用体积同步最小化。
                    discrepancies.append(
                        f"声明: {decl} — 但本轮及近 {self._recent_window} 轮回执中均未见对应成功记录（回执: {receipts[-3:] or '无'}）"
                    )

        # 本轮成功回执滚入近 N 轮窗口（供下轮跨轮引用补证）
        if receipts:
            buf.append(receipts)

        result = DeclarationCheckResult(
            consistent=not discrepancies,
            declarations=declarations,
            discrepancies=discrepancies,
            receipt_summary=receipts,
            cross_round_hits=cross_round_hits,
        )
        self._audit(final_answer, tool_messages, result, matched_by=matched_by)
        return result

    def _extract_declarations(self, answer: str) -> list[str]:
        """扫描回答文本提取完成声明（动词 + 宾语）."""
        decls: list[str] = []
        # EVO-20260815-640fc96a B3: markdown 结构行（fence 内代码/表格行/引用块）
        # 为引用内容而非行为声明，抽取前剥离
        answer = self._strip_markdown_structures(answer)
        for m in re.finditer(
            r"[^。！？.!?\n]{0,40}(" + "|".join(_DECLARE_VERBS) + r")[^。！？.!?\n]{0,40}", answer
        ):
            text = m.group(0).strip()
            if not text or text in decls:
                continue
            # Agency-first: "未执行/没有修改/not executed" describes absence of an
            # action. It must not be turned into a fabricated completion claim that then
            # demands a success receipt. Mixed clauses with a separate positive action
            # remain checkable (see _is_negated_action_statement).
            if self._is_negated_action_statement(text, m.group(1)):
                continue
            # EVO-20260810-50816b30: 能力陈述（"可以调用工具执行命令"）非完成声明，跳过
            if self._is_ability_statement(text):
                continue
            # EVO-20260815-640fc96a B2: 计划陈述（"下一步优先级：①…②…"）未来时态
            # 本质无回执可佐证，跳过；含完成标志（"已执行计划中的命令"）不豁免
            if self._is_plan_statement(text):
                continue
            decls.append(text)
        return decls

    @staticmethod
    def _strip_markdown_structures(answer: str) -> str:
        """剥离 markdown 结构行（EVO-20260815-640fc96a B3）.

        代码 fence 块整体移除；表格行（| 开头）/引用块（> 开头）按行移除——
        引用内容非行为声明（0814 误报实证：代码片段/表格行被判 False）。
        """
        text = re.sub(r"```.*?```", "", answer, flags=re.DOTALL)
        lines = [
            ln for ln in text.splitlines()
            if not ln.lstrip().startswith(_MARKDOWN_STRUCT_PREFIXES)
        ]
        return "\n".join(lines)

    @staticmethod
    def _is_negated_action_statement(text: str, verb: str) -> bool:
        """Return True when the matched action is explicitly negated, with no positive action claim.

        Examples exempted: ``未执行任何修改`` / ``没有创建文件`` / ``not executed``.
        Mixed clauses such as ``未修改配置，但已执行命令`` stay eligible for checking so a
        negative clause cannot mask an independent positive completion claim.
        """
        lower = text.lower()
        action_verbs_zh = [v for v in _DECLARE_VERBS if re.search(r"[\u4e00-\u9fff]", v) and not v.startswith("已")]
        action_alt_zh = "|".join(re.escape(v) for v in action_verbs_zh)
        # The extractor's 40-char prefix is greedy, so m.group(1) can be a noun-like
        # later verb (e.g. it captures "修改" in "未执行任何修改"). Determine negation
        # from the whole extracted clause rather than trusting that one regex group.
        zh_negated = any(
            re.search(re.escape(prefix) + r"\s*(?:任何)?\s*(?:" + action_alt_zh + r")", text)
            for prefix in _NEGATION_PREFIXES
        )
        action_verbs_en = [
            "wrote", "created", "deleted", "saved", "modified", "executed", "installed", "downloaded", "written"
        ]
        en_alt = "|".join(re.escape(v) for v in action_verbs_en)
        en_negated = bool(
            re.search(
                r"\b(?:did\s+not|didn't|have\s+not|haven't|has\s+not|hasn't|not|never)\s+(?:" + en_alt + r")\b",
                lower,
            )
        )
        if not (zh_negated or en_negated):
            return False

        # A separate explicit positive completion in the same extracted clause wins: keep
        # the clause for verification rather than blanket-exempting it due to one negation.
        positive_zh = re.search(
            r"(?:已|已经|成功)\s*(?:" + "|".join(re.escape(v) for v in _DECLARE_VERBS if not v.startswith("已")) + r")",
            text,
        )
        positive_en = re.search(
            r"\b(?:successfully|already)\s+(?:wrote|created|deleted|saved|modified|executed|installed|downloaded)\b",
            lower,
        )
        return not bool(positive_zh or positive_en)

    @staticmethod
    def _is_plan_statement(text: str) -> bool:
        """计划陈述判定（EVO-20260815-640fc96a B2）: 含计划标记且不含完成标志.

        例: "下一步优先级：①修复 ②验证" → 计划（跳过）；
            "已执行计划中的迁移" → 完成声明（保留，有"已"标志）。
        注意: 身份声明（"我是 X"）与比较结论（"与文档一致"）不在动词表内，
        天然不进入抽取——本豁免不影响真阳性捕获。
        """
        has_plan = any(m in text for m in _PLAN_MARKERS)
        if not has_plan:
            return False
        lower = text.lower()
        has_completion = any(m in lower for m in _COMPLETION_MARKERS)
        return not has_completion

    @staticmethod
    def _is_ability_statement(text: str) -> bool:
        """能力陈述判定: 含情态动词（可以/能够/can 等）且不含完成标志（已/了/成功等）.

        例: "可以调用工具执行命令" → 能力（跳过）; "已执行命令" → 完成（保留）。
        英文情态带空格避免误伤（scan/american 等）。
        """
        lower = text.lower()
        has_ability = any(m in lower for m in _ABILITY_MARKERS)
        if not has_ability:
            return False
        has_completion = any(m in lower for m in _COMPLETION_MARKERS)
        return not has_completion

    def _declaration_matches_receipt(self, declaration: str, receipts: list[str]) -> str:
        """声明与回执匹配（返回匹配方式: keyword/semantic/""=不匹配）.

        P0: 路径/文件名包含匹配 + 动词-工具映射（保留兜底）。
        P1 OPT-01: 未命中且 semantic_matcher 可用 → 轻量语义匹配，≥ 阈值判定一致。
        匹配器异常 → 保持关键词判定结果，不伪造语义一致。
        """
        if not receipts:
            return ""
        # 关键词/路径包含匹配（P0 兜底不变）
        path_tokens = re.findall(r"[A-Za-z0-9_\-./\\]{3,}", declaration)
        for tok in path_tokens:
            if "/" in tok or "\\" in tok or "." in tok:
                for r in receipts:
                    if tok in r:
                        return "keyword"
        # 动词-回执关键词匹配（P0: 声明含动词 且 回执含该动词 → 一致）
        for verb in _DECLARE_VERBS:
            if verb in declaration and any(verb in r for r in receipts):
                return "keyword"
        # 结构化工具名匹配：声明出现该工具语义动词，成功回执中存在对应 tool name。
        # `_TOOL_RECEIPT_KEYWORDS` 过去仅定义未消费；这里补上原设计意图，同时
        # 支持 nested:execute_command:success 等组合工具证据。
        lower_decl = declaration.lower()
        for tool_name, keywords in _TOOL_RECEIPT_KEYWORDS.items():
            if not any(str(keyword).lower() in lower_decl for keyword in keywords):
                continue
            if any(receipt == f"nested:{tool_name}:success" for receipt in receipts):
                return "keyword"
        # P1 语义匹配（可选，默认关闭）
        if self._semantic_matcher is not None:
            try:
                for r in receipts:
                    score = self._semantic_matcher(declaration, r)
                    if score >= self._semantic_threshold:
                        return "semantic"
            except Exception:
                return ""  # 匹配器异常 → 保持关键词判定（不伪造）
        return ""

    def _audit(
        self,
        answer: str,
        tool_msgs: list[Message],
        result: DeclarationCheckResult,
        matched_by: list[str] | None = None,
    ) -> None:
        """审计落盘（DFX-MNT-02 / P1 matched_by 可审计）."""
        if self._audit_dir is None:
            return
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        record = {
            "id": f"DC-{now.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:6]}",
            "ts": now.isoformat(),
            "session_id": _current_session_id.get() or "",
            "consistent": result.consistent,
            "declarations": result.declarations,
            "discrepancies": result.discrepancies,
            "cross_round_hits": result.cross_round_hits,  # EVO-20260820-409f3f60: 跨轮引用命中可审计
            "tool_call_ids": list(
                dict.fromkeys(
                    str(m.tool_call_id)
                    for m in tool_msgs
                    if getattr(m, "tool_call_id", None)
                )
            ),
            "receipts": result.receipt_summary,
            "matched_by": matched_by or [],  # P1: keyword/semantic（匹配方式可审计）
            "answer_preview": answer[:200],
        }
        with (self._audit_dir / "declaration_check.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def build_discrepancy_feedback(result: DeclarationCheckResult) -> str:
    """构造不一致时的如实反馈消息（声明 vs 事实 + 建议，AI-first 三件套）."""
    lines = ["[声明-回执校验] 事实: 你的最终回答中存在与工具执行回执不符的完成声明："]
    for d in result.discrepancies:
        lines.append(f"  - {d}")
    lines.append("原因: 以下声明在本轮工具回执中无对应成功记录。")
    lines.append("建议: 请如实更正声明（说明实际完成情况），或重新执行相应工具后再回答。")
    return "\n".join(lines)
