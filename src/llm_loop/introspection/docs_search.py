"""docs/ 文档语义检索实现层（design §2.1/§2.2 / spec §5）.

DocsSearcher：扫描 docs/*.md → 提取元数据 → 关键词/语义匹配 → 返回结构化条目。
本模块为检索实现层（无 LLM 可见性），被 tools_docs.py 消费。
程序仅提供检索通道；检索决策归 AI 自主（RULE-AI-00）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_SUMMARY_MAX_CHARS = 300
_DISPLAY_LIMIT = 6

_DOC_TYPE_PREFIXES: list[tuple[str, str]] = [
    ("ASSESSMENT-", "assessment"),
    ("ANALYSIS-", "analysis"),
    ("DESIGN-", "design"),
    ("SPEC-", "spec"),
    ("TASKS-", "tasks"),
    ("REFLECTION-", "reflection"),
    ("REPORT-", "report"),
    ("ISSUE-", "issue"),
    ("CHANGES", "changes"),
    ("INDEX", "index"),
    ("ai_rules", "rules"),
    ("ai_guidance_playbook", "playbook"),
]

_DOC_TYPE_ENUM = [
    "assessment",
    "analysis",
    "design",
    "spec",
    "tasks",
    "reflection",
    "report",
    "issue",
    "changes",
    "index",
    "rules",
    "playbook",
    "milestone",
    "other",
]


@dataclass
class DocMeta:
    """文档元数据（内部使用）."""

    path: Path
    title: str
    summary: str
    doc_type: str
    ts: str
    content: str


def _classify_doc_type(path: Path) -> str:
    """按文件名前缀返回 doc_type."""
    name = path.name
    for prefix, doc_type in _DOC_TYPE_PREFIXES:
        if name.startswith(prefix):
            return doc_type
    if re.match(r"^m\d+[_]", name):
        return "milestone"
    return "other"


def _extract_doc_meta(path: Path) -> DocMeta | None:
    """读 Markdown 文件提取元数据（损坏返回 None，fail-open）."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    lines = content.splitlines()
    title = path.stem
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            break
        if stripped and not stripped.startswith("#"):
            break

    summary_lines: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith(">"):
            summary_lines.append(stripped)
            if len(" ".join(summary_lines)) >= _SUMMARY_MAX_CHARS:
                break
    summary = " ".join(summary_lines)[:_SUMMARY_MAX_CHARS]

    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        ts = ""

    return DocMeta(
        path=path,
        title=title,
        summary=summary,
        doc_type=_classify_doc_type(path),
        ts=ts,
        content=content,
    )


def _keyword_match(query: str, meta: DocMeta) -> bool:
    """关键词全文匹配（空 query 不过滤）."""
    if not query:
        return True
    hay = f"{meta.title} {meta.summary} {meta.content}".lower()
    return query.lower() in hay


class DocsSearcher:
    """docs/ 文档语义检索器.

    扫描 docs/*.md → 提取元数据 → 关键词/语义匹配 → 返回结构化条目。
    docs/ 不存在时返回空列表（如实，不伪造）。
    """

    def __init__(
        self,
        *,
        docs_dir: str | Path,
        semantic_retriever: Any | None = None,
    ) -> None:
        self._docs_dir = Path(docs_dir)
        self._semantic = semantic_retriever

    def search(
        self,
        query: str,
        *,
        doc_type: str = "",
        limit: int = 10,
    ) -> list[dict]:
        """检索 docs/ 文档，返回结构化条目列表."""
        if not self._docs_dir.exists():
            return []

        candidates: list[DocMeta] = []
        for p in sorted(self._docs_dir.glob("*.md")):
            meta = _extract_doc_meta(p)
            if meta is None:
                continue
            if doc_type and meta.doc_type != doc_type:
                continue
            if not _keyword_match(query, meta):
                continue
            candidates.append(meta)

        if not candidates:
            return []

        results = self._semantic_recall(query, candidates) if self._should_use_semantic() else None
        if results is None:
            results = [
                {
                    "kind": "docs",
                    "file": str(m.path),
                    "title": m.title,
                    "summary": m.summary[:_SUMMARY_MAX_CHARS],
                    "relevance": 1.0,
                    "doc_type": m.doc_type,
                    "ts": m.ts,
                }
                for m in candidates
            ]

        results.sort(key=lambda r: r.get("relevance", 0.0), reverse=True)
        return results[:limit]

    def recent_docs(self, limit: int = 5) -> list[dict]:
        """A4: 返回最近 N 篇 docs/ 文档标题引导（按 ts 降序）.

        实时 glob 扫描 `docs/*.md`，按 mtime 降序返回最近 `limit` 篇
        `{file, title, summary, doc_type, ts}`（与 `search` 返回格式兼容）。
        docs/ 不存在或为空 → 空列表（如实）；glob/元数据提取异常 → 空列表（fail-open）。
        """
        limit = max(1, int(limit))
        metas: list[DocMeta] = []
        try:
            if not self._docs_dir.exists():
                return []
            for p in sorted(self._docs_dir.glob("*.md")):
                meta = _extract_doc_meta(p)
                if meta is None:
                    continue
                metas.append(meta)
        except Exception:  # noqa: BLE001 — 扫描异常 fail-open 返回空列表
            return []
        metas.sort(key=lambda m: m.ts, reverse=True)
        return [
            {
                "kind": "docs",
                "file": str(m.path),
                "title": m.title,
                "summary": m.summary[:_SUMMARY_MAX_CHARS],
                "relevance": 0.0,
                "doc_type": m.doc_type,
                "ts": m.ts,
            }
            for m in metas[:limit]
        ]

    def _should_use_semantic(self) -> bool:
        if self._semantic is None:
            return False
        try:
            return self._semantic.semantic_available()
        except Exception:  # noqa: BLE001
            return False

    def _semantic_recall(self, query: str, candidates: list[DocMeta]) -> list[dict] | None:
        """语义召回（异常降级关键词 + 如实标注）."""
        if self._semantic is None:
            return None
        try:
            docs_text = [f"{m.title} {m.summary}" for m in candidates]
            scores = self._semantic.search(query, candidates=docs_text, top_k=len(candidates))
            return [
                {
                    "kind": "docs",
                    "file": str(candidates[i].path),
                    "title": candidates[i].title,
                    "summary": candidates[i].summary[:_SUMMARY_MAX_CHARS],
                    "relevance": float(score),
                    "doc_type": candidates[i].doc_type,
                    "ts": candidates[i].ts,
                    "note": "mode=semantic",
                }
                for i, score in scores
            ]
        except Exception:  # noqa: BLE001 — 语义异常降级关键词
            return None
