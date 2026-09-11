"""经验库存储组件 ExperienceStore（design §2.3.2.4/§2.4.2）.

写入（文件名 sanitize + 路径安全 + 冲突检测）、检索（扫描目录 + front matter 解析 +
关键词匹配 + 默认仅 active）、状态流转（更新 status 不删除文档）。
R2（tasks §2）：三态扫描——正常/可降级文档正常参与检索，不可解析文档跳过并脱敏
留痕（best-effort）；目录级扫描失败独立防护为 scan_error 诊断态（不崩库）；
ExperienceSearchOutcome 承载结果 + 诊断四要素；last_experience_diagnostics 属性透传。
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.experiences.document import ExperienceDocument

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


class ExperienceStore:
    """经验库存储组件（操作 experiences/ 目录）。"""

    def __init__(self, experiences_dir: str | Path, *, embedder: Any | None = None) -> None:
        self._dir = Path(experiences_dir)
        self._embedder = embedder  # T5: 可选 embedder 注入（None 时走关键词匹配，零回归）
        # 文档向量只缓存机械可验证的输入→输出；query 向量每次现算。
        # filename 作为槽位可让同一经验内容变化时原位替换，避免陈旧 hash 无限累积。
        self._doc_embedding_cache: dict[str, tuple[str, list[float]]] = {}
        self._last_diagnostics: dict[str, Any] = {
            "scanned": 0,
            "degraded": 0,
            "skipped": 0,
            "scan_error": None,
        }

    @property
    def last_experience_diagnostics(self) -> dict:
        """最近一次扫描的诊断四要素摘要（实验性：单线程假设，并发场景需改参数传递）.

        每次公开方法（list_active / search_outcome / get / update_status）入口显式
        重置，search_outcome 完成时回填；值为 {scanned, degraded, skipped, scan_error}。
        """
        return self._last_diagnostics

    def _reset_diagnostics(self) -> None:
        """公开方法入口显式重置诊断（并发防护，见 last_experience_diagnostics docstring）."""
        self._last_diagnostics = {"scanned": 0, "degraded": 0, "skipped": 0, "scan_error": None}

    @staticmethod
    def sanitize_slug(slug: str) -> str:
        """转 kebab-case：小写 + 非字母数字转连字符 + 去首尾连字符 + 截断 50 字符。"""
        s = re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()
        return s[:50].rstrip("-")

    def save(self, doc: ExperienceDocument) -> str:
        """写入经验文档；返回文件名。冲突时抛 FileExistsError（不覆盖）。"""
        self._dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        slug = self.sanitize_slug(doc.title)
        if not slug:
            slug = "untitled"
        filename = f"EXPERIENCE-{date_str}-{slug}.md"
        path = self._dir / filename
        if path.exists():
            raise FileExistsError(f"经验文档已存在: {filename}（同日同 slug 冲突，不覆盖）")
        path.write_text(doc.to_md(), encoding="utf-8")
        return filename

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

        写入段零变化：降级形态 source 经 to_md round-trip 保留原形态（design §2.1.3-3）。
        """
        self._reset_diagnostics()
        path = self._safe_path(experience_id)
        if path is None or not path.exists():
            return False
        try:
            doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 — 防御纵深（design §2.1.3-4.1），写入段零变化
            _skip_trace(path.name, exc)
            return False
        doc.status = status
        doc.updated_at = datetime.now().astimezone().isoformat()
        path.write_text(doc.to_md(), encoding="utf-8")
        return True

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
