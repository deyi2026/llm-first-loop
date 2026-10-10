"""extensions/catalog 单测（DESIGN-20261009 P1-A: §8.3 来源标注 / §10.2 预算投影）."""

from pathlib import Path

import pytest

from llm_loop.extensions.catalog import (
    CATALOG_BUDGET_BYTES,
    SKILL_PAGE_MAX,
    ExtensionCatalog,
)
from llm_loop.extensions.store import ExtensionStore

FIXTURE = Path(__file__).parent.parent / "fixtures" / "std_plugin_demo"


@pytest.fixture()
def installed(tmp_path):
    store = ExtensionStore(tmp_path / "ext")
    store.install(FIXTURE, source="fixture", expected_revision=0)
    return store, ExtensionCatalog(store)


class TestListing:
    def test_skills_with_provenance(self, installed):
        store, cat = installed
        skills = cat.skills()
        refs = [s.ref for s in skills]
        assert refs == ["demo-plugin/deploy", "demo-plugin/report"]
        for s in skills:
            assert s.install_id == "demo-plugin"  # 来源标注（§8.3）
            assert s.catalog_revision == 1
            assert s.skill_path.startswith(
                str(store.package_root(store.read_state().installs[0].digest))
            )  # 事实源=不可变包副本

    def test_servers_listed_for_p1c(self, installed):
        _, cat = installed
        servers = cat.servers()
        assert [(s.name, s.status) for s in servers] == [("echo", "supported")]

    def test_disabled_component_excluded(self, installed):
        store, cat = installed
        store.set_enabled("demo-plugin", enabled=False, component="deploy",
                          expected_revision=1)
        refs = [s.ref for s in cat.skills()]
        assert refs == ["demo-plugin/report"]

    def test_scope_filter(self, installed):
        store, cat = installed
        store.set_enabled("demo-plugin", enabled=True, expected_revision=1)
        # scopes=["user"]；workspace scope 无安装 → 空
        assert cat.skills(scope="workspace") == []


class TestT26Budget:
    def test_summary_within_budget(self, installed):
        _, cat = installed
        text = cat.summary()
        assert text
        assert len(text.encode("utf-8")) <= CATALOG_BUDGET_BYTES
        assert "demo-plugin/deploy" in text
        assert "install=demo-plugin" in text  # 来源进入模型视图（§8.3）

    def test_summary_truncates_with_omitted_count(self, tmp_path):
        store = ExtensionStore(tmp_path / "ext")
        # 造一个多技能包（长 description）撑爆 8KB
        root = tmp_path / "pkg"
        root.mkdir()
        (root / "plugin.json").write_text('{"name":"big","version":"1"}')
        for i in range(40):
            d = root / "skills" / f"s{i}"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                f"---\nname: s{i}\ndescription: {'x' * 500}\n---\nbody\n"
            )
        store.install(root, source="t", expected_revision=0)
        cat = ExtensionCatalog(store)
        text = cat.summary()
        assert len(text.encode("utf-8")) <= CATALOG_BUDGET_BYTES
        assert "目录预算截断" in text

    def test_empty_summary_when_no_skills(self, tmp_path):
        cat = ExtensionCatalog(ExtensionStore(tmp_path / "ext"))
        assert cat.summary() == ""


class TestT27Hydration:
    def test_skill_page_full_text_with_frontmatter(self, installed):
        _, cat = installed
        page = cat.skill_page("demo-plugin/deploy")
        assert page is not None
        assert page.content.startswith("---")  # 原文视图（含 frontmatter）
        assert "allowed-tools" in page.content
        assert page.next_offset is None
        assert page.omitted_chars == 0
        assert page.install_id == "demo-plugin"

    def test_skill_page_pagination(self, installed):
        _, cat = installed
        p1 = cat.skill_page("demo-plugin/deploy", offset=0, limit=64)
        assert len(p1.content) == 64
        assert p1.next_offset == 64
        assert p1.omitted_chars == p1.total_chars - 64
        p2 = cat.skill_page("demo-plugin/deploy", offset=64, limit=64)
        assert p2.content  # 续页内容非空且不重叠

    def test_page_limit_capped_at_64kb(self, installed):
        _, cat = installed
        page = cat.skill_page("demo-plugin/deploy", limit=10 * 1024 * 1024)
        assert len(page.content.encode("utf-8")) <= SKILL_PAGE_MAX

    def test_unknown_ref_returns_none(self, installed):
        _, cat = installed
        assert cat.skill_page("ghost/nope") is None
        assert cat.find_skill("ghost/nope") is None
