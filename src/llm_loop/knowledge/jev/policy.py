"""EVO-20261015 (P1a): Jev 外发策略——预算上限、隐私投影与守卫（无传输）。

DESIGN-20261014-jev §8.4/§8.5 的实现锚定：
- 原子题数/HTTP 批数/并发分别限制；上限值已按 DESIGN §11.1 v0.8 预注册冻结。
- 首轮关闭 SDK 自动重试；默认不重试；累计预算不因重试重置。
- 外发只限受控投影：默认不发 Rules、完整会话、凭证、私有 reasoning、跨 scope 源。
- 条目/网页/证据里的指令视为数据；请求不携带任何工具授权字段。

本模块不 import 任何网络库。预算拒绝必须可观测（返回拒绝事实），不静默吞掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: 隐私红线：state/问题层出现即拒绝（§8.5 默认不发清单的机械面）。
FORBIDDEN_STATE_KEYS = frozenset({
    "rules", "rule_text", "rule_content", "reasoning", "reasoning_content",
    "credentials", "api_key", "apikey", "secret", "password", "token",
    "session_messages", "full_history", "transcript", "system_prompt",
})

#: 凭证样式扫描（命中即在投影值层面拒绝，防 allowlist 键名绕过）。
#: 启发式面不追求完备，覆盖主流格式；与递归守卫配合使用。
_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)api[_\-]?key\s*[=:]"),
    re.compile(r"(?i)(password|passwd|secret)\s*[=:]"),
    re.compile(r"(?i)authorization\s*[:]"),
    re.compile(r"(?i)token\s*[=:]\s*[A-Za-z0-9._\-]{8,}"),
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{16,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

#: 请求不得携带的工具授权字段及别名（Jev 不获 LFL 工具/资产写权限，§8.5）。
#: 作用域=请求顶层与 question 层；state 内同名键按 §8.5"state 内容是数据"处理，
#: 其红线（rules/凭证等）由 FORBIDDEN_STATE_KEYS 与凭证扫描承担。
FORBIDDEN_REQUEST_KEYS = frozenset({
    "tools", "tool_choice", "functions", "function_call", "function_calling",
    "tool_definitions", "tool_use", "allowed_tools", "tool_config", "capabilities",
    "commands", "actions", "permissions", "grants", "scopes",
})

#: 守卫递归深度上限：超过即 fail-closed 拒绝（防构造性绕过，非性能考量）。
MAX_PROJECTION_DEPTH = 8

#: 输出 token 保守估计（每题）：mock 阶段无实测依据的试验初值，仅使 output
#: 上限在 runner 路径真实可触发（审查 P3-2 备查项的落实）。
EST_OUTPUT_TOKENS_PER_QUESTION = 256


class ProjectionUnsafe(Exception):  # noqa: N818 - 策略拒绝事实，非通用错误类型命名空间
    """投影越界：携带红线键/凭证样式/工具授权字段。调用方必须放弃本次外发。"""


class BudgetRefused(Exception):  # noqa: N818 - 同上：拒绝即事实载荷
    """预算拒绝：携带 refusal 事实，由 shadow runner 落事件，不静默。"""

    def __init__(self, reason: str, facts: dict[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.facts = dict(facts)


@dataclass(frozen=True)
class OutboundPolicy:
    """外发策略（数值已按 DESIGN §11.1 v0.8 预注册冻结；观察结果后改闸属违规）。"""

    max_requests: int = 1
    max_input_tokens: int = 2000
    max_output_tokens: int = 2000
    max_questions_per_batch: int = 5
    request_deadline_s: float = 2.0  # §11.1 冻结值；仍不承诺总 P95
    retry_enabled: bool = False  # §8.4/§11.1：重试 0，隐式/显式均关
    cost_cap: float = 0.0  # mock 阶段费用上限为 0：任何非零费用都是未授权
    cost_source: str = "unknown"
    #: v0.8 预注册后转 False（DESIGN §11.1）：数值已是冻结闸，不再是试验初值；
    #: 冻结≠校准资格（6 题不构成 §9.2 资格），改闸需新一轮预注册。
    provisional: bool = False

    def to_facts(self) -> dict[str, Any]:
        return {
            "max_requests": self.max_requests,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_questions_per_batch": self.max_questions_per_batch,
            "request_deadline_s": self.request_deadline_s,
            "retry_enabled": self.retry_enabled,
            "cost_cap": self.cost_cap,
            "cost_source": self.cost_source,
            "provisional": self.provisional,
        }


@dataclass
class PolicyGuard:
    """run 内预算闸：requests/题数/token 各自计数，拒绝带事实返回。

    预算不因重试重置（§8.4）；retry_enabled=False 时调用方不得发起第二次物理尝试。
    """

    policy: OutboundPolicy = field(default_factory=OutboundPolicy)
    _requests_used: int = 0
    _questions_used: int = 0
    _input_tokens_used: int = 0
    _output_tokens_used: int = 0

    def acquire(
        self,
        *,
        question_count: int,
        est_input_tokens: int,
        est_output_tokens: int = 0,
    ) -> dict[str, Any]:
        """返回 attempt ticket；超限抛 BudgetRefused（facts 完整可观测）。"""
        p = self.policy
        facts = {
            "question_count": int(question_count),
            "est_input_tokens": int(est_input_tokens),
            "est_output_tokens": int(est_output_tokens),
            "requests_used": self._requests_used,
            "questions_used": self._questions_used,
            "input_tokens_used": self._input_tokens_used,
            "output_tokens_used": self._output_tokens_used,
            "policy": p.to_facts(),
        }
        if int(question_count) < 1:
            raise BudgetRefused("no_questions", facts)
        if int(question_count) > p.max_questions_per_batch:
            raise BudgetRefused("questions_over_batch_cap", facts)
        if self._requests_used >= p.max_requests:
            raise BudgetRefused("requests_over_cap", facts)
        if self._input_tokens_used + int(est_input_tokens) > p.max_input_tokens:
            raise BudgetRefused("input_tokens_over_cap", facts)
        if self._output_tokens_used + int(est_output_tokens) > p.max_output_tokens:
            raise BudgetRefused("output_tokens_over_cap", facts)
        ticket = {
            "attempt_seq": self._requests_used + 1,
            "deadline_s": p.request_deadline_s,
            "retry_enabled": p.retry_enabled,
        }
        self._requests_used += 1
        self._questions_used += int(question_count)
        self._input_tokens_used += int(est_input_tokens)
        self._output_tokens_used += int(est_output_tokens)
        return ticket

    def used(self) -> dict[str, int]:
        return {
            "requests_used": self._requests_used,
            "questions_used": self._questions_used,
            "input_tokens_used": self._input_tokens_used,
            "output_tokens_used": self._output_tokens_used,
        }


def build_projection(
    *,
    subject_ref: str,
    subject_hash: str,
    task_snapshot: dict[str, Any],
    allowlist: frozenset[str] | set[str],
) -> dict[str, Any]:
    """受控投影：task_snapshot 只复制 allowlist 键；其余键丢弃（不报错——未授权字段根本不进投影）。

    §8.5：外发只限实际获授权、所选题所需的受控投影。allowlist 是授权的机械面。
    """
    if not str(subject_ref or "").strip():
        raise ValueError("subject_ref is required")
    if not str(subject_hash or "").strip():
        raise ValueError("subject_hash is required")
    snapshot: dict[str, Any] = {}
    for key in task_snapshot:
        if key in allowlist:
            snapshot[key] = task_snapshot[key]
    return {
        "task_snapshot": snapshot,
        "subject_ref": str(subject_ref),
        "subject_hash": str(subject_hash),
    }


def _walk(node: Any, depth: int = 0):
    """递归产出 (键或 None, 值) 覆盖全部节点；超深度 fail-closed 由调用方拒绝。

    NF-1 修复：裸 str 叶子（list/tuple/set 元素）与 str dict 键此前逃逸扫描——
    前者两个 isinstance 分支都不中，后者只对照红线键名单不过凭证 pattern。
    """
    if depth > MAX_PROJECTION_DEPTH:
        raise ProjectionUnsafe(
            f"projection deeper than {MAX_PROJECTION_DEPTH} levels (fail-closed)"
        )
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, None  # str 键本身也要过凭证扫描
            yield key, value
            yield from _walk(value, depth + 1)
    elif isinstance(node, (list, tuple, set, frozenset)):
        for item in node:
            yield from _walk(item, depth + 1)
    elif isinstance(node, str):
        yield None, node  # 裸 str 叶子（容器元素）


def _assert_values_safe(state: dict[str, Any]) -> None:
    """红线键全深度检查 + 凭证样式全 str（键与值、含容器裸元素）扫描。"""
    for key, value in _walk(state):
        if key is not None and str(key).lower() in FORBIDDEN_STATE_KEYS:
            raise ProjectionUnsafe(f"state carries forbidden key: {key}")
        for text in (value, key):
            if isinstance(text, str):
                for pattern in _CREDENTIAL_PATTERNS:
                    if pattern.search(text):
                        raise ProjectionUnsafe(
                            f"state carries credential pattern: {pattern.pattern}"
                        )


def assert_projection_safe(request: dict[str, Any]) -> None:
    """三重守卫：红线键 / 凭证样式 / 工具授权字段。命中即抛 ProjectionUnsafe。"""
    for forbidden in FORBIDDEN_REQUEST_KEYS:
        if forbidden in request:
            raise ProjectionUnsafe(f"request carries tool-grant field: {forbidden}")
    state = request.get("state")
    if not isinstance(state, dict):
        raise ProjectionUnsafe("state_missing_or_not_object")
    _assert_values_safe(state)
    questions = request.get("questions")
    if isinstance(questions, dict):
        for name, question in questions.items():
            if not isinstance(question, dict):
                raise ProjectionUnsafe(f"question_not_object: {name}")
            for forbidden in FORBIDDEN_REQUEST_KEYS:
                if forbidden in question:
                    raise ProjectionUnsafe(
                        f"question carries tool-grant field: {forbidden}"
                    )


def estimate_input_tokens(request: dict[str, Any]) -> int:
    """粗估 token（字符数/4，中文保守取/2）。仅用于预算闸，不是计费事实。"""
    from llm_loop.knowledge.jev.wire import canonical_json

    text = canonical_json(request)
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, (cjk // 2) + (other // 4))
