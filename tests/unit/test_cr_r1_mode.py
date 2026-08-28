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


# ── Stage 2 Enforce Allowlist（DESIGN-20260901 rev2，用户带硬约束批准）──


class _S2Settings:
    """_cog_allowlist_hit 轻量 stub（纯函数层）."""

    def __init__(self, mode: str = "shadow", enforce_file: str = ""):
        self.cog_runtime_mode = mode
        self.cog_enforce_file = enforce_file


class _S2Sess:
    def __init__(self, sid: str):
        self.session_id = sid


def _hit(path: str, sid: str = "s-stage2") -> bool:
    from llm_loop.core.loop.build import _cog_allowlist_hit

    return _cog_allowlist_hit(_S2Settings("shadow", path), _S2Sess(sid))


def test_s2_allowlist_hit(tmp_path: Path):
    p = tmp_path / "allow.txt"
    p.write_text("# operator owned\ns-stage2\n", encoding="utf-8")
    assert _hit(str(p)) is True


def test_s2_allowlist_miss(tmp_path: Path):
    p = tmp_path / "allow.txt"
    p.write_text("other-sid\n", encoding="utf-8")
    assert _hit(str(p)) is False


def test_s2_empty_config_disabled():
    assert _hit("") is False  # 空配置=名单禁用（shadow）


def test_s2_relative_path_invalid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rel.txt").write_text("s-stage2\n", encoding="utf-8")
    assert _hit("rel.txt") is False  # P0-1: 相对路径=配置无效 fail-closed


def test_s2_missing_file(tmp_path: Path):
    assert _hit(str(tmp_path / "nope.txt")) is False  # P0-2: 缺失→shadow


def test_s2_oversize_64kib(tmp_path: Path):
    p = tmp_path / "allow.txt"
    p.write_text("x" * 70000, encoding="utf-8")
    assert _hit(str(p)) is False  # P1-3: >64KiB


def test_s2_over_256_entries(tmp_path: Path):
    p = tmp_path / "allow.txt"
    p.write_text("\n".join(f"sid-{i}" for i in range(300)), encoding="utf-8")
    assert _hit(str(p)) is False  # P1-3: >256 有效条目


def test_s2_oserror_fail_closed(tmp_path: Path):
    assert _hit(str(tmp_path)) is False  # 目录当文件 OSError → False（P0-2）


# ── 集成层: build 路径（P0-2 off 硬关 / P1-4 三字段 / E2E 热删）──


def _s2_read_events(engine) -> list:
    import json as _json

    f = Path(engine.settings.data_dir) / "audit" / "cognitive_telemetry.jsonl"
    if not f.exists():
        return []
    return [_json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _s2_last_pc(engine) -> dict:
    evs = [e for e in _s2_read_events(engine) if e.get("event") == "packet_compile"]
    assert evs, "无 packet_compile 事件（cognitive compute 未触发）"
    return evs[-1]


def test_s2_off_hard_blocks_allowlist(tmp_path, monkeypatch):
    """P0-2: mode=off 永远硬关——名单命中也不得产生 enforce compute/事件."""
    from tests.unit.test_injection_fingerprint import _build, _engine

    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    engine, sess = _engine(tmp_path)
    allow = tmp_path / "allow.txt"
    allow.write_text(sess.session_id + "\n", encoding="utf-8")
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings, cog_runtime_mode="off", cog_enforce_file=str(allow)
    )
    _build(engine, sess, [])
    pcs = [e for e in _s2_read_events(engine) if e.get("event") == "packet_compile"]
    assert pcs == []  # off 短路: 无 compute → 无事件


def test_s2_promoted_telemetry_fields(tmp_path, monkeypatch):
    """P1-4: shadow+命中 → packet_compile: mode=enforce / configured_mode=shadow / promoted=true."""
    from tests.unit.test_injection_fingerprint import _build, _engine

    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    engine, sess = _engine(tmp_path)
    allow = tmp_path / "allow.txt"
    allow.write_text(sess.session_id + "\n", encoding="utf-8")
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings, cog_runtime_mode="shadow", cog_enforce_file=str(allow)
    )
    _build(engine, sess, [])
    ev = _s2_last_pc(engine)
    assert ev["mode"] == "enforce"
    assert ev["configured_mode"] == "shadow"
    assert ev["promoted"] is True


def test_s2_hot_removal_round_n_n1(tmp_path, monkeypatch):
    """E2E 热删机械锁定（P1-5 prospective rollback）: round N promoted=true/enforce
    → operator 删 sid → round N+1 promoted=false/shadow."""
    from tests.unit.test_injection_fingerprint import _build, _engine

    monkeypatch.setenv("COG_RUNTIME_TELEMETRY", "1")
    engine, sess = _engine(tmp_path)
    allow = tmp_path / "allow.txt"
    allow.write_text(sess.session_id + "\n", encoding="utf-8")
    import dataclasses

    engine.settings = dataclasses.replace(
        engine.settings, cog_runtime_mode="shadow", cog_enforce_file=str(allow)
    )
    _build(engine, sess, [])  # round N
    ev1 = _s2_last_pc(engine)
    assert (ev1["mode"], ev1["promoted"]) == ("enforce", True)
    allow.write_text("", encoding="utf-8")  # operator rollback: 删 sid
    _build(engine, sess, [])  # round N+1（同 session 下一轮 build）
    ev2 = _s2_last_pc(engine)
    assert (ev2["mode"], ev2["promoted"], ev2["configured_mode"]) == (
        "shadow",
        False,
        "shadow",
    )
