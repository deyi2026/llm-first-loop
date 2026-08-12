"""feishu 测试公共 fixture：心跳路径隔离到 tmp（M47，防测试污染仓库 data/）."""

import pytest

from llm_loop.feishu import bridge as _bridge


@pytest.fixture(autouse=True)
def _isolate_heartbeat_path(monkeypatch, tmp_path):
    monkeypatch.setattr(_bridge, "_HEARTBEAT_PATH", str(tmp_path / "feishu_heartbeat.json"))
