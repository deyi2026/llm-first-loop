"""Durable resolved-episode index for prompt eligibility.

The conversation session remains the human-facing storage truth.  This store is
the durable retrieval surface that lets completed episodes retire from the
provider working context without becoming unreachable.

Design invariants:
- append-only, session-scoped JSONL under ``data/episodes``;
- stable deterministic ``episode:...`` refs;
- exact visible user/assistant/tool content is retained, while private
  ``reasoning_content`` and program-only prompt injections are not duplicated;
- search returns compact refs/previews; hydration is explicit and bounded.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from llm_loop.core.message import Message
from llm_loop.core.reference_injection import is_human_user_message


EPISODE_SCHEMA = 1
DEFAULT_HYDRATE_CHARS = 6000
MAX_HYDRATE_CHARS = 12000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id:
        raise ValueError("非法 session_id: 不能为空")
    if (
        session_id in {".", ".."}
        or "/" in session_id
        or "\\" in session_id
        or "\x00" in session_id
        or any(ch in session_id for ch in "*?[]")
    ):
        raise ValueError("非法 session_id: 不得包含路径分隔符、NUL、目录跳转或glob元字符")
    return session_id


def stable_episode_ref(session_id: str, user_message: Message, user_seq: int) -> str:
    """Return a deterministic ref for one human turn.

    New messages have a persisted timestamp.  ``user_seq`` remains part of the
    identity for legacy/zero-ts sessions and makes two identical user messages
    in one session distinct.
    """

    sid = _validate_session_id(session_id)
    ts_ns = int(float(getattr(user_message, "ts", 0.0) or 0.0) * 1_000_000_000)
    raw = (
        f"{sid}\0{user_seq}\0{ts_ns}\0{str(getattr(user_message, 'content', '') or '')}"
    ).encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"episode:{sid}:{user_seq}:{digest}"


def _snapshot_message(message: Message) -> dict[str, Any] | None:
    """Snapshot only visible task material, never duplicated hidden reasoning.

    Program-origin user/system messages are intentionally absent from hydration:
    the purpose of the episode store is to recover the user's question, visible
    assistant answers and tool evidence, not to resurrect stale prompt control.
    """

    if message.role == "user":
        if not is_human_user_message(message):
            return None
        return {
            "role": "user",
            "content": str(message.content or ""),
            "source": str(message.source),
            "ts": float(message.ts or 0.0),
        }
    if message.role == "assistant":
        return {
            "role": "assistant",
            "content": str(message.content or ""),
            "source": str(message.source),
            "tool_calls": message.tool_calls,
            "model_used": str(message.model_used or ""),
            "ts": float(message.ts or 0.0),
        }
    if message.role == "tool":
        return {
            "role": "tool",
            "content": str(message.content or ""),
            "source": str(message.source),
            "tool_call_id": message.tool_call_id,
            "tool_name": message.tool_name,
            "status": str(message.status) if message.status is not None else None,
            "error_detail": message.error_detail,
            "ts": float(message.ts or 0.0),
        }
    return None


def _render_transcript(messages: Iterable[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", "") or "")
        if role == "user":
            lines.append("[user]\n" + content)
            continue
        if role == "assistant":
            tool_calls = message.get("tool_calls")
            if tool_calls:
                try:
                    calls = json.dumps(tool_calls, ensure_ascii=False, separators=(",", ":"))
                except (TypeError, ValueError):
                    calls = str(tool_calls)
                lines.append("[assistant tool_calls]\n" + calls)
            if content:
                lines.append("[assistant]\n" + content)
            continue
        if role == "tool":
            name = str(message.get("tool_name") or "?")
            status = str(message.get("status") or "")
            suffix = f" status={status}" if status else ""
            lines.append(f"[tool {name}{suffix}]\n{content}")
    return "\n\n".join(lines)


@dataclass(frozen=True)
class EpisodeIndexResult:
    ref: str
    created: bool


class EpisodeStore:
    """Append-only durable index + exact visible transcript hydration."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, session_id: str) -> Path:
        sid = _validate_session_id(session_id)
        return self._root / f"{sid}.jsonl"

    def _iter_entries(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(entry, dict) and entry.get("session_id") == session_id:
                        out.append(entry)
        except OSError:
            return []
        return out

    def get(self, session_id: str, ref: str) -> dict[str, Any] | None:
        wanted = str(ref or "").strip()
        if not wanted:
            return None
        for entry in reversed(self._iter_entries(session_id)):
            if entry.get("ref") == wanted:
                return entry
        return None

    def index_episode(
        self,
        session_id: str,
        *,
        ref: str,
        user_seq: int,
        raw_messages: list[Message],
    ) -> EpisodeIndexResult:
        """Persist one resolved episode idempotently.

        A ref collision with different visible transcript is fail-closed because
        retirement is allowed only after durable identity is trustworthy.
        """

        sid = _validate_session_id(session_id)
        snapshots = [snap for m in raw_messages if (snap := _snapshot_message(m)) is not None]
        if not snapshots or snapshots[0].get("role") != "user":
            raise ValueError("resolved episode 缺少首个真实 user message")
        assistant_rows = [m for m in snapshots if m.get("role") == "assistant"]
        if not assistant_rows:
            raise ValueError("resolved episode 缺少 assistant 输出")
        transcript = _render_transcript(snapshots)
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8", "replace")).hexdigest()
        existing = self.get(sid, ref)
        if existing is not None:
            if str(existing.get("transcript_sha256") or "") != transcript_sha256:
                raise ValueError(f"episode ref collision: {ref}")
            return EpisodeIndexResult(ref=ref, created=False)

        question = str(snapshots[0].get("content") or "")
        final_answer = str(assistant_rows[-1].get("content") or "")
        tool_names = list(
            dict.fromkeys(
                str(m.get("tool_name") or "")
                for m in snapshots
                if m.get("role") == "tool" and str(m.get("tool_name") or "")
            )
        )
        entry: dict[str, Any] = {
            "schema": EPISODE_SCHEMA,
            "ref": ref,
            "session_id": sid,
            "resolved_at": _now(),
            "user_seq": int(user_seq),
            "question": question,
            "final_answer": final_answer,
            "tool_names": tool_names,
            "message_count": len(snapshots),
            "chars": sum(len(str(m.get("content") or "")) for m in snapshots),
            "transcript_sha256": transcript_sha256,
            "messages": snapshots,
        }
        path = self._path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        # One whole JSON line is appended under the session's single-run write
        # discipline.  Flush+fsync makes the retrieval proof durable before the
        # caller marks session messages eligible for retirement.
        with path.open("ab") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        return EpisodeIndexResult(ref=ref, created=True)

    def search(self, session_id: str, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        q = str(query or "").strip().casefold()
        rows = self._iter_entries(session_id)
        hits: list[dict[str, Any]] = []
        for entry in reversed(rows):
            hay = " ".join(
                [
                    str(entry.get("ref") or ""),
                    str(entry.get("question") or ""),
                    str(entry.get("final_answer") or ""),
                    " ".join(str(x) for x in (entry.get("tool_names") or [])),
                ]
            ).casefold()
            if q and q not in hay:
                continue
            question = " ".join(str(entry.get("question") or "").split())[:180]
            answer = " ".join(str(entry.get("final_answer") or "").split())[:180]
            tools = ",".join(str(x) for x in (entry.get("tool_names") or [])[:8])
            summary = f"ref={entry.get('ref')} | Q={question} | A={answer}"
            if tools:
                summary += f" | tools={tools}"
            hits.append(
                {
                    "kind": "episode",
                    "ts": entry.get("resolved_at", ""),
                    "id": entry.get("ref", ""),
                    "ref": entry.get("ref", ""),
                    "summary": summary,
                }
            )
            if len(hits) >= max(1, int(limit)):
                break
        return hits

    def hydrate(
        self,
        session_id: str,
        ref: str,
        *,
        offset: int = 0,
        max_chars: int = DEFAULT_HYDRATE_CHARS,
    ) -> dict[str, Any] | None:
        entry = self.get(session_id, ref)
        if entry is None:
            return None
        transcript = _render_transcript(entry.get("messages") or [])
        start = max(0, int(offset or 0))
        width = max(256, min(int(max_chars or DEFAULT_HYDRATE_CHARS), MAX_HYDRATE_CHARS))
        chunk = transcript[start : start + width]
        next_offset = start + len(chunk)
        complete = next_offset >= len(transcript)
        return {
            "ref": ref,
            "offset": start,
            "next_offset": None if complete else next_offset,
            "complete": complete,
            "total_chars": len(transcript),
            "content": chunk,
            "transcript_sha256": entry.get("transcript_sha256", ""),
        }
