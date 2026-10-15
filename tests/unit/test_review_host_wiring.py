"""Physical-entry regression: neither Registry nor browser actuator may run unreviewed."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.registry import ToolRegistry
from llm_loop.tools.review_host_admission import HostReviewAdmission, ReviewAdmissionTool
from tests.unit.test_review_host_admission import FakeChildRunner, _repo

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=json.loads((ROOT/"tests/fixtures/smc_browser_perception_v01.json").read_text())["base"]


class _FakeShell:
    name = "execute_command"
    description = "fake, no real shell executed"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}, "workdir": {"type": "string"}}, "required":["command"]}
    def __init__(self):
        self.calls = []
    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ToolResult(status=ToolResultStatus.SUCCESS,content="FAKE_EXEC",tool_call_id="",tool_name=self.name)


class _Backend:
    def __init__(self, raw):
        self.raw = raw
    def capture(self):
        return copy.deepcopy(self.raw)


class _Actuator:
    def __init__(self):
        self.calls=[]
    def dispatch(self, **kwargs):
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True, boundary_events=(), completeness_reasons=("non_exhaustive",),
        )


def _action(snapshot, name, action_id):
    obj=next(x for x in snapshot["objects"] if x.get("attributes",{}).get("name")==name)
    return {
        "schema":"smc.semantic_action.v0.1","domain":"browser",
        "scope_ref":obj["scope_ref"],"action_id":action_id,"verb":"click",
        "target_id":obj["id"],"args":{},"operation_class":"mutate",
        "idempotency_class":"unknown","atomicity_class":"single_dispatch",
        "expected_version":snapshot["snapshot"]["snapshot_id"],
        "version_scope":"object","version_precondition":"required",
    }


def test_registry_preblocks_full_test_before_fake_execute(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    registry=ToolRegistry()
    shell=_FakeShell()
    registry.register(shell)
    host=HostReviewAdmission()
    runner=FakeChildRunner()
    host.attach_runner(runner)
    registry.set_review_admission(host)
    token=current_session_id.set("author-1")
    try:
        args={"command":"pytest -q","workdir":str(repo)}
        blocked=registry.execute(ToolCall(id="c1",name="execute_command",arguments=args))
        assert blocked.status==ToolResultStatus.BLOCKED
        assert blocked.error_type=="E2_REVIEW_ADMISSION"
        assert shell.calls==[]
        unprotected=registry.execute(ToolCall(id="c2",name="execute_command",arguments={"command":"pytest tests/unit/test_x.py -q","workdir":str(repo)}))
        assert unprotected.status==ToolResultStatus.SUCCESS and len(shell.calls)==1
        issue=host.start("author-1","full_test",workdir=str(repo),command="pytest -q")
        runner.answer=f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issue['candidate_sha256']}"
        runner.state="completed"
        assert host.poll("author-1","child-review-1")["qualification"]=="PASS"
        allowed=registry.execute(ToolCall(id="c3",name="execute_command",arguments=args))
        assert allowed.status==ToolResultStatus.SUCCESS and len(shell.calls)==2
        replay=registry.execute(ToolCall(id="c4",name="execute_command",arguments=args))
        assert replay.status==ToolResultStatus.BLOCKED and len(shell.calls)==2
    finally:
        current_session_id.reset(token)


def test_browser_physical_adapter_publication_refuses_before_actuator(tmp_path: Path) -> None:
    raw=copy.deepcopy(FIXTURE)
    for layer in ("dom","ax"):
        button=next(x for x in raw[layer]["nodes"] if x.get("attributes",{}).get("name")=="Submit")
        button["attributes"]["name"]="Publish"
        if layer == "dom":
            button["attributes"]["text"] = "Publish"
    raw["dom"]["nodes"].append({
        "physical_id":"editor","parent_id":"n-root","frame_token":None,
        "kind":"text_field","attributes":{"role":"textbox","value_text":"Full article text"},
        "state":{"exists":True,"visible":True},
    })
    backend=_Backend(raw)
    actuator=_Actuator()
    perception=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path/"perception"))
    adapter_host=HostReviewAdmission()
    runner=FakeChildRunner()
    adapter_host.attach_runner(runner)
    adapter_host.attach_browser_capture(backend.capture)
    adapter=BrowserActionAdapter(
        perception=perception,receipt_store=BrowserActionReceiptStore(tmp_path/"receipts"),
        capture_backend=backend,actuator=actuator,review_authorizer=adapter_host.check_browser,
    )
    first=perception.snapshot("author-1",raw)
    denied=adapter.execute("author-1",_action(first,"Publish","attempt-denied"))
    assert denied["status"]=="rejected"
    assert "review_admission_blocked" in json.dumps(denied)
    assert actuator.calls==[]
    issued=adapter_host.start("author-1","article_publish",target_name="Publish")
    assert issued["accepted"]
    runner.state="completed"
    runner.answer=f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issued['candidate_sha256']}"
    assert adapter_host.poll("author-1","child-review-1")["qualification"]=="PASS"
    allowed=adapter.execute("author-1",_action(first,"Publish","attempt-approved"))
    assert allowed["status"]=="ok" and len(actuator.calls)==1
    denied2=adapter.execute("author-1",_action(first,"Publish","attempt-replayed"))
    assert denied2["status"]=="rejected" and len(actuator.calls)==1


def test_browser_normal_edit_mutation_remains_available(tmp_path: Path) -> None:
    raw=copy.deepcopy(FIXTURE)
    backend=_Backend(raw)
    act=_Actuator()
    p=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path/"p"))
    host=HostReviewAdmission()
    adapter=BrowserActionAdapter(
        perception=p,receipt_store=BrowserActionReceiptStore(tmp_path/"a"),
        capture_backend=backend,actuator=act,review_authorizer=host.check_browser,
    )
    first=p.snapshot("author-1",raw)
    assert adapter.execute("author-1",_action(first,"Submit","non-publication"))["status"]=="ok"
    assert len(act.calls)==1


def test_review_tool_model_never_sets_verdict_itself(tmp_path: Path) -> None:
    repo=_repo(tmp_path)
    host=HostReviewAdmission()
    host.attach_runner(FakeChildRunner())
    tool=ReviewAdmissionTool(host)
    token=current_session_id.set("author-1")
    try:
        res=tool.execute(action="start",kind="full_test",workdir=str(repo),command="pytest -q",verdict="PASS")
        assert res.status == ToolResultStatus.SUCCESS
        data=json.loads(res.content)
        assert data["accepted"] and data["child_id"]
        assert host.check_shell("author-1","pytest -q",str(repo)).blocked
    finally:
        current_session_id.reset(token)


def test_factory_registers_real_host_review_contract(tmp_path: Path) -> None:
    from llm_loop.factory import build_engine
    from tests.unit.test_factory import _settings

    engine = build_engine(_settings(tmp_path))  # type: ignore[arg-type]
    assert "review_admission" in engine.registry.names()
    authority = engine.registry._review_admission
    assert authority is not None
    assert authority._runner is engine.subagent_runner
    assert authority._event_store is not None
    assert authority.check_shell("factory-sid", "pytest -q", str(tmp_path)).blocked
    assert engine.registry.get("review_admission")._authority is authority


def test_semantic_and_operate_real_aliases_share_publication_physical_fence(tmp_path: Path) -> None:
    from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
    from llm_loop.tools.builtin.browser_semantic_operation import (
        BrowserSemanticOperationReceiptStore,
        BrowserSemanticOperationTool,
    )

    raw = copy.deepcopy(FIXTURE)
    for layer in ("dom", "ax"):
        button = next(
            x for x in raw[layer]["nodes"] if x.get("attributes", {}).get("name") == "Submit"
        )
        button["attributes"]["name"] = "Publish"
        if layer == "dom":
            button["attributes"]["text"] = "Publish"
    raw["dom"]["nodes"].append({
        "physical_id": "editor", "parent_id": "n-root", "frame_token": None,
        "kind": "text_field",
        "attributes": {"role": "textbox", "value_text": "Reviewable article content"},
        "state": {"exists": True, "visible": True},
    })
    backend = _Backend(raw)
    actuator = _Actuator()
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    authority = HostReviewAdmission()
    runner = FakeChildRunner()
    authority.attach_runner(runner)
    authority.attach_browser_capture(backend.capture)
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "physical-receipts"),
        capture_backend=backend, actuator=actuator,
        review_authorizer=authority.check_browser,
    )
    semantic = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action,
        session_id_getter=lambda: "author-1",
    )
    operate = BrowserSemanticOperationTool(
        perception=perception, capture_backend=backend, semantic_execute=semantic,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "semantic-receipts"),
        session_id_getter=lambda: "author-1",
    )
    snap = perception.snapshot("author-1", raw)
    target = next(x for x in snap["objects"] if x.get("attributes", {}).get("name") == "Publish")
    low = semantic.execute(verb="click", target_ref=target["grounding_ref"], args={})
    assert "review_admission_blocked" in low.content
    assert actuator.calls == []
    high = operate.execute(do="click", target={"kind": "button", "name": "Publish"})
    assert "review_admission" in high.content or "rejected" in high.content
    assert actuator.calls == []  # neither semantic alias can bypass the Host fence

    issue = authority.start("author-1", "article_publish", target_name="Publish")
    assert issue["accepted"]
    runner.state = "completed"
    runner.answer = (
        f"VERDICT: PASS\nP0=0 P1=0 P2=0\nSHA256: {issue['candidate_sha256']}"
    )
    assert authority.poll("author-1", "child-review-1")["qualification"] == "PASS"
    # A fresh observation produces an exact new action identity; the volatile
    # timestamp is intentionally ignored by the stable editor SHA.
    changed_observation = copy.deepcopy(raw)
    changed_observation["observed_at"] = "2026-10-15T01:02:05Z"
    backend.raw = changed_observation
    snap2 = perception.snapshot("author-1", changed_observation)
    target2 = next(x for x in snap2["objects"] if x.get("attributes", {}).get("name") == "Publish")
    allowed = semantic.execute(verb="click", target_ref=target2["grounding_ref"], args={})
    assert json.loads(allowed.content)["status"] == "ok"
    assert len(actuator.calls) == 1


def test_registry_blocks_high_signal_indirect_command_before_fake_shell(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    registry = ToolRegistry()
    shell = _FakeShell()
    registry.register(shell)
    authority = HostReviewAdmission()
    authority.attach_runner(FakeChildRunner())
    registry.set_review_admission(authority)
    token = current_session_id.set("owner-p0c")
    try:
        for i, command in enumerate((
            "xargs -I{} git push origin main",
            "xargs -I{} python -m pytest -q",
            "pytest -k '' -q",
            "python -m pytest -m '' -q",
        )):
            result = registry.execute(ToolCall(
                id=f"p0c-bypass-{i}",
                name="execute_command",
                arguments={"command": command, "workdir": str(repo)},
            ))
            assert result.status == ToolResultStatus.BLOCKED
            assert result.error_type == "E2_REVIEW_ADMISSION"
            assert not shell.calls
    finally:
        current_session_id.reset(token)


def test_review_admission_is_discoverable_full_and_compact_in_real_factory(
    tmp_path: Path,
) -> None:
    from llm_loop.factory import build_engine
    from tests.unit.test_factory import _settings

    engine = build_engine(_settings(tmp_path))
    for compact in (False, True):
        tool_defs = {item["name"]: item for item in engine.registry.schemas(lazy=compact)}
        assert "execute_command" in tool_defs
        assert "review_admission" in tool_defs
        review = tool_defs["review_admission"]["parameters"]["properties"]
        assert "action" in review and "start" in review["action"]["enum"]
        assert "kind" in review
        assert "command" in review and "workdir" in review
        command = tool_defs["execute_command"]["parameters"]["properties"]
        assert "command" in command and "workdir" in command
    assert engine.registry.get("review_admission")._authority is engine.registry._review_admission
