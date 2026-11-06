"""EVO-20261106-b0806c32: 跨会话 EVO 完成待登记暂存处（completion-handoff registry）.

背景：evolution_complete 归属校验（防伪造登记）会拒绝执行会话代登记；
此前唯一出路是 help_request 自然语言人工转交，信息易失真且依赖归属
会话肉眼读消息。本模块在「归属拒绝」时把程序组装的结构化登记参数
（suggestion_id/actions/evidence_refs/note + 建议 evolution_complete
调用参数全文）落到归属会话可读的 data/ 暂存处；归属会话调用
evolution_complete 时程序自动取用（一键落账），消灭转写环节。

边界：不改归属语义——登记权仍在归属会话；执行会话仍不能落账。
"""
from __future__ import annotations

import contextlib
import json
import re
from pathlib import Path

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def handoff_dir(audit_dir: str | Path) -> Path:
    return Path(audit_dir) / "evolution_completion_handoff"


def _safe_name(suggestion_id: str) -> str:
    return _SAFE_ID_RE.sub("_", str(suggestion_id))[:160] or "unknown"


def stage_completion_handoff(
    audit_dir: str | Path,
    *,
    suggestion_id: str,
    owner_session: str,
    implementing_session: str,
    actions: list | None = None,
    evidence_refs: list | None = None,
    note: str = "",
) -> Path:
    """归属拒绝时写入/覆盖暂存条目（按 suggestion_id 幂等 upsert）.

    条目含程序组装的 evolution_complete 调用参数全文；写失败不阻断
    拒绝回执（调用方 suppress）。
    """
    from llm_loop.timekeeping import system_local_now

    d = handoff_dir(audit_dir)
    d.mkdir(parents=True, exist_ok=True)
    entry = {
        "suggestion_id": str(suggestion_id),
        "staged_at": system_local_now().isoformat(),
        "owner_session": str(owner_session or ""),
        "implementing_session": str(implementing_session or ""),
        "actions": list(actions or []),
        "evidence_refs": list(evidence_refs or []),
        "note": str(note or ""),
        "consume_hint": (
            "owner 会话调用 evolution_complete(suggestion_id=..., note 可为空) 时"
            "程序将自动取用本条目的 actions/evidence_refs/note（一键落账）；"
            "登记成功后本条目自动清除。"
        ),
    }
    target = d / f"{_safe_name(str(suggestion_id))}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    tmp.replace(target)
    return target


def load_completion_handoff(audit_dir: str | Path, suggestion_id: str) -> dict | None:
    """读取该建议的暂存条目；不存在/坏文件 → None（fail-open 不阻断登记）。"""
    target = handoff_dir(audit_dir) / f"{_safe_name(str(suggestion_id))}.json"
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clear_completion_handoff(audit_dir: str | Path, suggestion_id: str) -> bool:
    """owner 登记成功后清除条目；不存在返回 False（幂等）。"""
    target = handoff_dir(audit_dir) / f"{_safe_name(str(suggestion_id))}.json"
    with contextlib.suppress(OSError):
        target.unlink(missing_ok=True)
        return True
    return False


def list_pending_handoffs(audit_dir: str | Path) -> list[dict]:
    """聚合视图用：列出全部待登记条目（坏文件跳过，不冒充）。"""
    d = handoff_dir(audit_dir)
    out: list[dict] = []
    try:
        files = sorted(d.glob("*.json"))
    except OSError:
        return out
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("suggestion_id"):
            out.append(
                {
                    "suggestion_id": data.get("suggestion_id"),
                    "owner_session": data.get("owner_session"),
                    "implementing_session": data.get("implementing_session"),
                    "staged_at": data.get("staged_at"),
                }
            )
    return out
