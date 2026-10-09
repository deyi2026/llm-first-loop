"""扩展目录与预算投影（DESIGN-20261009 §5.4/§8.3/§10.2，P1-A）.

- 按 scope 提供已安装包的技能/服务器目录（数据层，供 skill_list 等消费）
- 外部内容标注来源（install_id + catalog_revision，§8.3 内容污点）：
  description 等解析视图进入模型上下文时携带来源，不得据此扩大授权
- 预算投影（§10.2 硬数字）: 目录注入 ≤8KB；单包组件 ≤200（formats 截断）；
  description ≤2KB；SKILL.md 全文按页水合 ≤64KB，先完整落盘（store 包副本）
  后投影，裁剪处带 omitted count 与续读 ref
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llm_loop.extensions.formats import STATUS_SUPPORTED
from llm_loop.extensions.store import ExtensionStore
from llm_loop.skills.loader import SkillMeta, scan_skills_dir

CATALOG_BUDGET_BYTES = 8 * 1024  # 目录注入预算
DESCRIPTION_MAX = 2048  # §10.2 description ≤2KB
SKILL_PAGE_MAX = 64 * 1024  # §10.2 单页水合 ≤64KB


@dataclass(frozen=True)
class CatalogSkill:
    """目录中的技能条目（package-qualified ref + 来源标注）."""

    ref: str  # "pkg/name"
    name: str
    package: str
    description: str  # 已截断 ≤2KB
    install_id: str
    catalog_revision: int
    skill_path: str  # 包副本内 SKILL.md 绝对路径（来源可追溯）


@dataclass(frozen=True)
class CatalogServer:
    """目录中的 MCP 服务器条目（P1-A 仅登记；P1-C 才接线执行）."""

    name: str
    package: str
    transport: str
    status: str
    install_id: str
    catalog_revision: int


@dataclass(frozen=True)
class SkillPage:
    """skill_load 原文分页视图（先落盘后投影，裁剪如实标注）."""

    ref: str
    offset: int
    content: str
    total_chars: int
    omitted_chars: int
    next_offset: int | None  # None=已到末尾
    install_id: str
    catalog_revision: int


class ExtensionCatalog:
    """基于 ExtensionStore 的目录读取层（只读，不做任何安装/写操作）."""

    def __init__(self, store: ExtensionStore) -> None:
        self.store = store

    def _enabled_component_names(self, rec, kind: str) -> set[str]:
        return {
            c.name
            for c in rec.components
            if c.kind == kind and c.enabled and c.status == STATUS_SUPPORTED
        }

    def _package_skills(self, rec) -> list[SkillMeta]:
        """扫描包副本 skills/（不可变副本为事实源，package=插件名）."""
        skills_root = self.store.package_root(rec.digest) / "skills"
        if not skills_root.is_dir():
            return []
        return scan_skills_dir(skills_root, package=rec.plugin_name)

    def skills(self, scope: str = "user") -> list[CatalogSkill]:
        state = self.store.read_state()
        out: list[CatalogSkill] = []
        for rec in state.installs:
            if scope not in rec.scopes:
                continue
            enabled = self._enabled_component_names(rec, "skill")
            for meta in self._package_skills(rec):
                if meta.name not in enabled:
                    continue
                out.append(
                    CatalogSkill(
                        ref=f"{rec.plugin_name}/{meta.name}",
                        name=meta.name,
                        package=rec.plugin_name,
                        description=meta.description[:DESCRIPTION_MAX],
                        install_id=rec.install_id,
                        catalog_revision=state.revision,
                        skill_path=meta.path,
                    )
                )
        return sorted(out, key=lambda s: s.ref)

    def servers(self, scope: str = "user") -> list[CatalogServer]:
        """MCP 服务器目录（P1-A 登记；执行接线属 P1-C）."""
        state = self.store.read_state()
        out: list[CatalogServer] = []
        for rec in state.installs:
            if scope not in rec.scopes:
                continue
            for c in rec.components:
                if c.kind != "mcp_server":
                    continue
                out.append(
                    CatalogServer(
                        name=c.name,
                        package=rec.plugin_name,
                        transport="",
                        status=c.status,
                        install_id=rec.install_id,
                        catalog_revision=state.revision,
                    )
                )
        return sorted(out, key=lambda s: (s.package, s.name))

    def summary(self, budget: int = CATALOG_BUDGET_BYTES) -> str:
        """目录注入视图（≤budget 字节；超限截断并如实标注 omitted 条数）."""
        skills = self.skills()
        if not skills:
            return ""
        lines: list[str] = ["[已安装扩展技能]"]
        omitted = 0
        used = len(lines[0].encode("utf-8")) + 1
        for s in skills:
            provenance = f"install={s.install_id} rev={s.catalog_revision}"
            line = f"- {s.ref}: {s.description}（{provenance}）"
            size = len(line.encode("utf-8")) + 1
            if used + size > budget:
                omitted = len(skills) - (len(lines) - 1)
                break
            lines.append(line)
            used += size
        if omitted:
            lines.append(f"[目录预算截断] 另有 {omitted} 个技能未列出（§10.2）")
        return "\n".join(lines)

    def find_skill(self, ref: str) -> CatalogSkill | None:
        for s in self.skills():
            if s.ref == ref:
                return s
        return None

    def skill_page(
        self,
        ref: str,
        *,
        offset: int = 0,
        limit: int = SKILL_PAGE_MAX,
    ) -> SkillPage | None:
        """按 ref 水合技能原文（分页 ≤limit；先落盘后投影，§10.2）."""
        entry = self.find_skill(ref)
        if entry is None:
            return None
        text = Path(entry.skill_path).read_text(encoding="utf-8")
        limit = min(limit, SKILL_PAGE_MAX)
        chunk = text[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(text) else None
        return SkillPage(
            ref=ref,
            offset=offset,
            content=chunk,
            total_chars=len(text),
            omitted_chars=max(0, len(text) - (offset + len(chunk))),
            next_offset=next_offset,
            install_id=entry.install_id,
            catalog_revision=entry.catalog_revision,
        )
