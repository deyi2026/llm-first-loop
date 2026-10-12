"""Fleet slice 4 (G1): factory 生产接线，settings 显式 opt-in。

Contract（用户确认 2026-09-19）:
- 缺省配置 fleet 完全关闭：factory 不构造 ProjectCoordinator、不落任何
  state.json、subagent_lease 工具回执 fail-closed 与接线前逐字节一致（零回归）。
- 显式开启（fleet_workspace_root 非空）：factory 构造 ProjectCoordinator 注入
  SubAgentRunner —— build 时项目 state 已落盘（磁盘真相可见），lease 工具背后的
  runner 携带 coordinator，physical_root / fleet_dir / project_id / repo_head
  均按 settings 解析；runner 保持有界租约 TTL 默认（900s），不回退旧永不过期模式。
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from llm_loop.config import Settings, load_settings
from llm_loop.core.message import ToolResultStatus
from llm_loop.factory import build_engine


def _base_settings(tmp_path) -> Settings:
    return Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
    )


def _lease_tool(engine):
    return engine.registry.get("subagent_lease")


def test_default_settings_keep_fleet_off(tmp_path):
    """缺省（fleet_workspace_root 为空）→ 无 coordinator、无 state.json、工具 fail-closed."""
    engine = build_engine(_base_settings(tmp_path))
    tool = _lease_tool(engine)
    assert tool._runner._project_coordinator is None
    assert not (Path(engine.settings.data_dir) / "fleet" / "state.json").exists()
    # 零回归探针：接线前后该回执都必须是 failure（不含 coordinator 泄漏）.
    result = tool.execute(child_id="whatever")
    assert result.status is ToolResultStatus.FAILURE


def test_optin_wires_coordinator_and_persists_project_state(tmp_path):
    """显式开启 → runner 携带 coordinator；build 时项目 state 落盘于派生 fleet_dir."""
    ws_root = tmp_path / "ws-root"
    settings = replace(_base_settings(tmp_path), fleet_workspace_root=str(ws_root))
    engine = build_engine(settings)
    tool = _lease_tool(engine)
    coordinator = tool._runner._project_coordinator
    assert coordinator is not None
    assert coordinator.physical_root == str(ws_root)
    assert coordinator.repo_head == ""
    state_path = Path(settings.data_dir) / "fleet" / "state.json"
    assert state_path.is_file()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "default" in state["projects"]
    # factory 不显式传 ttl：保持 runner 有界租约默认，不回退 None 旧行为.
    assert tool._runner._fleet_lease_ttl_seconds == 900.0


def test_optin_respects_explicit_project_id_state_dir_and_repo_head(tmp_path):
    """project_id / fleet_state_dir / repo_head 均可显式覆盖并如实落盘."""
    settings = replace(
        _base_settings(tmp_path),
        fleet_workspace_root=str(tmp_path / "ws"),
        fleet_project_id="proj-x",
        fleet_state_dir=str(tmp_path / "custom-fleet"),
        fleet_repo_head="abc123",
    )
    engine = build_engine(settings)
    coordinator = _lease_tool(engine)._runner._project_coordinator
    assert coordinator is not None
    assert coordinator.project_id == "proj-x"
    assert coordinator.repo_head == "abc123"
    state = json.loads(
        (tmp_path / "custom-fleet" / "state.json").read_text(encoding="utf-8")
    )
    assert "proj-x" in state["projects"]
    # 显式 state_dir 覆盖时不再写派生路径.
    assert not (Path(settings.data_dir) / "fleet" / "state.json").exists()


def test_env_mapping_loads_fleet_optin_fields():
    """LFL_FLEET_* env → Settings 字段；缺省为空（=关闭）."""
    s = load_settings(
        {
            "LLM_API_KEY": "k",
            "LLM_BASE_URL": "https://x/v1",
            "LLM_MODEL": "m",
            "LFL_FLEET_WORKSPACE_ROOT": "/tmp/ws",
            "LFL_FLEET_PROJECT_ID": "p1",
            "LFL_FLEET_STATE_DIR": "/tmp/f",
            "LFL_FLEET_REPO_HEAD": "deadbeef",
        }
    )
    assert s.fleet_workspace_root == "/tmp/ws"
    assert s.fleet_project_id == "p1"
    assert s.fleet_state_dir == "/tmp/f"
    assert s.fleet_repo_head == "deadbeef"

    off = load_settings(
        {"LLM_API_KEY": "k", "LLM_BASE_URL": "https://x/v1", "LLM_MODEL": "m"}
    )
    assert off.fleet_workspace_root == ""
    assert off.fleet_project_id == ""
    assert off.fleet_state_dir == ""
    assert off.fleet_repo_head == ""
