"""架构演进建议 EvolutionStore（design.md §5.3 / §6.1.2 / FR-AUTO-EVOLVE）.

- submit_evolution: AI 结构化提交演进建议（建议内容/证据/影响范围/优先级）
- 范围边界判定（EVOLVE-03）: 涉 FR-SAFE-01/C1-C6/数据完整性 → 仅允许建议（标注需人工决策）
- 权限分级（EVOLVE-04）: EVOLVE_LOCAL_EXEC 分级（0=仅建议/1=白名单局部执行/2=全面执行）
- 审阅状态机（EVOLVE-05）: pending_review → accepted/rejected/executed
- 七态状态机（EXEC-07, T56）: pending_review → accepted → executing → executed/rolled_back/failed
  仅建议级下流转与现状一致（pending → accepted → [人工执行] executed），中间态只在自动执行路径生效
  （M17 FR-REVIEW-AI-04: verifying 中间态已收敛移除——生产无 verifying 流转；旧记录 status=verifying 如实保留展示）
- 字段扩展（T56）: actions（execute_request 动作序列）/ eval_id（评估关联）/ 流转时间戳
- 落盘 evolution_suggestions.jsonl + search_records 可检索
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

# 范围边界（不可 AI 执行，仅允许建议）
_BOUNDARY_MARKERS = [
    "safety",
    "安全",
    "灾难",
    "fr-safe",
    "协议",
    "约束 c",
    "constraint c",
    "tool_call_id",
    "数据结构",
    "数据完整性",
    "schema",
    "外部强制",
]

# 状态机（EXEC-07, T56; M17 FR-REVIEW-AI-04: 收敛为生产实际流转态，移除 verifying 残留）
EvolutionStatus = Literal[
    "pending_review",
    "accepted",
    "rejected",
    "executing",
    "executed",
    "rolled_back",
    "failed",
]


@dataclass
class EvolutionSuggestion:
    """演进建议记录（结构化，供人工审阅）."""

    id: str
    ts: str
    content: str  # 建议内容
    evidence: str = ""  # 证据（架构状态/检索结果）
    impact_scope: str = ""  # 影响范围（文件/模块/行为）
    priority: str = "medium"  # high/medium/low
    status: EvolutionStatus = "pending_review"
    requires_human: bool = False  # True=需人工决策（涉边界）
    session_id: str = ""
    # T56 字段扩展（EXEC-02/07 + EVAL-05，旧记录缺省补默认，零破坏）
    # M16 审计（FR-AUDIT-AI-07）: actions 字段保留（version 兼容）但 execute_request 未启用
    # （submit_evolution 为纯建议通道，执行动作由 AI 经修正工具自主完成，恒空列表）
    actions: list[dict] = field(default_factory=list)
    eval_id: str = ""  # 关联评估记录（evidence 引用 eval:<id>）
    # M49（EVO-20260812-dc911d93 双层作用域，借鉴 Prime Agent HarnessScope）:
    # global=持久架构变更，进 pending_review 人工审（默认，保守）；
    # session=本会话级改进，直达 executing 经修正工具执行+evolution_complete 登记闭环。
    # 涉边界内容强制 global（安全优先，AI 指定的 session 被覆盖时如实标注）。
    scope: str = "global"  # global|session
    executed_at: str = ""  # 流转时间戳（EXEC-07 验收"状态流转完整记录"）
    verified_at: str = ""
    rolled_back_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class EvolutionStore:
    """演进建议存储（JSONL，M12 + T56 七态扩展）."""

    def __init__(self, audit_dir: str | Path) -> None:
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "evolution_suggestions.jsonl"

    @staticmethod
    def _touches_boundary(impact_scope: str, content: str) -> bool:
        """范围边界判定（EVOLVE-03）: 涉安全/协议/数据完整性 → 需人工决策."""
        hay = f"{impact_scope} {content}".lower()
        return any(m in hay for m in _BOUNDARY_MARKERS)

    def submit(
        self,
        *,
        content: str,
        evidence: str = "",
        impact_scope: str = "",
        priority: str = "medium",
        session_id: str = "",
        actions: list[dict] | None = None,
        eval_id: str = "",
        scope: str = "global",
    ) -> EvolutionSuggestion:
        """提交演进建议（返回含 id 与状态；涉边界标注 requires_human；T56 透传 actions/eval_id）.

        M49 双层作用域：scope=session 直达 executing（不进人工审阅队列），
        涉边界内容强制回退 global（安全优先）。
        """
        requires_human = self._touches_boundary(impact_scope, content)
        scope_norm = scope if scope in {"global", "session"} else "global"
        if requires_human:
            scope_norm = "global"  # 涉边界强制人工审，AI 指定 session 被覆盖（如实由回执标注）
        suggestion = EvolutionSuggestion(
            id=f"EVO-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
            ts=datetime.now(UTC).isoformat(),
            content=content,
            evidence=evidence,
            impact_scope=impact_scope,
            priority=priority if priority in {"high", "medium", "low"} else "medium",
            status="executing" if scope_norm == "session" else "pending_review",
            requires_human=requires_human,
            session_id=session_id,
            actions=list(actions) if actions else [],
            eval_id=eval_id,
            scope=scope_norm,
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(suggestion.to_dict(), ensure_ascii=False) + "\n")
        return suggestion

    def list(self, status: str | None = None) -> list[dict]:
        """列出建议（可按状态过滤；旧记录缺省字段补默认，T56 版本兼容）."""
        if not self._path.exists():
            return []
        out: list[dict] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry = self._with_defaults(entry)
                if status and entry.get("status") != status:
                    continue
                out.append(entry)
        return out

    @staticmethod
    def _with_defaults(entry: dict) -> dict:
        """旧记录缺省字段补默认（T56 版本兼容，零破坏）."""
        for key, default in (
            ("actions", []),
            ("eval_id", ""),
            ("executed_at", ""),
            ("verified_at", ""),
            ("rolled_back_at", ""),
            ("scope", "global"),  # M49: 旧记录默认 global（保守，维持原人工审语义）
        ):
            if key not in entry:
                entry[key] = default
        return entry

    def review(self, suggestion_id: str, decision: str) -> dict | None:
        """人工审阅（EVOLVE-05）: accepted/rejected（审阅闭环）."""
        if decision not in {"accepted", "rejected"}:
            raise ValueError(f"decision 必须为 accepted/rejected，收到 {decision}")
        return self._transition(suggestion_id, status=decision)

    def transition(
        self,
        suggestion_id: str,
        *,
        status: EvolutionStatus,
        **fields: str,
    ) -> dict | None:
        """通用状态流转（EXEC-07, T56）: 任意合法状态迁移 + 附加字段落盘.

        M16 审计（FR-AUDIT-AI-09）: mark_executed 已移除（无生产调用方，功能与此方法重复），
        本方法为唯一流转实现；manual_complete（evolution_exec.py）走本入口标记 executed。
        """
        return self._transition(suggestion_id, status=status, **fields)

    def _transition(self, suggestion_id: str, *, status: str, **fields: str) -> dict | None:
        """内部流转实现: 仅对已存在的建议生效，不存在的返回 None."""
        if not self._path.exists():
            return None
        lines = self._path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        target: dict | None = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                out.append(line)
                continue
            if entry.get("id") == suggestion_id:
                entry = self._with_defaults(entry)
                entry["status"] = status
                for key, val in fields.items():
                    entry[key] = val
                target = entry
            out.append(json.dumps(entry, ensure_ascii=False))
        if target is not None:
            self._path.write_text("\n".join(out) + "\n", encoding="utf-8")
        return target

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """检索建议（关键词匹配 content/evidence/impact_scope）."""
        if not self._path.exists():
            return []
        q = query.lower()
        hits: list[dict] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                hay = f"{entry.get('content', '')} {entry.get('evidence', '')} {entry.get('impact_scope', '')}".lower()
                if q in hay:
                    hits.append(self._with_defaults(entry))
                if len(hits) >= limit:
                    break
        return hits


def _now() -> str:
    return datetime.now(UTC).isoformat()
