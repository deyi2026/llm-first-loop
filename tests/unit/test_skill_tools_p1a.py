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
