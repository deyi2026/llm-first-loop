"""T-0.6 E-2：fanout_decision 埋点（DESIGN-20261103 §6.6）.

验收口径：
- allow/deny 各写一条，字段取自决策临界区（running_before 是**决策前**的值）；
- 观测失败（claims 路径不可写）不改变 spawn 的接受/拒绝结果（不变量 1）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from llm_loop.introspection.claims import events as ev
from llm_loop.llm.client import LLMResponse


def _rows(audit_dir: Path) -> list[dict]:
    path = ev.events_path(audit_dir)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _blocking_engine(build_test_engine, max_handles: int = 1):
    engine, fake = build_test_engine([])
    runner = engine.registry.get("spawn_subagent")._runner
    runner._max_handles = max_handles
    entered = threading.Event()
    release = threading.Event()

    def _chat(messages, tools, **kwargs):
        del messages, tools, kwargs
        entered.set()
        assert release.wait(3.0)
        return LLMResponse(content="done", tool_calls=[], provider="fake")

    fake.chat = _chat  # type: ignore[method-assign]
    return engine, runner, entered, release


def test_fanout_allow_then_deny_writes_both_events(build_test_engine):
    engine, runner, entered, release = _blocking_engine(build_test_engine)
    audit_dir = runner._audit_dir()
    ev.reset_write_failures(audit_dir)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("parent-fanout")
    try:
        first = runner.start(task="占住唯一 background slot")
        assert first["accepted"] is True
        assert entered.wait(3.0)
        second = runner.start(task="应被资源边界拒绝")
        assert second["accepted"] is False
        runner.cancel_parent("parent-fanout")
    finally:
        current_session_id.reset(tok)
        release.set()

    rows = _rows(audit_dir)
    assert [r["decision"] for r in rows] == ["allow", "deny"]
    allow, deny = rows
    assert allow["kind"] == "fanout_decision"
    assert allow["running_before"] == 0
    assert allow["limit"] == 1
    assert allow["reason_code"] is None
    assert deny["reason_code"] == "handle_capacity"
    assert deny["running_before"] == 1  # 决策前（未插入新 handle）的计数
    assert deny["parent"] == "parent-fanout"
    assert ev.write_failures(audit_dir) == 0


def test_fanout_event_failure_does_not_change_spawn_outcome(build_test_engine):
    engine, runner, entered, release = _blocking_engine(build_test_engine)
    audit_dir = runner._audit_dir()
    ev.reset_write_failures(audit_dir)
    # claims 路径被文件占用 → append 必然失败
    (Path(audit_dir) / ev.CLAIMS_DIRNAME).parent.mkdir(parents=True, exist_ok=True)
    (Path(audit_dir) / ev.CLAIMS_DIRNAME).write_text("blocked", encoding="utf-8")
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("parent-fanout-fail")
    try:
        first = runner.start(task="占住唯一 background slot")
        assert first["accepted"] is True
        assert entered.wait(3.0)
        second = runner.start(task="应被资源边界拒绝")
        assert second["accepted"] is False
        assert second["state"] == "refused"
        runner.cancel_parent("parent-fanout-fail")
    finally:
        current_session_id.reset(tok)
        release.set()

    assert _rows(audit_dir) == []
    assert ev.write_failures(audit_dir) >= 2


def test_per_parent_gate_denies_and_reports_count_and_exits(build_test_engine):
    """N4-A1：同 parent 超过 max_running_children → parent_concurrency + 计数 + 出口."""
    engine, runner, entered, release = _blocking_engine(build_test_engine, max_handles=16)
    runner._max_running_children = 1
    audit_dir = runner._audit_dir()
    ev.reset_write_failures(audit_dir)
    from llm_loop.core.run_context import current_session_id

    tok = current_session_id.set("parent-gate")
    try:
        first = runner.start(task="占住 parent 唯一槽位")
        assert first["accepted"] is True
        assert entered.wait(3.0)
        second = runner.start(task="同 parent 第二个")
        assert second["accepted"] is False
        assert second["state"] == "refused"
        detail = second["detail"]
        assert "subagent_parent_concurrency" in detail
        assert "已达上限 1" in detail  # 当前计数 + 上限
        assert "出口" in detail  # 三出口提示
        runner.cancel_parent("parent-gate")
    finally:
        current_session_id.reset(tok)
        release.set()

    rows = _rows(audit_dir)
    assert [r["decision"] for r in rows] == ["allow", "deny"]
    assert rows[1]["reason_code"] == "parent_concurrency"
    assert rows[1]["running_before"] == 1
    assert rows[1]["limit"] == 1


def test_per_parent_gate_defaults_to_16_and_clamps_env(monkeypatch):
    from llm_loop.subagent.runner import _resolve_max_running_children

    monkeypatch.delenv("LFL_MAX_RUNNING_CHILDREN", raising=False)
    assert _resolve_max_running_children() == 16
    monkeypatch.setenv("LFL_MAX_RUNNING_CHILDREN", "64")
    assert _resolve_max_running_children() == 32
    monkeypatch.setenv("LFL_MAX_RUNNING_CHILDREN", "0")
    assert _resolve_max_running_children() == 1
    monkeypatch.setenv("LFL_MAX_RUNNING_CHILDREN", "abc")
    assert _resolve_max_running_children() == 16


def test_max_running_children_config_and_runner_agree(monkeypatch):
    """P2-5：config 与 runner 是两个独立读取入口，必须对同一批 env 给出同一答案.

    claim 侧有 `test_policy_matches_config_defaults` 守默认值；per-parent 闸此前没有
    任何漂移测试，改一处 clamp 不会被发现。
    """
    from llm_loop.config import load_settings
    from llm_loop.subagent.runner import _resolve_max_running_children

    cases = {"": 16, "1": 1, "16": 16, "32": 32, "64": 32, "0": 1, "abc": 16}
    required = {"LLM_API_KEY": "test-key", "LLM_BASE_URL": "https://provider.invalid/v1"}
    for raw, expected in cases.items():
        monkeypatch.setenv("LFL_MAX_RUNNING_CHILDREN", raw)
        assert _resolve_max_running_children() == expected, f"runner raw={raw!r}"
        settings = load_settings({**required, "LFL_MAX_RUNNING_CHILDREN": raw})
        assert settings.tool_runtime.max_running_children == expected, f"config raw={raw!r}"
