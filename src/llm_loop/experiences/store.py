"""经验库存储组件 ExperienceStore（design §2.3.2.4/§2.4.2）.

写入（文件名 sanitize + 路径安全 + 冲突检测）、检索（扫描目录 + front matter 解析 +
关键词匹配 + 默认仅 active）、状态流转（更新 status 不删除文档）。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from llm_loop.experiences.document import ExperienceDocument, ExperienceParseError


class ExperienceStore:
    """经验库存储组件（操作 experiences/ 目录）。"""

    def __init__(self, experiences_dir: str | Path) -> None:
        self._dir = Path(experiences_dir)

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
        """扫描 experiences/*.md，过滤 active，关键词匹配，按 ts 排序截断到 limit。"""
        if not self._dir.exists():
            return []
        results: list[dict] = []
        for path in sorted(self._dir.glob("EXPERIENCE-*.md")):
            try:
                doc = ExperienceDocument.from_md(path.read_text(encoding="utf-8"))
            except (ExperienceParseError, OSError):
                continue  # 文件损坏跳过（fail-open，如实标注部分不可读）
            if doc.status != "active":
                continue
            if query and not self._match(doc, query):
                continue
            results.append(self._to_record(path.name, doc))
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
