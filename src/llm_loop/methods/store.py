"""Durable Method store for model-owned reusable reasoning/action methods.

Method records are retrieval assets, never automatic prompt injections. The program owns
identity, lifecycle, provenance and exact bytes; semantic applicability remains model-owned.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
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

from llm_loop.knowledge import heldout_guard
from llm_loop.knowledge.heldout_guard import HeldoutContaminationError
from llm_loop.timekeeping import system_local_now
from llm_loop.usage_net import row_annotation as _usage_net_row_annotation
from llm_loop.usage_net import summarize_since_last_transition
from llm_loop.use_ledger import (
    BENEFITS as USE_BENEFITS,
)
from llm_loop.use_ledger import (
    EVIDENCE_LEVELS as USE_EVIDENCE_LEVELS,
)
from llm_loop.use_ledger import (
    SCHEMA_METHOD_V2 as SCHEMA_METHOD_USE_V2,
)
from llm_loop.use_ledger import (
    append_ledger_line,
    canonical_json,
    count_valid_lines,
    dedupe_slot_heads,
    derive_slot_id,
    derive_submission_hash,
    ensure_appendable_tail,
    line_integrity_matches,
    quarantine_torn_tail,
    read_ledger_entries,
    resolve_submission,
)

_VALID_STATUSES = {"teacher", "candidate", "qualified", "active", "hold", "invalidated", "retired"}
# These are status-only labels, not access tiers. They must never acquire a
# qualification/proof prerequisite: applicability and use remain model-owned.
_QUALITY_LABEL_STATUSES = frozenset({"candidate", "qualified", "active", "hold"})
_DISPOSITION_STATUSES = frozenset({"invalidated", "retired"})
# 2026-10-22 retrieval-idf 字段基础权重（冻结 goldset 30 条中文任务式 query 消融，见报告表）：
# name 是作者手写的“何时用”摘要 → 8；body 是正文细节 → 5；id 仍是身份位 10。
# description 的实际权重是条件值，见 _DESC_CORROBORATED_WEIGHT：只有当一个 query 的**多个**
# 不同词项同时命中 description（≥2）才算“适用场景佐证”，才升到 8；单个词项出现在描述里属弱
# 证据（可能只是顺带提及），退回基础值 4 —— 保留 EVO-20261017 的“body 实质命中 > 描述顺带
# 提及”口径。仅 idf 加权时保持 desc=4 作对照；运行期只读。
_FIELD_WEIGHTS: dict[str, int] = {"id": 10, "name": 8, "desc": 4, "body": 5}
# 2026-10-22 method-alias-retrieval：别名是"检索提示"（retrieval hint），不是权威字段。
# 权重必须严格低于 desc(4)：任何权威字段（id/name/desc/body）的命中都必须压过别名命中，
# 否则通用 bigram 一旦被写进 aliases 就能把无关卡顶到 top-1（实测回归：锁存活查询的
# top-1 被别名卡抢走）。别名只加进 lexical，不进 term_hits/coverage —— 它不证明该卡
# 覆盖了 query 的任何词项。
_ALIAS_WEIGHT = 3
# 2026-10-22：description 命中 ≥2 个不同 query 词项时的佐证权重。
_DESC_CORROBORATED_WEIGHT = 8
# 2026-10-23 retrieval-gate (P1-1①)：一个词命中就进排序池，等于把 limit 顶满 —— 实测
# 6 个查询里 5 个 `list(q, 200)` 返回 200 条（同一主题上千张卡时几乎全是噪声）。准入
# 门槛：候选须满足任一才进池 —— ①命中 name（作者写的"何时用"摘要）；②命中 ≥2 个不同
# query 词项（只看权威字段，alias 不计入 coverage）；③只命中一个词，但该词在池内
# df ≤ _GATE_RARE_DF（罕见词本身就是判别证据）。闸门用的是同一次扫描已经算好的 df，
# 不额外读盘、不改 idf，所以被放行的卡分数与加闸门前逐位相同，变化只在"谁进池"。
_GATE_RARE_DF = 3
# 门槛是降噪，不是限召回：严格池不足 limit 条时按分数回填被拦卡，保证「页长不变、只换人选」。
_GATE_BACKFILL_MIN = 5
# 2026-10-23 tie-break：分数与 coverage 打平时仍按 method_id 倒序（与加闸门前逐位一致）。
# status 只作展示字段，不进排序键 —— 不同 status 的平手若被重排，调用方钉住的顺序就变了。
_GATE_STATUS_ORDER = {"active": 0, "qualified": 1, "candidate": 2, "hold": 3}
_ALIAS_SEPARATORS_RE = re.compile(r"[,:#\n\r\t]")
# Used only to distribute a bounded amount of embedding work across the corpus.
# This order does not filter discovery, choose a relevant method, or authorize use.
_SEMANTIC_PREWARM_STATUS_ORDER = (
    "teacher", "active", "qualified", "candidate", "hold", "invalidated",
)
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

# EVO-20261017-lifecycle-alignment: lifecycle status is a model-owned quality badge,
# not a permission tier and not a ranking factor. A candidate is as usable and as
# findable as an active card; lexical + coverage relevance alone orders discovery,
# exactly like Experience retrieval where verification_state is displayed but never
# scored. Status still matters for destructive operations (invalidate/retire need an
# independent factual basis) and for human review, both of which protect assets
# rather than restrict use.

# 2026-10-20 卡片形态自由: the write boundary checks only that a card carries
# readable content, never what shape it takes. Procedure, index, and one-line
# reminder cards are equally valid (docs/METHOD_CARD_WRITING.md). Same posture as
# Experience: formatting is not an admission rule, only usability is.
def _card_content_missing(body: str) -> list[str]:
    """Return ``["body"]`` when the body has no non-heading content line."""
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line in {"---", "***", "```"}:
            continue
        return []
    return ["body"]


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


# --- alias gate -------------------------------------------------------------
# Aliases are a retrieval hint channel only (store.list scores them below the
# description baseline). Their value is vocabulary the card does NOT already
# contain; a string copied from the description cannot move the score, while a
# string shared by dozens of cards pushes unrelated cards up. So every write
# self-checks: too-short, lifecycle-generic, duplicate, and high-document-frequency
# aliases are dropped before they reach the frontmatter.
_GENERIC_ALIAS_TOKENS = frozenset(
    {"method", "candidate", "qualified", "active", "hold", "invalidated", "retired", "teacher"}
)
_ALIAS_MAX_PER_CARD = 6  # observed pool maximum is 5; keep one slot of headroom
_ALIAS_MIN_CHARS = 3


def _alias_text(value: str) -> str:
    """Normalize like the search index does: latin/number runs and CJK runs, lowercased."""
    return " ".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))


def alias_df_threshold(pool_size: int) -> int:
    """Highest document frequency an alias may have and still discriminate.

    Measured 2026-10-23 on a 1369-card pool with 337 existing aliases: 333 had
    df=1 and only 3 exceeded it (df=4/11/66 — cross-card symbols such as
    ``action_id``). A threshold of 3 blocks exactly that known noise class while
    still letting two or three cards in a small pool share a phrasing; the cap of
    5 keeps the gate from drifting into "blocks nothing" as the pool grows.
    """
    return max(2, min(5, pool_size // 400))


def gate_aliases(
    aliases: list[str] | None,
    *,
    name: str,
    corpus: list[str],
    pool_size: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Filter author-supplied aliases; return (kept, dropped-with-reason).

    Order of checks is first-match: too_short -> generic -> duplicate ->
    low_discrimination -> cap, so every dropped entry carries exactly one reason
    the caller can report. Empty strings are ignored outright: they are not a
    rejected alias, they are absent input.
    """
    kept: list[str] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    name_norm = _alias_text(name)
    threshold = alias_df_threshold(pool_size)
    for raw in aliases or []:
        alias = str(raw).strip()
        if not alias:
            continue
        norm = _alias_text(alias)
        df = sum(1 for text in corpus if norm and norm in text)
        if len(alias) < _ALIAS_MIN_CHARS:
            dropped.append({"alias": alias, "reason": "too_short", "df": df})
            continue
        if _ALIAS_SEPARATORS_RE.search(alias):
            # aliases are joined with ", " into a single YAML scalar, so a comma/hash/
            # colon would either split into bogus aliases or start a comment. Reject at
            # the gate: the write path must stay an injection-free round trip.
            dropped.append({"alias": alias, "reason": "unsafe_chars", "df": df})
            continue
        if norm in _GENERIC_ALIAS_TOKENS:
            dropped.append({"alias": alias, "reason": "generic", "df": df})
            continue
        if not norm or norm == name_norm or norm in seen:
            dropped.append({"alias": alias, "reason": "duplicate", "df": df})
            continue
        if df > threshold:
            dropped.append({"alias": alias, "reason": "low_discrimination", "df": df})
            continue
        if len(kept) >= _ALIAS_MAX_PER_CARD:
            dropped.append({"alias": alias, "reason": "cap", "df": df})
            continue
        seen.add(norm)
        kept.append(alias)
    return kept, dropped


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
    # 2026-10-22 method-alias-retrieval：作者声明的"何时适用"同义/口语表述
    # （front matter `aliases: a, b, c`）。它只是一条检索同义通道：参与词法排序、
    # 进入语义候选文本与 inventory 关键词匹配，并可在 card() 里投影给作者自查。
    # 别名不判断适用性、不构成使用许可、与 status（仅是质量徽标）无关——能否用某张卡
    # 仍然只由阅读正文的模型决定。空元组表示作者未声明别名，此时每条读取路径都与
    # 未引入该字段前逐字等价。放在字段末尾以保持既有位置参数构造兼容。
    aliases: tuple[str, ...] = ()

    @property
    def method_ref(self) -> str:
        return f"method:{self.method_id}"

    def card(self) -> dict[str, Any]:
        card: dict[str, Any] = {
            "kind": "method",
            "ts": self.updated_at or self.created_at,
            "id": self.method_id,
            "key": self.method_ref,
            # 2026-10-18 method-summary-parity：summary 是检索结果里"扫一眼判断相关性"
            # 的主字段。经验行放自然语言标题；实测 98% 方法卡的 name 是 kebab-case 机器
            # ID，近 7 天方法深读率 10.5%（经验 53%）。对齐经验：summary 放 description
            # 首句，机器 ID 保留在 id/key 位；description 为空时回退 name。
            "summary": (self.description or "").strip()[:120] or self.name,
            "description": self.description[:500],
            "status": self.status,
            "source_model": self.source_model,
            "content_hash": self.content_hash,
            "projection_complete": False,
            "task_applicability": "not_evaluated",
            "file": self.path,
        }
        # 2026-10-22 method-alias-retrieval：只有作者真声明了别名才投影该键。
        # 绝大多数卡没有 aliases，无条件输出空列表会让每条检索结果多一个恒空字段；
        # 空别名 = 键不存在，调用方据此区分"未声明别名"与"声明了空别名"。
        # 别名只是可检索的同义表述，不判断适用性、不构成使用许可、与 status 无关。
        if self.aliases:
            card["aliases"] = list(self.aliases)
        return card

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
        contamination_guard: Callable[[str], dict[str, Any]] | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        self._dir = Path(methods_dir)
        self._seed_dir = Path(seed_dir) if seed_dir is not None else None
        self._write_guard = write_guard
        # held-out 写侧防线（fail-closed）：None 时惰性走 heldout_guard.check_text，
        # 不在构造期解析 manifest（env/工作区在构造后仍可变化）。
        self._contamination_guard = contamination_guard
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

    def _reject_heldout_contamination(self, text: str) -> None:
        """写侧 fail-closed：命中 held-out 探针即拒写（eval/rules/holdout.md §4）.

        只判 ``status == "blocked"``：guard unavailable/内部异常由 heldout_guard
        映射为非 blocked → 放行（fail-open 由 guard 自身保证）。
        异常消息只含类别（task_id/statement_probe）与 task_id，绝不携带待检文本。
        """
        verdict = (
            self._contamination_guard(text)
            if self._contamination_guard is not None
            else heldout_guard.check_text(text)
        )
        if verdict.get("status") == "blocked":
            raise HeldoutContaminationError(
                "method candidate rejected: held-out contamination "
                f"({verdict.get('reason')}): task_id={verdict.get('task_id')}"
            )

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
        # held-out 写侧防线（最终载荷封堵点①）：所有"整目录落卡"路径
        # （save_candidate 首写 / seed overlay）在创建任何 staging 字节之前，
        # 对即将落盘的 METHOD.md 全文过检——拒写时目录/staging 零副作用。
        # 检查对象是落盘原文本身，不按字段拼装（拼装遗漏正是第一轮
        # aliases/freshness_refs 漏检的根因）。
        self._reject_heldout_contamination(files["METHOD.md"].decode("utf-8", errors="replace"))
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
        # held-out 写侧防线（最终载荷封堵点②）：所有 RMW 卡片改写
        # （update_status / annotate_freshness / annotate_aliases 及未来新入口）
        # 在写 tmp 之前对完整序列化载荷过检——注解入口注入的任何 frontmatter
        # 字段（如 freshness_refs/aliases）天然全部在检查面内，新增改写入口
        # 无法绕过。P1-A（annotate_freshness 旁路）由此封堵。
        self._reject_heldout_contamination(payload)
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
            # 2026-10-22 method-alias-retrieval：逗号切分、逐项 strip、丢空项。
            # `aliases:`（空值）与完全缺省该键都得到 ()，两条路径逐字等价。
            aliases=tuple_field("aliases"),
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
        ``poc``). CJK runs expand into overlapping bigrams: a whole natural-language
        Chinese sentence is one unsplittable run, so matching it as a single
        substring missed every query in the frozen 30-query baseline (0/30 top-1).
        Bigrams are mechanical and dependency-free; on that same frozen set they
        reached 10/30 top-1, equal to semantic recall. Applicability is still left
        to the model — this only decides which cards are candidates.
        """
        raw = query.lower().strip()
        terms: list[str] = []
        for token in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]+", raw):
            if re.fullmatch(r"[\u4e00-\u9fff]+", token):
                if len(token) == 1:
                    terms.append(token)
                else:
                    terms.extend(token[i : i + 2] for i in range(len(token) - 1))
            else:
                terms.append(token)
        return terms

    @staticmethod
    def _normalized_search_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", value.lower()))

    def _admission_block(
        self,
        record: MethodRecord,
        term_hits: list[tuple[str, int]],
        lexical_terms: list[tuple[str, int]],
        identifier_bonus: int,
        df: dict[str, int],
    ) -> str:
        """P1-1① gate: "" when the candidate may be ranked, else the drop reason.

        Alias hits are hints, not coverage evidence, so a card reached only through an
        alias keeps working (the author declared the term) but a card whose single
        common-term hit is alias-backed cannot claim authoritative coverage.
        """
        if identifier_bonus > 0:
            # A stable-id fragment is identity evidence, not a topic term.
            return ""
        matched = list(dict.fromkeys(term for term, _ in term_hits))
        if not matched:
            # alias-only: keep the declared hint channel, never counted as coverage.
            return "" if lexical_terms else "no_evidence"
        if len(matched) >= 2:
            return ""  # (2) two distinct query terms corroborate each other
        term = matched[0]
        if term in self._normalized_search_text(record.name):
            return ""  # (1) name is the author-written "when to use" summary
        if df.get(term, 0) <= _GATE_RARE_DF:
            return ""  # (3) a rare term is itself discriminative evidence
        return "common_single_term"

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

    def list(
        self, query: str = "", limit: int = 20, *, stats: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Discovery view over discoverable cards (2026-10-22 retrieval-idf rules).

        Lifecycle: ``retired`` and ``invalidated`` are known-dead knowledge and never
        enter discovery; an exact ``method:<id>`` ref still hydrates any status via
        get(), and inventory() keeps every status visible for the admin view.
        Admission (2026-10-23 gate): a candidate enters the ranking pool only on a name
        hit, or >=2 distinct authoritative query terms, or one term whose in-pool df is
        rare (_GATE_RARE_DF). Alias-only hits keep their declared channel but never
        count as coverage. ``stats`` is a pure observation sink (pool_before/admitted/
        dropped_by_gate/dropped_terms); leaving it None changes no behaviour.
        Ranking: idf-weighted lexical field scores (rare discriminative terms outweigh
        high-frequency filler bigrams such as 怎么/一个) + identifier_bonus + coverage,
        ties broken by status quality (active > qualified > candidate > hold) then by
        ascending method_id.
        """
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
        # 2026-10-22 retrieval-idf: one directory scan computes every record's per-term
        # field scores and accumulates document frequencies in the same pass. df counts
        # discoverable records whose authoritative score for that term is > 0 — the same
        # criterion coverage uses — and N is the discoverable corpus size, so no second
        # disk I/O. Alias-only hits stay out of df: they are hints, not evidence of
        # term coverage.
        rows: list[tuple[MethodRecord, list[tuple[str, int]], list[tuple[str, int]], int]] = []
        df: dict[str, int] = {}
        discoverable = 0
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status in _DISPOSITION_STATUSES:
                continue
            discoverable += 1
            id_text = self._normalized_search_text(record.method_id + " " + record.method_ref)
            name_text = self._normalized_search_text(record.name)
            desc_text = self._normalized_search_text(record.description)
            body_text = self._normalized_search_text(record.body)
            # 2026-10-22 method-alias-retrieval：别名是作者声明的检索提示（口语/同义
            # 写法），不是权威字段。它只进 lexical，权重 _ALIAS_WEIGHT 严格低于 desc，
            # 因此任何 id/name/desc/body 命中都压过它。别名不判断适用性、不构成使用
            # 许可、与 status 无关。空别名得到 ""，`term in ""` 恒假，零贡献 ——
            # 没有 aliases 的卡与引入本字段前逐字等价。
            alias_text = self._normalized_search_text(" ".join(record.aliases))
            # 2026-10-22 retrieval-idf: name is the author-written "when to use" summary
            # (8); body carries the procedure (5); id is the identity slot (10).
            # description is conditional: one incidental term is weak evidence, so it
            # keeps the base weight; >=2 distinct query terms is corroboration and
            # promotes it to _DESC_CORROBORATED_WEIGHT. That keeps EVO-20261017's
            # "substantive body hit beats an incidental description mention" rule.
            desc_weight = (
                _DESC_CORROBORATED_WEIGHT
                if sum(1 for term in terms if term in desc_text) >= 2
                else _FIELD_WEIGHTS["desc"]
            )
            fields = (
                (id_text, _FIELD_WEIGHTS["id"]),
                (name_text, _FIELD_WEIGHTS["name"]),
                (desc_text, desc_weight),
                (body_text, _FIELD_WEIGHTS["body"]),
            )
            # Two separate accumulators, and that split is the whole point of this fix:
            # - term_hits: authoritative-field hits only -> matched / coverage / df. A
            #   card that only matched through an alias has NOT covered a query term.
            # - lexical_terms: what lexical sums, taking max(authoritative, alias) per
            #   term, so an alias still surfaces the card without pretending coverage.
            term_hits: list[tuple[str, int]] = []
            lexical_terms: list[tuple[str, int]] = []
            for term in terms:
                core = max((weight for text, weight in fields if term in text), default=0)
                alias = _ALIAS_WEIGHT if term in alias_text else 0
                weight = max(core, alias)
                if weight:
                    lexical_terms.append((term, weight))
                if core:
                    term_hits.append((term, core))
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
            if terms and not lexical_terms and identifier_bonus == 0:
                continue
            rows.append((record, term_hits, lexical_terms, identifier_bonus))
            # dict.fromkeys keeps per-record df increments unique and ordered. df stays
            # count-of-authoritative-hits so alias-only terms simply never appear in it
            # (read back with .get(term, 0) below) — idf itself is untouched.
            for term in dict.fromkeys(hit_term for hit_term, _ in term_hits):
                df[term] = df.get(term, 0) + 1
        # 2026-10-23 retrieval-gate (P1-1①): the scan above already produced df, so the
        # gate costs no extra I/O and cannot move idf. Only pool membership changes.
        pool_before = len(rows)
        dropped_terms: dict[str, int] = {}
        blocked_rows: list[
            tuple[MethodRecord, list[tuple[str, int]], list[tuple[str, int]], int]
        ] = []
        admitted: list[
            tuple[MethodRecord, list[tuple[str, int]], list[tuple[str, int]], int]
        ] = []
        for row in rows:
            record, term_hits, lexical_terms, identifier_bonus = row
            # No query terms means "browse the inventory", not "answer a question": an
            # empty/whitespace query must keep returning every discoverable card (the
            # gate exists to stop a *shared term* from crowding out the right card, and
            # there is no shared term here). Skipping it also keeps `list("")` usable as
            # the admin/seed-completeness view.
            if not terms or not self._admission_block(
                record, term_hits, lexical_terms, identifier_bonus, df
            ):
                admitted.append(row)
                continue
            blocked_rows.append(row)
            # dropped_terms explains the noise per query term: attribute each discard to
            # the authoritative terms it hit (alias-only discards fall back to lexical).
            for term in dict.fromkeys(
                [hit for hit, _ in term_hits] or [hit for hit, _ in lexical_terms]
            ):
                dropped_terms[term] = dropped_terms.get(term, 0) + 1
        rows = admitted

        def _score(
            row: tuple[MethodRecord, list[tuple[str, int]], list[tuple[str, int]], int],
        ) -> tuple[float, float, MethodRecord]:
            record, term_hits, lexical_terms, identifier_bonus = row
            # idf = log((N+1)/(df+1)) + 1: ubiquitous terms trend toward 1.0 while rare
            # discriminative terms rise, so a noise card matching many shared bigrams
            # no longer ties or beats the card holding the rare term. Summation follows
            # the (deterministic) query-term order; round(...,4) before comparing keeps
            # repeated runs bit-identical.
            lexical = 0.0
            for term, weight in lexical_terms:
                lexical += (math.log((discoverable + 1) / (df.get(term, 0) + 1)) + 1.0) * weight
            # matched/coverage count authoritative hits only: an alias-only term must not
            # move a card across a coverage band (+50 each) and out-rank a real hit.
            matched = len(term_hits)
            coverage = (matched / len(terms)) if terms else 0.0
            score = round(identifier_bonus + round(lexical, 4) * 10 + int(coverage * 50), 4)
            return (score, coverage, record)

        def _order(
            items: list[tuple[float, float, MethodRecord]],
        ) -> list[tuple[float, float, MethodRecord]]:
            # Tie-break: score then coverage, both descending, then method_id descending
            # via the stable pre-sort. status is deliberately NOT a key: the gate already
            # changed which cards enter the page, and re-ordering equal-score ties by
            # status would also rewrite the order callers had pinned (id descending).
            # Two stable passes express "id descending" inside one ascending-key sort.
            items.sort(key=lambda item: item[2].method_id, reverse=True)
            items.sort(key=lambda item: (-item[0], -item[1]))
            return items

        ranked = _order([_score(row) for row in rows])
        # Backfill (2026-10-23, revised after review): the gate is a page-filler filter,
        # never a page-shortener. It may change *which* cards occupy the page, never how
        # many: a caller that asked for 20 and had 2 cards clear the gate still gets 20,
        # because the semantic leg calls with limit=max(limit*4,20) and a shrunken page
        # would silently rewrite the RRF fusion downstream. So `need` is the caller's
        # limit, not a fixed floor: blocked cards re-enter only to fill the page, and on
        # a narrow query the returned set is byte-identical to pre-gate behaviour.
        need = max(0, limit)
        strict_total = len(ranked)
        backfilled = 0
        if strict_total < need and blocked_rows:
            extras = _order([_score(row) for row in blocked_rows])[: need - strict_total]
            ranked = _order(ranked + list(extras))
            backfilled = len(extras)

        if stats is not None:
            stats.update(
                {
                    "pool_before": pool_before,
                    # admitted/dropped describe the *gate*; returned describes the page.
                    # Keeping them separate lets a reader tell "the gate rejected it" from
                    # "the page backfilled it", which is the number needed to tune the
                    # threshold later.
                    "admitted": strict_total,
                    "dropped_by_gate": pool_before - strict_total,
                    "backfilled": backfilled,
                    "returned": min(len(ranked), max(0, limit)),
                    "dropped_terms": dict(
                        sorted(dropped_terms.items(), key=lambda kv: (-kv[1], kv[0]))
                    ),
                }
            )
        result: list[dict[str, Any]] = []
        for _, _, record in ranked[:max(0, limit)]:
            card = record.card()
            self._attach_last_signal_age(card, record)
            if record.freshness_refs:
                card["freshness"] = self.freshness(record.method_ref)
            result.append(card)
        return result

    def inventory(
        self,
        query: str = "",
        limit: int = 200,
        *,
        status: str = "",
    ) -> dict[str, Any]:
        """管理/可观测性目录：全生命周期状态分组 + 记录列表（含 retired/invalidated）.

        与 list()（检索视图，跳过 retired/invalidated 两个处置态）不同，inventory 面向 web 管理页：
        所有状态同列并带 status 徽标，供人工审视与生命周期流转。只读、
        关键词子串匹配（id/name/description）、按 ts 倒序；counts 为全量
        统计（不受 query/limit 影响），无语义排序与零信号衰减。
        """
        needle = query.strip().lower()
        counts: dict[str, int] = {}
        entries: list[dict[str, Any]] = []
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None:
                continue
            record_status = str(record.status or "unknown")
            counts[record_status] = counts.get(record_status, 0) + 1
            if status and record_status != status:
                continue
            if needle:
                # 2026-10-22 method-alias-retrieval：管理页关键词匹配也认别名，作者/模型
                # 用口语词能查到同一张卡。别名仍是检索同义表述，不是适用性或使用许可。
                # `" ".join(())` == ""：无别名的卡 haystack 与改动前逐字相同。
                haystack = self._normalized_search_text(
                    f"{record.method_id} {record.method_ref} {record.name} "
                    f"{' '.join(record.aliases)} {record.description}"
                )
                if needle not in haystack:
                    continue
            card = record.card()
            self._attach_last_signal_age(card, record)
            entries.append(card)
        entries.sort(
            key=lambda item: (str(item.get("ts") or ""), str(item.get("id") or "")),
            reverse=True,
        )
        return {"counts": counts, "records": entries[: max(0, limit)]}

    @staticmethod
    def semantic_candidate(record: MethodRecord) -> dict[str, Any]:
        # 2026-10-22 method-alias-retrieval：别名排在 name 之后、description 之前，让语义
        # 召回也能被作者声明的口头叫法收敛到同一张卡。别名为空时 content 与引入本字段前
        # 逐字相同（不插入多余空格）。别名只是检索同义通道：不判断适用性、不构成使用许可、
        # 与 status 无关——是否用这张卡仍由阅读正文的模型决定。
        prefix = f"{record.method_id} {record.name}"
        if record.aliases:
            prefix = f"{prefix} {' '.join(record.aliases)}"
        return {
            "kind": "method",
            "id": record.method_id,
            "key": record.method_ref,
            "content": f"{prefix} {record.description} {record.body}",
        }

    def semantic_candidates(self) -> list[dict[str, Any]]:
        """Project Method records for mechanical semantic recall.

        The projection exposes content for vectorization only; it does not assert task
        applicability. 2026-10-22 retrieval-idf: retired and invalidated records are
        excluded with the exact same口径 as lexical ``list()`` discovery — both
        disposition statuses are invisible to every discovery view, so an invalidated
        card can no longer re-enter results through the semantic arm (prewarm included:
        its bucket stays empty). Exact ``method:<id>`` refs and inventory() still expose
        them. Status-stratified round-robin order gives each discoverable lifecycle
        bucket a chance to enter the bounded background/startup embedding queue; this
        is a cache-warming fairness rule, not a retrieval or use gate.
        """
        grouped: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
            status: [] for status in _SEMANTIC_PREWARM_STATUS_ORDER
        }
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status in _DISPOSITION_STATUSES:
                continue
            grouped.setdefault(record.status, []).append((
                record.updated_at or record.created_at,
                record.method_id,
                self.semantic_candidate(record),
            ))
        for rows in grouped.values():
            rows.sort(key=lambda row: (row[0], row[1]), reverse=True)
        positions = {status: 0 for status in grouped}
        result: list[dict[str, Any]] = []
        while True:
            added = False
            for status in _SEMANTIC_PREWARM_STATUS_ORDER:
                rows = grouped[status]
                position = positions[status]
                if position < len(rows):
                    result.append(rows[position][2])
                    positions[status] = position + 1
                    added = True
            if not added:
                break
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
        work_unit_id: str = "",
        benefit: str = "unknown",
        evidence_level: str = "model_declared",
        suggestion: str = "",
        supersedes: str = "",
        read_version: str = "",
        run_id: str = "",
        attribution: str = "",
        self_reported: bool = False,
        allow_unresolved: bool = False,
    ) -> dict[str, Any]:
        """Serialize use evidence with any destructive disposition it may support."""
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._record_use_locked(
                method_ref, episode_ref=episode_ref, decision=decision,
                note=note, model=model, evidence_refs=evidence_refs,
                session_id=session_id, work_unit_id=work_unit_id, benefit=benefit,
                evidence_level=evidence_level, suggestion=suggestion,
                supersedes=supersedes, read_version=read_version, run_id=run_id,
                attribution=attribution, self_reported=self_reported,
                allow_unresolved=allow_unresolved,
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
        work_unit_id: str = "",
        benefit: str = "unknown",
        evidence_level: str = "model_declared",
        suggestion: str = "",
        supersedes: str = "",
        read_version: str = "",
        run_id: str = "",
        attribution: str = "",
        self_reported: bool = False,
        allow_unresolved: bool = False,
    ) -> dict[str, Any]:
        """Append one model-authored Method applicability/use declaration.

        This is observability, not qualification: it never changes lifecycle status and
        never proves task benefit. Seed Methods are not copied into the runtime overlay
        merely because the model declared how it treated them.
        session_id (EVO-20260923-618f7fd1 ②) is optional provenance kept as audit
        attribution; legacy entries without it simply never match a session query.

        TASK-ac085ab1-001 P0 记录契约（设计草案 v3）: v2 条目带 schema 标记、
        工作单元绑定、读取版本绑定与模型自评；slot_id / submission_hash 两层键
        程序派生，flock 内先扫后写——同 (slot, submission_hash) 重试折叠为既有
        回执，同 slot 不同内容经 supersedes 追加修订（父记录校验），不改写
        历史行；每行附完整性凭据，坏尾先隔离再追加。task_benefit 保持独立
        评估语义（not_evaluated），模型自评只进 benefit 字段。
        """
        record = self.get(method_ref)
        if record is None:
            raise FileNotFoundError(method_ref)
        allowed = {"applied", "adapted", "not_applicable", "rejected"}
        clean_decision = decision.strip().lower()
        if clean_decision not in allowed:
            raise ValueError(f"decision must be one of {sorted(allowed)}")
        clean_episode = episode_ref.strip()
        # P1-1（独立审查回执 20261015-ac085ab1）：非空 episode 仍须运行时溯源
        # 前缀；空 episode 仅在调用方显式 allow_unresolved=True 时放行——由下方
        # binding 判定落 binding=unresolved、slot_id=''（use_ledger.
        # resolve_submission 定义的归属 unresolved 退化路径），调用方不得伪造
        # 哨兵前缀（如 "episode:unset"）把不同无归属任务并入同一伪 slot 链。
        episode_ok = clean_episode.startswith("episode:") or (
            allow_unresolved and not clean_episode
        )
        if not episode_ok:
            raise ValueError("Method use declaration requires runtime episode provenance")
        clean_benefit = str(benefit or "").strip().lower() or "unknown"
        if clean_benefit not in USE_BENEFITS:
            raise ValueError(f"benefit must be one of {sorted(USE_BENEFITS)}")
        clean_level = str(evidence_level or "").strip().lower() or "model_declared"
        if clean_level not in USE_EVIDENCE_LEVELS:
            raise ValueError(f"evidence_level must be one of {sorted(USE_EVIDENCE_LEVELS)}")
        clean_wu = str(work_unit_id or "").strip()[:128]
        if clean_wu:
            binding = "explicit"
            resolved_wu = clean_wu
        else:
            # 无显式工作单元时回退 episode（执行单元，细于 session）；两者皆缺
            # → 归属 unresolved，不参与需要任务绑定的统计分母。
            binding = "episode_fallback" if clean_episode else "unresolved"
            resolved_wu = clean_episode
        clean_refs = [str(v).strip() for v in (evidence_refs or []) if str(v).strip()]
        clean_note = note.strip()[:2000]
        clean_suggestion = str(suggestion or "").strip()[:2000]
        version = str(read_version or "").strip() or record.content_hash
        slot_id = (
            derive_slot_id(
                work_unit_id=resolved_wu, kind="method",
                ref=record.method_ref, version=version,
            )
            if resolved_wu
            else ""
        )
        submission_hash = derive_submission_hash(
            decision=clean_decision, benefit=clean_benefit, evidence_level=clean_level,
            evidence_refs=clean_refs, note=clean_note, suggestion=clean_suggestion,
        )
        entry = {
            "ts": _now(),
            "method_ref": record.method_ref,
            "method_content_hash": record.content_hash,
            "method_status": record.status,
            "episode_ref": clean_episode,
            "decision": clean_decision,
            "model": model.strip()[:256],
            "evidence_refs": clean_refs,
            "note": clean_note,
            "application_proven": clean_decision in {"applied", "adapted"},
            "task_benefit": "not_evaluated",
            "promotion": "not_evaluated",
            # ── v2 记录契约（TASK-ac085ab1-001）──
            "schema": SCHEMA_METHOD_USE_V2,
            "work_unit_id": resolved_wu,
            "work_unit_binding": binding,
            "run_id": str(run_id or "").strip()[:128],
            "read_version": version,
            "slot_id": slot_id,
            "submission_hash": submission_hash,
            "revision": 1,
            "supersedes": "",
            "benefit": clean_benefit,
            "evidence_level": clean_level,
            "suggestion": clean_suggestion,
        }
        if attribution:
            entry["attribution"] = str(attribution).strip()[:64]
        if self_reported:
            entry["self_reported"] = True
        clean_session = session_id.strip()[:128]
        if clean_session:
            entry["session_id"] = clean_session
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / _USAGE_LEDGER_FILE
        existing = read_ledger_entries(path)
        outcome = resolve_submission(
            existing, slot_id=slot_id, submission_hash=submission_hash,
            object_field="method_ref", object_ref=record.method_ref,
            requested_supersedes=str(supersedes or "").strip(),
        )
        if outcome.action == "invalid":
            raise ValueError(outcome.reason)
        if outcome.action == "dedupe" and outcome.existing is not None:
            receipt = dict(outcome.existing)
            receipt["idempotent"] = True
            return receipt  # 传输层重试/重复提交：返回既有回执，不重复追加
        ensure_appendable_tail(path)
        ledger_seq = count_valid_lines(path) + 1
        entry["revision"] = outcome.revision
        entry["supersedes"] = (
            str(outcome.parent.get("submission_hash") or "") if outcome.parent else ""
        )
        entry["ledger_seq"] = ledger_seq
        entry["ledger_watermark"] = ledger_seq
        # held-out 写侧防线（P1-B）：note/suggestion/model/evidence_refs/attribution
        # 等模型可达字段在最终序列化整行入账前过检。canonical_json 与
        # append_ledger_line 落盘序列化同构（其后再追加的 integrity 凭据是
        # 程序计算的 sha256，不引入新文本）——检查的正是即将持久化的载荷。
        self._reject_heldout_contamination(canonical_json(entry))
        entry = append_ledger_line(path, entry)
        self._refresh_usage_watermark_locked()
        return entry

    def recover_usage_ledger(self) -> dict[str, Any]:
        """显式恢复入口：torn 尾部隔离旁文件 + 诊断报告（锁内执行）."""
        with _store_lock(self._dir):
            return quarantine_torn_tail(self._dir / _USAGE_LEDGER_FILE)


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
        """Read bounded-size local use declarations; semantic interpretation stays model-owned.

        P-SET-4（GOAL-20261016-cf563b27 批次一）：读取面与 ``record_use`` 去重
        扫描（``read_ledger_entries``）同一完整性口径——行级 integrity 凭据
        失配的行不进入统计/回执视图，篡改行不再"计入统计却对去重不可见"；
        legacy 无凭据行（无 ``integrity`` 字段）仍可读，口径不变。
        """
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
                if not line_integrity_matches(value):
                    continue
                if wanted and str(value.get("method_ref", "")).lower() != wanted:
                    continue
                result.append(value)
        except OSError:
            return []
        return result

    def usage_net(self, method_ref: str) -> dict[str, Any] | None:
        """EVO-20261014-7299aec2: 使用净分派生视图（只读汇总，不改账本、不裁决）。

        锚点为最近 lifecycle transition：账本条目内嵌 method_status（声明时状态）
        与当前 status 尾段一致的条目才计入（口径见 llm_loop/usage_net.py D3）。
        无卡或无声明返回 None，调用方据此不附加任何字段。
        """
        ref = str(method_ref or "").strip()
        if not ref:
            return None
        record = self.get(ref)
        if record is None:
            return None
        entries = self.usage_entries(ref)  # 文件序=旧→新
        if not entries:
            return None
        # TASK-ac085ab1-001: 统计以 slot 为单位取链头（同工作单元×对象×版本的
        # 修订只计一条现行评价）；legacy（无 slot）条目按字段齐全度参与——
        # ref+决定计入总次数，缺自评/版本的不进入分层分母（legacy_entries 披露）。
        heads = dedupe_slot_heads(entries)
        summary = summarize_since_last_transition(
            list(reversed(heads)),
            decision_key="decision",
            status_key="method_status",
            current_status=str(record.status or ""),
        )
        v2_heads = [e for e in heads if e.get("slot_id")]
        version_scope = "current_version_only"
        matched = [
            e
            for e in v2_heads
            if str(e.get("read_version") or "") == str(record.content_hash)
        ]
        if not matched and v2_heads:
            version_scope = "all_v2_heads_no_current_version_match"
            matched = v2_heads  # 卡片已修订：如实累计全部 v2 链头并标注口径
        summary["benefit_counts"] = {
            name: sum(1 for e in matched if str(e.get("benefit") or "") == name)
            for name in sorted(USE_BENEFITS)
        }
        summary["benefit_version_scope"] = version_scope
        summary["legacy_entries"] = len(entries) - len(v2_heads)
        summary["slot_revisions_collapsed"] = len(entries) - len(heads)
        return summary

    def usage_feedback(self, method_ref: str) -> dict[str, Any] | None:
        """TASK-ac085ab1-003 P1 查询回流：命中行反馈注释数据（只读派生视图）.

        供检索短卡附分项反馈、近因问题摘要、当前版本状态与读取入口；
        与 usage_net 同一真值源，不改账本、不改排序、不裁决。
        """
        summary = self.usage_net(method_ref)
        if summary is None:
            return None
        ref = str(method_ref or "").strip()
        record = self.get(ref)
        current_version = str(record.content_hash) if record is not None else ""
        heads = dedupe_slot_heads(self.usage_entries(ref))
        v2_heads = [
            e for e in heads if e.get("slot_id") and e.get("read_version") == current_version
        ] if current_version else [e for e in heads if e.get("slot_id")]
        recent_issue = ""
        for entry in reversed(v2_heads):
            if str(entry.get("benefit") or "") in {"hindered", "mixed"} or str(
                entry.get("decision") or ""
            ) == "rejected":
                note = " ".join(str(entry.get("note") or "").split())[:160]
                if note:
                    recent_issue = note  # 取最近一条非空问题摘要
                    break
        state = (
            "current"
            if v2_heads
            else ("stale_after_card_edit" if any(e.get("slot_id") for e in heads) else "none")
        )
        feedback = {
            "read_entry": record.method_ref if record is not None else ref,
            "feedback_version_state": state,
            "recent_issue": recent_issue,
            "feedback_watermark": count_valid_lines(self._dir / _USAGE_LEDGER_FILE),
        }
        feedback.update(_usage_net_row_annotation(summary))
        feedback["benefit_counts"] = dict(summary.get("benefit_counts", {}))
        legacy = int(summary.get("legacy_entries", 0) or 0)
        if legacy:
            feedback["usage_feedback_legacy"] = legacy  # 未分层分母如实披露
        return feedback

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
        # held-out 写侧防线：note/evidence_refs/task_type 等模型可达字段最终
        # 序列化后的整行（与下方落盘 write 的字节同构）入账前过检。
        self._reject_heldout_contamination(json.dumps(entry, ensure_ascii=False, sort_keys=True))
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

        Status is a declared quality badge, not a permission tier. Any transition is
        accepted, including candidate -> active in one write, because status neither
        gates retrieval visibility (list() ranks by relevance alone) nor blocks use.
        This matches Experience records, where verification_state is model-declared
        and never a usability requirement. Only asset protection stays gated below:
        teacher immutability and independent factual basis for invalidate/retire.
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
        # EVO-20260929-5283ab1b P1 (R3): destructive disposition needs independent
        # factual basis. The program never decides a Method *should* die; it only
        # refuses to record a conviction resting solely on one session's own
        # self-judgment. reopen stays permanently available (nothing is deleted).
        if target in _QUALITY_LABEL_STATUSES:
            # Explicit no-gate contract: qualification receipts are optional
            # evidence, never prerequisites for changing a quality/status badge.
            pass
        elif (
            target in _DISPOSITION_STATUSES
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
        # aliases sits right after description on purpose: update_status rewrites the
        # frontmatter from this whitelist, and without it a status flip would drop
        # aliases to the alphabetically-sorted tail and churn the key order of every
        # card it touches.
        ordered = ["method_id", "name", "description", "aliases", "status", "source_model", "teacher_refs", "source_episode_refs", "evidence_refs", "freshness_refs", "parent_ref", "supersedes", "created_at", "updated_at"]
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

    def _alias_corpus(self) -> tuple[list[str], int]:
        """Normalized text of every discoverable card, for the alias df check.

        Deliberately uncached: one save scans the pool once (~25ms at 1369 cards),
        which is cheaper than keeping an index consistent with concurrent writes.
        Retired cards are skipped so their ids/aliases cannot inflate df.
        """
        texts: list[str] = []
        for path in self._iter_paths():
            record = self._load_path(path)
            if record is None or record.status == "retired":
                continue
            texts.append(
                self._normalized_search_text(
                    " ".join(
                        (
                            record.method_id,
                            record.method_ref,
                            record.name,
                            record.description,
                            record.body,
                            " ".join(record.aliases),
                        )
                    )
                )
            )
        return texts, len(texts)

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
        aliases: list[str] | None = None,
        alias_drops: list[dict[str, Any]] | None = None,
    ) -> MethodRecord:
        """Write-once candidate publication; derived hooks run only on certain commits.

        ``aliases`` are retrieval hints, not card content: they are gated here and
        never rewrite an existing card (write-once). ``alias_drops`` is an optional
        out-parameter the caller may pass to report why a supplied alias was not
        persisted; it is filled only when a new card is actually written.
        """
        # held-out 写侧防线：不在入口手工拼字段预检（第一轮的拼装遗漏正是
        # 漏检根因）；权威封堵在 _commit_new_directory 对最终落盘卡片全文
        # 执行（封堵点①），拒写时目录/staging 零副作用。
        self._require_write_safe()
        with _store_lock(self._dir):
            record, created = self._save_candidate_locked(
                name=name, description=description, body=body,
                source_model=source_model, teacher_refs=teacher_refs,
                source_episode_refs=source_episode_refs, evidence_refs=evidence_refs,
                parent_ref=parent_ref, freshness_refs=freshness_refs,
                aliases=aliases, alias_drops=alias_drops,
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
        aliases: list[str] | None = None,
        alias_drops: list[dict[str, Any]] | None = None,
    ) -> tuple[MethodRecord, bool]:
        """Persist semantic content supplied by the model; never overwrite or auto-promote.

        Aliases are gated mechanically before the write (see ``gate_aliases``); the
        card body and every other frontmatter key stay exactly as supplied.
        """
        # Shape is model-owned: procedure/index/reminder cards all pass. The boundary
        # only refuses a body with no readable content (blank or headings-only).
        if _card_content_missing(body):
            raise ValueError(
                "Method Card needs at least one non-heading line of content in body; "
                "a blank or headings-only card cannot help a later reader"
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
        # Gate aliases before the write so a noisy hint never becomes durable state.
        # The scan is skipped entirely when no aliases were supplied, which keeps the
        # alias-free write path byte-identical to before this feature existed.
        kept_aliases: list[str] = []
        if aliases:
            corpus_texts, pool_size = self._alias_corpus()
            kept_aliases, dropped_aliases = gate_aliases(
                aliases, name=name, corpus=corpus_texts, pool_size=pool_size
            )
            if alias_drops is not None:
                alias_drops.extend(dropped_aliases)
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
        front += line("aliases", ", ".join(kept_aliases))
        front += "status: candidate\n" + line("source_model", source_model) + line("teacher_refs", ",".join(checked_teachers))
        front += line("source_episode_refs", ",".join(checked_episode_refs)) + line("evidence_refs", ",".join(evidence_refs or []))
        front += line("freshness_refs", ",".join(checked_freshness_refs))
        front += line("parent_ref", parent_ref) + line("created_at", now) + line("updated_at", now) + "---\n"
        # held-out 写侧防线：card_text 的权威检查在 _commit_new_directory
        # （封堵点①）对这份最终序列化全文执行，此处不重复拼检。
        card_text = front + body.strip() + "\n"
        self._commit_new_directory(method_id, {"METHOD.md": card_text.encode("utf-8")}, operation="save_candidate")
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

    def annotate_aliases(
        self,
        method_ref: str,
        aliases: list[str],
        *,
        mode: str = "merge",
    ) -> tuple[MethodRecord, list[dict[str, Any]]]:
        """Add/replace the retrieval-hint aliases of an existing card.

        ``save_candidate`` is idempotent by design and never rewrites, so cards
        created before aliases existed had no in-band way to gain them; the only
        alternative was hand-editing frontmatter (bypassing the gate). This is the
        same one-key read-modify-write as ``annotate_freshness``: body and every
        other field stay byte-identical, ``mode="merge"`` appends to the aliases
        already on the card, ``mode="replace"`` overwrites, and the same
        mechanical gate (length / generic / duplicate / df / cap) runs on whatever
        would be persisted. Returns ``(record, dropped)``; a no-op returns the
        record without touching the file.
        """
        if mode not in {"merge", "replace"}:
            raise ValueError(f"mode must be merge|replace, got {mode!r}")
        self._require_write_safe()
        with _store_lock(self._dir):
            return self._annotate_aliases_locked(method_ref, aliases, mode)

    def _annotate_aliases_locked(
        self, method_ref: str, aliases: list[str], mode: str
    ) -> tuple[MethodRecord, list[dict[str, Any]]]:
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
        existing = self._load_path(path)
        if existing is None:
            raise ValueError("card is unreadable")
        old_aliases = list(existing.aliases)
        requested = list(aliases if mode == "replace" else [*old_aliases, *aliases])
        corpus_texts, pool_size = self._alias_corpus()
        kept, dropped = gate_aliases(
            requested, name=existing.name, corpus=corpus_texts, pool_size=pool_size
        )
        if kept == old_aliases:
            # Nothing survived the gate (or nothing changed): do not churn mtime,
            # updated_at, or key order for a write that would be a no-op.
            return existing, dropped
        now = _now()
        old_match = re.search(r"^aliases:.*$", front, re.MULTILINE)
        if not kept and old_aliases:
            # Review P1 (2nd round): mode="replace" with everything dropped would write
            # `aliases: ` — an empty scalar that round-trips cleanly and therefore passes
            # the check below, silently wiping aliases the caller never asked to delete.
            # Refuse instead: pruning to zero is a decision the caller must make explicitly.
            raise ValueError(
                "refusing to replace aliases with an empty set while the card has "
                f"{len(old_aliases)} alias(es); pass mode='merge' or delete explicitly"
            )
        old_value = old_match.group(0).split(":", 1)[1].strip() if old_match else ""
        new_line = f"aliases: {', '.join(kept)}"
        if old_match:
            front = front[: old_match.start()] + new_line + front[old_match.end():]
        else:
            desc_match = re.search(r"^description:.*$", front, re.MULTILINE)
            anchor = desc_match.end() if desc_match is not None else 0
            front = front[:anchor] + "\n" + new_line + front[anchor:]
        updated_match = re.search(r"^updated_at:.*$", front, re.MULTILINE)
        if updated_match:
            front = front[: updated_match.start()] + f"updated_at: {now}" + front[updated_match.end():]
        payload = "---\n" + front + "\n---\n" + body
        # Validate before writing (review P1-2): a composed payload that no longer parses
        # back to the requested aliases must fail here, not after _replace_card has already
        # replaced the card on disk — otherwise a bad join leaves a corrupt card behind and
        # the raise happens on top of the damage.
        reparsed, reparsed_body = _parse_frontmatter(payload)
        if reparsed.get("aliases") != ", ".join(kept) or reparsed_body != body:
            raise ValueError(
                f"alias annotation would not round-trip (aliases={reparsed.get('aliases')!r}, "
                f"kept={kept!r}); refusing to write"
            )
        self._replace_card(path, payload, operation="annotate_aliases")
        record = self._load_path(path)
        if record is None:
            raise RuntimeError("annotation did not round-trip")
        try:
            with (self._dir / "annotations.jsonl").open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": now,
                            "event": "annotate_aliases",
                            "method_ref": method_id,
                            "mode": mode,
                            "old": old_value,
                            "new": kept,
                            "dropped": dropped,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass
        return record, dropped

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
