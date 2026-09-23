"""Method-card injection helpers (EVO-20260923-618f7fd1).

Two program-origin surfaces, both fail-open:

1. Session-opening reference-layer appendix listing ACTIVE method cards
   (name + one-line trigger, full text stays behind search_records hydration).
2. A single per-run status-layer reminder fired at the no-tool-call final
   boundary when exact method hydrations lack any method_manage record_use.

Everything here is mechanical: no policy retries, no fuzzy matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_loop.core.injection_labels import (
    InjectionLayer,
    origin_metadata,
    reference_has_imperative,
    render_program_appendix,
)
from llm_loop.core.message import Message, MessageSource

_ACTIVE_KIND = "method_active_cards"
_REMINDER_KIND = "method_use_reminder"
_MAX_CARDS = 12
_MAX_DESC_CHARS = 80


@dataclass(frozen=True)
class MethodUseLedger:
    """Method refs exactly hydrated vs. refs with a record_use this run."""

    hydrated: tuple[str, ...]
    recorded: tuple[str, ...]

    def unrecorded(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ref in self.hydrated:
            if ref not in self.recorded and ref not in seen:
                seen.append(ref)
        return tuple(seen)


def has_active_cards_injection(sess: Any) -> bool:
    """Idempotency probe: session already carries the active-cards appendix."""
    for msg in getattr(sess, "messages", []) or []:
        meta = getattr(msg, "metadata", None) or {}
        if meta.get("injection_kind") == _ACTIVE_KIND:
            return True
    return False


def _one_line(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat[:_MAX_DESC_CHARS] + ("…" if len(flat) > _MAX_DESC_CHARS else "")


def build_active_cards_message(methods_dir: str | None) -> Message | None:
    """Reference-layer carrier listing active cards; None on fail-open/empty."""
    try:
        if not methods_dir:
            return None
        from llm_loop.methods.store import MethodStore

        records = MethodStore(methods_dir).list("", limit=_MAX_CARDS * 4)
        lines: list[str] = []
        for card in records:
            if card.get("status") != "active":
                continue
            ref = str(card.get("key") or "").strip()
            if not ref:
                continue
            name = str(card.get("summary") or ref)
            desc = _one_line(card.get("description") or "")
            if reference_has_imperative(desc):
                desc = ""  # 防整段清单被 R2 祈使句中和：放弃该卡描述仅留名称
            lines.append(f"- {ref} — {name}" + (f"：{desc}" if desc else ""))
            if len(lines) >= _MAX_CARDS:
                break
        if not lines:
            return None
        # 整段兜底：任一描述使全文触发 R2 祈使句过滤时，整体降级为仅名称清单
        if reference_has_imperative("\n".join(lines)):
            lines = [ln.split("：", 1)[0] for ln in lines]
        body = "\n".join(
            [
                f"方法池 active 卡清单（{len(lines)} 张；仅名称与触发线索，"
                "全文经 search_records(kind=method) 检索后按 method:<id> 精确水合）：",
                *lines,
            ]
        )
        content = render_program_appendix(
            body,
            InjectionLayer.REFERENCE,
            slot_kind="method_active_cards",
        )
        return Message(
            role="user",
            source=MessageSource.USER,
            content=content,
            metadata=origin_metadata(
                InjectionLayer.REFERENCE,
                injection_kind=_ACTIVE_KIND,
            ),
        )
    except Exception:  # fail-open: appendix is best-effort reference material
        return None


def scan_method_use_ledger(tool_trace: list[Any]) -> MethodUseLedger:
    """Derive hydrated vs. recorded method refs from this run's tool trace."""
    hydrated: list[str] = []
    recorded: list[str] = []
    for row in tool_trace or []:
        try:
            if isinstance(row, dict):
                name = str(row.get("name", "") or "")
                arguments = row.get("arguments") or {}
                status = str(row.get("status", "success") or "")
            else:
                name = str(getattr(row, "name", "") or "")
                arguments = getattr(row, "arguments", None) or {}
                status = str(getattr(row, "status", "success") or "")
            if status != "success":
                continue
            if name == "search_records":
                if str(arguments.get("kind", "")) != "method":
                    continue
                query = str(arguments.get("query", "") or "").strip()
                if query.startswith("method:"):
                    hydrated.append(query)
            elif name == "method_manage":
                if str(arguments.get("action", "")) != "record_use":
                    continue
                ref = str(arguments.get("method_ref", "") or "").strip()
                if ref:
                    recorded.append(ref)
        except Exception:
            continue
    return MethodUseLedger(hydrated=tuple(hydrated), recorded=tuple(recorded))


def build_use_reminder_message(unrecorded_refs: tuple[str, ...]) -> Message:
    """Status-layer reminder carrier; caller fires it once per run."""
    refs = ", ".join(unrecorded_refs[:6]) + (
        f" 等{len(unrecorded_refs)}张" if len(unrecorded_refs) > 6 else ""
    )
    body = (
        f"方法 use 回记提醒（每 run 至多一次，不阻塞收尾）：本 run 已精确水合方法卡 "
        f"{refs}，尚无对应 method_manage(action=record_use) 回记；"
        "适用则补 applied/adapted/not_applicable/rejected，"
        "或再次直接给出最终答复。"
    )
    content = render_program_appendix(
        body,
        InjectionLayer.STATUS,
        slot_kind="method_use_reminder",
    )
    return Message(
        role="user",
        source=MessageSource.USER,
        content=content,
        metadata=origin_metadata(
            InjectionLayer.STATUS,
            injection_kind=_REMINDER_KIND,
        ),
    )
