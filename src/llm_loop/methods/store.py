"""Durable Method store for model-owned reusable reasoning/action methods.

Method records are retrieval assets, never automatic prompt injections. The program owns
identity, lifecycle, provenance and exact bytes; semantic applicability remains model-owned.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.timekeeping import system_local_now

_VALID_STATUSES = {"teacher", "candidate", "qualified", "active", "hold", "invalidated", "retired"}
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_STORE_LOCK_FILE = ".__method_store.lock"
_STAGING_DIR = ".__method_store_staging"
_USAGE_LEDGER_FILE = "usage.jsonl"
_USAGE_WATERMARK_FILE = ".usage_watermark.json"
_DIR_FSYNC_ATTEMPTS = 3
_PROCESS_LOCK = threading.RLock()

logger = logging.getLogger(__name__)

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX retains only in-process exclusion
    fcntl = None  # type: ignore[assignment]


class MethodPersistError(OSError):
    """A Method card mutation did not reach its atomic visibility point."""


class MethodCommitUncertainError(OSError):
    """A card is atomically visible, but the directory durability fence failed.

    The caller must reconcile by exact readback and must not blindly repeat a
    lifecycle transition, qualification, or candidate creation.
    """

    def __init__(
        self, message: str, *, method_ref: str, operation: str,
        expected_sha256: str, visible_state: str,
    ) -> None:
        super().__init__(message)
        self.method_ref = method_ref
        self.operation = operation
        self.expected_sha256 = expected_sha256
        self.visible_state = visible_state


def _normalize_task_type(value: object) -> str:
    """Canonicalize a model-declared qualification task domain (EVO-20261010-994e30f4).

    Free-form by design (browser / code-edit / diagnosis / writing / ...), but
    case/whitespace variants collapse to one token so ``Code Edit``,
    ``code_edit`` and ``code-edit`` count as a single type. Empty or missing
    declarations stay ``unknown`` and never count toward activation diversity.
    """
    text = str(value if value is not None else "").strip().casefold()
    text = "-".join(part for part in text.replace("_", " ").split() if part)
    return text[:64] or "unknown"


@contextlib.contextmanager
def _store_lock(directory: Path):
    """One writer across Web/Feishu/Learning (POSIX flock + process RLock).

    Lock acquisition failures fail closed. Exceptions raised inside the critical
    section retain their type: a lifecycle denial is not a lock failure.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MethodPersistError(f"Method store directory unavailable: {exc}") from exc
    with _PROCESS_LOCK:
        if fcntl is None:
            yield
            return
        fd: int | None = None
        try:
            fd = os.open(directory / _STORE_LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            if fd is not None:
                with contextlib.suppress(OSError):
                    os.close(fd)
            raise MethodPersistError(f"Method store lock unavailable: {exc}") from exc
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(fd)


def _write_file_exclusive(path: Path, payload: bytes) -> None:
    """Create in a non-observable staging location, then fsync file bytes."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)
        raise


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _visible_state(path: Path, payload: bytes) -> str:
    try:
        return "matches" if path.read_bytes() == payload else "mismatch"
    except OSError:
        return "unreadable"

# EVO-20260930-429f7c12: zero-signal candidate ranking decay.  A candidate that
# has never produced any interaction signal (qualification or use declaration)
# keeps its full ranking weight for a grace window (new cards need exposure),
# then sinks by 2 points per idle day up to a cap.  Any recorded signal removes
# the decay entirely — this changes discovery ordering only, never lifecycle
# status, and the disposition evidence gate (EVO-20260929-5283ab1b) is untouched.
_ZERO_SIGNAL_GRACE_DAYS = 7
_ZERO_SIGNAL_DECAY_PER_DAY = 2
_ZERO_SIGNAL_DECAY_CAP = 80

# EVO-20260929-5283ab1b P2 (R5 Card Contract): the persistence layer requires the
# same six sections the generation protocol demands, so a weak model cannot
# bypass structure at the write boundary. Structure only — content quality stays
# model-owned. Matches the reflection renderer exactly (## Trigger ...).
_CARD_SECTIONS: tuple[str, ...] = (
    "Trigger",
    "Discriminator",
    "Short path",
    "Stop conditions",
    "Verification",
    "Counterexamples",
)


def _card_contract_missing(body: str) -> list[str]:
    """Return required sections that are absent, empty, or placeholder ``(none)``."""
    missing: list[str] = []
    for title in _CARD_SECTIONS:
        match = re.search(rf"^##\s+{re.escape(title)}\s*$", body, re.MULTILINE)
        if match is None:
            missing.append(title)
            continue
        rest = body[match.end():]
        nxt = re.search(r"^##\s+", rest, re.MULTILINE)
        chunk = rest[: nxt.start()] if nxt else rest
        text = chunk.strip()
        if not text or text == "(none)":
            missing.append(title)
    return missing


def _checked_freshness_refs(refs: list[str]) -> list[str]:
    """Validate+dedupe workspace-relative freshness_refs (shared by save/annotate)."""
    checked: list[str] = []
    for ref in refs:
        clean = str(ref).strip()
        if not clean:
            continue
        if clean.startswith(("/", "~")) or ".." in clean.split("/") or "\\" in clean:
            raise ValueError(
                f"freshness_refs entries must be workspace-relative paths without '..': {clean}"
            )
        if clean not in checked:
            checked.append(clean)
    return checked


def _now() -> str:
    return system_local_now().isoformat()


def _age_days(ts: str) -> int | None:
    """Whole days between a past host-local ISO timestamp and now; None if unparseable."""
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).strip())
        now = system_local_now()
        if parsed.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        delta = now - parsed
    except (ValueError, TypeError, OverflowError):
        return None
    return max(0, delta.days)


def _scalar(value: str) -> Any:
    raw = value.strip()
    if raw in {"true", "false"}:
        return raw == "true"
    if raw in {"null", "None", "~"}:
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {'"', "'"}:
        return raw[1:-1]
    return raw


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    data: dict[str, Any] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key:
            data[key] = _scalar(value)
    return data, text[match.end():]


@dataclass(frozen=True)
class MethodRecord:
    method_id: str
    name: str
    description: str
    status: str
    body: str
    path: str
    content_hash: str
    source_model: str = ""
    teacher_refs: tuple[str, ...] = ()
    source_episode_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    parent_ref: str = ""
    supersedes: str = ""
    created_at: str = ""
    updated_at: str = ""
    qualification: dict[str, Any] = field(default_factory=dict)
    freshness_refs: tuple[str, ...] = ()

    @property
    def method_ref(self) -> str:
        return f"method:{self.method_id}"

    def card(self) -> dict[str, Any]:
        return {
            "kind": "method",
            "ts": self.updated_at or self.created_at,
            "id": self.method_id,
            "key": self.method_ref,
            "summary": self.name,
            "description": self.description[:500],
            "status": self.status,
            "source_model": self.source_model,
            "content_hash": self.content_hash,
            "projection_complete": False,
            "task_applicability": "not_evaluated",
            "file": self.path,
        }

    def hydrated(self) -> dict[str, Any]:
        result = self.card()
        result.update({
            "body": self.body,
            "teacher_refs": list(self.teacher_refs),
            "source_episode_refs": list(self.source_episode_refs),
            "evidence_refs": list(self.evidence_refs),
            "parent_ref": self.parent_ref,
            "supersedes": self.supersedes,
            "qualification": self.qualification,
            "freshness_refs": list(self.freshness_refs),
            "projection_complete": True,
        })
        return result


class MethodStore:
    """Two-tier Method store: reviewed seed assets plus private runtime overlays."""

    def __init__(
        self,
        methods_dir: str | Path,
        *,
        seed_dir: str | Path | None = None,
        write_guard: Callable[[], bool] | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self._dir = Path(methods_dir)
        self._seed_dir = Path(seed_dir) if seed_dir is not None else None
        self._write_guard = write_guard
        self._post_save_hooks: list[Callable[[MethodRecord], None]] = []
        # EVO-20260930-429f7c12: per-file signal cache keyed by path; value stamp
        # is (mtime_ns, size) so external lifecycle writes invalidate correctly.
        self._signal_stamp_cache: dict[str, tuple[int, int]] = {}
        self._signal_value_cache: dict[str, Any] = {}
        if workspace_root is not None:
            self._workspace_root = Path(workspace_root).resolve()
        elif self._seed_dir is not None:
            self._workspace_root = self._seed_dir.resolve().parent
        else:
            self._workspace_root = None

    def add_post_save_hook(self, hook: Callable[[MethodRecord], None]) -> None:
        """Register a fail-open observer for newly persisted semantic Method content."""
        if hook not in self._post_save_hooks:
            self._post_save_hooks.append(hook)

    def _notify_post_save(self, record: MethodRecord) -> None:
        for hook in list(self._post_save_hooks):
            try:
                hook(record)
            except Exception:  # noqa: BLE001 - Method durability outranks derived vectors
                continue

    def _require_write_safe(self) -> None:
        if self._write_guard is None:
            return
        try:
            allowed = bool(self._write_guard())
        except Exception as exc:  # noqa: BLE001 — health failure must fail closed for mutation
            raise PermissionError("knowledge store quarantined: write health unavailable") from exc
        if not allowed:
            raise PermissionError("knowledge store quarantined: mutation disabled")

    def _fsync_or_uncertain(
        self, path: Path, payload: bytes, method_ref: str,
        operation: str, directories: tuple[Path, ...],
    ) -> None:
        """Fsync directory entries without replaying an already-visible mutation."""
        for directory in directories:
            last_error: OSError | None = None
            for _ in range(_DIR_FSYNC_ATTEMPTS):
                try:
                    _fsync_directory(directory)
                    break
                except OSError as exc:
                    last_error = exc
            else:
                raise MethodCommitUncertainError(
                    f"Method {operation} atomically visible but directory fsync unconfirmed: {last_error}",
                    method_ref=method_ref,
                    operation=operation,
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                    visible_state=_visible_state(path, payload),
                )

    def _commit_new_directory(
        self, method_id: str, files: dict[str, bytes], *, operation: str,
    ) -> Path:
        """Atomically publish a complete new Method directory from invisible staging.

        Used for both first candidate writes and seed overlays. The stage is
        two levels below the store root, so ordinary */METHOD.md discovery does
        not expose in-flight cards. Only the final rename makes them visible.
        Call under the store's single-writer lock.
        """
        dest = self._dir / method_id
        if dest.exists():
            raise FileExistsError(f"Method runtime directory exists: {dest}")
        stage_root = self._dir / _STAGING_DIR
        stage = stage_root / f"{method_id}.{uuid.uuid4().hex}.stage"
        try:
            stage_root.mkdir(exist_ok=True)
            stage.mkdir(mode=0o700)
            for filename, data in files.items():
                if filename not in {"METHOD.md", "qualification.json"}:
                    raise ValueError(f"invalid staged Method filename: {filename}")
                _write_file_exclusive(stage / filename, data)
            _fsync_directory(stage)
            os.rename(stage, dest)
        except FileExistsError:
            raise
        except OSError as exc:
            raise MethodPersistError(f"Method {operation} not committed: {exc}") from exc
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
        payload = files["METHOD.md"]
        self._fsync_or_uncertain(
            dest / "METHOD.md", payload, f"method:{method_id}", operation,
            (self._dir, stage_root),
        )
        return dest

    def _replace_card(self, path: Path, payload: str, *, operation: str) -> None:
        """Single-writer atomic RMW card replacement; no in-place truncation."""
        data = payload.encode("utf-8")
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:12]}.tmp")
        try:
            _write_file_exclusive(temp, data)
            os.replace(temp, path)
        except OSError as exc:
            raise MethodPersistError(f"Method {operation} not committed: {exc}") from exc
        finally:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
        self._fsync_or_uncertain(
            path, data, f"method:{path.parent.name}", operation, (path.parent,),
        )

    @staticmethod
    def _safe_id(value: str) -> str:
        candidate = value.strip().lower()
        if not _SAFE_ID_RE.fullmatch(candidate):
            raise ValueError("method_id must match [a-z0-9][a-z0-9._-]{0,127}")
        return candidate

    def _iter_paths(self) -> list[Path]:
        # ASSESS-20261008 BUG-18: seed → runtime 显式覆盖——同 ID 冲突由来源身份
        # 决定（Runtime copy wins），各来源内部确定性排序。原实现把两类路径整体
        # sorted 后用后者覆盖，优先级实际取决于目录字典序（z-seed/a-runtime 下
        # seed 会赢），与注释意图相反。
        by_id: dict[str, Path] = {}
        if self._seed_dir is not None and self._seed_dir.exists():
            for path in sorted(self._seed_dir.glob("*/METHOD.md")):
                by_id[path.parent.name] = path
        if self._dir.exists():
            for path in sorted(self._dir.glob("*/METHOD.md")):
                by_id[path.parent.name] = path
        return [by_id[k] for k in sorted(by_id)]

    def _load_path(self, path: Path) -> MethodRecord | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        meta, body = _parse_frontmatter(raw)
        method_id = str(meta.get("method_id") or meta.get("name") or path.parent.name).strip().lower()
        if not _SAFE_ID_RE.fullmatch(method_id):
            return None
        status = str(meta.get("status") or "candidate").strip().lower()
        if status not in _VALID_STATUSES:
            return None
        def tuple_field(name: str) -> tuple[str, ...]:
            value = meta.get(name, "")
            return tuple(v.strip() for v in value.split(",") if v.strip()) if isinstance(value, str) else ()
        qualification: dict[str, Any] = {}
        qfile = path.parent / "qualification.json"
        if qfile.exists():
            try:
                value = json.loads(qfile.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    qualification = value
            except (OSError, json.JSONDecodeError):
                qualification = {"state": "unreadable"}
        return MethodRecord(
            method_id=method_id,
            name=str(meta.get("title") or meta.get("name") or method_id),
            description=str(meta.get("description") or ""),
            status=status,
            body=body.strip(),
            path=str(path),
            content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            source_model=str(meta.get("source_model") or ""),
            teacher_refs=(
                tuple_field("teacher_refs")
                or ((str(meta.get("teacher_ref") or "").strip(),) if str(meta.get("teacher_ref") or "").strip() else ())
            ),
            source_episode_refs=tuple_field("source_episode_refs"),
            evidence_refs=tuple_field("evidence_refs"),
            parent_ref=str(meta.get("parent_ref") or ""),
            supersedes=str(meta.get("supersedes") or ""),
            created_at=str(meta.get("created_at") or ""),
            updated_at=str(meta.get("updated_at") or ""),
            qualification=qualification,
            freshness_refs=tuple_field("freshness_refs"),
        )

    def get(self, method_ref: str) -> MethodRecord | None:
        method_id = method_ref.removeprefix("method:").strip().lower()
        if not _SAFE_ID_RE.fullmatch(method_id):
            return None
        runtime_path = self._dir / method_id / "METHOD.md"
        if runtime_path.exists():
            return self._load_path(runtime_path)
        if self._seed_dir is not None:
            seed_path = self._seed_dir / method_id / "METHOD.md"
            if seed_path.exists():
                return self._load_path(seed_path)
        return None

    def recover(self) -> dict[str, Any]:
        """Read-only T2 recovery inventory; never auto-delete or promote cards.

        A staged partial directory is outside normal Method discovery and needs
        operator review, not implicit deletion. Report invalid and incomplete
        runtime entries separately instead of silently treating them as cards.
        """
        report: dict[str, Any] = {
            "exists": self._dir.is_dir(), "records": 0,
            "invalid_records": [], "incomplete_dirs": [],
            "unclassified_dirs": [], "orphan_stages": [],
        }
        if not self._dir.is_dir():
            return report
        stage_root = self._dir / _STAGING_DIR
        if stage_root.is_dir():
            report["orphan_stages"] = sorted(p.name for p in stage_root.iterdir())
        for directory in sorted(self._dir.iterdir()):
            if not directory.is_dir() or not _SAFE_ID_RE.fullmatch(directory.name):
                continue
            path = directory / "METHOD.md"
            if not path.is_file():
                # A plain foreign directory is not proof of a failed Method
                # commit. Only Method-specific residual files indicate an
                # incomplete old overlay; surface all others without claiming.
                names = {p.name for p in directory.iterdir()}
                if names.intersection({"qualification.json", "qualification.jsonl"}) or any(
                    name.startswith("METHOD.") for name in names
                ):
                    report["incomplete_dirs"].append(directory.name)
                else:
                    report["unclassified_dirs"].append(directory.name)
            elif self._load_path(path) is None:
                report["invalid_records"].append(directory.name)
            else:
                report["records"] += 1
        return report

    @staticmethod
    def _search_terms(query: str) -> list[str]:
        """Normalize discovery terms without assigning semantic applicability.

        Hyphenated stable-id fragments become separately searchable (``poc-a-b`` ->
        ``poc``), while CJK runs remain intact. This is intentionally mechanical.
        """
        raw = query.lower().strip()
        return [t for t in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+", raw) if t]

    @staticmethod
    def _normalized_search_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))

    def _freshness_snapshot(self, record: MethodRecord) -> dict[str, str]:
        if not record.freshness_refs or self._workspace_root is None:
            return {}
        out: dict[str, str] = {}
        root = self._workspace_root
        for raw in record.freshness_refs:
            rel = Path(raw)
            if rel.is_absolute() or ".." in rel.parts:
                out[raw] = "unsupported"
                continue
            target = (root / rel).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                out[raw] = "unsupported"
                continue
            if not target.is_file():
                out[raw] = "missing"
                continue
            try:
                out[raw] = hashlib.sha256(target.read_bytes()).hexdigest()
            except OSError:
                out[raw] = "unreadable"
        return out

    def freshness(self, method_ref: str) -> dict[str, Any]:
        record = self.get(method_ref)
        if record is None:
            return {"state": "missing_method", "refs": []}
        if not record.freshness_refs:
            return {"state": "not_tracked", "refs": []}
        current = self._freshness_snapshot(record)
        baseline: dict[str, str] | None = None
        for entry in reversed(self.qualification_entries(method_ref)):
            value = entry.get("freshness_hashes")
            if isinstance(value, dict):
                baseline = {str(k): str(v) for k, v in value.items()}
                break
        if baseline is None:
            return {"state": "unbaselined", "refs": list(record.freshness_refs), "current": current}
        changed = [ref for ref in record.freshness_refs if current.get(ref) != baseline.get(ref)]
        missing = [ref for ref in record.freshness_refs if current.get(ref) == "missing"]
        state = "current" if not changed else ("missing" if missing else "changed")
        return {
            "state": state,
            "refs": list(record.freshness_refs),
            "changed_refs": changed,
            "missing_refs": missing,
            "current": current,
            "baseline": baseline,
        }

    def _last_signal_ts(self, record: MethodRecord) -> str:
        """Latest interaction-signal timestamp (qualification or use), '' when none.

        EVO-20260930-429f7c12: both sources are appended with host-local ISO
        timestamps of the same format, so lexicographic max is chronological max.
        """
        usage_index = self._usage_last_signal_index()
        usage_ts = usage_index.get(record.method_ref, "")
        qual_ts = self._qualification_last_signal(record)
        return max(usage_ts, qual_ts)

    def _usage_last_signal_index(self) -> dict[str, str]:
        path = self._dir / "usage.jsonl"
        cache_key = f"usage:{path}"
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._signal_stamp_cache.pop(cache_key, None)
            self._signal_value_cache.pop(cache_key, None)
            return {}
        if self._signal_stamp_cache.get(cache_key) == stamp and cache_key in self._signal_value_cache:
            value = self._signal_value_cache[cache_key]
            return dict(value) if isinstance(value, dict) else {}
        index: dict[str, str] = {}
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                ref = str(entry.get("method_ref") or "").strip().lower()
                ts = str(entry.get("ts") or "").strip()
                if ref and ts and ts > index.get(ref, ""):
                    index[ref] = ts
        except OSError:
            index = {}
        self._signal_stamp_cache[cache_key] = stamp
        self._signal_value_cache[cache_key] = index
        return dict(index)

    def _qualification_last_signal(self, record: MethodRecord) -> str:
        path = Path(record.path).parent / "qualification.jsonl"
        cache_key = f"qual:{path}"
        try:
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._signal_stamp_cache.pop(cache_key, None)
            self._signal_value_cache.pop(cache_key, None)
            return ""
        if self._signal_stamp_cache.get(cache_key) == stamp and cache_key in self._signal_value_cache:
            return str(self._signal_value_cache[cache_key])
        latest = ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                ts = str(entry.get("ts") or "").strip()
                if ts > latest:
                    latest = ts
        except OSError:
            latest = ""
        self._signal_stamp_cache[cache_key] = stamp
        self._signal_value_cache[cache_key] = latest
        return latest

    def _attach_last_signal_age(self, card: dict[str, Any], record: MethodRecord) -> None:
        """Project days since the latest interaction signal; None means zero signals ever."""
        last = self._last_signal_ts(record)
        card["last_signal_age_days"] = _age_days(last)

    def list(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        query = query.strip()
        if query.lower().startswith("method:"):
            record = self.get(query)
            if record is None:
                return []
            hydrated = record.hydrated()
            self._attach_last_signal_age(hydrated, record)
            hydrated["qualification_entries"] = self.qualification_entries(query)
            hydrated["freshness"] = self.freshness(query)
            return [hydrated]
        terms = self._search_terms(query)
        # Generic lifecycle nouns are useful as standalone inventory queries, but when
        # mixed with task language they add noise rather than discrimination.
        if len(terms) > 1:
            specific = [t for t in terms if t not in {"method", "candidate", "qualified", "active"}]
            if specific:
                terms = specific
        raw_chunks = [chunk for chunk in re.split(r"\s+", query.lower()) if chunk]
        ranked: list[tuple[int, float, MethodRecord]] = []
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status == "retired":
                continue
            id_text = self._normalized_search_text(record.method_id + " " + record.method_ref)
            name_text = self._normalized_search_text(record.name)
            desc_text = self._normalized_search_text(record.description)
            body_text = self._normalized_search_text(record.body)
            fields = ((id_text, 10), (name_text, 8), (desc_text, 4), (body_text, 1))
            matched = 0
            lexical = 0
            for term in terms:
                term_score = max((weight for text, weight in fields if term in text), default=0)
                if term_score:
                    matched += 1
                    lexical += term_score
            identifier_bonus = 0
            for chunk in raw_chunks:
                # A stable-id-like fragment is strong mechanical evidence of identity.
                # This fixes historical misses such as `poc-a-b` without treating it as
                # a guessed exact `method:<id>` hydration ref.
                if "-" not in chunk:
                    continue
                chunk_norm = self._normalized_search_text(chunk)
                if len(chunk_norm) >= 3 and chunk_norm in id_text:
                    identifier_bonus = max(identifier_bonus, 250)
            if terms and matched == 0 and identifier_bonus == 0:
                continue
            coverage = (matched / len(terms)) if terms else 0.0
            life = {"active": 35, "qualified": 25, "candidate": 0, "teacher": -5, "hold": -10, "invalidated": -20}.get(record.status, -25)
            # EVO-20260930-429f7c12: a candidate with zero interaction signals
            # decays with idle age so mass-generated cards cannot crowd out
            # qualified/active ones on lexical score alone. Any qualification
            # or use declaration restores full weight permanently.
            if record.status == "candidate" and not self._last_signal_ts(record):
                age = _age_days(record.created_at)
                if age is not None and age > _ZERO_SIGNAL_GRACE_DAYS:
                    life -= min(
                        _ZERO_SIGNAL_DECAY_CAP,
                        (age - _ZERO_SIGNAL_GRACE_DAYS) * _ZERO_SIGNAL_DECAY_PER_DAY,
                    )
            score = identifier_bonus + lexical * 10 + int(coverage * 50) + life
            ranked.append((score, coverage, record))
        ranked.sort(key=lambda item: (item[0], item[1], item[2].method_id), reverse=True)
        result: list[dict[str, Any]] = []
        for _, _, record in ranked[:max(0, limit)]:
            card = record.card()
            self._attach_last_signal_age(card, record)
            if record.freshness_refs:
                card["freshness"] = self.freshness(record.method_ref)
            result.append(card)
        return result

    @staticmethod
    def semantic_candidate(record: MethodRecord) -> dict[str, Any]:
        return {
            "kind": "method",
            "id": record.method_id,
            "key": record.method_ref,
            "content": (
                f"{record.method_id} {record.name} {record.description} {record.body}"
            ),
        }

    def semantic_candidates(self) -> list[dict[str, Any]]:
        """Project Method records for mechanical semantic recall.

        The projection exposes content for vectorization only; it does not assert task
        applicability and retired records stay excluded exactly as in lexical discovery.
        """
        result: list[dict[str, Any]] = []
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status == "retired":
                continue
            result.append(self.semantic_candidate(record))
        return result

    def _ensure_runtime_copy(self, record: MethodRecord) -> MethodRecord:
        """Publish a complete seed overlay before any mutable lifecycle write.

        Requires the store lock; first-time overlays are committed as an atomic
        directory rename with the seed qualification summary included.
        """
        source = Path(record.path)
        runtime_path = self._dir / record.method_id / "METHOD.md"
        if runtime_path.exists():
            current = self._load_path(runtime_path)
            if current is None:
                raise ValueError("runtime Method overlay is unreadable")
            return current
        # Runtime-created candidates already live under self._dir and need no copy.
        try:
            source.resolve().relative_to(self._dir.resolve())
            source_is_runtime = True
        except ValueError:
            source_is_runtime = False
        if source_is_runtime:
            return record
        # Seed-side qualification summary is shipped evidence, not mutable runtime state.
        seed_q = source.parent / "qualification.json"
        files = {"METHOD.md": source.read_bytes()}
        if seed_q.is_file():
            files["qualification.json"] = seed_q.read_bytes()
        self._commit_new_directory(record.method_id, files, operation="seed_overlay")
        copied = self._load_path(runtime_path)
        if copied is None:
            raise RuntimeError("runtime Method overlay did not round-trip")
        return copied

    def record_use(
        self,
        method_ref: str,
        *,
        episode_ref: str,
        decision: str,
        note: str = "",
        model: str = "",
        evidence_refs: list[str] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Serialize use evidence with any destructive disposition it may support."""
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._record_use_locked(
                method_ref, episode_ref=episode_ref, decision=decision,
                note=note, model=model, evidence_refs=evidence_refs,
                session_id=session_id,
            )

    def _record_use_locked(
        self,
        method_ref: str,
        *,
        episode_ref: str,
        decision: str,
        note: str = "",
        model: str = "",
        evidence_refs: list[str] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Append one model-authored Method applicability/use declaration.

        This is observability, not qualification: it never changes lifecycle status and
        never proves task benefit. Seed Methods are not copied into the runtime overlay
        merely because the model declared how it treated them.
        session_id (EVO-20260923-618f7fd1 ②) is optional provenance used by the
        goal-level method_use_gate; legacy entries without it simply never match.
        """
        record = self.get(method_ref)
        if record is None:
            raise FileNotFoundError(method_ref)
        allowed = {"applied", "adapted", "not_applicable", "rejected"}
        clean_decision = decision.strip().lower()
        if clean_decision not in allowed:
            raise ValueError(f"decision must be one of {sorted(allowed)}")
        clean_episode = episode_ref.strip()
        if not clean_episode.startswith("episode:"):
            raise ValueError("Method use declaration requires runtime episode provenance")
        entry = {
            "ts": _now(),
            "method_ref": record.method_ref,
            "method_content_hash": record.content_hash,
            "method_status": record.status,
            "episode_ref": clean_episode,
            "decision": clean_decision,
            "model": model.strip()[:256],
            "evidence_refs": [str(v).strip() for v in (evidence_refs or []) if str(v).strip()],
            "note": note.strip()[:2000],
            "application_proven": clean_decision in {"applied", "adapted"},
            "task_benefit": "not_evaluated",
            "promotion": "not_evaluated",
        }
        clean_session = session_id.strip()[:128]
        if clean_session:
            entry["session_id"] = clean_session
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / _USAGE_LEDGER_FILE
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._refresh_usage_watermark_locked()
        return entry

    def _count_usage_lines(self) -> int:
        """Count non-empty usage ledger lines; unreadable ledger reports zero."""
        path = self._dir / _USAGE_LEDGER_FILE
        if not path.is_file():
            return 0
        count = 0
        try:
            with path.open("rb") as f:
                for raw in f:
                    if raw.strip():
                        count += 1
        except OSError:
            return 0
        return count

    def _refresh_usage_watermark_locked(self) -> None:
        """Keep a monotonic line-count watermark for the append-only usage ledger.

        EVO-20261010 usage-ledger loss: ``record_use`` had fsync'd and returned
        success, yet the uncommitted append was later destroyed by a git
        tree-clean revert because the ledger was also a tracked file. The
        watermark never gates writes and never ratchets down; it only makes
        external truncation observable at the next integrity check.
        Call under the store's single-writer lock.
        """
        wm_path = self._dir / _USAGE_WATERMARK_FILE
        previous = 0
        try:
            previous = int(json.loads(wm_path.read_text(encoding="utf-8")).get("count", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            previous = 0
        count = max(previous, self._count_usage_lines())
        try:
            payload = json.dumps({"count": count, "ts": _now()}, sort_keys=True)
            with wm_path.open("w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:  # noqa: BLE001 - watermark is observability, not a write gate
            logger.warning("usage watermark refresh failed (non-fatal): %s", exc)

    def check_usage_integrity(self) -> dict[str, Any]:
        """Report ledger-vs-watermark drift without mutating either file.

        ``lost > 0`` means the ledger currently holds fewer entries than the
        high-water mark of successful fsync'd appends: entries were removed by
        an external actor (git revert, manual edit, partial restore).
        """
        wm_path = self._dir / _USAGE_WATERMARK_FILE
        try:
            watermark = json.loads(wm_path.read_text(encoding="utf-8"))
            watermark_count = int(watermark.get("count", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"monitored": False, "lost": 0}
        current = self._count_usage_lines()
        lost = max(watermark_count - current, 0)
        report: dict[str, Any] = {
            "monitored": True,
            "lost": lost,
            "watermark_count": watermark_count,
            "current_count": current,
            "watermark_ts": str(watermark.get("ts", "")),
        }
        if lost:
            logger.error(
                "method usage ledger lost %d entr%s (watermark=%d current=%d watermark_ts=%s)",
                lost, "y" if lost == 1 else "ies", watermark_count, current, report["watermark_ts"],
            )
        return report

    def usage_entries(self, method_ref: str = "") -> list[dict[str, Any]]:
        """Read bounded-size local use declarations; semantic interpretation stays model-owned."""
        path = self._dir / "usage.jsonl"
        if not path.is_file():
            return []
        wanted = method_ref.strip().lower()
        result: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                if wanted and str(value.get("method_ref", "")).lower() != wanted:
                    continue
                result.append(value)
        except OSError:
            return []
        return result

    def record_qualification(
        self,
        method_ref: str,
        *,
        task_ref: str,
        verdict: str,
        mechanism: str = "not_evaluated",
        task_benefit: str = "not_evaluated",
        promotion: str = "not_evaluated",
        evidence_refs: list[str] | None = None,
        note: str = "",
        evaluator: str = "model",
        task_type: str = "unknown",
    ) -> dict[str, Any]:
        """Serialize seed overlay creation and qualification append with lifecycle RMW."""
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._record_qualification_locked(
                method_ref, task_ref=task_ref, verdict=verdict, mechanism=mechanism,
                task_benefit=task_benefit, promotion=promotion,
                evidence_refs=evidence_refs, note=note, evaluator=evaluator,
                task_type=task_type,
            )

    def _record_qualification_locked(
        self,
        method_ref: str,
        *,
        task_ref: str,
        verdict: str,
        mechanism: str = "not_evaluated",
        task_benefit: str = "not_evaluated",
        promotion: str = "not_evaluated",
        evidence_refs: list[str] | None = None,
        note: str = "",
        evaluator: str = "model",
        task_type: str = "unknown",
    ) -> dict[str, Any]:
        """Append a bounded qualification declaration without changing lifecycle status."""
        record = self.get(method_ref)
        if record is None:
            raise FileNotFoundError(method_ref)
        allowed = {"pass", "fail", "mixed", "insufficient", "not_evaluated"}
        fields = {"verdict": verdict, "mechanism": mechanism, "task_benefit": task_benefit, "promotion": promotion}
        for key, value in fields.items():
            if value not in allowed:
                raise ValueError(f"{key} must be one of {sorted(allowed)}")
        clean_task_ref = task_ref.strip()
        if promotion == "pass" and clean_task_ref in set(record.source_episode_refs):
            raise ValueError("promotion=pass qualification must be independent of the candidate source episode")
        if promotion == "pass" and not clean_task_ref.startswith("episode:"):
            raise ValueError(
                "promotion=pass qualification must reference a real episode ref (episode:...); "
                "model-invented refs cannot prove independence"
            )
        record = self._ensure_runtime_copy(record)
        entry = {
            "ts": _now(),
            # Canonical runtime provenance.  ``task_ref`` is retained as a
            # read-compatible alias for existing qualification.jsonl readers;
            # model-facing code must not supply either identity.
            "qualification_episode_ref": clean_task_ref,
            "task_ref": clean_task_ref,
            "verdict": verdict,
            "mechanism": mechanism,
            "task_benefit": task_benefit,
            "promotion": promotion,
            "evidence_refs": [str(v).strip() for v in (evidence_refs or []) if str(v).strip()],
            "note": note.strip()[:4000],
            "evaluator": evaluator.strip()[:128] or "model",
            # EVO-20261010-994e30f4: model-declared task domain of the
            # qualification episode. Old entries without this key read as
            # "unknown" and never count toward activation diversity.
            "task_type": _normalize_task_type(task_type),
        }
        freshness_hashes = self._freshness_snapshot(record)
        if freshness_hashes:
            entry["freshness_hashes"] = freshness_hashes
        qpath = Path(record.path).parent / "qualification.jsonl"
        with qpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    def qualification_entries(self, method_ref: str) -> list[dict[str, Any]]:
        record = self.get(method_ref)
        if record is None:
            return []
        path = Path(record.path).parent / "qualification.jsonl"
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    result.append(value)
        except OSError:
            return []
        return result

    def _blocked(self, method_ref: str, requested: str, missing_fact: str, detail: str, *, episode_ref: str = "") -> dict[str, Any]:
        """Journal a mechanically blocked transition, then let the caller raise.

        Never raises itself: a journaling failure must not mask the original
        lifecycle error. See note_blocked_transition for the durable contract.
        """
        try:
            return self.note_blocked_transition(
                method_ref, requested=requested, missing_fact=missing_fact, detail=detail, episode_ref=episode_ref
            )
        except Exception:
            return {"journal_persisted": False}

    def _disposition_basis(self, record: MethodRecord) -> dict[str, Any]:
        """Mechanical independence facts backing a destructive disposition.

        Structure only: the program reports which independent evidence exists
        (a qualification verdict=fail, or rejected use declarations from >=2
        distinct episodes). It never weighs whether that evidence is *enough*
        to kill the Method — that judgment belongs to the caller.
        """
        basis: dict[str, Any] = {}
        fail_entries = [
            e for e in self.qualification_entries(record.method_ref)
            if e.get("verdict") == "fail"
        ]
        if fail_entries:
            basis["independent_qualification_fail"] = [
                str(e.get("qualification_episode_ref") or e.get("task_ref") or "") for e in fail_entries
            ]
        rejected_episodes: list[str] = []
        for entry in self.usage_entries(record.method_ref):
            if entry.get("decision") == "rejected":
                ref = str(entry.get("episode_ref", ""))
                if ref and ref not in rejected_episodes:
                    rejected_episodes.append(ref)
        if len(rejected_episodes) >= 2:
            basis["cross_episode_rejected"] = rejected_episodes
        return basis

    def note_blocked_transition(
        self,
        method_ref: str,
        *,
        requested: str,
        missing_fact: str,
        detail: str = "",
        episode_ref: str = "",
    ) -> dict[str, Any]:
        """Durably journal a lifecycle transition that was attempted and mechanically blocked.

        EVO-20260929-5283ab1b P1 (R4 as journal, not a new lifecycle state):
        historically a failed qualify (e.g. promotion=pass missing) left zero
        durable trace and the candidate silently decayed. This append-only
        journal keeps the attempt retrievable and countable; it never mutates
        lifecycle status and never interprets why the model tried.
        """
        record = self.get(method_ref)
        entry: dict[str, Any] = {
            "ts": _now(),
            "event": "lifecycle_transition_attempt",
            "method_ref": method_ref,
            "method_status": record.status if record is not None else "unknown",
            "requested": requested,
            "result": "blocked",
            "missing_fact": missing_fact,
            "episode_ref": episode_ref.strip()[:256],
            "detail": detail.strip()[:500],
        }
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            entry["journal_persisted"] = True
            path = self._dir / "lifecycle_attempts.jsonl"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            entry["journal_persisted"] = False
        return entry

    def attempt_entries(self, method_ref: str = "") -> list[dict[str, Any]]:
        """Read blocked lifecycle-transition attempts; mechanical facts only."""
        path = self._dir / "lifecycle_attempts.jsonl"
        if not path.is_file():
            return []
        wanted = method_ref.strip().lower()
        result: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                if wanted and str(value.get("method_ref", "")).lower() != wanted:
                    continue
                result.append(value)
        except OSError:
            return []
        return result

    def update_status(self, method_ref: str, target_status: str, *, episode_ref: str = "") -> MethodRecord:
        """Serialize lifecycle checks, seed overlay, and atomic card transition."""
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._update_status_locked(method_ref, target_status, episode_ref=episode_ref)

    def _update_status_locked(self, method_ref: str, target_status: str, *, episode_ref: str = "") -> MethodRecord:
        """Mechanical lifecycle transition; semantic choice belongs to the caller/model/owner.

        Activating a candidate directly is rejected. A method must first pass through qualified,
        so a same-episode self-distillation cannot become active in one write.
        """
        record = self.get(method_ref)
        if record is None:
            raise FileNotFoundError(method_ref)
        record = self._ensure_runtime_copy(record)
        target = target_status.strip().lower()
        if target not in _VALID_STATUSES:
            raise ValueError(f"invalid method status: {target}")
        if record.status == "teacher" and target != "teacher":
            self._blocked(method_ref, target, "teacher_immutable", "teacher lifecycle is immutable", episode_ref=episode_ref)
            raise ValueError("teacher lifecycle is immutable; create a candidate distilled from it")
        if record.status == "candidate" and target == "active":
            self._blocked(method_ref, target, "independent_qualification", "candidate -> active is forbidden", episode_ref=episode_ref)
            raise ValueError("candidate cannot become active directly; qualify independently first")
        if target == "qualified":
            entries = self.qualification_entries(method_ref)
            if not any(
                e.get("promotion") == "pass"
                and (e.get("qualification_episode_ref") or e.get("task_ref"))
                for e in entries
            ):
                self._blocked(method_ref, target, "promotion_pass", "no promotion=pass with episode provenance", episode_ref=episode_ref)
                raise ValueError(
                    "qualified requires at least one promotion=pass qualification with runtime episode provenance"
                )
        if target == "active" and record.status != "active":
            # EVO-20261010-994e30f4: activation requires cross-task-type
            # qualification. task_type is a model declaration; the program
            # cannot verify task domains, so the gate only counts distinct
            # declared types among verdict=pass entries ("unknown" never
            # counts; the source task counts as one). Cards that are already
            # active are grandfathered: the check applies to transitions into
            # active only, never retroactively.
            distinct_types = {
                _normalize_task_type(e.get("task_type"))
                for e in self.qualification_entries(method_ref)
                if e.get("verdict") == "pass"
            }
            distinct_types.discard("unknown")
            if len(distinct_types) < 2:
                self._blocked(
                    method_ref, target, "cross_task_type_qualification",
                    f"distinct pass task_type count={len(distinct_types)} (<2)",
                    episode_ref=episode_ref,
                )
                raise ValueError(
                    "activation requires cross-task-type qualification: record "
                    "verdict=pass qualifications spanning >=2 distinct task_type "
                    "values (source domain plus at least one other); missing/unknown "
                    "task_type does not count"
                )
        # EVO-20260929-5283ab1b P1 (R3): destructive disposition needs independent
        # factual basis. The program never decides a Method *should* die; it only
        # refuses to record a conviction resting solely on one session's own
        # self-judgment. reopen stays permanently available (nothing is deleted).
        if (
            target in {"invalidated", "retired"}
            and record.status not in {"invalidated", "retired"}
            and not self._disposition_basis(record)
        ):
            self._blocked(method_ref, target, "independent_disposition_evidence", "no independent basis", episode_ref=episode_ref)
            raise ValueError(
                "destructive disposition (invalidate/retire) requires independent factual basis: "
                "one qualification with verdict=fail, or rejected use declarations from >=2 distinct "
                "episodes; record the evidence first, then retry the disposition"
            )
        path = Path(record.path)
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        meta["status"] = target
        meta["updated_at"] = _now()
        ordered = ["method_id", "name", "description", "status", "source_model", "teacher_refs", "source_episode_refs", "evidence_refs", "freshness_refs", "parent_ref", "supersedes", "created_at", "updated_at"]
        lines: list[str] = []
        for key in ordered:
            value = meta.pop(key, None)
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        for key in sorted(meta):
            value = meta[key]
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        self._replace_card(
            path, "---\n" + "\n".join(lines) + "\n---\n" + body.strip() + "\n",
            operation="update_status",
        )
        updated = self._load_path(path)
        if updated is None:
            raise RuntimeError("method lifecycle update did not round-trip")
        return updated

    def save_candidate(
        self,
        *,
        name: str,
        description: str,
        body: str,
        source_model: str = "",
        teacher_refs: list[str] | None = None,
        source_episode_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        parent_ref: str = "",
        freshness_refs: list[str] | None = None,
    ) -> MethodRecord:
        """Write-once candidate publication; derived hooks run only on certain commits."""
        self._require_write_safe()
        with _store_lock(self._dir):
            record, created = self._save_candidate_locked(
                name=name, description=description, body=body,
                source_model=source_model, teacher_refs=teacher_refs,
                source_episode_refs=source_episode_refs, evidence_refs=evidence_refs,
                parent_ref=parent_ref, freshness_refs=freshness_refs,
            )
        if created:
            self._notify_post_save(record)
        return record

    def _save_candidate_locked(
        self,
        *,
        name: str,
        description: str,
        body: str,
        source_model: str = "",
        teacher_refs: list[str] | None = None,
        source_episode_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        parent_ref: str = "",
        freshness_refs: list[str] | None = None,
    ) -> tuple[MethodRecord, bool]:
        """Persist semantic content supplied by the model; never overwrite or auto-promote."""
        # P2 Card Contract: the persistence boundary demands the same structure
        # the generation protocol promises. Applies to new writes only; the
        # existing pool is never retroactively rescanned.
        missing_sections = _card_contract_missing(body)
        if missing_sections:
            raise ValueError(
                "Method Card contract violation: body must contain non-empty sections "
                f"{list(_CARD_SECTIONS)} (missing/empty: {missing_sections})"
            )
        # P3 freshness_refs: model-declared workspace-relative paths baselined at
        # qualification time; freshness() later reports current/changed/missing
        # as mechanical facts and never downgrades lifecycle on drift.
        checked_freshness_refs = _checked_freshness_refs(freshness_refs or [])
        if parent_ref and self.get(parent_ref) is None:
            raise ValueError(f"parent_ref not found: {parent_ref}")
        checked_teachers: list[str] = []
        for teacher_ref in teacher_refs or []:
            teacher = self.get(teacher_ref)
            if teacher is None or teacher.status != "teacher":
                raise ValueError(f"teacher_ref must identify a teacher Method: {teacher_ref}")
            checked_teachers.append(teacher.method_ref)
        checked_episode_refs: list[str] = []
        for ref in source_episode_refs or []:
            clean = str(ref).strip()
            if not clean:
                continue
            if not clean.startswith("episode:"):
                raise ValueError(
                    f"source_episode_refs entries must be real episode refs (episode:...), got: {clean}"
                )
            checked_episode_refs.append(clean)
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:72] or "candidate"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        method_id = self._safe_id(f"{base}-{digest}")
        out_dir = self._dir / method_id
        path = out_dir / "METHOD.md"
        if path.exists():
            record = self._load_path(path)
            if record is None:
                raise ValueError("existing candidate is unreadable")
            return record, False
        if out_dir.exists():
            raise MethodPersistError("Method directory exists without readable METHOD.md; reconcile before saving")
        now = _now()
        def line(k: str, v: str) -> str:
            clean = v.replace("\n", " ").strip()
            return f"{k}: {clean}\n" if clean else ""
        front = "---\n" + line("method_id", method_id) + line("name", name) + line("description", description)
        front += "status: candidate\n" + line("source_model", source_model) + line("teacher_refs", ",".join(checked_teachers))
        front += line("source_episode_refs", ",".join(checked_episode_refs)) + line("evidence_refs", ",".join(evidence_refs or []))
        front += line("freshness_refs", ",".join(checked_freshness_refs))
        front += line("parent_ref", parent_ref) + line("created_at", now) + line("updated_at", now) + "---\n"
        self._commit_new_directory(method_id, {"METHOD.md": (front + body.strip() + "\n").encode("utf-8")}, operation="save_candidate")
        record = self._load_path(path)
        if record is None:
            raise RuntimeError("candidate write did not round-trip")
        return record, True

    def annotate_freshness(self, method_ref: str, freshness_refs: list[str]) -> MethodRecord:
        """Serialize one-key annotation RMW with qualification/lifecycle updates."""
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._annotate_freshness_locked(method_ref, freshness_refs)

    def _annotate_freshness_locked(self, method_ref: str, freshness_refs: list[str]) -> MethodRecord:
        """Update ONLY the frontmatter ``freshness_refs`` of an existing card.

        EVO-20260929-5283ab1b P5-B follow-up: existing cards could not declare
        freshness_refs after creation (save_candidate is idempotent by design
        and never overwrites). This channel edits exactly one frontmatter key:
        the card body and every other field stay byte-identical, and a SHA
        baseline still only lands at the next qualification. The old→new value
        goes to an append-only journal under the store root.
        """
        refs = _checked_freshness_refs(list(freshness_refs))
        method_id = method_ref.removeprefix("method:").strip().lower()
        if not _SAFE_ID_RE.fullmatch(method_id):
            raise ValueError(f"invalid method ref: {method_ref}")
        path = self._dir / method_id / "METHOD.md"
        if not path.is_file():
            raise ValueError(f"method not found in runtime store: {method_ref}")
        raw = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(raw)
        if match is None:
            raise ValueError("card has no parseable frontmatter")
        front = match.group(1)
        body = raw[match.end():]
        now = _now()
        old_match = re.search(r"^freshness_refs:.*$", front, re.MULTILINE)
        old_value = old_match.group(0).split(":", 1)[1].strip() if old_match else ""
        new_line = f"freshness_refs: {','.join(refs)}" if refs else "freshness_refs: "
        if old_match:
            front = front[: old_match.start()] + new_line + front[old_match.end():]
        else:
            status_match = re.search(r"^status:.*$", front, re.MULTILINE)
            anchor = status_match.end() if status_match is not None else 0
            front = front[:anchor] + "\n" + new_line + front[anchor:]
        updated_match = re.search(r"^updated_at:.*$", front, re.MULTILINE)
        if updated_match:
            front = front[: updated_match.start()] + f"updated_at: {now}" + front[updated_match.end():]
        self._replace_card(path, "---\n" + front + "\n---\n" + body, operation="annotate_freshness")
        record = self._load_path(path)
        if record is None:
            raise RuntimeError("annotation did not round-trip")
        try:
            with (self._dir / "annotations.jsonl").open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": now,
                            "event": "annotate_freshness",
                            "method_ref": method_id,
                            "old": old_value,
                            "new": refs,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            # annotation itself succeeded; the journal is best-effort provenance
            pass
        return record

    def find_by_evidence(self, evidence_ref: str) -> str | None:
        """Return ``method_ref`` whose ``evidence_refs`` contains ``evidence_ref``.

        Best-effort reverse lookup for LearningJournal reconcile: closes the
        crash window between ``save_candidate`` (durable) and journal
        ``mark_saved`` (durable). Scans records on demand; O(files).
        """
        needle = str(evidence_ref).strip()
        if not needle:
            return None
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None:
                continue
            if needle in record.evidence_refs:
                return record.method_ref
        return None
