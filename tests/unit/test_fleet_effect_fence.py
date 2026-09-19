"""R1 fleet effect fence: lease capability at every physical commit boundary.

Invariants under test:

- ``effect_mutation_authority`` denies (and permanently revokes the binding)
  once the binding's lease fence reports authority lost; denial is sticky per
  binding AND per session in this process (child stops producing side effects);
- an unreadable fence probe fails closed;
- bindings without a fence keep pre-R1 behavior (generation fencing only);
- ``FleetStore.lease_is_current`` mirrors ``_require_current`` exactly:
  active+unexpired -> True; expired / superseded / settled / unknown -> False;
- commit boundaries honor the fence: execute_command spawn (fg+bg),
  codearts_dispatch remote dispatch, dsh _run_once / _start_background spawn,
  and edit_file (file commit) are all typed refusals with no side effect;
- runner heartbeat failure marks the session sticky-fenced and the runner's
  fence probe follows the live lease truth.
"""

from __future__ import annotations

import time
import types
from pathlib import Path

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.session import SessionStore
from llm_loop.core.tool_execution_journal import ToolExecutionJournal
from llm_loop.event_log.store import EventStore
from llm_loop.fleet.store import FencedError, FleetStore
from llm_loop.tools.builtin.edit_file import EditFileTool
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

REPO_ROOT = Path(__file__).resolve().parents[2]


def _journal(tmp_path: Path):
    events = EventStore(tmp_path / "events", enabled=True)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    sid = sessions.create()
    journal = ToolExecutionJournal(
        event_store=events,
        result_root=tmp_path / "tool-results",
        session_store=sessions,
    )
    return journal, sessions, sid


def _call(cid: str = "call-fence-1") -> ToolCall:
    return ToolCall(id=cid, name="edit_file", arguments={})


def _seed_fleet(fleet_dir: Path) -> tuple[FleetStore, str, str]:
    store = FleetStore(fleet_dir)
    store.create_project("p")
    workspace = store.create_workspace("p", "/tmp/phys-fence", "sha")
    return store, "p", workspace.workspace_id


# ---------------------------------------------------- A: journal fence semantics


def _authority(journal, sessions, sid, tmp_path, fence):
    call = _call()
    sess = sessions.load(sid)
    execution_id = journal.declared(sess, call, round_no=1)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=fence,
    ):
        from llm_loop.core.tool_execution_journal import current_tool_effect_binding

        binding = current_tool_effect_binding()
        with journal.effect_mutation_authority(binding) as allowed:
            return allowed


def test_fence_lost_denies_and_revokes_binding_sticky(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    verdict = [False]

    def fence() -> bool:
        return verdict[0]

    # First probe: fence says lost -> denied.
    assert _authority(journal, sessions, sid, tmp_path, fence) is False
    # Binding is permanently revoked even if the fence later says healthy.
    verdict[0] = True
    assert _authority(journal, sessions, sid, tmp_path, fence) is False


def test_fence_loss_is_sticky_per_session_for_new_bindings(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    assert _authority(journal, sessions, sid, tmp_path, lambda: False) is False
    # New binding with a healthy fence still starts revoked (sticky session).
    assert _authority(journal, sessions, sid, tmp_path, lambda: True) is False
    # Another session is unaffected.
    sid2 = sessions.create()
    assert _authority(journal, sessions, sid2, tmp_path, lambda: True) is True


def test_fence_probe_exception_fails_closed(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)

    def boom() -> bool:
        raise RuntimeError("disk truth unreadable")

    assert _authority(journal, sessions, sid, tmp_path, boom) is False
    assert journal.effect_fence_lost(sid) is True


def test_no_fence_keeps_pre_r1_behavior(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    # lease_fence=None: authority granted exactly like before R1.
    assert _authority(journal, sessions, sid, tmp_path, None) is True


# ---------------------------------------------------- B: store lease_is_current


def test_lease_is_current_matrix(tmp_path: Path) -> None:
    store, project, ws = _seed_fleet(tmp_path / "fleet")
    lease = store.acquire_lease(project, ws, owner_id="ow", ttl_seconds=30)
    assert store.lease_is_current(lease) is True

    # Superseded by operator force-reclaim: predecessor loses authority.
    successor = store.force_reclaim(
        project,
        ws,
        "ow2",
        expected_lease_id=lease.lease_id,
        expected_generation=lease.generation,
        reason="operator r1 test takeover",
        authorized_by="operator-1",
        ttl_seconds=30,
    )
    assert store.lease_is_current(lease) is False
    assert store.lease_is_current(successor) is True

    # Settled: successor loses authority too.
    store.settle(successor, {"final": "ok"})
    assert store.lease_is_current(successor) is False

    # Unknown lease object -> False, never raises.
    ghost = types.SimpleNamespace(lease_id="nope", generation=999, workspace_id=ws)
    assert store.lease_is_current(ghost) is False


def test_lease_is_current_false_after_real_expiry(tmp_path: Path) -> None:
    store, project, ws = _seed_fleet(tmp_path / "fleet")
    lease = store.acquire_lease(project, ws, owner_id="ow", ttl_seconds=0.2)
    assert store.lease_is_current(lease) is True
    time.sleep(0.25)
    assert store.lease_is_current(lease) is False


# ---------------------------------------------------- C: commit boundaries


def test_execute_command_fg_refused_when_fenced_no_spawn(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    marker = tmp_path / "spawned.marker"
    call = ToolCall(
        id="call-cmd-fence",
        name="execute_command",
        arguments={"command": f"touch {marker}"},
    )
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = ExecuteCommandTool(timeout_s=10)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        result = tool.execute(command=f"touch {marker}", workdir=str(tmp_path))
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "effect authority" in result.content
    assert not marker.exists(), "fenced spawn must not happen"


def test_execute_command_bg_refused_when_fenced_no_spawn(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    marker = tmp_path / "bg.marker"
    call = ToolCall(
        id="call-cmd-bg-fence",
        name="execute_command",
        arguments={"command": f"sleep 2; touch {marker}", "run_in_background": True},
    )
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = ExecuteCommandTool(timeout_s=10)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        result = tool.execute(
            command=f"sleep 2; touch {marker}",
            workdir=str(tmp_path),
            run_in_background=True,
        )
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "effect authority" in result.content
    assert not marker.exists()


def test_execute_command_allows_when_fence_healthy(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    marker = tmp_path / "ok.marker"
    call = ToolCall(id="call-cmd-ok", name="execute_command", arguments={})
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = ExecuteCommandTool(timeout_s=10)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: True,
    ):
        result = tool.execute(command=f"touch {marker}", workdir=str(tmp_path))
    assert result.status == ToolResultStatus.SUCCESS
    assert marker.exists()


def test_edit_file_refused_when_fenced_no_write(tmp_path: Path) -> None:
    journal, sessions, sid = _journal(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("BEFORE\n", encoding="utf-8")
    call = ToolCall(
        id="call-edit-fence",
        name="edit_file",
        arguments={"path": str(target), "old_string": "BEFORE", "new_string": "AFTER"},
    )
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        result = EditFileTool().execute(
            path=str(target), old_string="BEFORE", new_string="AFTER"
        )
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "effect authority" in result.content
    assert target.read_text(encoding="utf-8") == "BEFORE\n"


def test_codearts_dispatch_refused_when_fenced(tmp_path: Path) -> None:
    from llm_loop.tools.builtin.codearts_dispatch import CodeArtsDispatchTool

    journal, sessions, sid = _journal(tmp_path)
    calls = []

    class FakeScheduler:
        def dispatch(self, task, session_id=""):
            calls.append((task, session_id))
            return {"status": "dispatched"}

    call = ToolCall(id="call-ca-fence", name="codearts_dispatch", arguments={})
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = CodeArtsDispatchTool(FakeScheduler())
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        result = tool.execute(task_description="fenced", task_markdown="x")
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert calls == [], "fenced remote dispatch must not fire"


def test_dsh_run_once_fenced_returns_typed_sentinel(tmp_path: Path) -> None:
    from llm_loop.tools.builtin.dsh_task import DshTaskTool

    journal, sessions, sid = _journal(tmp_path)
    call = ToolCall(id="call-dsh-fence", name="dsh_task", arguments={})
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = DshTaskTool()
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        code, out, err, elapsed = tool._run_once(
            "say hi", str(tmp_path), 5.0, "/bin/true"
        )
    assert code == "fenced"
    assert "effect authority" in err


def test_dsh_start_background_refused_when_fenced(tmp_path: Path, monkeypatch) -> None:
    from llm_loop.tools.builtin import dsh_task as dsh_module
    from llm_loop.tools.builtin.dsh_task import DshTaskTool

    journal, sessions, sid = _journal(tmp_path)
    spawns = []
    monkeypatch.setattr(
        dsh_module.subprocess,
        "Popen",
        lambda *a, **k: spawns.append((a, k)) or object(),
    )
    call = ToolCall(id="call-dshbg-fence", name="dsh_task", arguments={})
    execution_id = journal.declared(sessions.load(sid), call, round_no=1)
    tool = DshTaskTool()
    with journal.effect_context(
        session_id=sid,
        execution_id=execution_id,
        round_no=1,
        call=call,
        workspace_root=str(tmp_path),
        lease_fence=lambda: False,
    ):
        result = tool._start_background("say hi", str(tmp_path), 5.0, "/bin/true")
    assert result.status == ToolResultStatus.UNAUTHORIZED
    assert "effect authority" in result.content
    assert spawns == [], "fenced background spawn must not happen"


# ---------------------------------------------------- D: runner fence helpers


class _FakeCoordinator:
    def __init__(self, store, project, ws):
        self.store = store
        self.project = project
        self.ws = ws

    def renew_run(self, lease, *, extend_seconds):
        raise FencedError("superseded by rival coordinator")

    def lease_is_current(self, lease):
        return self.store.lease_is_current(lease)


def test_runner_renew_failure_marks_sticky_fence(tmp_path: Path) -> None:
    from llm_loop.subagent.runner import SubAgentRunner

    journal, sessions, sid = _journal(tmp_path)
    store, project, ws = _seed_fleet(tmp_path / "fleet")
    lease = store.acquire_lease(project, ws, owner_id="ow", ttl_seconds=30)
    runner_ns = types.SimpleNamespace(
        _project_coordinator=_FakeCoordinator(store, project, ws),
        _fleet_lease_ttl_seconds=30,
        _fleet_leases={sid: lease},
        _tool_journal=journal,
    )
    assert journal.effect_fence_lost(sid) is False
    SubAgentRunner._renew_fleet_run(runner_ns, sid)
    assert journal.effect_fence_lost(sid) is True


def test_runner_fence_probe_follows_live_lease_truth(tmp_path: Path) -> None:
    from llm_loop.subagent.runner import SubAgentRunner

    journal, sessions, sid = _journal(tmp_path)
    store, project, ws = _seed_fleet(tmp_path / "fleet")
    lease = store.acquire_lease(project, ws, owner_id="ow", ttl_seconds=30)
    coord = _FakeCoordinator(store, project, ws)
    runner_ns = types.SimpleNamespace(
        _project_coordinator=coord,
        _fleet_leases={sid: lease},
        _tool_journal=journal,
    )

    probe = SubAgentRunner._fleet_lease_fence(runner_ns, sid)
    assert probe is not None and probe() is True
    assert SubAgentRunner._fleet_fence_lost(runner_ns, sid) is False

    # Operator takeover: the old holder's probe flips to lost, fail closed.
    store.force_reclaim(
        project,
        ws,
        "ow2",
        expected_lease_id=lease.lease_id,
        expected_generation=lease.generation,
        reason="r1 test takeover",
        authorized_by="operator-1",
        ttl_seconds=30,
    )
    assert probe() is False
    assert SubAgentRunner._fleet_fence_lost(runner_ns, sid) is True


def test_runner_fence_probe_none_without_coordinator(tmp_path: Path) -> None:
    from llm_loop.subagent.runner import SubAgentRunner

    journal, sessions, sid = _journal(tmp_path)
    runner_ns = types.SimpleNamespace(
        _project_coordinator=None,
        _fleet_leases={},
        _tool_journal=journal,
    )
    assert SubAgentRunner._fleet_lease_fence(runner_ns, sid) is None
    assert SubAgentRunner._fleet_fence_lost(runner_ns, sid) is False
