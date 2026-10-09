"""P2-A store/assembly 集成：厂商包安装（source_format provenance）与运行时转换装配.

验收（§11 P2-A / §12.2 T24）：
- 厂商包可安装，记录带 source_format；标准包路径行为不变（不影响标准加载）
- 装配层对厂商包执行 §5.1 厂商变量展开（${CLAUDE_PLUGIN_ROOT} → 包根）
- invalid/unsupported 条目不进入装配
"""

import shutil
from pathlib import Path

import pytest

from llm_loop.extensions.store import ExtensionStore, InstallRecord
from llm_loop.extensions.vendor_formats import (
    FORMAT_CLAUDE,
    FORMAT_STANDARD,
    parse_vendor_package,
)
from llm_loop.tools.mcp_assembly import LAYER_USER, _installed_servers

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture()
def store(tmp_path):
    return ExtensionStore(tmp_path / "extensions")


def _install_claude(store: ExtensionStore, tmp_path: Path):
    src = tmp_path / "vendor_src"
    shutil.copytree(FIXTURES / "vendor_claude_demo", src)
    return src, store.install(src, source="local", expected_revision=0)


class TestStoreVendorInstall:
    def test_vendor_install_records_source_format(self, store, tmp_path):
        _, rec = _install_claude(store, tmp_path)
        assert rec.source_format == FORMAT_CLAUDE
        kinds = {(c.kind, c.name) for c in rec.components}
        assert ("skill", "lint") in kinds
        assert ("mcp_server", "local-srv") in kinds
        assert ("mcp_server", "web-srv") in kinds

    def test_vendor_pkg_copy_immutable_source(self, store, tmp_path):
        src, rec = _install_claude(store, tmp_path)
        pkg_root = store.package_root(rec.digest)
        assert (pkg_root / ".claude-plugin" / "plugin.json").exists()
        # 修改源不影影响已安装副本
        (src / ".claude-plugin" / "plugin.json").write_text("{}")
        conv = parse_vendor_package(pkg_root)
        assert conv.report.plugin_name == "claude-demo"

    def test_standard_install_keeps_default_format(self, store, tmp_path):
        src = tmp_path / "std"
        shutil.copytree(FIXTURES / "std_plugin_demo", src)
        rec = store.install(src, source="local", expected_revision=0)
        assert rec.source_format == FORMAT_STANDARD
        comp = {(c.kind, c.name) for c in rec.components}
        assert ("skill", "deploy") in comp  # 标准路径行为不变

    def test_old_records_without_source_format_load_default(self):
        # 旧 installed.json（P2-A 之前）无 source_format 键 → 默认标准格式
        rec = InstallRecord.from_dict({
            "install_id": "old", "plugin_name": "old", "version": "1.0",
            "source": "local", "digest": "d" * 16, "revision": 1,
        })
        assert rec.source_format == FORMAT_STANDARD


class TestAssemblyVendorConversion:
    def test_vendor_servers_converted_at_assembly(self, store, tmp_path):
        _, rec = _install_claude(store, tmp_path)
        # supported 条目默认装配；needs_configuration 条目需用户显式启用（P1-A 语义）
        layers = _installed_servers(store)
        by_name = {layer.name: layer for layer in layers}
        assert set(by_name) == {"web-srv"}
        assert by_name["web-srv"].entry["type"] == "http"
        assert by_name["web-srv"].layer == LAYER_USER
        # invalid 条目不进入装配
        assert "broken" not in by_name

        state = store.read_state()
        store.set_enabled(
            rec.install_id, component="local-srv", enabled=True, expected_revision=state.revision
        )
        layers = _installed_servers(store)
        by_name = {layer.name: layer for layer in layers}
        pkg_root = store.package_root(rec.digest)
        # ${CLAUDE_PLUGIN_ROOT} 在厂商 adapter 内展开为已安装包根（§5.1）
        assert by_name["local-srv"].entry["command"] == str(pkg_root / "bin" / "srv")
        assert by_name["local-srv"].entry["args"] == ["--config", "${APP_CONFIG}"]
        # ${CLAUDE_PLUGIN_DATA} → ${PLUGIN_DATA}（厂商重命名）→ 装配层展开为实例 data 目录
        layer = by_name["local-srv"]
        assert layer.entry["env"]["DATA_DIR"] == str(store.instance_data_dir(rec.install_id))

    def test_gemini_httpurl_assembled_as_http(self, store, tmp_path):
        src = tmp_path / "gemini_src"
        shutil.copytree(FIXTURES / "vendor_gemini_demo", src)
        store.install(src, source="local", expected_revision=0)
        layers = _installed_servers(store)
        by_name = {layer.name: layer for layer in layers}
        assert by_name["http-srv"].entry["type"] == "http"
        assert by_name["http-srv"].entry["url"] == "https://example.com/mcp"
        # trust/cwd/excludeTools 等未映射字段不进入装配条目（不偷换原义）
        assert "trust" not in by_name["toolbox"].entry
        assert "cwd" not in by_name["toolbox"].entry
