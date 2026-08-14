"""经验库存储组件 ExperienceStore（design §2.3.2.4/§2.4.2）.

写入（文件名 sanitize + 路径安全 + 冲突检测）、检索（扫描目录 + front matter 解析 +
关键词匹配 + 默认仅 active）、状态流转（更新 status 不删除文档）。
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.experiences.document import ExperienceDocument, ExperienceParseError


class ExperienceStore:
    """经验库存储组件（操作 experiences/ 目录）。"""

    def __init__(self, experiences_dir: str | Path, *, embedder: Any | None = None) -> None:
        self._dir = Path(experiences_dir)
        self._embedder = embedder  # T5: 可选 embedder 注入（None 时走关键词匹配，零回归）

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

    def list_active(self, query: str = "", limit: int = 20) -> list[dict]:
        """扫描 experiences/*.md，过滤 active，按相关性排序截断到 limit.

        T5: embedder 注入且 embed(query) 成功时走语义检索（cosine 相似度降序）；
        否则回退关键词匹配（fail-open，零回归）。结果附 score 字段。
        """
        if not self._dir.exists():
            return []
        # 收集 active 文档
        active: list[tuple[str, ExperienceDocument]] = []
        for path in sorted(self._dir.glob("EXPERIENCE-*.md")):
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except (ExperienceParseError, OSError):
                continue
            if doc.status != "active":
                continue
            active.append((path.name, doc))

        # T5: 尝试语义检索路径
        if query and self._embedder is not None:
            try:
                query_vec = self._embedder.embed(query)
            except Exception:
                query_vec = None
            if query_vec is not None:
                return self._semantic_search(active, query_vec, limit, degraded=False)
            # embed 失败 → 回退关键词匹配（fail-open）
            return self._keyword_search(active, query, limit, degraded=True)

        # 无 query 或无 embedder → 关键词匹配
        return self._keyword_search(active, query, limit, degraded=False)

    def _semantic_search(
        self, active: list[tuple[str, ExperienceDocument]], query_vec: list[float], limit: int, *, degraded: bool
    ) -> list[dict]:
        """语义检索：对每条 active 计算 cosine 相似度，降序排列。"""
        if self._embedder is None:
            return []
        scored: list[tuple[float, str, ExperienceDocument]] = []
        for filename, doc in active:
            doc_text = " ".join([doc.title, doc.scenario, doc.root_cause, doc.solution])
            try:
                doc_vec = self._embedder.embed(doc_text)
            except Exception:
                doc_vec = None
            if doc_vec is None:
                continue
            score = _cosine_similarity(query_vec, doc_vec)
            scored.append((score, filename, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, filename, doc in scored[:limit]:
            rec = self._to_record(filename, doc)
            rec["score"] = round(score, 4)
            results.append(rec)
        return results

    def _keyword_search(
        self, active: list[tuple[str, ExperienceDocument]], query: str, limit: int, *, degraded: bool
    ) -> list[dict]:
        """关键词匹配检索（fail-open 回退时附降级标注）。"""
        results = []
        for filename, doc in active:
            if query and not self._match(doc, query):
                continue
            rec = self._to_record(filename, doc)
            rec["score"] = None
            if degraded:
                rec["degraded"] = "[语义检索降级] embed 失败，回退关键词匹配"
            results.append(rec)
        return results[:limit]

    def get(self, experience_id: str) -> ExperienceDocument | None:
        """按文件名/标识读取并解析；不存在/损坏返回 None。"""
        path = self._safe_path(experience_id)
        if path is None or not path.exists():
            return None
        try:
            return ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        except ExperienceParseError:
            return None

    def update_status(self, experience_id: str, status: str) -> bool:
        """更新 status 字段 + 刷新 updated_at，不删除文档；不存在返回 False。"""
        path = self._safe_path(experience_id)
        if path is None or not path.exists():
            return False
        try:
            doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
        except ExperienceParseError:
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
    def _match(doc: ExperienceDocument, query: str) -> bool:
        """关键词匹配 title/scenario/root_cause/solution/tags。"""
        q = query.lower()
        fields_text = " ".join(
            [doc.title, doc.scenario, doc.root_cause, doc.solution, " ".join(doc.tags)]
        ).lower()
        return q in fields_text

    @staticmethod
    def _to_record(filename: str, doc: ExperienceDocument) -> dict:
        """构造检索结果记录。"""
        return {
            "kind": "experience",
            "ts": doc.updated_at or doc.created_at,
            "id": filename.removesuffix(".md"),
            "summary": doc.title,
            "file": filename,
            "tags": doc.tags,
            "source": doc.source,
            "status": doc.status,
        }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（0.0-1.0；零向量返回 0.0）。"""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
