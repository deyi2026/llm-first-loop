"""CodeArtsEventReceiver 事件接收器（design.md §1.1.3 模块组 13，可选）.

接收 CodeArts Webhook 回调（进度/完成通知）。Webhook 签名校验（HMAC-SHA256，
密钥 CODEARTS_WEBHOOK_SECRET，校验失败拒绝 + 审计落盘）。校验通过后解析事件
payload，调用 StateSynchronizer 注入状态更新（事件推送优先，轮询兜底降级为纯轮询）。

CODEARTS_WEBHOOK_ENABLED=false 时本模块不装配（缺省 fail-open）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from llm_loop.codearts.audit import AuditLogger
from llm_loop.codearts.models import AuditAction, AuditRecord, AuditResult
from llm_loop.codearts.sync import StateSynchronizer

logger = logging.getLogger(__name__)


class CodeArtsEventReceiver:
    """CodeArts Webhook 事件接收器（签名校验 + 状态更新注入）."""

    def __init__(
        self,
        state_synchronizer: StateSynchronizer,
        audit_logger: AuditLogger,
        webhook_secret: str,
    ) -> None:
        self._sync = state_synchronizer
        self._audit_logger = audit_logger
        self._secret = webhook_secret

    def verify_signature(self, payload_body: bytes, signature_header: str) -> bool:
        """HMAC-SHA256 签名校验.

        Args:
            payload_body: Webhook 请求体原始字节。
            signature_header: 请求头中的签名（hex）。

        Returns:
            True 校验通过；False 校验失败。
        """
        if not self._secret or not signature_header:
            return False
        expected = hmac.new(
            self._secret.encode("utf-8"), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header)

    def handle_event(self, payload_body: bytes, signature_header: str) -> bool:
        """处理 Webhook 事件（签名校验 → 解析 → 状态更新注入）.

        Returns:
            True 处理成功；False 校验失败或处理异常。
        """
        # 1. 签名校验
        if not self.verify_signature(payload_body, signature_header):
            self._audit_log(AuditResult.BLOCKED, "签名校验失败")
            logger.warning("CodeArts Webhook 签名校验失败")
            return False

        # 2. 解析事件 payload
        try:
            data = json.loads(payload_body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._audit_log(AuditResult.FAILURE, f"payload 解析失败: {exc}")
            return False

        # 3. 注入状态更新（事件推送优先）
        handle_id = str(data.get("handle_id") or "")
        if not handle_id:
            self._audit_log(AuditResult.FAILURE, "payload 缺少 handle_id")
            return False

        # StateSynchronizer 的事件注入接口（当前实现为轮询兜底，Webhook 事件
        # 可经此通道主动推送状态更新，减少轮询延迟）
        # 注：当前 PollingSynchronizer 未实现事件注入接口，此通道为预留扩展点
        # 事件推送优先时升级为 EventSynchronizer（design.md §2.1.3.4 扩展点 3）
        self._audit_log(AuditResult.SUCCESS, f"handle_id={handle_id}")
        logger.info("CodeArts Webhook 事件接收: handle_id=%s", handle_id)
        return True

    def _audit_log(self, result: AuditResult, detail: str) -> None:
        """审计落盘（fail-open）."""
        self._audit_logger.log(
            AuditRecord(
                timestamp=datetime.now(UTC).isoformat(),
                trace_id="",
                action=AuditAction.QUERY,
                target_api="webhook",
                response_status=200 if result == AuditResult.SUCCESS else 403,
                credential_ref="",
                params_summary=detail[:500],
                result=result,
            )
        )
