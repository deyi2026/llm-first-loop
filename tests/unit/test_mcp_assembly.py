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
    LAYER_LEGACY,
    LAYER_USER,
    LAYER_WORKSPACE,
    _reset_assembly_state_for_tests,
    assemble_mcp_tools,
    assembly_catalog_epoch,
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
