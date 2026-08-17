"""投影一致性门闸单测（EVO-20260817-b6554376，借鉴 DSH seq 水印）.

验证 stable_digest 确定性、projection_ver 参数敏感、projection_check 状态机
（miss/ok/mismatch），以及 Session.projection_guard 字段透传向后兼容。
"""
from pathlib import Path

from llm_loop.core.history import stable_digest, projection_ver, projection_check
from llm_loop.core.session import Session, SessionStore


def test_stable_digest_deterministic():
    a = stable_digest({"b": 1, "a": [2, {"d": 3, "c": 4}]})
    b = stable_digest({"a": [2, {"c": 4, "d": 3}], "b": 1})  # 键序不同
    assert a == b  # sort_keys 稳定
    assert len(a) == 64  # sha256 hex


def test_stable_digest_changes_on_content():
    assert stable_digest("hello") != stable_digest("hello ")
    assert stable_digest([1, 2]) != stable_digest([1, 2, 3])


def test_projection_ver_parameter_sensitive():
    base = dict(model="m", budget=1000, anchor=0, memory_fp="x", interop_fp="y",
                system_fp="z", settings_fp="w")
    v1 = projection_ver(**base)
    # 每个参数变化都应改变 ver（漏覆盖参数 = 缓存行错误过期/误告警）
    for key in ("model", "budget", "anchor", "memory_fp", "interop_fp", "system_fp", "settings_fp"):
        changed = dict(base)
        changed[key] = "DIFF" if not isinstance(base[key], int) else base[key] + 1
        assert projection_ver(**changed) != v1, f"ver 未覆盖参数 {key}"


def test_projection_check_state_machine():
    ver = projection_ver(model="m", budget=1000, anchor=0, memory_fp="x",
                         interop_fp="y", system_fp="z", settings_fp="w")
    prev = {"ver": ver, "seq": 10, "built_hash": "h1"}
    # 无前序 → miss
    assert projection_check(None, ver=ver, seq=10, built_hash="h1") == "miss"
    # ver/seq 匹配且 hash 同 → ok（稳定期）
    assert projection_check(prev, ver=ver, seq=10, built_hash="h1") == "ok"
    # ver/seq 匹配但 hash 不同 → mismatch（非确定性构建/历史被改）
    assert projection_check(prev, ver=ver, seq=10, built_hash="h2") == "mismatch"
    # seq 变化 → miss（新消息追加，正常）
    assert projection_check(prev, ver=ver, seq=11, built_hash="h1") == "miss"
    # ver 变化 → miss（参数变更，正常）
    ver2 = projection_ver(model="m", budget=1001, anchor=0, memory_fp="x",
                          interop_fp="y", system_fp="z", settings_fp="w")
    assert projection_check(prev, ver=ver2, seq=10, built_hash="h1") == "miss"


def test_projection_guard_json_roundtrip(tmp_path: Path):
    """Session.projection_guard 落盘/加载往返 + 缺省向后兼容."""
    store = SessionStore(tmp_path)
    sid = "t-proj-guard"
    s = Session(session_id=sid)
    s.projection_guard["deepseek"] = {"ver": "v", "seq": 5, "built_hash": "h", "ts": "t"}
    store._save_locked(s)

    loaded = store._load_from_json(sid)
    assert loaded.projection_guard["deepseek"]["seq"] == 5

    # 旧 JSON 无字段 → 空 dict（向后兼容）
    import json
    p = tmp_path / f"{sid}.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data.pop("projection_guard")
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    loaded2 = store._load_from_json(sid)
    assert loaded2.projection_guard == {}
