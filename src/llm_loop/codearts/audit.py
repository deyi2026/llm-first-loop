"""AuditLogger 审计记录器（design.md §2.2.2.8）.

CodeArts 调度行为审计落盘 `data/audit/codearts_dispatch.jsonl`（append-only，
复用 dsh_task._audit fail-open 模式：O_APPEND + JSONL + 写失败 warning 不抛异常）。

序列化前对 params_summary 做敏感值脱敏（替换 env 敏感值、token 模式、AK/SK 模式
为 ***）。credential_ref 仅含凭证类型与 ID 标识（如 ak_sk:cn-north-4），不含明文。
target_api 仅含接口路径不含完整 URL query。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.codearts.models import AuditRecord

logger = logging.getLogger(__name__)

_AUDIT_FILENAME = "codearts_dispatch.jsonl"

# 敏感 env 变量名模式（复用 dsh_task._redact 思路）
_SENSITIVE_ENV_RE = re.compile(
    r"(.*_KEY|.*_TOKEN|.*_SECRET|.*_PASSWORD|.*_CREDENTIAL|CODEARTS_AK|CODEARTS_SK|"
    r"CODEARTS_IAM_TOKEN|CODEARTS_WEBHOOK_SECRET|LLM_API_KEY|EMBEDDING_API_KEY)",
    re.IGNORECASE,
)

# token / AK / SK 明文模式（长度下限防误替换短串）
_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_]{32,}(?![A-Za-z0-9])")
_AK_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{20}(?![A-Za-z0-9])")
_SK_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{40}(?![A-Za-z0-9])")


def _redact(text: str) -> str:
    """敏感值脱敏：env 敏感值替换 + token/AK/SK 模式替换为 ***."""
    if not text:
        return text
    out = text
    # env 敏感值替换（防泄漏进审计日志）
    for name, val in os.environ.items():
        if val and len(val) >= 8 and _SENSITIVE_ENV_RE.match(name):
            out = out.replace(val, "***")
    # token / AK / SK 模式替换
    out = _TOKEN_PATTERN.sub("***", out)
    out = _AK_PATTERN.sub("***", out)
    out = _SK_PATTERN.sub("***", out)
    return out


class AuditLogger:
    """CodeArts 调度审计记录器（fail-open，不含凭证明文）."""

    def __init__(self, audit_dir: Path | str) -> None:
        self._audit_dir = Path(audit_dir)
        self._path = self._audit_dir / _AUDIT_FILENAME

    def log(self, record: AuditRecord) -> None:
        """落盘审计记录（fail-open：写失败 warning 不阻断主链路）.

        序列化前对 params_summary 脱敏；credential_ref 仅含类型与区域标识。
        """
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            rec = {
                "timestamp": record.timestamp,
                "trace_id": record.trace_id,
                "action": record.action.value,
                "target_api": record.target_api,
                "response_status": record.response_status,
                "credential_ref": record.credential_ref,
                "params_summary": _redact(record.params_summary)[:2000],
                "result": record.result.value,
            }
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("CodeArts 审计落盘失败（fail-open）: %s", self._path, exc_info=True)

    @staticmethod
    def now_iso() -> str:
        """当前 UTC 时间 ISO8601（供构造 AuditRecord.timestamp）."""
        return datetime.now(UTC).isoformat()
