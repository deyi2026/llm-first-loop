"""GLM HTTP 400/code 1210 mechanical compatibility helpers.

The proven wire defect is structural: multiple consecutive tail ``role=user`` frames may
be rejected by the GLM endpoint. Runtime recovery therefore owns only exact error-code
classification, bounded diagnostics, and one lossless tail-user normalization attempt.
Historical program-injection strip/defer/replay machinery was retired in P2-B because
P1-C removed its producers.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.llm.errors import LLMError, LLMHTTPError, parse_provider_error_code

logger = logging.getLogger(__name__)
_SNAPSHOT_SCHEMA = 2


def is_err1210(exc: LLMError) -> bool:
    """Return True only for the exact provider HTTP 400/code 1210 contract."""
    if not isinstance(exc, LLMHTTPError) or exc.status_code != 400:
        return False
    return parse_provider_error_code(exc.body or "") == "1210"


@dataclass
class Err1210RecoveryResult:
    """One bounded mechanical recovery attempt."""

    attempted: bool = False
    recovered: bool = False
    exhausted: bool = False
    resp: Any | None = None
    transformed_tail_users: int = 0
    provider_retry_count: int = 0


def snapshot_offending_payload(
    *,
    messages: list[dict],
    tools: list[dict],
    params: dict[str, Any],
    session_id: str,
    model: str,
    is_compact_first: bool = False,
    data_dir: str | Path,
) -> Path | None:
    """Best-effort diagnostic snapshot for a real 1210; never affects recovery decisions."""
    if os.environ.get("ERR1210_SNAPSHOT", "1") != "1":
        return None
    try:
        from datetime import UTC, datetime

        ts = datetime.now(UTC)
        ts_str = ts.strftime("%Y%m%dT%H%M%S") + f"{ts.microsecond // 1000:03d}Z"
        out_dir = Path(data_dir) / "audit" / "offending_payloads"
        out_dir.mkdir(parents=True, exist_ok=True)
        snap = {
            "schema": _SNAPSHOT_SCHEMA,
            "ts_utc": ts.isoformat(),
            "session_id": session_id,
            "model": model,
            "is_compact_first": bool(is_compact_first),  # historical diagnostic field
            "messages": messages,
            "tools": tools,
            "params": params,
            "recovery_contract": "tail_user_normalization_only",
            "trace_key": {
                "session_id": session_id,
                "local_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        }
        path = out_dir / f"{ts_str}_{session_id[:8]}.json"
        path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001 - diagnostic persistence is fail-open
        logger.warning("offending payload 快照落盘失败（fail-open）", exc_info=True)
        return None
