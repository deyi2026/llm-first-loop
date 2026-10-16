"""No-provider Host admission / real executor boundary for one direct-child canary."""

# ruff: noqa: SIM117  # Layered context managers preserve budget/transport cancellation order.

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest

from llm_loop.core.run_context import (
    current_model_label,
    current_run_generation,
    current_session_id,
    current_tool_discovery_scope,
    current_workspace_root,
)
from llm_loop.core.session import SessionStore
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.resources import task_budget_subagent_profile as policy
from llm_loop.resources.task_budget_admin_once import (
    AdminOnceEventPlan,
    prepare_admin_once_event_budget,
)
from llm_loop.resources.task_budget_dispatch import (
    bind_task_budget,
    checked_provider_attempt,
    checked_tool_dispatch,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry
from llm_loop.web.task_budget_canary import _read_operator_config

URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
SPAWN = {
    "task": "Calculate 31415+27182; answer CANARY_SUM=58597",
    "requires": {"tools": []},
    "inherit": False,
}


@contextmanager
def _runtime(sid: str, gen: str, workspace: str):
    tokens = [
        (current_session_id, current_session_id.set(sid)),
        (current_run_generation, current_run_generation.set(gen)),
        (current_workspace_root, current_workspace_root.set(workspace)),
        (current_model_label, current_model_label.set(policy.MODEL_REF)),
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def _authorized(tmp_path: Path):
    events = EventStore(tmp_path / "events", enabled=True)
    sid = "canary-root"
    text = "operator approved diagnostic"
    event = events.append_durable_human_message(
        sid,
        build_message_payload(
            index=0, role="user", source="user", content=text,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    now = time.time()
    plan = AdminOnceEventPlan(
        session_id=sid, workspace_scope=exact_workspace_scope(str(tmp_path)),
        authorization_id="a" * 32,
        valid_from_epoch_s=now-5, valid_until_epoch_s=now+250,
        event_store=events, budget_store=TaskBudgetStore(tmp_path/"ledger"),
        profile=policy.PROFILE,
    )
    execution = prepare_admin_once_event_budget(
        plan=plan, event=event, session_id=sid, workspace_root=str(tmp_path),
        run_generation="canary-root-generation", user_text=text,
        ingress=issue_ingress("web"),
    )
    return events, plan, execution


def _attempt():
    return checked_provider_attempt(
        provider_id="glm", model_id="glm-5.3",
        wire_protocol="openai", target_url=URL,
    )


def test_exact_operator_config_and_no_default_activation(tmp_path):
    now=time.time()
    config = {
        "schema": policy.CONFIG_SCHEMA,
        "profile": policy.PROFILE,
        "authorization_id": "c" * 32,
        "session_id": "canary-root",
        "workspace_root": str(tmp_path),
        "model_ref": policy.MODEL_REF,
        "valid_from_epoch_s": now,
        "valid_until_epoch_s": now+250,
    }
    path=tmp_path/"operator-canary.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    assert _read_operator_config(path) == config
    for key, val in (
        ("provider_proxy", "http://127.0.0.1:4444"),
        ("allowed_tools", ["execute_command"]),
        ("profile", "web-glm-one-physical-attempt-v3"),
    ):
        changed=dict(config)
        changed[key]=val
        path.write_text(json.dumps(changed))
        with pytest.raises(TaskBudgetDeniedError):
            _read_operator_config(path)
    path.write_text(json.dumps(config))
    path.chmod(0o644)
    with pytest.raises(TaskBudgetDeniedError):
        _read_operator_config(path)
    assert policy.capabilities().allowed_tools == policy.PARENT_TOOLS
    assert policy.capabilities().allow_subagents
    assert not policy.capabilities().allow_wake


def test_one_web_root_durable_approval_and_child_shared_budget(tmp_path):
    _,plan,root=_authorized(tmp_path)
    assert plan.budget_id.startswith("webadminonce-")
    row=plan.budget_store.read(plan.budget_id)
    assert row["grant"]["profile"] == policy.PROFILE
    assert row["grant"]["limits"]["physical_attempts"] == 8
    assert row["grant"]["limits"]["tool_invocations"] == 3
    child_id="subagent_123abcefa123"
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)):
        with bind_task_budget(root), bind_isolated_provider_transport(IsolatedTransportProfile()):
            with _attempt():
                pass
            with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_member_not_authorized"):
                root.bind_direct_canary_child(child_id,"gen-child")
            with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
                child=root.bind_direct_canary_child(child_id,"gen-child")
            with checked_tool_dispatch("subagent_result", arguments={"child_id":child_id,"wait_seconds":2}):
                pass
            with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_tool_once_limit"):
                with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
                    pytest.fail("a second spawn must not physically dispatch")
    with _runtime(child_id,"gen-child",str(tmp_path)):
        with bind_task_budget(child),bind_isolated_provider_transport(IsolatedTransportProfile()):
            with _attempt():
                pass
            with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_child_tools_denied"):
                child.assert_tool_allowed("spawn_subagent")
    row=plan.budget_store.read(plan.budget_id)
    assert len(row["members"]) == 2
    assert row["members"][child_id]["session_id"] == child_id
    assert row["members"][child_id]["parent_id"] == plan.budget_id
    report=plan.budget_store.report(plan.budget_id)
    assert report["used_or_reserved"]["physical_attempts"] == 2
    assert report["used_or_reserved"]["tool_invocations"] == 2


@pytest.mark.parametrize("args", [
    {"task":"x"},
    {"task":"x","requires":{"tools":["read_file"]}},
    {"task":"x","requires":{"tools":[]},"inherit":True},
    {"task":"x","requires":{"tools":[]},"model":"other/model"},
    {"task":"x","requires":{"tools":[]},"context":"hidden context"},
    {"task":"x","requires":{"tools":[]},"acceptance":["extra"]},
    {"task":"x","requires":{"tools":[]},"extra":"stealth"},
    {"task":"x","requires":{"tools":[]},"inherit":1},
])
def test_invalid_spawn_never_reserves_or_dispatches(tmp_path,args):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_"):
            with checked_tool_dispatch("spawn_subagent",arguments=args):
                pytest.fail("invalid arguments crossed Host dispatch")
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["tool_invocations"] == 0


@pytest.mark.parametrize("name,args",[
    ("execute_command",{"cmd":"true"}),
    ("agent_message",{"target_id":"subagent_x","content":"unsafe"}),
    ("schedule",{"delay":"1"}),
    ("subagent_result",{"child_id":"subagent_foreign","wait_seconds":0}),
    ("subagent_result",{"child_id":"subagent_x","wait_seconds":20}),
])
def test_unqualified_parent_tools_and_foreign_result_denied(tmp_path,name,args):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with pytest.raises(TaskBudgetDeniedError):
            with checked_tool_dispatch(name,arguments=args):
                pytest.fail("forbidden tool executed")
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["tool_invocations"] == 0


def test_child_exact_generation_and_provider_are_fenced(tmp_path):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
            child=root.bind_direct_canary_child("subagent_abcab12","g-child")
    with _runtime("subagent_abcab12","incorrect",str(tmp_path)):
        with pytest.raises(TaskBudgetDeniedError,match="active_run_generation_mismatch"):
            with bind_task_budget(child):
                pytest.fail("generation drift crossed physical Provider")
    with _runtime("unrelated","g-child",str(tmp_path)):
        with pytest.raises(TaskBudgetDeniedError,match="active_session_scope_mismatch"):
            with bind_task_budget(child):
                pytest.fail("session drift crossed physical Provider")
    with _runtime("subagent_abcab12","g-child",str(tmp_path)):
        with bind_task_budget(child),bind_isolated_provider_transport(IsolatedTransportProfile()):
            with pytest.raises(TaskBudgetDeniedError,match="signed_provider_identity_mismatch"):
                with checked_provider_attempt(provider_id="other",model_id="glm-5.3",wire_protocol="openai",target_url=URL):
                    pytest.fail("wrong target")
            with pytest.raises(TaskBudgetDeniedError,match="signed_model_identity_mismatch"):
                with checked_provider_attempt(provider_id="glm",model_id="other",wire_protocol="openai",target_url=URL):
                    pytest.fail("wrong model")
            with pytest.raises(TaskBudgetDeniedError):
                child.assert_tool_allowed("subagent_result")
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"] == 0


def test_failed_provider_call_cannot_be_retried_even_under_global_quota(tmp_path):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root),bind_isolated_provider_transport(IsolatedTransportProfile()):
        with pytest.raises(RuntimeError,match="provider unavailable"), _attempt():
            raise RuntimeError("provider unavailable")
        with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_provider_retry_denied"):
            with _attempt():
                pytest.fail("second transport physically sent")
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"] == 1


def test_parent_stop_revokes_child_and_does_not_affect_unrelated_budget(tmp_path):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
            child=root.bind_direct_canary_child("subagent_abcab12","g-child")
        root.request_stop(reason="owner_only_cancel")
        with pytest.raises(TaskBudgetDeniedError,match="local_run_stop_requested"):
            with _attempt():
                pytest.fail("stopped parent Provider")
    with _runtime("subagent_abcab12","g-child",str(tmp_path)):
        with bind_task_budget(child, cleanup_scope=True):
            with pytest.raises(TaskBudgetDeniedError,match="budget_not_active"):
                with _attempt():
                    pytest.fail("late child transport sent")
    assert plan.budget_store.read(plan.budget_id)["phase"] == "stop_requested"


class _OfflineFakeGLM:
    provider="glm"
    model="glm-5.3"
    def __init__(self):
        self.responses=0
        self.scopes=[]
        self.owner_ids=[]

    def chat(self,messages,tools,**kwargs):
        del messages,kwargs
        from llm_loop.resources.task_budget_dispatch import active_task_budget
        b=active_task_budget()
        assert b is not None and b.member.ingress_kind=="subagent"
        assert b.member.session_id.startswith("subagent_")
        self.owner_ids.append(b.member.session_id)
        self.scopes.append([x.get("function",{}).get("name") for x in tools])
        assert not tools
        with _attempt():
            self.responses+=1
            return LLMResponse(
                content="CANARY_SUM=58597",tool_calls=[],provider="glm"
            )


def test_real_background_child_runner_binds_own_budget_member_no_provider(tmp_path):
    events,plan,root=_authorized(tmp_path)
    sessions=SessionStore(tmp_path/"sessions",event_store=events)
    llm=_OfflineFakeGLM()
    runner=SubAgentRunner(
        llm=cast(LLMClient,llm),registry=ToolRegistry(),session_store=sessions,
        max_iterations=2,llm_resolver=lambda ref: cast(LLMClient,llm),
    )
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with bind_isolated_provider_transport(IsolatedTransportProfile()):
            with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
                spawn=runner.start(
                    SPAWN["task"],depth=0,
                    inherit=False,model=policy.MODEL_REF,required_tools=[],
                    max_rounds=2,
                )
            assert spawn["accepted"],spawn
            assert spawn["tool_scope"]==""
            ok,why,snap=runner.result_current(str(spawn["child_id"]),wait_seconds=3)
            assert ok,why
            assert snap["state"]=="completed",snap
            assert snap["result"].final_answer=="CANARY_SUM=58597"
            with checked_tool_dispatch("subagent_result",arguments={"child_id":spawn["child_id"],"wait_seconds":0}):
                pass
    assert llm.responses==1
    assert llm.scopes==[[]]
    assert llm.owner_ids==[spawn["child_id"]]
    row=plan.budget_store.read(plan.budget_id)
    assert len(row["members"])==2
    assert row["members"][spawn["child_id"]]["run_generation"]==snap["generation"]
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"]==1


def test_old_profiles_remain_zero_tool_and_no_child(tmp_path):
    from llm_loop.resources.task_budget_knowledge_profile import (
        capabilities as knowledge_capabilities,
    )
    from llm_loop.resources.task_budget_positive_authority import capabilities as old_capabilities
    assert not old_capabilities().allow_subagents
    assert old_capabilities().allowed_tools == frozenset()
    assert not knowledge_capabilities().allow_subagents
    k_tools = knowledge_capabilities().allowed_tools
    assert k_tools is not None and "spawn_subagent" not in k_tools


def test_web_host_pins_new_profile_and_root_tool_visibility(
    build_test_engine, tmp_path, monkeypatch,
):
    from llm_loop.core.loop.runner import BackgroundRunner
    from llm_loop.web import build_app
    from llm_loop.web import task_budget_canary as web_canary
    from llm_loop.web.task_budget_canary import bind_web_canary

    engine,_fake=build_test_engine([])
    workspace=tmp_path/"operator-workspace"
    workspace.mkdir()
    engine.set_workspace(str(workspace),"direct-child-test")
    sid=engine.session.create(model_override=policy.MODEL_REF)
    engine.runner=BackgroundRunner(engine)
    engine._event_store=EventStore(tmp_path/"boot-events",enabled=True)
    cfg={
        "schema":policy.CONFIG_SCHEMA,
        "profile":policy.PROFILE,
        "authorization_id":"f"*32,
        "session_id":sid,
        "workspace_root":str(workspace),
        "model_ref":policy.MODEL_REF,
        "valid_from_epoch_s":time.time()-2,
        "valid_until_epoch_s":time.time()+290,
    }
    path=tmp_path/"pinned-canary.json"
    path.write_text(json.dumps(cfg),encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setattr(web_canary,"business_config_snapshot",
                        lambda service: {"LFL_TASK_BUDGET_WEB_CANARY_CONFIG":str(path)})
    app=build_app(engine=engine)
    pinned=app.state.task_budget_web_canary
    assert isinstance(pinned.plan,AdminOnceEventPlan)
    assert pinned.plan.profile==policy.PROFILE
    assert pinned.plan.budget_store.directory.name=="task_budget_subagent_canary"
    assert engine._task_budget_restricted_session_id==sid
    prior=current_tool_discovery_scope.get()
    with bind_web_canary(pinned):
        assert current_tool_discovery_scope.get()==policy.PARENT_TOOLS
    assert current_tool_discovery_scope.get()==prior
    assert not list(pinned.plan.budget_store.directory.glob("budget-*.json"))


def test_forged_second_child_member_rejected_before_physical_dispatch(tmp_path):
    _,plan,root=_authorized(tmp_path)
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
            first=root.bind_direct_canary_child("subagent_abc123","generation-child-A")
            with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_member_not_authorized"):
                root.bind_direct_canary_child("subagent_def456","generation-child-B")
    row=plan.budget_store.read(plan.budget_id)
    assert len(row["members"])==2
    assert row["members"][first.member.member_id]["session_id"]=="subagent_abc123"
    assert "subagent_def456" not in row["members"]


def test_result_two_poll_limit_and_no_foreign_child_read(tmp_path):
    _,plan,root=_authorized(tmp_path)
    cid="subagent_abcd4567"
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
            root.bind_direct_canary_child(cid,"g-child")
        for wait in (0,3):
            with checked_tool_dispatch("subagent_result",arguments={"child_id":cid,"wait_seconds":wait}):
                pass
        with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_tool_once_limit"):
            with checked_tool_dispatch("subagent_result",arguments={"child_id":cid}):
                pytest.fail("third polling forbidden")
        with pytest.raises(TaskBudgetDeniedError,match="subagent_canary_direct_child_required"):
            with checked_tool_dispatch("subagent_result",arguments={"child_id":"subagent_foreign"}):
                pytest.fail("cross-parent read forbidden")
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["tool_invocations"]==3


class _HoldingBudgetedFakeGLM(_OfflineFakeGLM):
    def __init__(self):
        super().__init__()
        self.entered=threading.Event()
        self.release=threading.Event()
        self.after_stop_denied=False

    def chat(self,messages,tools,**kwargs):
        del messages,tools,kwargs
        with _attempt():
            self.entered.set()
            assert self.release.wait(timeout=6.0)
        self.responses+=1
        return LLMResponse(content="late attempted answer",tool_calls=[],provider="glm")


def test_cancel_root_generation_cascades_child_with_shared_budget(tmp_path):
    events,plan,root=_authorized(tmp_path)
    sessions=SessionStore(tmp_path/"sessions",event_store=events)
    llm=_HoldingBudgetedFakeGLM()
    runner=SubAgentRunner(
        llm=cast(LLMClient,llm),registry=ToolRegistry(),session_store=sessions,
        max_iterations=2,llm_resolver=lambda ref: cast(LLMClient,llm),
    )
    with _runtime(plan.session_id,"canary-root-generation",str(tmp_path)),bind_task_budget(root):
        with bind_isolated_provider_transport(IsolatedTransportProfile()):
            with checked_tool_dispatch("spawn_subagent",arguments=SPAWN):
                started=runner.start(
                    SPAWN["task"],depth=0,model=policy.MODEL_REF,
                    inherit=False,required_tools=[],max_rounds=2,
                )
            assert started["accepted"],started
            cid=started["child_id"]
            assert llm.entered.wait(timeout=4.0)
            assert runner.cancel_parent(plan.session_id,run_generation="wrong-run") == 0
            assert not runner._cancel_events[cid].is_set()
            cancelled=runner.cancel_parent(
                plan.session_id,run_generation="canary-root-generation"
            )
            assert cancelled==1
            root.request_stop(reason="user_stopped_exact_root")
            llm.release.set()
            ok,why,final=runner.result_current(cid,wait_seconds=3)
            assert ok,why
            assert final["state"] in {"cancelled","failed"},final
            with pytest.raises(TaskBudgetDeniedError,match="local_run_stop_requested"):
                with _attempt():
                    pytest.fail("root late provider effect")
    assert llm.responses==1
    assert plan.budget_store.read(plan.budget_id)["phase"]=="stop_requested"
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["physical_attempts"]==1


def test_operator_setup_requires_explicit_direct_profile_and_no_proxy(
    monkeypatch, tmp_path,
):
    """The operator script may CREATE a future config, never implicitly enable it."""
    import sys
    from types import SimpleNamespace

    from scripts import task_budget_admin_once_setup as setup

    workspace=tmp_path/"workspace"
    workspace.mkdir()
    created=[]
    session=SimpleNamespace(
        create=lambda: (created.append("created") or "new-dedicated-web-session"),
        exists=lambda sid: sid=="pre-existing-web-session",
    )
    engine=SimpleNamespace(
        session=session,
        workspace_root=str(workspace),
        _event_store=SimpleNamespace(enabled=True),
        runner=SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(setup,"build_engine",lambda settings: engine)
    monkeypatch.setattr(setup,"load_settings",lambda: object())
    target=tmp_path/"new-direct-config.json"
    monkeypatch.setattr(sys,"argv",["operator_setup",
        "--profile","direct-subagent",
        "--output",str(target),"--ttl-seconds","300"])
    assert setup.main()==0
    cfg=_read_operator_config(target)
    assert cfg["schema"]==policy.CONFIG_SCHEMA
    assert cfg["profile"]==policy.PROFILE
    assert cfg["session_id"]=="new-dedicated-web-session"
    assert created==["created"]
    assert cfg["model_ref"]==policy.MODEL_REF
    assert cfg["valid_until_epoch_s"]-cfg["valid_from_epoch_s"]<=3600
    assert target.stat().st_mode & 0o077 == 0

    bad=tmp_path/"must-not-exist.json"
    monkeypatch.setattr(sys,"argv",["operator_setup",
        "--profile","direct-subagent","--provider-proxy","http://127.0.0.1:6152",
        "--output",str(bad)])
    with pytest.raises(SystemExit) as exc:
        setup.main()
    assert exc.value.code==2
    assert not bad.exists()


def test_operator_setup_default_keeps_one_attempt_profile(monkeypatch,tmp_path):
    import sys
    from types import SimpleNamespace

    from scripts import task_budget_admin_once_setup as setup

    workspace=tmp_path/"workspace"
    workspace.mkdir()
    engine=SimpleNamespace(
        session=SimpleNamespace(
            create=lambda:"legacy-web-session",
            exists=lambda sid:False,
        ),
        workspace_root=str(workspace),
        _event_store=SimpleNamespace(enabled=True),
        runner=SimpleNamespace(enabled=True),
    )
    monkeypatch.setattr(setup,"build_engine",lambda _:engine)
    monkeypatch.setattr(setup,"load_settings",lambda:object())
    target=tmp_path/"old-default.json"
    monkeypatch.setattr(sys,"argv",["operator_setup","--output",str(target)])
    assert setup.main()==0
    config=_read_operator_config(target)
    assert config["schema"]=="web-task-budget-admin-once/v1"
    assert "profile" not in config
    assert "allowed_tools" not in config


def test_real_registry_spawn_and_result_tool_reaches_zero_tool_budgeted_child(tmp_path):
    """Real physical Registry -> SpawnTool -> Runner and Registry -> ResultTool.

    Previous positive test called runner.start directly. It never exercised
    the SpawnSubAgentTool 'requires.tools=[]' conversion boundary.
    """
    import re

    from llm_loop.core.message import ToolCall, ToolResultStatus
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool
    from llm_loop.tools.builtin.subagent_result import SubAgentResultTool

    events, plan, root = _authorized(tmp_path)
    sessions = SessionStore(tmp_path / "sessions", event_store=events)
    llm = _OfflineFakeGLM()
    registry = ToolRegistry()
    runner = SubAgentRunner(
        llm=cast(LLMClient, llm),
        registry=registry,
        session_store=sessions,
        max_iterations=3,
        llm_resolver=lambda ref: cast(LLMClient, llm),
    )
    registry.register(SpawnSubAgentTool(runner))
    registry.register(SubAgentResultTool(runner))
    with _runtime(plan.session_id, "canary-root-generation", str(tmp_path)):
        with bind_task_budget(root), bind_isolated_provider_transport(IsolatedTransportProfile()):
            start = registry.execute(ToolCall(
                id="real-registry-spawn", name="spawn_subagent", arguments=SPAWN
            ))
            assert start.status == ToolResultStatus.SUCCESS, start.content
            match = re.search(r"child_id=(subagent_[0-9a-f]+)", start.content)
            assert match, start.content
            result = registry.execute(ToolCall(
                id="real-registry-result", name="subagent_result",
                arguments={"child_id": match.group(1), "wait_seconds": 3},
            ))
            assert result.status == ToolResultStatus.SUCCESS, result.content
            assert "CANARY_SUM=58597" in result.content
    assert llm.responses == 1
    row = plan.budget_store.read(plan.budget_id)
    assert len(row["members"]) == 2
    report = plan.budget_store.report(plan.budget_id)
    assert report["used_or_reserved"]["physical_attempts"] == 1
    assert report["used_or_reserved"]["tool_invocations"] == 2


def test_spawn_tool_preserves_explicit_empty_vs_omitted_tools_without_provider():
    """Only explicit requires.tools=[] produces a hard zero-tool child scope."""
    from types import SimpleNamespace

    from llm_loop.core.message import ToolResultStatus
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    class _RecordingRunner:
        def __init__(self):
            self.registry = SimpleNamespace(names=lambda: ["wait"])
            self.kwargs = []

        def start(self, **kwargs):
            self.kwargs.append(kwargs)
            return {"accepted": False, "state": "refused", "detail": "no worker launched"}

    fake_runner = _RecordingRunner()
    tool = SpawnSubAgentTool(fake_runner)
    for kw in (
        {"task": "zero tools", "requires": {"tools": []}},
        {"task": "legacy omitted"},
        {"task": "nonempty", "requires": {"tools": ["wait"]}},
    ):
        result = tool.execute(**kw)
        assert result.status == ToolResultStatus.FAILURE
    assert [row["required_tools"] for row in fake_runner.kwargs] == [
        [], None, ["wait"]
    ]


def test_real_registry_invalid_spawn_fails_closed_before_child_reservation(tmp_path):
    """Physical Registry must not create any child for a malformed scoped call."""
    from llm_loop.core.message import ToolCall, ToolResultStatus
    from llm_loop.tools.builtin.spawn_subagent import SpawnSubAgentTool

    events, plan, root = _authorized(tmp_path)
    llm = _OfflineFakeGLM()
    registry = ToolRegistry()
    runner = SubAgentRunner(
        llm=cast(LLMClient, llm),
        registry=registry,
        session_store=SessionStore(tmp_path / "sessions", event_store=events),
        llm_resolver=lambda _: cast(LLMClient, llm),
    )
    registry.register(SpawnSubAgentTool(runner))
    with _runtime(plan.session_id, "canary-root-generation", str(tmp_path)):
        with bind_task_budget(root):
            result = registry.execute(ToolCall(
                id="forbidden-child-tools", name="spawn_subagent",
                arguments={"task": "unauthorized", "requires": {"tools": ["read_file"]}},
            ))
            assert result.status == ToolResultStatus.BLOCKED, result.content
            assert "subagent_canary_child_must_have_zero_tools" in result.content
    assert llm.responses == 0
    assert not runner._handles
    assert plan.budget_store.report(plan.budget_id)["used_or_reserved"]["tool_invocations"] == 0
