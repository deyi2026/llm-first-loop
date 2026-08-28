"""CR-R1 任务组 2 单测（tasks 2.3）：COG_RUNTIME_MODE 三态解析与 off 短路。

- _env_cog_mode 纯函数：合法三值直通 / 非法与空回退 shadow（config 内联范式同 anchor_mode）。
- history off 短路：同环境（活跃 goal 存在）下 shadow=默认落盘 / off 不写 store（行为级区分度）。
- build 侧 MODE 覆写（off/shadow→anchor+平铺）为内联逻辑，由任务 7 不变量集成断言覆盖。
"""
from pathlib import Path

from llm_loop.config import _env_cog_mode


# ── _env_cog_mode 解析（tasks 2.1）──────────────────────────────────


def test_env_cog_mode_valid_values(monkeypatch):
    for v in ("off", "shadow", "enforce"):
        monkeypatch.setenv("COG_RUNTIME_MODE_TEST", v)
        assert _env_cog_mode("COG_RUNTIME_MODE_TEST") == v
    for v in ("OFF", "Shadow", "ENFORCE"):  # 大小写不敏感
        monkeypatch.setenv("COG_RUNTIME_MODE_TEST", v)
        assert _env_cog_mode("COG_RUNTIME_MODE_TEST") == v.lower()


def test_env_cog_mode_invalid_falls_back_shadow(monkeypatch):
    monkeypatch.setenv("COG_RUNTIME_MODE_TEST", "yolo")
    assert _env_cog_mode("COG_RUNTIME_MODE_TEST") == "shadow"


def test_env_cog_mode_unset_defaults_shadow(monkeypatch):
    monkeypatch.delenv("COG_RUNTIME_MODE_TEST", raising=False)
    assert _env_cog_mode("COG_RUNTIME_MODE_TEST") == "shadow"


def test_env_cog_mode_whitespace_tolerant(monkeypatch):
    monkeypatch.setenv("COG_RUNTIME_MODE_TEST", "  enforce  ")
    assert _env_cog_mode("COG_RUNTIME_MODE_TEST") == "enforce"


# ── history off 短路（tasks 2.2）───────────────────────────────────


def _seed_goal(tmp_path: Path):
    from llm_loop.introspection.goal import GoalStore

    store = GoalStore(tmp_path / "audit")
    g = store.create("mode 测试目标", session_id="s1")
    store.checkpoint(g.id, what="w1", next_step="n1")


def test_persist_shadow_default_writes_shard(tmp_path, monkeypatch):
    from llm_loop.cognitive.state import SemanticStateStore
    from llm_loop.core.history import _persist_semantic_state

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("COG_RUNTIME_MODE", raising=False)  # 默认 shadow
    _seed_goal(tmp_path)
    assert _persist_semantic_state("s1") is True
    shard = SemanticStateStore(tmp_path / "audit").path_for("s1")
    assert shard.exists()  # 默认（shadow）落盘


def test_persist_off_short_circuits_no_write(tmp_path, monkeypatch):
    from llm_loop.cognitive.state import SemanticStateStore
    from llm_loop.core.history import _persist_semantic_state

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COG_RUNTIME_MODE", "off")
    _seed_goal(tmp_path)
    assert _persist_semantic_state("s1") is False
    shard = SemanticStateStore(tmp_path / "audit").path_for("s1")
    assert not shard.exists()  # off 连 store 写都不做（tasks 2.2）


def test_persist_off_short_circuit_beats_goal_absence(tmp_path, monkeypatch):
    """off 返回 False 的原因是短路而非无 goal——用活跃 goal 存在与 off 对比同环境区分。"""
    from llm_loop.core.history import _persist_semantic_state

    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("COG_RUNTIME_MODE", "off")
    _seed_goal(tmp_path)  # 有活跃 goal 仍 False → 证明是 off 短路
    assert _persist_semantic_state("s1") is False
