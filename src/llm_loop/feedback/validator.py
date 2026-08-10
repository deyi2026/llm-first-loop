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
        for m in re.finditer(
            r"[^。！？.!?\n]{0,40}(" + "|".join(_DECLARE_VERBS) + r")[^。！？.!?\n]{0,40}", answer
        ):
            text = m.group(0).strip()
            if text and text not in decls:
                decls.append(text)
        return decls

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
