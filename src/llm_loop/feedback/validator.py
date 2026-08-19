"""声明-回执校验 DeclarationValidator（design.md §2.1.3.4 机制三 / FR-FBK-01）.

识别 LLM 最终回答中的"完成声明"（如"已写入文件"），对照本轮真实工具回执；
不一致时如实反馈差异（声明 vs 事实），交由 LLM 更正（最多 1 次，不阻断循环）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.core.message import Message, ToolResultStatus

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

# EVO-20260819-2254e3b4（用户批准）: 声明分类强化——否定/将来/条件/疑问/建议/
# 状态描述/程序转述语句一律豁免，仅"完成声明"参与回执比对（SE-20260819-002-f658
# 实证 26 条误报全为此类: "未执行"/"将更新"/"若 resolved"/"执行中"/"程序执行了"等）。
_NEGATION_MARKERS = ["未", "无", "没有", "尚未", "不", "没"]  # 否定（"未执行"→豁免）
# 将来/条件/疑问/建议（"将更新"/"若完成"/"是否执行"/"建议批准转执行"→豁免）
_FUTURE_MARKERS = [
    "将", "若", "如果", "是否", "请", "建议", "待", "稍后", "到时",
    "拟", "打算", "能否", "要不要", "之后会", "后续会",
]
# 状态/过程描述（"当前状态"/"执行中"/"执行过程"→豁免）
_STATE_MARKERS = ["当前状态", "状态为", "执行中", "执行过程", "进行中", "要点", "状态："]
# 程序/系统转述（"程序执行了紧急压缩"→豁免，非 AI 完成声明）
_TRANSCRIPT_MARKERS = ["程序执行", "程序已", "系统已", "系统执行"]
# 英文过去分词 = 天然完成时态（直接视为完成声明）
_EN_COMPLETED_VERBS = (
    r"\b(written|created|deleted|saved|modified|executed|installed|downloaded|updated)\b"
)

# B3 markdown 结构行（代码 fence/表格行/引用块）为引用内容，不进入声明抽取
_MARKDOWN_STRUCT_PREFIXES = ("|", ">")


@dataclass
class DeclarationCheckResult:
    """一次声明-回执校验结果."""

    consistent: bool
    declarations: list[str] = field(default_factory=list)
    discrepancies: list[str] = field(default_factory=list)  # 声明了什么 vs 实际事实
    receipt_summary: list[str] = field(default_factory=list)


class DeclarationValidator:
    """声明-回执校验（FR-FBK-01 / P1 OPT-01 语义匹配）."""

    def __init__(
        self,
        audit_dir: str | Path | None = None,
        *,
        semantic_matcher: Callable[[str, str], float] | None = None,
        semantic_threshold: float = 0.75,
    ) -> None:
        self._audit_dir = Path(audit_dir) if audit_dir else None
        self._semantic_matcher = semantic_matcher  # P1: 轻量语义匹配（默认 None → 纯关键词/路径）
        self._semantic_threshold = semantic_threshold

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
        # 收集成功回执摘要
        receipts: list[str] = []
        for m in tool_messages:
            if m.status == ToolResultStatus.SUCCESS:
                receipts.append(f"{m.tool_name}: {m.content[:120]}")
            elif m.status == ToolResultStatus.BLOCKED:
                receipts.append(f"{m.tool_name}（已阻断）: {m.content[:120]}")

        # 提取完成声明
        declarations = self._extract_declarations(final_answer)

        discrepancies: list[str] = []
        matched_by: list[str] = []
        for decl in declarations:
            matched = self._declaration_matches_receipt(decl, receipts)
            if matched:
                matched_by.append(matched)
            else:
                discrepancies.append(
                    f"声明: {decl} — 但本轮工具回执中未见对应成功记录（回执: {receipts[:3] or '无'}）"
                )

        result = DeclarationCheckResult(
            consistent=not discrepancies,
            declarations=declarations,
            discrepancies=discrepancies,
            receipt_summary=receipts,
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
            # EVO-20260810-50816b30: 能力陈述（"可以调用工具执行命令"）非完成声明，跳过
            if self._is_ability_statement(text):
                continue
            # EVO-20260815-640fc96a B2: 计划陈述（"下一步优先级：①…②…"）未来时态
            # 本质无回执可佐证，跳过；含完成标志（"已执行计划中的命令"）不豁免
            if self._is_plan_statement(text):
                continue
            # EVO-20260819-2254e3b4: 非完成声明（否定/将来/条件/疑问/建议/
            # 状态描述/程序转述/无完成标志）一律豁免，仅"完成声明"参与回执比对
            if self._is_non_completion_statement(text):
                continue
            decls.append(text)
        return decls

    @staticmethod
    def _is_non_completion_statement(text: str) -> bool:
        """EVO-20260819-2254e3b4: 非完成声明过滤（用户批准，SE-20260819-002-f658
        实证 26 条误报归因）——否定/将来/条件/疑问/建议/状态描述/程序转述语句
        一律豁免；完成声明须含完成标志（中文"已/了/成功/完成"或英文过去分词）。

        例: "未执行"→否定豁免; "将更新 status"→将来豁免; "执行中"→状态豁免;
            "程序执行了紧急压缩"→转述豁免; "已更新落盘"→保留校验（含"已"）。
        """
        lower = text.lower()
        if any(m in text for m in _NEGATION_MARKERS):
            return True
        if any(m in text for m in _FUTURE_MARKERS):
            return True
        if any(m in text for m in _STATE_MARKERS):
            return True
        if any(m in text for m in _TRANSCRIPT_MARKERS):
            return True
        # 完成性要求: 中文完成标志 或 英文过去分词，否则视为描述/承诺/过程
        has_cn_completion = any(m in text for m in _COMPLETION_MARKERS)
        has_en_completion = re.search(_EN_COMPLETED_VERBS, lower) is not None
        return not (has_cn_completion or has_en_completion)

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
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "consistent": result.consistent,
            "declarations": result.declarations,
            "discrepancies": result.discrepancies,
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
