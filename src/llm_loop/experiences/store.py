"""经验库存储组件 ExperienceStore（design §2.3.2.4/§2.4.2）.

写入（文件名 sanitize + 路径安全 + 冲突检测）、检索（扫描目录 + front matter 解析 +
关键词匹配 + 默认仅 active）、状态流转（更新 status 不删除文档）。
R2（tasks §2）：三态扫描——正常/可降级文档正常参与检索，不可解析文档跳过并脱敏
留痕（best-effort）；目录级扫描失败独立防护为 scan_error 诊断态（不崩库）；
ExperienceSearchOutcome 承载结果 + 诊断四要素；last_experience_diagnostics 属性透传。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_loop.experiences.document import ExperienceDocument
from llm_loop.timekeeping import system_local_now
from llm_loop.usage_net import summarize_since_last_transition

logger = logging.getLogger(__name__)


@dataclass
class ExperienceSearchOutcome:
    """单次经验库扫描的完整结果 + 诊断四要素载体（design §2.1.3-4.2，D11）."""

    records: list[dict]
    scanned_count: int = 0
    degraded_count: int = 0
    skipped_count: int = 0
    scan_error: str | None = None  # 目录级扫描失败的脱敏摘要（None = 扫描正常完成）


def _sanitize_trace(text: str) -> str:
    """留痕脱敏：Path.home() 绝对路径前缀替换为 ~（防 str(exc) 泄漏 /Users/...）."""
    home = str(Path.home())
    if home and home != "/":
        return text.replace(home, "~")
    return text


def _trace_excerpt(exc: BaseException) -> str:
    """异常摘要三要素后两项：类型名 + 消息压缩为单行 + 脱敏 + 截断 200 字符."""
    line = " ".join(f"{type(exc).__name__}: {exc}".split())
    return _sanitize_trace(line)[:200]


def _skip_trace(filename: str, exc: BaseException) -> None:
    """跳过不可解析文档的 WARNING 留痕（best-effort：留痕自身失败不影响主流程）.

    filename 仅取 path.name（白名单字段，无目录成分）；摘要经 _sanitize_trace 脱敏，
    留痕全文不含 home 前缀绝对路径片段。
    """
    try:  # noqa: SIM105 — 显式 try/except 防护为规格要求形态（design D7 best-effort）
        logger.warning("[经验库] 跳过不可解析文档 %s: %s", filename, _trace_excerpt(exc))
    except Exception:  # noqa: BLE001 — 留痕为 best-effort，logging 故障不作硬契约依赖
        pass


class ExperiencePersistError(OSError):
    """经验写入确定未提交（跨进程锁不可用 / replace·link 前失败）；同一 payload 重试安全."""


class ExperienceCommitUncertainError(OSError):
    """经验文档已原子可见但目录 fsync 未确认：提交结果不确定.

    DRC T2 红线：禁止把本异常解释成"肯定没写"后盲重放——save 可能已占用文件名
    （同日同 slug），update 可能已生效；必须先按 expected_sha256 + visible_state
    对最终文件做逐字 readback reconcile（store.get），再决定语义层动作。
    """

    def __init__(
        self,
        message: str,
        *,
        experience_id: str,
        expected_sha256: str,
        visible_state: str,
    ) -> None:
        super().__init__(message)
        self.experience_id = experience_id
        self.expected_sha256 = expected_sha256
        self.visible_state = visible_state


_DIR_FSYNC_ATTEMPTS = 3
_LOCK_FILENAME = ".__experience_store.lock"


def _write_temp_exclusive(path: Path, payload: str) -> None:
    """独占 tmp 写入 + file fsync（DRC T2 replace 前；O_EXCL 防复用旧 tmp）."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    """目录 fsync：让 link/replace 的目录项变更跨崩溃可见（T2 durability fence）."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _payload_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _visible_state(path: Path, payload: str) -> str:
    """逐字 readback：最终文件是否等于 intended payload（matches/mismatch/unreadable）."""
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        return "unreadable"
    return "matches" if current == payload else "mismatch"


class ExperienceStore:
    """经验库存储组件（操作 experiences/ 目录）。"""

    def __init__(
        self,
        experiences_dir: str | Path,
        *,
        embedder: Any | None = None,
        semantic_ranker: Callable[..., list[tuple[int, float]]] | None = None,
        write_guard: Callable[[], bool] | None = None,
        near_dup_threshold: float = 0.80,
    ) -> None:
        self._dir = Path(experiences_dir)
        # DRC T2：非 POSIX 无 fcntl 运行时的进程内写锁 fallback（不声称跨进程保证）
        self._thread_lock = threading.RLock()
        self._write_guard = write_guard
        self._embedder = embedder  # T5: 可选 embedder 注入（None 时走关键词匹配，零回归）
        self._semantic_ranker = semantic_ranker
        self._post_save_hooks: list[Callable[[dict[str, Any]], Any]] = []
        # T0-C1: 写时近重复链接阈值（保守未校准默认；仅高相似改写触发无损链接）
        self._near_dup_threshold = near_dup_threshold
        # 文档向量只缓存机械可验证的输入→输出；query 向量每次现算。
        # filename 作为槽位可让同一经验内容变化时原位替换，避免陈旧 hash 无限累积。
        self._doc_embedding_cache: dict[str, tuple[str, list[float]]] = {}
        self._last_diagnostics: dict[str, Any] = {
            "scanned": 0,
            "degraded": 0,
            "skipped": 0,
            "scan_error": None,
        }
        self._last_semantic_diagnostics: dict[str, Any] = {}


    def _require_write_safe(self) -> None:
        if self._write_guard is None:
            return
        try:
            allowed = bool(self._write_guard())
        except Exception as exc:  # noqa: BLE001 — health failure must fail closed for mutation
            raise PermissionError("knowledge store quarantined: write health unavailable") from exc
        if not allowed:
            raise PermissionError("knowledge store quarantined: mutation disabled")

    @property
    def last_experience_diagnostics(self) -> dict:
        """最近一次扫描的诊断四要素摘要（实验性：单线程假设，并发场景需改参数传递）.

        每次公开方法（list_active / search_outcome / get / update_status）入口显式
        重置，search_outcome 完成时回填；值为 {scanned, degraded, skipped, scan_error}。
        """
        return self._last_diagnostics

    @property
    def last_semantic_diagnostics(self) -> dict[str, Any]:
        """Latest semantic-ranking diagnostics, separate from scan/parse diagnostics."""
        return dict(self._last_semantic_diagnostics)

    def _reset_diagnostics(self) -> None:
        """公开方法入口显式重置诊断（并发防护，见 last_experience_diagnostics docstring）."""
        self._last_diagnostics = {"scanned": 0, "degraded": 0, "skipped": 0, "scan_error": None}
        self._last_semantic_diagnostics = {}

    def add_post_save_hook(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        """Register best-effort derived work after the durable document write."""
        self._post_save_hooks.append(fn)

    @staticmethod
    def sanitize_slug(slug: str) -> str:
        """转 kebab-case：小写 + 非字母数字转连字符 + 去首尾连字符 + 截断 50 字符.

        2026-10-10 修复：旧实现只保留 ASCII [a-zA-Z0-9]，纯中文/中文开头标题塌缩为
        空串 → save() 回退 "untitled" → 同日第二条中文经验即同 slug 冲突被拒（不可逆
        丢失；experiences/ 已累积 18 个 *-untitled.md）。现保留 Unicode 字母数字
        （\\w 去下划线），纯 ASCII 输出与旧实现逐字节一致（回归测试锁定）。
        """
        s = re.sub(r"([^\w]|_)+", "-", slug).strip("-").lower()
        return s[:50].rstrip("-")

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        """跨进程单写者锁（flock LOCK_EX；POSIX 锁失败 fail-closed，DRC T2）.

        多进程（web/feishu/learning 服务）共享同一 experiences/ 目录：save 的
        exists 检查 + 近重复扫描、update_status 的 read-modify-write 都必须在
        单写者临界区内完成。无 fcntl 的非 POSIX 运行时退化为进程内 RLock
        （与 ScheduleStore._file_lock 同形，明确不声称跨进程 T2）。
        """
        try:
            import fcntl
        except ImportError:
            with self._thread_lock:
                yield
            return
        lock_path = self._dir / _LOCK_FILENAME
        handle = None
        try:
            handle = lock_path.open("a", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise ExperiencePersistError(
                f"经验库跨进程文件锁不可用，拒绝无锁写入: {exc}"
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def save(self, doc: ExperienceDocument) -> str:
        """写入经验文档；返回文件名。冲突时抛 FileExistsError（不覆盖）.

        DRC T2（#7 迁移，2026-10-08）：store flock 内 tmp(O_EXCL)→file fsync
        →os.link 原子 create-if-absent→目录 fsync。replace/link 前失败=
        ExperiencePersistError（确定未提交，同一 payload 重试安全）；link 成功后
        目录 fsync 耗尽=ExperienceCommitUncertainError（禁止盲重放，先 get() 逐字
        readback）。post_save_hooks 仅在确定提交后运行（derived work 不参与回滚）。
        """
        self._require_write_safe()
        self._dir.mkdir(parents=True, exist_ok=True)
        date_str = system_local_now().strftime("%Y%m%d")
        slug = self.sanitize_slug(doc.title)
        if not slug:
            # 纯符号/空标题兜底（2026-10-10）：标题 hash 区分不同条目，避免同日全部
            # 塌缩成同一个 "untitled" 互相冲突拒绝；同标题同日重试仍走既有同 slug
            # 冲突契约（FileExistsError），保持重试幂等语义不变。
            slug = f"untitled-{_payload_sha256(doc.title)[:8]}"
        filename = f"EXPERIENCE-{date_str}-{slug}.md"
        path = self._dir / filename
        experience_id = filename.removesuffix(".md")
        with self._file_lock():
            if path.exists():
                raise FileExistsError(f"经验文档已存在: {filename}（同日同 slug 冲突，不覆盖）")
            # T0-C1（2026-09-16）: 写时近重复无损链接——新条目记 supersedes 指针，绝不改写
            # 旧条目（合并走人工批准事务）；embedder 缺失/故障一律跳过（fail-open 不阻断写入）。
            try:
                near = self._find_near_duplicate_ids(filename, doc)
                if near:
                    doc.supersedes = list(dict.fromkeys([*(doc.supersedes or []), *near]))
                    logger.info("[经验库] 近重复无损链接: %s supersedes %s", filename, near)
            except Exception:  # noqa: BLE001 — 链接探测失败不影响写入本身
                logger.warning("[经验库] 近重复探测异常，本次跳过链接（fail-open）", exc_info=True)
            payload = doc.to_md()
            temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
            try:
                _write_temp_exclusive(temp, payload)
                try:
                    os.link(temp, path)  # 原子 create-if-absent：绝不覆盖任何已存在文件
                except FileExistsError as exc:
                    raise FileExistsError(
                        f"经验文档已存在: {filename}（并发创建冲突，不覆盖）"
                    ) from exc
                except OSError as exc:
                    raise ExperiencePersistError(
                        f"经验文档创建失败(确定未提交): {filename}: {exc}"
                    ) from exc
            except OSError as exc:
                # FileExistsError 是既有语义冲突契约，原样上抛；其余 replace 前失败=确定未提交
                if not isinstance(exc, (FileExistsError, ExperiencePersistError)):
                    raise ExperiencePersistError(
                        f"经验文档写入失败(确定未提交): {filename}: {exc}"
                    ) from exc
                raise
            finally:
                temp.unlink(missing_ok=True)
            self._fsync_dir_or_uncertain(path, payload, experience_id)
        candidate = self._semantic_candidate(filename, doc)
        for hook in tuple(self._post_save_hooks):
            try:
                hook(dict(candidate))
            except Exception:  # noqa: BLE001 — derived vector work never rolls back durable write
                logger.debug("experience post-save hook failed", exc_info=True)
        return filename

    def _fsync_dir_or_uncertain(self, path: Path, payload: str, experience_id: str) -> None:
        """link/replace 已生效后的目录 fsync：有界重试，耗尽→typed uncertain + readback.

        持 store flock 时逐字 readback 最终文件（单写者下 readback 可信）；
        调用方必须仍处于 _file_lock 临界区内。
        """
        last_exc: OSError | None = None
        for _ in range(_DIR_FSYNC_ATTEMPTS):
            try:
                _fsync_directory(path.parent)
                return
            except OSError as exc:
                last_exc = exc
        raise ExperienceCommitUncertainError(
            f"经验文档已原子可见但目录 fsync 失败(提交结果不确定): {experience_id}: {last_exc}",
            experience_id=experience_id,
            expected_sha256=_payload_sha256(payload),
            visible_state=_visible_state(path, payload),
        )

    def list_active(
        self,
        query: str = "",
        limit: int = 20,
        *,
        record_kind: str | None = None,
    ) -> list[dict]:
        """扫描 experiences/*.md，过滤 active，按相关性排序截断到 limit（兼容 wrapper）.

        T5: embedder 注入且 embed(query) 成功时走语义检索（cosine 相似度降序）；
        否则回退关键词匹配（fail-open，零回归）。结果附 score 字段。
        跳过发生且结果非空时，命中记录附 degraded="[经验库降级] ..."（拼接共存）；
        可降级记录附 degraded_fields=["source"]。签名与返回形状零变化。
        """
        return self.search_outcome(query, limit, record_kind=record_kind).records

    def catalog(
        self,
        query: str = "",
        limit: int = 200,
        *,
        status: str = "",
    ) -> dict[str, Any]:
        """管理/可观测性目录：全生命周期状态分组 + 记录列表（含 inactive）.

        与 search_outcome（检索视图，隐藏非 active 文档）不同，catalog 面向
        web 管理页：archived/invalidated/superseded 同样列出并带 status 徽标，
        供人工审视与生命周期操作。只读、关键词子串匹配、无语义排序；
        记录按文件名倒序（≈创建时间倒序），counts 为全量统计（不受 query/limit 影响）。
        """
        self._reset_diagnostics()
        counts: dict[str, int] = {}
        records: list[dict] = []
        skipped = 0
        scan_error: str | None = None
        usage = self.usage_stats()  # EVO-20261013 知识页：经验卡使用统计投影
        try:
            paths = sorted(self._dir.glob("EXPERIENCE-*.md"), reverse=True)
        except OSError as exc:  # 与 search_outcome 同形：目录级失败如实上报诊断态
            paths = []
            scan_error = str(exc)
        for path in paths:
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — 单文档坏档跳过并计数
                skipped += 1
                _skip_trace(path.name, exc)
                continue
            doc_status = str(doc.status or "active")
            counts[doc_status] = counts.get(doc_status, 0) + 1
            if status and doc_status != status:
                continue
            record = self.to_hydrated_record(path.stem, doc)
            stat = usage.get(str(record.get("experience_ref") or ""), {})
            record["use_count"] = int(stat.get("use_count") or 0)
            record["last_used_at"] = stat.get("last_used_at")
            if query:
                haystack = f"{record.get('summary', '')} {record.get('scenario', '')} {' '.join(record.get('tags') or [])}"
                if query.lower() not in haystack.lower():
                    continue
            if len(records) < limit:
                records.append(record)
        self._last_diagnostics["scanned"] = len(paths)
        self._last_diagnostics["skipped"] = skipped
        self._last_diagnostics["scan_error"] = scan_error
        return {"counts": counts, "records": records, "diagnostics": self._last_diagnostics}

    def search_outcome(
        self,
        query: str = "",
        limit: int = 20,
        *,
        record_kind: str | None = None,
    ) -> ExperienceSearchOutcome:
        """三态扫描 + 诊断载体：正常/可降级文档入结果，不可解析文档跳过并脱敏留痕.

        目录级扫描失败（glob PermissionError/OSError）不崩库，以 scan_error 诊断态
        如实上报（不伪装业务零结果）；诊断计数在匹配/截断之前完成——被 results[:limit]
        截断的记录不影响统计。
        """
        self._reset_diagnostics()
        if not self._dir.exists():
            return ExperienceSearchOutcome(records=[])
        try:
            paths = sorted(self._dir.glob("EXPERIENCE-*.md"))
        except OSError as exc:
            summary = _trace_excerpt(exc)
            self._last_diagnostics = {
                "scanned": 0,
                "degraded": 0,
                "skipped": 0,
                "scan_error": summary,
            }
            return ExperienceSearchOutcome(records=[], scan_error=summary)

        active: list[tuple[str, ExperienceDocument]] = []
        scanned_count = len(paths)
        degraded_count = 0
        skipped_count = 0
        for path in paths:
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — 防御纵深：store 不假设下层异常面完备（D4）
                skipped_count += 1
                _skip_trace(path.name, exc)
                continue
            if self._is_degraded_source(doc.source):
                degraded_count += 1  # 可降级文档：正常入候选，不跳过不留痕（design §2.1.3-1）
            if doc.status != "active":
                continue
            if record_kind is not None and doc.record_kind != record_kind:
                continue
            active.append((path.name, doc))

        active = self._filter_superseded(active)

        records = self._search(active, query, limit)

        if skipped_count > 0 and records:
            text = f"[经验库降级] 跳过 {skipped_count} 个不可解析文档，结果可能不全"
            for rec in records:
                self._append_degraded(rec, text)

        outcome = ExperienceSearchOutcome(
            records=records,
            scanned_count=scanned_count,
            degraded_count=degraded_count,
            skipped_count=skipped_count,
        )
        self._last_diagnostics = {
            "scanned": outcome.scanned_count,
            "degraded": outcome.degraded_count,
            "skipped": outcome.skipped_count,
            "scan_error": None,
        }
        return outcome

    def _search(
        self, active: list[tuple[str, ExperienceDocument]], query: str, limit: int
    ) -> list[dict]:
        """相关性检索：weighted lexical 为主，semantic 为可选附加信号。

        程序只排序相关性，不判断经验对当前任务是否适用；后者仍由模型结合
        lifecycle/source/current facts 判断。空 query 保持按文件顺序列 active catalog。
        """
        if not query:
            return self._keyword_search(active, query, limit, degraded=False)

        lexical = [
            (self._lexical_score(doc, query), filename, doc) for filename, doc in active
        ]
        if self._semantic_ranker is not None:
            candidates = [self._semantic_candidate(filename, doc) for filename, doc in active]
            try:
                ranked = self._semantic_ranker(query, candidates, top_k=len(candidates))
            except Exception:  # noqa: BLE001 — semantic path is optional enhancement
                ranked = []
            owner = getattr(self._semantic_ranker, "__self__", None)
            self._last_semantic_diagnostics = dict(
                getattr(owner, "last_cached_rank_diagnostics", {}) or {}
            )
            if not ranked:
                degraded = bool(
                    self._last_semantic_diagnostics.get("semantic_requested")
                    and self._last_semantic_diagnostics.get("semantic_fallback_reason")
                )
                return self._rank_lexical(lexical, limit, degraded=degraded)
            return self._hybrid_ranked_search(lexical, ranked, limit)
        if self._embedder is None:
            return self._rank_lexical(lexical, limit, degraded=False)

        try:
            query_vec = self._embedder.embed(query)
        except Exception:
            query_vec = None
        if query_vec is None:
            # embed 失败 → fail-open 到 lexical ranking，并如实标注。
            return self._rank_lexical(lexical, limit, degraded=True)
        return self._hybrid_search(lexical, query_vec, limit)

    @staticmethod
    def _filter_superseded(
        active: list[tuple[str, ExperienceDocument]],
    ) -> list[tuple[str, ExperienceDocument]]:
        """Hide active records superseded by a newer active canonical record."""
        if not any(doc.supersedes for _fname, doc in active):
            return active
        superseded_ids: set[str] = set()
        for _fname, doc in active:
            superseded_ids.update(doc.supersedes or [])
        if not superseded_ids:
            return active
        before = len(active)
        filtered = [
            (fname, doc)
            for fname, doc in active
            if fname.removesuffix(".md") not in superseded_ids
        ]
        logger.info("[经验库] supersede 去重: %d → %d（隐藏被链接旧条目）", before, len(filtered))
        return filtered

    @staticmethod
    def _semantic_candidate(filename: str, doc: ExperienceDocument) -> dict[str, Any]:
        return {
            "kind": doc.record_kind,
            "id": filename.removesuffix(".md"),
            "key": f"experience:{filename.removesuffix('.md')}",
            "content": " ".join([doc.title, doc.scenario, doc.root_cause, doc.solution]).strip(),
        }

    def semantic_candidates(self, *, record_kind: str | None = None) -> list[dict[str, Any]]:
        """Return active canonical candidates for derived-vector warmup; no ranking authority."""
        if not self._dir.exists():
            return []
        try:
            paths = sorted(self._dir.glob("EXPERIENCE-*.md"))
        except OSError:
            return []
        active: list[tuple[str, ExperienceDocument]] = []
        for path in paths:
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — warmup skips malformed rows exactly like discovery
                continue
            if doc.status != "active":
                continue
            if record_kind is not None and doc.record_kind != record_kind:
                continue
            active.append((path.name, doc))
        active = self._filter_superseded(active)
        return [self._semantic_candidate(filename, doc) for filename, doc in active]

    def _hybrid_ranked_search(
        self,
        lexical: list[tuple[float, str, ExperienceDocument]],
        ranked: list[tuple[int, float]],
        limit: int,
    ) -> list[dict]:
        """Fuse qualified semantic hits with lexical-primary weighting.

        Rows with neither lexical evidence nor a semantic score above the retriever's
        calibrated threshold are excluded, so semantic ON cannot pad a noise query with
        unrelated zero-signal cards.
        """
        semantic_by_index = {index: score for index, score in ranked}
        max_lexical = max((score for score, _, _ in lexical), default=0.0)
        scored: list[tuple[float, str, ExperienceDocument]] = []
        for index, (lexical_score, filename, doc) in enumerate(lexical):
            if lexical_score <= 0 and index not in semantic_by_index:
                continue
            semantic_score = min(1.0, max(0.0, float(semantic_by_index.get(index, 0.0))))
            lexical_norm = lexical_score / max_lexical if max_lexical > 0 else 0.0
            score = 0.65 * lexical_norm + 0.35 * semantic_score
            scored.append((score, filename, doc))
        scored.sort(key=lambda row: (-row[0], row[1]))
        results: list[dict] = []
        for score, filename, doc in scored[:limit]:
            rec = self._to_record(filename, doc)
            rec["score"] = round(score, 4)
            results.append(rec)
        return results

    def _hybrid_search(
        self,
        lexical: list[tuple[float, str, ExperienceDocument]],
        query_vec: list[float],
        limit: int,
    ) -> list[dict]:
        """合并 lexical + semantic；强 lexical 命中不会被纯 semantic 噪声压过。"""
        if self._embedder is None:
            return []
        max_lexical = max((score for score, _, _ in lexical), default=0.0)
        scored: list[tuple[float, str, ExperienceDocument]] = []
        for lexical_score, filename, doc in lexical:
            doc_vec = self._document_embedding(filename, doc)
            if doc_vec is None:
                semantic_score = 0.0
            else:
                semantic_score = min(1.0, max(0.0, _cosine_similarity(query_vec, doc_vec)))
            lexical_norm = lexical_score / max_lexical if max_lexical > 0 else 0.0
            # lexical 是主信号；semantic 只补充相关性，不授予 task applicability。
            score = 0.75 * lexical_norm + 0.25 * semantic_score
            scored.append((score, filename, doc))
        scored.sort(key=lambda row: (-row[0], row[1]))
        results: list[dict] = []
        for score, filename, doc in scored[:limit]:
            rec = self._to_record(filename, doc)
            rec["score"] = round(score, 4)
            results.append(rec)
        return results

    def _document_embedding(
        self, filename: str, doc: ExperienceDocument
    ) -> list[float] | None:
        """按实际嵌入文本内容指纹复用文档向量；失败结果不缓存。"""
        if self._embedder is None:
            return None
        doc_text = " ".join([doc.title, doc.scenario, doc.root_cause, doc.solution])
        namespace = self._embedder_cache_namespace()
        fingerprint = hashlib.sha256(
            f"{namespace}\0{doc_text}".encode()
        ).hexdigest()
        cached = self._doc_embedding_cache.get(filename)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        try:
            doc_vec = self._embedder.embed(doc_text)
        except Exception:
            doc_vec = None
        if doc_vec is not None:
            self._doc_embedding_cache[filename] = (fingerprint, doc_vec)
        return doc_vec

    def _find_near_duplicate_ids(
        self, filename: str, doc: ExperienceDocument, *, cap: int = 3
    ) -> list[str]:
        """T0-C1 写时近重复探测: 语义相似 ≥ near_dup_threshold 的 active 旧条目 id.

        无损链接（link-not-merge）: 只产出 supersedes 指针，不改写旧条目；存量合并
        事务走人工批准。fail-open: 无 embedder / 嵌入失败 / 扫描异常 → 返回空。
        阈值 0.80 为保守默认（未校准，仅拦截高相似改写）。
        """
        if self._semantic_ranker is not None:
            candidates = self.semantic_candidates()
            if not candidates:
                return []
            query_text = self._semantic_candidate(filename, doc)["content"]
            try:
                ranked = self._semantic_ranker(query_text, candidates, top_k=len(candidates))
            except Exception:  # noqa: BLE001 — near-dup hint is fail-open
                return []
            hits = [
                (float(score), str(candidates[index].get("id") or ""))
                for index, score in ranked
                if 0 <= index < len(candidates)
                and float(score) >= self._near_dup_threshold
                and str(candidates[index].get("id") or "")
            ]
            def _mtime(fid: str) -> float:
                try:
                    return (self._dir / f"{fid}.md").stat().st_mtime
                except OSError:
                    return 0.0

            # Preserve the historical near-duplicate tie contract: newest canonical
            # record wins when semantic scores tie, so cap truncation does not hide the
            # latest chain head merely because filename ordering is older-first.
            hits.sort(key=lambda row: (-row[0], -_mtime(row[1]), row[1]))
            return [fid for _score, fid in hits[:cap]]
        if self._embedder is None:
            return []
        # 探测文本与文档指纹文本同构，直接复用文档向量缓存（写时嵌入一次，
        # 后续检索命中同一 fingerprint），不产生额外 embedder 调用。
        q_vec = self._document_embedding(filename, doc)
        if not q_vec:
            return []
        try:
            paths = sorted(self._dir.glob("EXPERIENCE-*.md"))
        except OSError:
            return []
        hits: list[tuple[float, str]] = []
        for path in paths:
            try:
                other = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — 损坏文档跳过
                continue
            if other.status != "active":
                continue
            doc_vec = self._document_embedding(path.name, other)
            if not doc_vec:
                continue
            score = _cosine_similarity(q_vec, doc_vec)
            if score >= self._near_dup_threshold:
                hits.append((score, path.name.removesuffix(".md")))
        def _mtime(fid: str) -> float:
            try:
                return (self._dir / f"{fid}.md").stat().st_mtime
            except OSError:
                return 0.0

        # 平分时最新写入优先（mtime 判新, 文件名兜底; 字符串序对 r9/r10 类编号
        # 不是时间序）——cap 截断不丢最新链头
        hits.sort(key=lambda row: (-row[0], -_mtime(row[1]), row[1]))
        return [fid for _score, fid in hits[:cap]]

    def _embedder_cache_namespace(self) -> str:
        """机械描述向量契约，防 provider/model/vector-version 变化复用旧向量。"""
        embedder = self._embedder
        if embedder is None:
            return "none"
        parts = [f"{type(embedder).__module__}.{type(embedder).__qualname__}"]
        for name in ("provider", "vector_version", "model", "base_url", "_dim"):
            value = getattr(embedder, name, None)
            if value not in (None, ""):
                parts.append(f"{name}={value}")
        return "|".join(parts)

    def _keyword_search(
        self, active: list[tuple[str, ExperienceDocument]], query: str, limit: int, *, degraded: bool
    ) -> list[dict]:
        """Weighted lexical 检索；空 query 保持 catalog 顺序。"""
        if not query:
            results: list[dict] = []
            for filename, doc in active[:limit]:
                rec = self._to_record(filename, doc)
                rec["score"] = None
                results.append(rec)
            return results
        lexical = [(self._lexical_score(doc, query), filename, doc) for filename, doc in active]
        return self._rank_lexical(lexical, limit, degraded=degraded)

    def _rank_lexical(
        self,
        lexical: list[tuple[float, str, ExperienceDocument]],
        limit: int,
        *,
        degraded: bool,
    ) -> list[dict]:
        matched = [row for row in lexical if row[0] > 0]
        matched.sort(key=lambda row: (-row[0], row[1]))
        results: list[dict] = []
        for score, filename, doc in matched[:limit]:
            rec = self._to_record(filename, doc)
            rec["score"] = round(score, 4)
            if degraded:
                self._append_degraded(rec, "[语义检索降级] embed 失败，回退关键词匹配")
            results.append(rec)
        return results

    @staticmethod
    def _lexical_score(doc: ExperienceDocument, query: str) -> float:
        """字段加权 lexical score；只做相关性事实，不推断任务适用性。"""
        norm_query = _normalize_search_text(query)
        if not norm_query:
            return 0.0
        terms = _lexical_terms(norm_query)
        fields = (
            (5.0, doc.title),
            (4.0, " ".join(doc.tags)),
            (3.0, doc.scenario),
            (3.0, doc.root_cause),
            (2.0, doc.solution),
        )
        score = 0.0
        matched_terms: set[str] = set()
        for field_weight, raw in fields:
            field = _normalize_search_text(raw)
            if not field:
                continue
            if norm_query in field:
                score += 6.0 * field_weight
            for term, term_weight in terms.items():
                if term in field:
                    score += field_weight * term_weight
                    matched_terms.add(term)
        if matched_terms and terms:
            matched_mass = sum(terms[term] for term in matched_terms)
            total_mass = sum(terms.values())
            score += 4.0 * matched_mass / total_mass
        return score

    def get(self, experience_id: str) -> ExperienceDocument | None:
        """按文件名/标识读取并解析；不存在/任何解析故障返回 None（读取面 fail-open 隔离）."""
        self._reset_diagnostics()
        path = self._safe_path(experience_id)
        if path is None or not path.exists():
            return None
        try:
            return ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 防御纵深（design §2.1.3-4.1，与三读取路径对齐）
            _skip_trace(path.name, exc)
            return None

    def update_status(self, experience_id: str, status: str) -> bool:
        """更新 status 字段 + 刷新 updated_at，不删除文档；不存在/读取故障返回 False.

        DRC T2（#7 迁移，2026-10-08）：read-modify-write 在跨进程 store flock 内
        执行，tmp(O_EXCL)→file fsync→os.replace→目录 fsync——最终文件只可能是
        整体旧或整体新，不再出现崩溃截断的半卡。replace 前失败=
        ExperiencePersistError（原文件原样保留，同一 payload 重试安全）；replace 后
        目录 fsync 耗尽=ExperienceCommitUncertainError（禁止盲重放，先 get() 核对）。
        降级形态 source 经 to_md round-trip 保留原形态（design §2.1.3-3）。
        """
        self._require_write_safe()
        self._reset_diagnostics()
        path = self._safe_path(experience_id)
        if path is None or not path.exists():
            return False
        with self._file_lock():
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 — 防御纵深（design §2.1.3-4.1），读取面 fail-open
                _skip_trace(path.name, exc)
                return False
            doc.status = status
            doc.updated_at = system_local_now().isoformat()
            payload = doc.to_md()
            temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:12]}.tmp")
            try:
                _write_temp_exclusive(temp, payload)
                os.replace(temp, path)
            except OSError as exc:
                raise ExperiencePersistError(
                    f"经验文档状态更新失败(确定未提交，原文件保留): {path.name}: {exc}"
                ) from exc
            finally:
                temp.unlink(missing_ok=True)
            self._fsync_dir_or_uncertain(path, payload, path.name.removesuffix(".md"))
        return True

    # ------------------------------------------------------------------
    # Usage ledger (EVO-20261011-945fc53c 方案A): experience 使用声明真值源
    # ------------------------------------------------------------------

    def record_use(
        self,
        experience_id: str,
        *,
        use_decision: str,
        note: str = "",
        evidence_refs: list[str] | None = None,
        episode_ref: str = "",
        session_id: str = "",
        model: str = "",
    ) -> dict:
        """追加一条模型声明的经验使用记录（observability 账本）.

        与 MethodStore.record_use 同构语义：只落账、不修改卡片、不证明任务收益。
        写入在跨进程 flock 内完成：追加 JSONL 一行 + fsync + 刷新单调水位
        (experiences/.usage_watermark.json)。确定未提交时抛 ExperiencePersistError，
        调用方必须如实失败——不得把使用声明降级为“只回执不落账”（诚实优先）。
        """
        doc = self.get(experience_id)
        if doc is None:
            raise FileNotFoundError(experience_id)
        clean_decision = str(use_decision).strip()
        if clean_decision not in {"applied", "adapted", "not_applicable", "rejected"}:
            raise ValueError(
                "use_decision must be one of applied|adapted|not_applicable|rejected"
            )
        entry = {
            "schema": "experience-use/v1",
            "ts": system_local_now().isoformat(),
            "experience_ref": f"experience:{experience_id.removesuffix('.md')}",
            "id": experience_id.removesuffix(".md"),
            "record_kind": doc.record_kind,
            "verification_state": doc.verification_state,
            "status": doc.status,
            "use_decision": clean_decision,
            "note": str(note).strip()[:2000],
            "evidence_refs": [
                str(v).strip()[:256] for v in (evidence_refs or []) if str(v).strip()
            ],
            "document_projection_sha256": _payload_sha256(doc.to_md()),
            "episode_ref": str(episode_ref).strip()[:256],
            "session_id": str(session_id).strip()[:128],
            "model": str(model).strip()[:256],
            "application_proven": clean_decision in {"applied", "adapted"},
            "authority": "model_declared",
            "task_benefit": "not_evaluated",
        }
        self._append_usage_entry(entry)
        return entry

    def record_migrated_entry(self, entry: dict) -> dict:
        """方案B 一次性迁移专用：回放历史 event_stream 声明.

        幂等键 knowledge_event_key：账本中已存在同键条目时静默跳过（可安全重跑）。
        """
        for key in ("ts", "experience_ref", "use_decision", "knowledge_event_key"):
            if not str(entry.get(key) or "").strip():
                raise ValueError(f"migrated entry missing required field: {key}")
        if entry["use_decision"] not in {
            "applied",
            "adapted",
            "not_applicable",
            "rejected",
        }:
            raise ValueError("migrated entry use_decision invalid")
        entry.setdefault("schema", "experience-use/v1")
        entry.setdefault("note", "")
        entry.setdefault("evidence_refs", [])
        entry.setdefault("migrated_from", "event_stream")
        self._append_usage_entry(entry, dedupe_key="knowledge_event_key")
        return entry

    def usage_ledger_path(self) -> Path:
        return self._dir / "usage.jsonl"

    def _append_usage_entry(self, entry: dict, *, dedupe_key: str = "") -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self.usage_ledger_path()
        with self._file_lock():
            if dedupe_key:
                dedupe_value = str(entry.get(dedupe_key) or "")
                for row in self._iter_usage_entries():
                    if str(row.get(dedupe_key) or "") == dedupe_value:
                        return  # 幂等：该历史声明已回放过
            try:
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise ExperiencePersistError(
                    f"经验使用账本追加失败(确定未提交): {exc}"
                ) from exc
            self._refresh_usage_watermark_locked()

    def _iter_usage_entries(self) -> Iterator[dict]:
        path = self.usage_ledger_path()
        if not path.is_file():
            return
        try:
            with path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(
                            "[经验库] 使用账本存在不可解析行，已跳过（前80字符）: %s",
                            line[:80],
                        )
        except OSError:
            return

    def usage_entries(self, experience_ref: str = "", *, limit: int = 200) -> list[dict]:
        """读取使用声明账本（refine_experience.record_use 的真值源）.

        读取面 fail-open：账本缺失/不可读返回空列表（调用方不得据此推断“无使用”）。
        默认倒序（最新在前），limit 上限 200。
        """
        ref = str(experience_ref or "").strip()
        if ref and not ref.startswith("experience:"):
            ref = f"experience:{ref}"
        rows: list[dict] = []
        for row in self._iter_usage_entries():
            if ref and str(row.get("experience_ref") or "") != ref:
                continue
            rows.append(row)
        rows.reverse()
        return rows[: max(0, min(int(limit), 200))]

    def usage_net(self, experience_ref: str = "") -> dict[str, Any] | None:
        """EVO-20261014-7299aec2: 使用净分派生视图（只读汇总，不改账本、不裁决）。

        锚点为最近 lifecycle transition：账本条目内嵌 status（声明时状态）与当前
        文档 status 尾段一致的条目才计入（口径见 llm_loop/usage_net.py D3）。
        disproven 取当前文档 verification_state（D1 纠偏触发，不改净分权重）。
        文档不可得时不重锚、全量累计并在 anchor 标注；无声明返回 None。
        """
        ref = str(experience_ref or "").strip()
        # 账本条目以 experience:<stem>（无 .md）为真值形式（record_use 归一），此处对齐
        stem = ref.removeprefix("experience:").removesuffix(".md")
        ref = f"experience:{stem}"
        doc = self.get(stem)
        entries = self.usage_entries(ref)  # 倒序=新→旧
        if not entries:
            return None
        current_status = str(getattr(doc, "status", "") or "") if doc is not None else ""
        return summarize_since_last_transition(
            entries,
            decision_key="use_decision",
            status_key="status",
            current_status=current_status,
            disproven=str(getattr(doc, "verification_state", "") or "") == "disproven",
        )

    def usage_stats(self) -> dict[str, dict[str, Any]]:
        """聚合使用账本：每个 experience_ref 的 use_count / last_used_at.

        与 usage_entries 同一真值源（usage.jsonl），fail-open：账本缺失/不可读
        返回空 dict（调用方不得据此推断“无使用”，仅展示为 0 次）。
        last_used_at 取 ts 字典序最大值（ISO-8601 同格式下字典序即时间序）。
        """
        stats: dict[str, dict[str, Any]] = {}
        for row in self._iter_usage_entries():
            ref = str(row.get("experience_ref") or "").strip()
            if not ref:
                continue
            ts = str(row.get("ts") or "")
            entry = stats.setdefault(ref, {"use_count": 0, "last_used_at": ""})
            entry["use_count"] += 1
            if ts > entry["last_used_at"]:
                entry["last_used_at"] = ts
        for entry in stats.values():
            if not entry["last_used_at"]:
                entry["last_used_at"] = None
        return stats

    def _count_usage_lines(self) -> int:
        path = self.usage_ledger_path()
        if not path.is_file():
            return 0
        count = 0
        try:
            with path.open("rb") as handle:
                for raw in handle:
                    if raw.strip():
                        count += 1
        except OSError:
            return 0
        return count

    def _read_usage_watermark(self) -> int:
        wm_path = self._dir / ".usage_watermark.json"
        try:
            return int(
                json.loads(wm_path.read_text(encoding="utf-8")).get("count", 0)
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def _refresh_usage_watermark_locked(self) -> None:
        """单调水位：只增不减，用于检测外部删除（lost>0）而非写入门禁."""
        wm_path = self._dir / ".usage_watermark.json"
        try:
            count = max(self._read_usage_watermark(), self._count_usage_lines())
            payload = json.dumps(
                {"count": count, "ts": system_local_now().isoformat()}, sort_keys=True
            )
            with wm_path.open("w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:  # watermark 是观察指标，不是写入门禁
            logger.warning("usage watermark refresh failed (non-fatal): %s", exc)

    def check_usage_integrity(self) -> dict:
        """账本 vs 水位漂移报告（同 MethodStore.check_ledger_integrity 语义）."""
        wm_path = self._dir / ".usage_watermark.json"
        try:
            watermark = json.loads(wm_path.read_text(encoding="utf-8"))
            watermark_count = int(watermark.get("count", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"monitored": False, "lost": 0}
        current = self._count_usage_lines()
        lost = max(watermark_count - current, 0)
        report: dict = {
            "monitored": True,
            "lost": lost,
            "watermark_count": watermark_count,
            "current_count": current,
            "watermark_ts": str(watermark.get("ts", "")),
        }
        if lost:
            logger.error(
                "[经验库] 使用账本丢失 %d 条 (watermark=%d current=%d)",
                lost,
                watermark_count,
                current,
            )
        return report

    def _safe_path(self, experience_id: str) -> Path | None:
        """构造安全路径（限定 experiences/ 内，防穿越）。"""
        name = experience_id
        if not name.endswith(".md"):
            name += ".md"
        path = (self._dir / name).resolve()
        try:
            path.relative_to(self._dir.resolve())
        except ValueError:
            return None
        return path

    @staticmethod
    def _is_degraded_source(source: dict) -> bool:
        """判定 source 是否为降级形态（单键 raw，_coerce_mapping 产出，design §2.1.3-1）."""
        return set(source.keys()) == {"raw"}

    @staticmethod
    def _to_record(filename: str, doc: ExperienceDocument) -> dict:
        """Build a compact discovery card without claiming current applicability."""
        stem = filename.removesuffix(".md")
        experience_ref = f"experience:{stem}"
        scenario = " ".join(str(doc.scenario or "").split())[:240]
        rec: dict = {
            "kind": doc.record_kind,
            "record_kind": doc.record_kind,
            "verification_state": doc.verification_state,
            "ts": doc.updated_at or doc.created_at,
            "id": stem,
            "summary": doc.title,
            "file": filename,
            "tags": doc.tags,
            "source": doc.source,
            "status": doc.status,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "key": experience_ref,
            "experience_ref": experience_ref,
            "scenario": scenario,
            "superseded_by": doc.superseded_by,
            "promoted_to_rule": doc.promoted_to_rule,
            "last_verified_at": doc.last_verified_at,
            "task_applicability": "not_evaluated",
        }
        if ExperienceStore._is_degraded_source(doc.source):
            rec["degraded_fields"] = ["source"]
        return rec

    @staticmethod
    def to_hydrated_record(experience_id: str, doc: ExperienceDocument) -> dict:
        """Project the exact stored experience for explicit ref hydration.

        This is a mechanical projection only.  It deliberately reports that task
        applicability has not been evaluated so historical evidence cannot become
        current strategy merely because it was retrieved.
        """
        stem = experience_id.removesuffix(".md")
        experience_ref = f"experience:{stem}"
        rec: dict = {
            "kind": doc.record_kind,
            "record_kind": doc.record_kind,
            "verification_state": doc.verification_state,
            "ts": doc.updated_at or doc.created_at,
            "id": stem,
            "summary": doc.title,
            "file": f"{stem}.md",
            "tags": doc.tags,
            "source": doc.source,
            "status": doc.status,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "key": experience_ref,
            "experience_ref": experience_ref,
            "hydrated": True,
            "representation": "full_record",
            "projection_complete": True,
            "scenario": doc.scenario,
            "root_cause": doc.root_cause,
            "solution": doc.solution,
            "evidence": doc.evidence,
            "body": doc.body,
            "superseded_by": doc.superseded_by,
            "promoted_to_rule": doc.promoted_to_rule,
            "last_verified_at": doc.last_verified_at,
            "task_applicability": "not_evaluated",
        }
        if ExperienceStore._is_degraded_source(doc.source):
            rec["degraded_fields"] = ["source"]
        return rec

    @staticmethod
    def _append_degraded(rec: dict, text: str) -> None:
        """degraded 保持 str 类型拼接共存（修正 setdefault 先到先得互斥丢标注缺陷，D12）."""
        existing = rec.get("degraded")
        rec["degraded"] = f"{existing}；{text}" if existing else text


def _normalize_search_text(text: object) -> str:
    """Lowercase + whitespace normalization shared by lexical scoring."""
    return " ".join(str(text or "").lower().split())


def _lexical_terms(query: str) -> dict[str, float]:
    """Extract weighted ASCII words and CJK n-grams from a natural-language query.

    CJK runs longer than four characters are decomposed into 2-4 grams so a natural
    sentence can match stored phrases without requiring the whole sentence verbatim.
    """
    terms: dict[str, float] = {}
    for token in re.findall(r"[a-z0-9]+", query):
        if len(token) < 2:
            continue
        terms[token] = max(terms.get(token, 0.0), 1.0 if len(token) >= 4 else 0.6)
    for run in re.findall(r"[\u3400-\u9fff]+", query):
        if len(run) <= 4:
            terms[run] = max(terms.get(run, 0.0), 1.0)
            continue
        for size, weight in ((2, 0.45), (3, 0.7), (4, 1.0)):
            for start in range(len(run) - size + 1):
                gram = run[start : start + size]
                terms[gram] = max(terms.get(gram, 0.0), weight)
    return terms


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（0.0-1.0；零向量返回 0.0）。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
