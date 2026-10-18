"""P1-C：MCP 装配合并优先级 + 精确身份冲突报告 + 装配 epoch（设计 §4.2/§7）.

- 优先级：installed@workspace > installed@user > legacy:MCP_SERVERS
- 同一精确身份多层出现 → 单实例生效 + 冲突报告（不静默叠加）；
  同名不同端点 → 同样取最高优先层并报告（name-conflict）
- effective 字段 provenance：全部字段标注来源层
- 装配 epoch：assemble 后基线；tools/list_changed 推进 catalog epoch →
  mcp_catalog_changed_since_assembly() 判定失效（P1-C 热刷新依据）
"""

import json
import time
from pathlib import Path

import pytest

from llm_loop.extensions.store import ExtensionStore
from llm_loop.tools.mcp_assembly import (
    LAYER_FILE_USER,
    LAYER_FILE_WORKSPACE,
    LAYER_LEGACY,
    LAYER_USER,
    LAYER_WORKSPACE,
    FileConfigSource,
    _reset_assembly_state_for_tests,
    assemble_mcp_tools,
    assembly_catalog_epoch,
    default_file_sources,
    effective_mcp_servers,
    mcp_catalog_changed_since_assembly,
)
from llm_loop.tools.mcp_client import McpConnection, McpServerSpec
from llm_loop.tools.registry import ToolRegistry
from tests.fixtures.fake_mcp_http_server import FakeMcpHttpServer


def _write_pkg(root: Path, name: str, servers: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "plugin.json").write_text(
        json.dumps({"name": name, "schema_version": "1.0.0", "version": "0.1.0"})
    )
    (root / "mcp.json").write_text(json.dumps({"mcpServers": servers}))


@pytest.fixture()
def reset_assembly():
    _reset_assembly_state_for_tests()
    yield
    _reset_assembly_state_for_tests()


def test_exact_identity_conflict_reported_not_stacked(tmp_path):
    """同一精确身份（installed@user vs legacy）→ 单实例 + 冲突报告 + provenance."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "demo-plugin",
        {"echo": {"type": "stdio", "command": "echo", "args": ["hi"]}},
    )
    store.install(tmp_path / "pkg", source="local", expected_revision=0)
    legacy = json.dumps([{"name": "echo", "type": "stdio", "command": "echo", "args": ["hi"]}])

    plan = effective_mcp_servers(store, legacy)
    assert len(plan.servers) == 1, "同一精确身份不得叠加为两台"
    assert plan.servers[0].layer == LAYER_USER
    assert plan.servers[0].install_id == "demo-plugin"
    assert set(plan.servers[0].provenance.values()) == {LAYER_USER}, "字段级 provenance"
    assert len(plan.conflicts) == 1
    conflict = plan.conflicts[0]
    assert conflict.name == "echo"
    assert conflict.identity == "stdio|echo hi"
    assert conflict.winner_layer == LAYER_USER
    assert conflict.loser_layers == [LAYER_LEGACY]


def test_workspace_beats_user_and_legacy(tmp_path):
    """三层同现：workspace 安装实例 > user 安装实例 > legacy."""
    store = ExtensionStore(tmp_path / "ext")
    identity = {"type": "http", "url": "http://127.0.0.1:9000/mcp"}
    _write_pkg(tmp_path / "pkg-user", "user-plugin", {"shared": dict(identity)})
    _write_pkg(tmp_path / "pkg-ws", "ws-plugin", {"shared": dict(identity)})
    store.install(tmp_path / "pkg-user", source="local", expected_revision=0, scopes=["user"])
    store.install(
        tmp_path / "pkg-ws",
        source="local",
        expected_revision=1,
        scopes=["workspace"],
    )
    legacy = json.dumps([{"name": "shared", **identity}])

    plan = effective_mcp_servers(store, legacy)
    assert len(plan.servers) == 1
    assert plan.servers[0].layer == LAYER_WORKSPACE
    assert plan.servers[0].install_id == "ws-plugin"
    conflict = plan.conflicts[0]
    assert conflict.winner_layer == LAYER_WORKSPACE
    assert conflict.loser_layers == [LAYER_USER, LAYER_LEGACY]


def test_same_name_different_endpoint_is_name_conflict(tmp_path):
    """同名不同端点：不得叠加（注册名会碰撞），取最高优先层并报告 name-conflict."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "demo-plugin",
        {"echo": {"type": "http", "url": "http://127.0.0.1:7001/mcp"}},
    )
    store.install(tmp_path / "pkg", source="local", expected_revision=0)
    legacy = json.dumps([{"name": "echo", "type": "http", "url": "http://127.0.0.1:7002/mcp"}])

    plan = effective_mcp_servers(store, legacy)
    assert len(plan.servers) == 1
    assert plan.servers[0].layer == LAYER_USER
    assert plan.conflicts[0].identity == "<name-conflict>"


def test_plugin_root_expansion_and_isolation(tmp_path):
    """标准保留变量 ${PLUGIN_ROOT}/${PLUGIN_DATA} 由宿主替换；坏包隔离跳过."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "demo-plugin",
        {
            "good": {
                "type": "stdio",
                "command": "python3",
                "args": ["${PLUGIN_ROOT}/run.py"],
                "env": {"DATA": "${PLUGIN_DATA}"},
            }
        },
    )
    store.install(tmp_path / "pkg", source="local", expected_revision=0)

    plan = effective_mcp_servers(store, "[]")
    assert len(plan.servers) == 1
    entry = plan.servers[0].entry
    rec = store.read_state().installs[0]
    pkg_root = str(store.package_root(rec.digest))
    data_dir = str(store.instance_data_dir(rec.install_id))
    assert entry["args"] == [f"{pkg_root}/run.py"]
    assert entry["env"] == {"DATA": data_dir}


def test_disabled_component_excluded(tmp_path):
    """安装记录组件 disabled → 不进入装配候选（enablement 在组件层）."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "demo-plugin",
        {"echo": {"type": "stdio", "command": "echo", "args": ["hi"]}},
    )
    rec = store.install(tmp_path / "pkg", source="local", expected_revision=0)
    store.set_enabled(rec.install_id, enabled=False, component="echo", expected_revision=1)

    plan = effective_mcp_servers(store, "[]")
    assert plan.servers == []


def test_assembly_epoch_invalidated_by_list_changed(reset_assembly):
    """装配 epoch 基线：list_changed 推进 catalog epoch → 失效可判定（端到端）."""
    server = FakeMcpHttpServer("modern")
    try:
        registry = ToolRegistry()
        legacy = json.dumps([{"name": "srv", "type": "http", "url": server.url}])
        registered = assemble_mcp_tools(registry, None, legacy)
        assert registered, "现代 HTTP fixture 应注册成功"
        baseline = assembly_catalog_epoch()
        assert baseline is not None
        assert mcp_catalog_changed_since_assembly() is False

        # 目录变化（服务器宣告 tools/list_changed）→ catalog epoch 推进 → 装配失效
        conn = McpConnection(
            McpServerSpec(name="srv", type="http", url=server.url),
            call_timeout=10,
            probe_timeout_s=2,
        )
        conn.connect()
        server.state.emit_list_changed()
        deadline = time.monotonic() + 3.0
        while not conn.stale and time.monotonic() < deadline:
            time.sleep(0.05)
        assert conn.stale
        conn.close()
        assert assembly_catalog_epoch() == baseline, "装配基线不随目录变化漂移"
        assert mcp_catalog_changed_since_assembly() is True, "装配应判定失效"
    finally:
        server.close()


def test_sse_entry_in_package_binds_legacy_transport(tmp_path, reset_assembly):
    """P2-B：包内 type=sse → sse 旧传输绑定（identity 含 sse 前缀，显式不回退）."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "sse-plugin",
        {
            "legacy": {"type": "sse", "url": "http://127.0.0.1:9301/sse"},
            "stream": {"type": "http", "url": "http://127.0.0.1:9301/mcp"},
        },
    )
    store.install(tmp_path / "pkg", source="local", expected_revision=0)
    plan = effective_mcp_servers(store, "[]")
    by_name = {s.name.split(":", 1)[1] if ":" in s.name else s.name: s.entry for s in plan.servers}
    assert by_name["legacy"]["type"] == "sse"
    assert by_name["legacy"]["url"] == "http://127.0.0.1:9301/sse"
    assert by_name["stream"]["type"] == "http"
    # 身份区分传输：sse 与 http 同 host 也不冲突
    identities = {s.identity for s in plan.servers}
    assert any(i.startswith("sse|") for i in identities)
    assert any(i.startswith("http|") for i in identities)


# ────────────────────────── P0-1：文件配置层 ──────────────────────────


def _file_source(tmp_path: Path, layer: str, servers: dict) -> FileConfigSource:
    """构造文件配置源：workspace 层写 tmp_path/.mcp.json，user 层写独立目录."""
    base = tmp_path / ("ws-root" if layer == LAYER_FILE_WORKSPACE else "user-root")
    path = base / (".mcp.json" if layer == LAYER_FILE_WORKSPACE else "mcp.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))
    return FileConfigSource(
        path=path,
        layer=layer,
        base_dir=base,
        data_dir=tmp_path / "data",
    )


def test_file_layers_beat_installed_and_legacy(tmp_path):
    """五层优先级：file@workspace > file@user > installed > legacy（同身份不叠加）."""
    store = ExtensionStore(tmp_path / "ext")
    _write_pkg(
        tmp_path / "pkg",
        "demo-plugin",
        {"shared": {"type": "http", "url": "http://127.0.0.1:9000/mcp"}},
    )
    store.install(tmp_path / "pkg", source="local", expected_revision=0)
    identity = {"type": "http", "url": "http://127.0.0.1:9000/mcp"}
    legacy = json.dumps([{"name": "shared", **identity}])
    sources = (
        _file_source(tmp_path, LAYER_FILE_USER, {"shared": dict(identity)}),
        _file_source(tmp_path, LAYER_FILE_WORKSPACE, {"shared": dict(identity)}),
    )

    plan = effective_mcp_servers(store, legacy, sources)
    assert len(plan.servers) == 1, "五层同身份仍只生效一台"
    assert plan.servers[0].layer == LAYER_FILE_WORKSPACE
    conflict = plan.conflicts[0]
    assert conflict.winner_layer == LAYER_FILE_WORKSPACE
    assert conflict.loser_layers == [LAYER_FILE_USER, LAYER_USER, LAYER_LEGACY]


def test_file_entry_type_inference_ecosystem_compat(tmp_path):
    """生态兼容：无 type 字段按 command/url 推断（Cursor/Claude Desktop 风格）."""
    sources = (
        _file_source(
            tmp_path,
            LAYER_FILE_WORKSPACE,
            {
                "local": {"command": "python3", "args": ["-m", "some.server"]},
                "remote": {"url": "http://127.0.0.1:9100/mcp"},
                "broken": {"command": ""},
            },
        ),
    )
    plan = effective_mcp_servers(None, "[]", sources)
    by_name = {s.name: s.entry for s in plan.servers}
    assert by_name["local"]["type"] == "stdio"
    assert by_name["local"]["command"] == "python3"
    assert by_name["local"]["enabled"] is True
    assert by_name["remote"]["type"] == "http"
    assert "broken" not in by_name, "缺 command/url 且无 type 的条目隔离跳过"


def test_file_entry_explicit_disabled(tmp_path):
    """文件条目 enabled=false：进 plan（register 侧跳过），字段级可见."""
    sources = (
        _file_source(
            tmp_path,
            LAYER_FILE_USER,
            {"paused": {"type": "stdio", "command": "echo", "enabled": False}},
        ),
    )
    plan = effective_mcp_servers(None, "[]", sources)
    assert len(plan.servers) == 1
    assert plan.servers[0].entry["enabled"] is False


def test_file_bad_json_isolated_fail_open(tmp_path):
    """坏 JSON / 缺 mcpServers / 条目非对象：整层或单条隔离，不影响其他层."""
    bad = FileConfigSource(
        path=tmp_path / "ws-root" / ".mcp.json",
        layer=LAYER_FILE_WORKSPACE,
        base_dir=tmp_path / "ws-root",
        data_dir=tmp_path / "data",
    )
    bad.path.parent.mkdir(parents=True, exist_ok=True)
    bad.path.write_text("{not json")
    good = _file_source(tmp_path, LAYER_FILE_USER, {"echo": {"type": "stdio", "command": "echo"}})

    plan = effective_mcp_servers(None, "[]", (bad, good))
    assert [s.name for s in plan.servers] == ["echo"]
    assert plan.servers[0].layer == LAYER_FILE_USER

    bad.path.write_text(json.dumps({"servers": {}}))  # 缺 mcpServers 键
    plan = effective_mcp_servers(None, "[]", (bad, good))
    assert [s.name for s in plan.servers] == ["echo"]

    bad.path.write_text(json.dumps({"mcpServers": {"x": "not-an-object", "y": {"type": "stdio", "command": "cat"}}}))
    plan = effective_mcp_servers(None, "[]", (bad, good))
    assert {s.name for s in plan.servers} == {"echo", "y"}


def test_file_plugin_root_expansion(tmp_path):
    """文件层变量展开：${PLUGIN_ROOT}=该层 base_dir，${PLUGIN_DATA}=data_dir."""
    sources = (
        _file_source(
            tmp_path,
            LAYER_FILE_WORKSPACE,
            {
                "local": {
                    "type": "stdio",
                    "command": "${PLUGIN_ROOT}/bin/server",
                    "args": ["--data", "${PLUGIN_DATA}"],
                }
            },
        ),
    )
    plan = effective_mcp_servers(None, "[]", sources)
    entry = plan.servers[0].entry
    assert entry["command"] == str(tmp_path / "ws-root" / "bin" / "server")
    assert entry["args"] == ["--data", str(tmp_path / "data")]


def test_default_file_sources_modes(tmp_path):
    """MCP_FILE_CONFIG 档位：off=()；user=仅用户级；auto/未知=两层."""
    assert default_file_sources(tmp_path / "data", tmp_path, mode="off") == ()
    assert default_file_sources(tmp_path / "data", tmp_path, mode="OFF") == ()
    user_only = default_file_sources(tmp_path / "data", tmp_path, mode="user")
    assert [s.layer for s in user_only] == [LAYER_FILE_USER]
    both = default_file_sources(tmp_path / "data", tmp_path, mode="")
    assert [s.layer for s in both] == [LAYER_FILE_USER, LAYER_FILE_WORKSPACE]
    assert default_file_sources(tmp_path / "data", tmp_path, mode="bogus") == both, "未知值按 auto 处理"


def test_missing_file_is_empty_layer_not_error(tmp_path):
    """文件不存在=空层（默认无 .mcp.json 的环境行为完全不变）."""
    ghost = FileConfigSource(
        path=tmp_path / "nope" / ".mcp.json",
        layer=LAYER_FILE_WORKSPACE,
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
    )
    plan = effective_mcp_servers(None, "[]", (ghost,))
    assert plan.servers == []
    assert plan.conflicts == []
