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

Interrupted/truncated model output is a separate recovery class. Its compact
``truncated:...`` index remains append-only, while an immutable private artifact may
retain the exact model-origin text/reasoning that existed before any display tail is
applied. Those artifacts are explicit-retrieval facts only; they never authorize
automatic replay into a later provider request.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import Message
from llm_loop.core.reference_injection import is_human_user_message

EPISODE_SCHEMA = 1
DEFAULT_HYDRATE_CHARS = 6000
MAX_HYDRATE_CHARS = 12000

# B2(EVO-20260902-41898b20): truncated run 索引（{sid}.truncated.jsonl，非退休型）
TRUNCATED_SCHEMA = 1
# 行级 <2KB 硬顶 → 尾段在索引行内二次裁剪（完整尾段存于 B1 会话消息与事件日志）
TRUNCATED_ROW_TEXT_TAIL_CHARS = 700
TRUNCATED_ROW_REASONING_TAIL_CHARS = 800
TRUNCATION_ARTIFACT_SCHEMA = 1


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


def stable_tool_span_ref(
    session_id: str,
    user_message: Message,
    user_seq: int,
    consumer_seq: int,
    tool_call_ids: Iterable[str],
) -> str:
    """Return a deterministic ref for one consumed tool-evidence span.

    A human turn may contain several tool rounds before one non-tool assistant
    consumes their results.  The span identity therefore binds the human turn,
    consumer position, and declared call ids without depending on mutable prompt
    projection details.
    """

    sid = _validate_session_id(session_id)
    ts_ns = int(float(getattr(user_message, "ts", 0.0) or 0.0) * 1_000_000_000)
    calls = "\0".join(str(call_id or "") for call_id in tool_call_ids)
    raw = (
        f"{sid}\0{user_seq}\0{consumer_seq}\0{ts_ns}\0"
        f"{str(getattr(user_message, 'content', '') or '')}\0{calls}"
    ).encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"toolspan:{sid}:{user_seq}:{consumer_seq}:{digest}"


def stable_closed_tool_span_ref(
    session_id: str,
    user_message: Message,
    user_seq: int,
    terminal_seq: int,
    terminal_reason: str,
    tool_call_ids: Iterable[str],
) -> str:
    """Deterministic ref for a durably closed, non-consumed tool attempt."""

    sid = _validate_session_id(session_id)
    ts_ns = int(float(getattr(user_message, "ts", 0.0) or 0.0) * 1_000_000_000)
    calls = "\0".join(str(call_id or "") for call_id in tool_call_ids)
    raw = (
        f"{sid}\0{user_seq}\0{terminal_seq}\0{terminal_reason}\0{ts_ns}\0"
        f"{str(getattr(user_message, 'content', '') or '')}\0{calls}"
    ).encode("utf-8", "replace")
    digest = hashlib.sha256(raw).hexdigest()[:20]
    return f"closedspan:{sid}:{user_seq}:{terminal_seq}:{digest}"


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

    def _truncated_artifact_dir(self, session_id: str) -> Path:
        sid = _validate_session_id(session_id)
        return self._root / f"{sid}.truncated.artifacts"

    def _truncated_artifact_path(self, session_id: str, artifact_ref: str) -> Path | None:
        prefix = "truncation:"
        if not isinstance(artifact_ref, str) or not artifact_ref.startswith(prefix):
            return None
        digest = artifact_ref[len(prefix) :]
        if len(digest) != 64:
            return None
        try:
            int(digest, 16)
        except ValueError:
            return None
        return self._truncated_artifact_dir(session_id) / f"{digest}.json"

    def capture_truncated_artifact(
        self,
        session_id: str,
        *,
        reason: str,
        round_no: int,
        provider: str,
        model: str,
        text_full: str = "",
        reasoning_full: str = "",
        partial_sha256: str = "",
        provider_replay: dict[str, Any] | None = None,
        tool_call_drafts: list[dict[str, Any]] | None = None,
    ) -> str:
        """Persist exact pre-projection model bytes as an immutable private artifact.

        The artifact is content-addressed and chmod 0600. It is intentionally not a
        conversational message and not an automatic continuation source. Callers may
        attach the returned ref to a compact ``truncated:...`` row for explicit
        search/hydration.
        """
        sid = _validate_session_id(session_id)
        if not text_full and not reasoning_full and not provider_replay and not tool_call_drafts:
            return ""
        snapshot: dict[str, Any] = {
            "schema": TRUNCATION_ARTIFACT_SCHEMA,
            "session_id": sid,
            "reason": str(reason or ""),
            "round": int(round_no or 0),
            "provider": str(provider or ""),
            "model": str(model or ""),
            "text_full": str(text_full or ""),
            "reasoning_full": str(reasoning_full or ""),
            "partial_sha256": str(partial_sha256 or ""),
            "provider_replay": provider_replay if isinstance(provider_replay, dict) else None,
            "tool_call_drafts": [
                dict(item) for item in (tool_call_drafts or []) if isinstance(item, dict)
            ],
        }
        canonical = json.dumps(
            snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        digest = hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()
        artifact_ref = f"truncation:{digest}"
        artifact = {**snapshot, "artifact_ref": artifact_ref}
        raw = json.dumps(artifact, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        directory = self._truncated_artifact_dir(sid)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(directory, 0o700)
        path = directory / f"{digest}.json"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing != raw:
                raise ValueError("truncation artifact digest collision/content mismatch")
            return artifact_ref
        tmp = directory / f".{digest}.{os.getpid()}.tmp"
        try:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            with contextlib.suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            with contextlib.suppress(OSError):
                os.chmod(path, 0o600)
            try:
                dir_fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except OSError:
                pass
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
        return artifact_ref

    def _load_truncated_artifact(
        self, session_id: str, artifact_ref: str
    ) -> dict[str, Any] | None:
        path = self._truncated_artifact_path(session_id, artifact_ref)
        if path is None or not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema") != TRUNCATION_ARTIFACT_SCHEMA:
            return None
        if str(payload.get("session_id") or "") != _validate_session_id(session_id):
            return None
        if str(payload.get("artifact_ref") or "") != artifact_ref:
            return None
        return payload

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

    # ── B2(EVO-20260902-41898b20)：truncated run 索引（独立文件，非退休型）──

    def _truncated_path(self, session_id: str) -> Path:
        """truncated 索引独立文件（与 resolved 索引同目录、不混文件、schema 独立演进）."""
        sid = _validate_session_id(session_id)
        return self._root / f"{sid}.truncated.jsonl"

    def _iter_truncated(self, session_id: str) -> list[dict[str, Any]]:
        """按文件顺序（≈时间序）读本会话全部 truncated 行；损坏行跳过不抛穿."""
        path = self._truncated_path(session_id)
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

    def index_truncated_run(
        self,
        session_id: str,
        *,
        ts: str = "",
        run_end_reason: str,
        error_digest: str = "",
        last_round: int = 0,
        run_end_seq: int = 0,
        text_tail: str = "",
        reasoning_tail: str = "",
        partial_chars: int = 0,
        partial_sha256: str = "",
        artifact_ref: str = "",
        ref: str = "",
    ) -> bool:
        """持久化一条 truncated run 行（append + flush + fsync，幂等）.

        幂等键 = (session_id, run_end_seq)（run_end 事件 seq；seq<=0 视为事件存储
        不可用，如实追加不去重）。行级 <2KB：尾段入库前二次裁剪（完整尾段在
        B1 会话消息/事件日志）。永不参与 resolved 退休判定（独立文件天然隔离）。

        Returns:
            True=新写入；False=幂等命中（已存在同键行）。
        """
        sid = _validate_session_id(session_id)
        wanted_ref = str(ref or "").strip()
        if wanted_ref and not wanted_ref.startswith("truncated:"):
            raise ValueError("truncated ref 必须以 truncated: 开头")
        for entry in self._iter_truncated(sid):
            if wanted_ref and str(entry.get("ref") or "") == wanted_ref:
                return False
            if run_end_seq > 0:
                try:
                    if int(entry.get("run_end_seq") or 0) == int(run_end_seq):
                        return False
                except (TypeError, ValueError):
                    continue
        entry: dict[str, Any] = {
            "schema": TRUNCATED_SCHEMA,
            "entry_kind": "truncated",
            "ref": wanted_ref or f"truncated:{int(run_end_seq or 0)}",
            "session_id": sid,
            "ts": ts or _now(),
            "run_end_reason": str(run_end_reason or ""),
            "error_digest": str(error_digest or "")[:200],
            "last_round": int(last_round or 0),
            "run_end_seq": int(run_end_seq or 0),
            "text_tail": str(text_tail or "")[:TRUNCATED_ROW_TEXT_TAIL_CHARS],
            "reasoning_tail": str(reasoning_tail or "")[:TRUNCATED_ROW_REASONING_TAIL_CHARS],
            "partial_chars": int(partial_chars or 0),
            "partial_sha256": str(partial_sha256 or ""),
            "artifact_ref": str(artifact_ref or ""),
        }
        path = self._truncated_path(sid)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
        with path.open("ab") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        return True

    def search_truncated(
        self, session_id: str, query: str = "", limit: int = 10
    ) -> list[dict[str, Any]]:
        """truncated 行检索（与 resolved 检索同构的 hit 形状 + state=truncated）."""
        q = str(query or "").strip().casefold()
        hits: list[dict[str, Any]] = []
        for entry in reversed(self._iter_truncated(session_id)):
            hay = " ".join(
                str(entry.get(k) or "")
                for k in ("run_end_reason", "error_digest", "text_tail", "reasoning_tail")
            ).casefold()
            if q and q not in hay:
                continue
            ref = str(entry.get("ref") or "")
            reason = str(entry.get("run_end_reason") or "")
            tail_head = " ".join(str(entry.get("text_tail") or "").split())[:120]
            summary = (
                f"ref={ref} | type=truncated | reason={reason}"
                f" | round={entry.get('last_round', 0)}"
                + (" | exact_artifact=true" if entry.get("artifact_ref") else "")
                + (f" | error={entry.get('error_digest', '')[:120]}" if entry.get("error_digest") else "")
                + (f" | tail={tail_head}…" if tail_head else "")
            )
            hits.append(
                {
                    "kind": "episode",
                    "ts": entry.get("ts", ""),
                    "id": ref,
                    "ref": ref,
                    "state": "truncated",
                    "run_end_reason": reason,
                    "summary": summary,
                }
            )
            if len(hits) >= max(1, int(limit)):
                break
        return hits

    def hydrate_truncated(
        self,
        session_id: str,
        ref: str,
        *,
        offset: int = 0,
        max_chars: int = DEFAULT_HYDRATE_CHARS,
    ) -> dict[str, Any] | None:
        """Hydrate a truncated ref, preferring the exact immutable source artifact.

        Legacy rows without an artifact remain readable through their compact tails.
        New rows expose exact model-origin text/reasoning through the same bounded
        paging contract used by resolved episodes.
        """
        wanted = str(ref or "").strip()
        if not wanted.startswith("truncated:"):
            return None
        for entry in reversed(self._iter_truncated(session_id)):
            if str(entry.get("ref") or "") != wanted:
                continue
            artifact_ref = str(entry.get("artifact_ref") or "")
            artifact = self._load_truncated_artifact(session_id, artifact_ref)
            if artifact is None:
                legacy = dict(entry)
                legacy_content = "\n\n".join(
                    part
                    for part in (
                        "[assistant_text_tail]\n" + str(entry.get("text_tail") or "")
                        if entry.get("text_tail")
                        else "",
                        "[assistant_reasoning_tail]\n" + str(entry.get("reasoning_tail") or "")
                        if entry.get("reasoning_tail")
                        else "",
                    )
                    if part
                )
                legacy.update(
                    {
                        "offset": 0,
                        "next_offset": None,
                        "complete": True,
                        "total_chars": len(legacy_content),
                        "content": legacy_content,
                        "exact_artifact": False,
                    }
                )
                return legacy
            exact_text = str(artifact.get("text_full") or "")
            exact_reasoning = str(artifact.get("reasoning_full") or "")
            rendered = "\n\n".join(
                part
                for part in (
                    "[assistant_text]\n" + exact_text if exact_text else "",
                    "[assistant_reasoning]\n" + exact_reasoning if exact_reasoning else "",
                )
                if part
            )
            start = max(0, int(offset or 0))
            # Explicit truncation recovery is allowed to return the exact source up
            # to the caller/tool physical cap. Do not reapply the ordinary 12K
            # resolved-episode display budget after the model asked to read the source.
            width = max(256, int(max_chars or DEFAULT_HYDRATE_CHARS))
            chunk = rendered[start : start + width]
            next_offset = start + len(chunk)
            complete = next_offset >= len(rendered)
            return {
                "ref": wanted,
                "artifact_ref": artifact_ref,
                "offset": start,
                "next_offset": None if complete else next_offset,
                "complete": complete,
                "total_chars": len(rendered),
                "content": chunk,
                "exact_artifact": True,
                "partial_sha256": str(artifact.get("partial_sha256") or ""),
                "reason": str(artifact.get("reason") or ""),
                "provider": str(artifact.get("provider") or ""),
                "model": str(artifact.get("model") or ""),
            }
        return None

    def index_tool_span(
        self,
        session_id: str,
        *,
        ref: str,
        user_seq: int,
        consumer_seq: int,
        raw_messages: list[Message],
    ) -> EpisodeIndexResult:
        """Persist one already-consumed tool span before provider retirement.

        This is deliberately distinct from ``index_episode``: consuming raw tool
        evidence does not prove that the entire user task is resolved.  The entry
        reuses the same append-only/search/hydrate surface so no second retrieval
        store is introduced.
        """

        sid = _validate_session_id(session_id)
        snapshots = [snap for m in raw_messages if (snap := _snapshot_message(m)) is not None]
        if not snapshots or snapshots[0].get("role") != "user":
            raise ValueError("consumed tool span 缺少首个真实 user message")
        if not any(m.get("role") == "tool" for m in snapshots):
            raise ValueError("consumed tool span 缺少 tool evidence")
        if not any(m.get("role") == "assistant" and m.get("tool_calls") for m in snapshots):
            raise ValueError("consumed tool span 缺少 assistant tool declaration")
        if snapshots[-1].get("role") != "assistant" or snapshots[-1].get("tool_calls"):
            raise ValueError("consumed tool span 缺少 non-tool assistant consumer")

        transcript = _render_transcript(snapshots)
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8", "replace")).hexdigest()
        existing = self.get(sid, ref)
        if existing is not None:
            if (
                str(existing.get("transcript_sha256") or "") != transcript_sha256
                or str(existing.get("entry_kind") or "tool_span") != "tool_span"
            ):
                raise ValueError(f"tool span ref collision: {ref}")
            return EpisodeIndexResult(ref=ref, created=False)

        question = str(snapshots[0].get("content") or "")
        assistant_rows = [m for m in snapshots if m.get("role") == "assistant"]
        final_answer = str(assistant_rows[-1].get("content") or "")
        tool_names = list(
            dict.fromkeys(
                str(m.get("tool_name") or "")
                for m in snapshots
                if m.get("role") == "tool" and str(m.get("tool_name") or "")
            )
        )
        indexed_at = _now()
        entry: dict[str, Any] = {
            "schema": EPISODE_SCHEMA,
            "entry_kind": "tool_span",
            "ref": ref,
            "session_id": sid,
            # Keep resolved_at for backward-compatible search ordering; entry_kind
            # makes clear that this does not claim whole-task resolution.
            "resolved_at": indexed_at,
            "indexed_at": indexed_at,
            "user_seq": int(user_seq),
            "consumer_seq": int(consumer_seq),
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
        with path.open("ab") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        return EpisodeIndexResult(ref=ref, created=True)

    def index_closed_tool_span(
        self,
        session_id: str,
        *,
        ref: str,
        user_seq: int,
        terminal_seq: int,
        terminal_reason: str,
        raw_messages: list[Message],
    ) -> EpisodeIndexResult:
        """Persist a failed/closed tool protocol without claiming consumption/resolution."""

        sid = _validate_session_id(session_id)
        reason = str(terminal_reason or "").strip()
        if not reason or reason == "completed":
            raise ValueError("closed tool span 缺少非 completed terminal reason")
        if not raw_messages:
            raise ValueError("closed tool span 缺少消息")
        terminal = raw_messages[-1]
        terminal_md = terminal.metadata if isinstance(terminal.metadata, dict) else {}
        if (
            terminal.role != "assistant"
            or terminal.tool_calls
            or terminal_md.get("answer_origin") != "program"
            or str(terminal_md.get("run_end_reason") or "") != reason
        ):
            raise ValueError("closed tool span terminal 不是匹配的 program/non-success assistant")

        snapshots = [snap for m in raw_messages if (snap := _snapshot_message(m)) is not None]
        if not snapshots or snapshots[0].get("role") != "user":
            raise ValueError("closed tool span 缺少首个真实 user message")
        if not any(m.get("role") == "tool" for m in snapshots):
            raise ValueError("closed tool span 缺少 tool evidence")
        if not any(m.get("role") == "assistant" and m.get("tool_calls") for m in snapshots):
            raise ValueError("closed tool span 缺少 assistant tool declaration")
        if snapshots[-1].get("role") != "assistant" or snapshots[-1].get("tool_calls"):
            raise ValueError("closed tool span 缺少 terminal assistant role frame")

        transcript = _render_transcript(snapshots)
        transcript_sha256 = hashlib.sha256(transcript.encode("utf-8", "replace")).hexdigest()
        existing = self.get(sid, ref)
        if existing is not None:
            if (
                str(existing.get("transcript_sha256") or "") != transcript_sha256
                or str(existing.get("entry_kind") or "") != "closed_tool_span"
                or str(existing.get("terminal_reason") or "") != reason
            ):
                raise ValueError(f"closed tool span ref collision: {ref}")
            return EpisodeIndexResult(ref=ref, created=False)

        question = str(snapshots[0].get("content") or "")
        tool_names = list(
            dict.fromkeys(
                str(m.get("tool_name") or "")
                for m in snapshots
                if m.get("role") == "tool" and str(m.get("tool_name") or "")
            )
        )
        indexed_at = _now()
        entry: dict[str, Any] = {
            "schema": EPISODE_SCHEMA,
            "entry_kind": "closed_tool_span",
            "ref": ref,
            "session_id": sid,
            "resolved_at": indexed_at,
            "indexed_at": indexed_at,
            "user_seq": int(user_seq),
            "terminal_seq": int(terminal_seq),
            "terminal_reason": reason,
            "question": question,
            "final_answer": "",
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
            transcript = _render_transcript(entry.get("messages") or [])
            hay = " ".join(
                [
                    str(entry.get("ref") or ""),
                    str(entry.get("question") or ""),
                    str(entry.get("final_answer") or ""),
                    str(entry.get("terminal_reason") or ""),
                    " ".join(str(x) for x in (entry.get("tool_names") or [])),
                    transcript,
                ]
            ).casefold()
            if q and q not in hay:
                continue
            question = " ".join(str(entry.get("question") or "").split())[:180]
            answer = " ".join(str(entry.get("final_answer") or "").split())[:180]
            tools = ",".join(str(x) for x in (entry.get("tool_names") or [])[:8])
            subtype = str(entry.get("entry_kind") or "episode")
            if subtype == "closed_tool_span":
                reason = str(entry.get("terminal_reason") or "")
                summary = (
                    f"ref={entry.get('ref')} | type=closed_tool_span | "
                    f"reason={reason} | Q={question}"
                )
            else:
                summary = f"ref={entry.get('ref')} | Q={question} | A={answer}"
            if subtype not in {"episode", "closed_tool_span"}:
                summary = f"ref={entry.get('ref')} | type={subtype} | Q={question} | A={answer}"
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
