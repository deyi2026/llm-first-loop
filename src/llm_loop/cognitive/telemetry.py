"""CR-R1 6.2: cognitive telemetry 事件流（不变量⑪——归因与口径）.

事件流: data/audit/cognitive_telemetry.jsonl（env COG_RUNTIME_TELEMETRY=1 才写）.
事件类型: state_rebuild / packet_compile / tier_degraded / reset.
四要素: session_id / run_id / round / goal_id（缺一记 WARN 但仍落盘，字段空串）.
认知维度: cognitive_epoch / state_revision / hot_tokens / warm_tokens /
cold_ref_count / packet_tokens / mode.

设计约束（design.md L93）:
- fail-open: 写失败仅静默返回（遥测不阻断主流程）;
- env 关关默认零行为（与 ERR1210_* 开关族一致）;
- 每事件一行 JSONL，UTC ISO 时间戳。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["telemetry_enabled", "emit_cognitive_event"]


def telemetry_enabled() -> bool:
    """env COG_RUNTIME_TELEMETRY=1 时启用事件流写入."""
    return os.environ.get("COG_RUNTIME_TELEMETRY", "0") == "1"


def emit_cognitive_event(
    event: str,
    *,
    data_dir: str | Path,
    session_id: str = "",
    run_id: str = "",
    round_no: int = 0,
    goal_id: str = "",
    cognitive_epoch: int = 0,
    state_revision: int = 0,
    hot_tokens: int = 0,
    warm_tokens: int = 0,
    cold_ref_count: int = 0,
    packet_tokens: int = 0,
    mode: str = "",
) -> bool:
    """追加一条 cognitive 事件；返回是否实际写入（未启用/写失败 → False）."""
    if not telemetry_enabled():
        return False
    rec = {
        "ts": datetime.now(UTC).isoformat(),
        "event": event,
        "session_id": session_id,
        "run_id": run_id,
        "round": round_no,
        "goal_id": goal_id,
        "cognitive_epoch": cognitive_epoch,
        "state_revision": state_revision,
        "hot_tokens": hot_tokens,
        "warm_tokens": warm_tokens,
        "cold_ref_count": cold_ref_count,
        "packet_tokens": packet_tokens,
        "mode": mode,
    }
    try:
        path = Path(data_dir) / "audit" / "cognitive_telemetry.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False  # fail-open: 遥测写失败不阻断主流程
