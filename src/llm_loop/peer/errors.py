"""lfl.peer.v1 封闭错误码与领域异常。

真值源：``docs/schemas/lfl.peer.v1/reason-codes.json``；该文件的 codes 键集合与
``receipt.schema.json`` 的 reason_code 枚举强一致，由 scripts/verify_peer_schemas.py 强制。
本模块是运行期镜像：``tests/peer/test_peer_contract.py`` 断言两者相等，防止漂移。
实现中禁止新增自由文本错误码（新增=改契约+升版本）。
"""
from __future__ import annotations

REASON_CODES: frozenset[str] = frozenset(
    {
        "artifact_digest_mismatch",
        "artifact_missing",
        "audit_unavailable",
        "blocked_timeout",
        "cancelled_by_grant_revocation",
        "cancelled_by_operator",
        "command_not_allowed",
        "crashed",
        "desktop_target_not_grounded",
        "execution_not_authorized",
        "executor_internal_error",
        "executor_unhealthy",
        "grant_exhausted",
        "grant_expired",
        "grant_issuer_not_human",
        "grant_not_found",
        "grant_revoked",
        "grant_unbounded",
        "idempotency_conflict",
        "pair_fingerprint_mismatch",
        "pair_nonce_expired",
        "params_schema_invalid",
        "path_outside_allowed_paths",
        "peer_bad_signature",
        "peer_not_paired",
        "peer_replay_detected",
        "peer_stale_signature",
        "peer_transport_unavailable",
        "peer_unknown_node",
        "policy_desktop_type_not_allowed",
        "policy_task_kind_not_allowed",
        "quota_concurrency_exceeded",
        "requires_supervised_execution",
        "sandbox_denied",
        "supervision_channel_unavailable",
        "supervision_ticket_consumed",
        "supervision_ticket_expired",
        "supervision_ticket_mismatch",
        "supervision_ticket_missing",
        "supervision_timeout",
    "task_not_found",
        "timeout",
        "unknown_outcome",
        "unsupported_display_protocol",
    }
)


class PeerError(Exception):
    """携带封闭 reason_code 的领域异常；路由层据此生成 receipt。"""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in REASON_CODES:
            raise ValueError(f"unknown peer reason_code: {reason_code}")
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)


class InvalidTaskTransitionError(RuntimeError):
    """状态机非法迁移。属程序缺陷，不映射为线上 reason_code。"""


def is_known_reason_code(code: str) -> bool:
    return code in REASON_CODES
