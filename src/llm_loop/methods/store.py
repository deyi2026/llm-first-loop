"""Durable Method store for model-owned reusable reasoning/action methods.

Method records are retrieval assets, never automatic prompt injections. The program owns
identity, lifecycle, provenance and exact bytes; semantic applicability remains model-owned.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_VALID_STATUSES = {"teacher", "candidate", "qualified", "active", "hold", "invalidated", "retired"}
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


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
            "projection_complete": True,
        })
        return result


class MethodStore:
    """Two-tier Method store: reviewed seed assets plus private runtime overlays."""

    def __init__(self, methods_dir: str | Path, *, seed_dir: str | Path | None = None) -> None:
        self._dir = Path(methods_dir)
        self._seed_dir = Path(seed_dir) if seed_dir is not None else None

    @staticmethod
    def _safe_id(value: str) -> str:
        candidate = value.strip().lower()
        if not _SAFE_ID_RE.fullmatch(candidate):
            raise ValueError("method_id must match [a-z0-9][a-z0-9._-]{0,127}")
        return candidate

    def _iter_paths(self) -> list[Path]:
        paths: list[Path] = []
        if self._seed_dir is not None and self._seed_dir.exists():
            paths.extend(self._seed_dir.glob("*/METHOD.md"))
        if self._dir.exists():
            paths.extend(self._dir.glob("*/METHOD.md"))
        # Runtime copy wins exact-id collisions, but both stores remain independently auditable.
        by_id: dict[str, Path] = {}
        for path in sorted(paths):
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

    def list(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        query = query.strip()
        if query.lower().startswith("method:"):
            record = self.get(query)
            if record is None:
                return []
            hydrated = record.hydrated()
            hydrated["qualification_entries"] = self.qualification_entries(query)
            return [hydrated]
        terms = [t for t in re.split(r"\s+", query.lower()) if t]
        ranked: list[tuple[int, MethodRecord]] = []
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status == "retired":
                continue
            hay = f"{record.name} {record.description} {record.body}".lower()
            if terms and not all(term in hay for term in terms):
                continue
            lexical = sum(5 if t in record.name.lower() else 3 if t in record.description.lower() else 1 for t in terms)
            life = {"active": 3, "qualified": 2, "candidate": 1, "teacher": 0, "hold": -1, "invalidated": -2}.get(record.status, -3)
            ranked.append((lexical * 10 + life, record))
        ranked.sort(key=lambda item: (item[0], item[1].method_id), reverse=True)
        return [r.card() for _, r in ranked[:max(0, limit)]]

    def _ensure_runtime_copy(self, record: MethodRecord) -> MethodRecord:
        """Copy a tracked seed to runtime storage before any mutable lifecycle write."""
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
        runtime_path.parent.mkdir(parents=True, exist_ok=False)
        runtime_path.write_bytes(source.read_bytes())
        # Seed-side qualification summary is evidence shipped with the seed, not mutable runtime state.
        seed_q = source.parent / "qualification.json"
        if seed_q.exists():
            (runtime_path.parent / "qualification.json").write_bytes(seed_q.read_bytes())
        copied = self._load_path(runtime_path)
        if copied is None:
            raise RuntimeError("runtime Method overlay did not round-trip")
        return copied

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
        record = self._ensure_runtime_copy(record)
        entry = {
            "ts": _now(),
            "task_ref": clean_task_ref,
            "verdict": verdict,
            "mechanism": mechanism,
            "task_benefit": task_benefit,
            "promotion": promotion,
            "evidence_refs": [str(v).strip() for v in (evidence_refs or []) if str(v).strip()],
            "note": note.strip()[:4000],
            "evaluator": evaluator.strip()[:128] or "model",
        }
        qpath = Path(record.path).parent / "qualification.jsonl"
        with qpath.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
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

    def update_status(self, method_ref: str, target_status: str) -> MethodRecord:
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
            raise ValueError("teacher lifecycle is immutable; create a candidate distilled from it")
        if record.status == "candidate" and target == "active":
            raise ValueError("candidate cannot become active directly; qualify independently first")
        if target == "qualified":
            entries = self.qualification_entries(method_ref)
            if not any(e.get("promotion") == "pass" and e.get("task_ref") for e in entries):
                raise ValueError("qualified requires at least one recorded promotion=pass qualification with task_ref")
        path = Path(record.path)
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        meta["status"] = target
        meta["updated_at"] = _now()
        ordered = ["method_id", "name", "description", "status", "source_model", "teacher_refs", "source_episode_refs", "evidence_refs", "parent_ref", "supersedes", "created_at", "updated_at"]
        lines: list[str] = []
        for key in ordered:
            value = meta.pop(key, None)
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        for key in sorted(meta):
            value = meta[key]
            if value not in (None, ""):
                lines.append(f"{key}: {value}")
        path.write_text("---\n" + "\n".join(lines) + "\n---\n" + body.strip() + "\n", encoding="utf-8")
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
    ) -> MethodRecord:
        """Persist semantic content supplied by the model; never overwrite or auto-promote."""
        if parent_ref and self.get(parent_ref) is None:
            raise ValueError(f"parent_ref not found: {parent_ref}")
        checked_teachers: list[str] = []
        for teacher_ref in teacher_refs or []:
            teacher = self.get(teacher_ref)
            if teacher is None or teacher.status != "teacher":
                raise ValueError(f"teacher_ref must identify a teacher Method: {teacher_ref}")
            checked_teachers.append(teacher.method_ref)
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:72] or "candidate"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
        method_id = self._safe_id(f"{base}-{digest}")
        out_dir = self._dir / method_id
        path = out_dir / "METHOD.md"
        if path.exists():
            record = self._load_path(path)
            if record is None:
                raise ValueError("existing candidate is unreadable")
            return record
        out_dir.mkdir(parents=True, exist_ok=False)
        now = _now()
        def line(k: str, v: str) -> str:
            clean = v.replace("\n", " ").strip()
            return f"{k}: {clean}\n" if clean else ""
        front = "---\n" + line("method_id", method_id) + line("name", name) + line("description", description)
        front += "status: candidate\n" + line("source_model", source_model) + line("teacher_refs", ",".join(checked_teachers))
        front += line("source_episode_refs", ",".join(source_episode_refs or [])) + line("evidence_refs", ",".join(evidence_refs or []))
        front += line("parent_ref", parent_ref) + line("created_at", now) + line("updated_at", now) + "---\n"
        path.write_text(front + body.strip() + "\n", encoding="utf-8")
        record = self._load_path(path)
        if record is None:
            raise RuntimeError("candidate write did not round-trip")
        return record
