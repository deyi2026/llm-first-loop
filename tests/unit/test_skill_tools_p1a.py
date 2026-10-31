"""P1-A 装配闭环单测（DESIGN-20261009 §11 退出条件: 包生效与使用回执可查）.

install（代码 API）→ skill_list 可见（package-qualified + 来源标注）
→ skill_load 读取原文（provenance 回执 + 分页）。
"""

from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.message import ToolResultStatus
from llm_loop.extensions.catalog import ExtensionCatalog
from llm_loop.extensions.store import ExtensionStore
from llm_loop.introspection.tools_skill_files import run_skill_list, run_skill_load
from llm_loop.runtime.paths import resolve_runtime_paths

FIXTURE = Path(__file__).parent.parent / "fixtures" / "std_plugin_demo"
REPO_ROOT = Path(__file__).parents[2]


def _host(tmp_path, with_catalog=True, skills_dir=None):
    store = ExtensionStore(tmp_path / "ext")
    store.install(FIXTURE, source="fixture", expected_revision=0)
    return SimpleNamespace(
        skills_dir=skills_dir,
        extensions_catalog=ExtensionCatalog(store) if with_catalog else None,
    )


class TestClosedLoop:
    def test_install_to_skill_list_to_skill_load(self, tmp_path):
        host = _host(tmp_path)
        listing = run_skill_list(host, {})
        assert listing.status == ToolResultStatus.SUCCESS
        assert "demo-plugin/deploy" in listing.content
        assert "install=demo-plugin" in listing.content  # 使用回执可查（§8.3）
        assert "rev=1" in listing.content

        loaded = run_skill_load(host, {"name": "demo-plugin/deploy"})
        assert loaded.status == ToolResultStatus.SUCCESS
        assert loaded.content.startswith("[技能 demo-plugin/deploy]")
        assert "install=demo-plugin" in loaded.content
        assert "不扩大授权" in loaded.content  # §8.3 污点语义进入模型视图
        assert "allowed-tools" in loaded.content  # 原文（含 frontmatter）
        assert "已到末尾" in loaded.content

    def test_skill_load_unknown_package_ref_fails(self, tmp_path):
        host = _host(tmp_path)
        r = run_skill_load(host, {"name": "ghost/nope"})
        assert r.status == ToolResultStatus.FAILURE
        assert "未找到标准包技能" in r.content

    def test_skill_load_pagination_arg(self, tmp_path):
        host = _host(tmp_path)
        r = run_skill_load(host, {"name": "demo-plugin/deploy", "offset": 4})
        assert r.status == ToolResultStatus.SUCCESS
        assert f"offset={4}" in r.content
        assert "omitted=0" in r.content
        assert "已到末尾" in r.content  # fixture 全文 <64KB → 单页到末尾

    def test_legacy_local_skill_still_works_with_catalog(self, tmp_path):
        skills = tmp_path / "skills" / "local1"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text(
            "---\nname: local1\ndescription: 本地\n---\n本地正文"
        )
        host = _host(tmp_path, skills_dir=str(tmp_path / "skills"))
        listing = run_skill_list(host, {})
        assert "local1" in listing.content
        assert "demo-plugin/deploy" in listing.content  # 两段并存
        loaded = run_skill_load(host, {"name": "local1"})
        assert loaded.status == ToolResultStatus.SUCCESS
        assert "本地正文" in loaded.content

    def test_host_without_catalog_zero_regression(self, tmp_path):
        skills = tmp_path / "skills" / "only"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text(
            "---\nname: only\ndescription: d\n---\nb"
        )
        host = SimpleNamespace(skills_dir=str(tmp_path / "skills"),
                               extensions_catalog=None)
        listing = run_skill_list(host, {})
        assert "only" in listing.content
        assert "标准包" not in listing.content
        loaded = run_skill_load(host, {"name": "only"})
        assert loaded.status == ToolResultStatus.SUCCESS


class TestRuntimePathsExtensionsDir:
    def test_extensions_dir_derived_from_data_dir(self, tmp_path):
        rp = resolve_runtime_paths(
            data_dir=tmp_path, code_root=REPO_ROOT, data_dir_explicit=True
        )
        assert rp.extensions_dir == tmp_path.resolve() / "extensions"

    def test_extensions_dir_creates_layout_on_store_init(self, tmp_path):
        rp = resolve_runtime_paths(
            data_dir=tmp_path, code_root=REPO_ROOT, data_dir_explicit=True
        )
        store = ExtensionStore(rp.extensions_dir)
        assert (store.root / "packages").is_dir()
        assert (store.root / "instances").is_dir()
        assert (store.root / "locks").is_dir()


class TestManifestGateCoversDiscovery:
    """EVO-20261031-6b21e0f4: 门禁必须覆盖发现侧，不只是加载侧.

    门禁此前只在 skill_load 生效，skill_list 仍把注定被拒的技能列出来，
    模型据此去 load 再吃一次拒绝——「开门禁」只做一半等于没开。
    """

    @staticmethod
    def _skills(tmp_path):
        d = tmp_path / "skills" / "alpha"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: alpha\ndescription: A\n---\n正文\n", encoding="utf-8"
        )
        return tmp_path / "skills"

    @staticmethod
    def _host(skills):
        return SimpleNamespace(skills_dir=str(skills), extensions_catalog=None)

    def test_gated_list_hides_unverified_skill(self, tmp_path, monkeypatch):
        from llm_loop.skills.loader import build_manifest, write_manifest

        skills = self._skills(tmp_path)
        write_manifest(skills, build_manifest(skills))
        # 改动 SKILL.md 之外的辅助文件 → 目录树基线失配 → modified
        (skills / "alpha" / "extra.md").write_text("x\n", encoding="utf-8")
        monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
        listing = run_skill_list(self._host(skills), {})
        assert listing.status == ToolResultStatus.SUCCESS
        # 被隐藏技能的**名字**本就应出现在披露段里，所以断言的是
        # 「可用条目」形态（"- alpha:"）不出现，而不是名字完全不出现。
        assert "- alpha:" not in listing.content
        assert "已隐藏 1 个" in listing.content
        assert "alpha(modified)" in listing.content

    def test_ungated_list_keeps_skill_visible(self, tmp_path, monkeypatch):
        from llm_loop.skills.loader import build_manifest, write_manifest

        skills = self._skills(tmp_path)
        write_manifest(skills, build_manifest(skills))
        (skills / "alpha" / "extra.md").write_text("x\n", encoding="utf-8")
        monkeypatch.delenv("LFL_SKILLS_REQUIRE_MANIFEST", raising=False)
        listing = run_skill_list(self._host(skills), {})
        assert "- alpha:" in listing.content

    def test_gated_list_shows_verified_skill(self, tmp_path, monkeypatch):
        from llm_loop.skills.loader import build_manifest, write_manifest

        skills = self._skills(tmp_path)
        write_manifest(skills, build_manifest(skills))
        monkeypatch.setenv("LFL_SKILLS_REQUIRE_MANIFEST", "1")
        listing = run_skill_list(self._host(skills), {})
        assert "alpha" in listing.content
        assert "已隐藏" not in listing.content
