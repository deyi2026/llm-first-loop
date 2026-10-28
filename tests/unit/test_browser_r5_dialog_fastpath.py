"""R5: dialog-open fast paths for observation and gating.

A synchronous JS dialog (alert/confirm/prompt/beforeunload) freezes the
renderer: every full capture can only burn its recv timeout (~20s live)
before degrading, so the pre-R5 dialog flow paid 2x20s (operate grounding +
adapter pre-observation) exactly when the model needed the ONE verb that can
free the page. These tests pin the three fast paths:

1. CdpBrowserMutationActuator.dialog_state() - the read-only probe (closed
   shape, open detail mapping + 300-char message cap, zero fabrication on
   missing params, zero persistence, zero CDP commands).
2. browser_perceive snapshot - dialog open => explicit blocked_by_dialog
   receipt with ZERO capture calls (vision=evidence included); dialog
   closed => the original capture path byte-identical; probe errors fall
   through to the original path.
3. browser_operate _ground_page - dialog open => ground on the session's
   latest persisted world with ZERO captures, or the deterministic
   dialog_open_no_prior_world contract error.
4. BrowserActionAdapter - verb=dialog + probe open => light mode with ZERO
   pre-captures (probe failures still reject); click / closed dialogs still
   capture; the pre-existing capture-failure light-mode fallback stays
   intact (regression pin).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationContractError,
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_DIALOG_OPEN = {
    "schema": "smc.browser_dialog_state.v0.1",
    "open": True,
    "dialog": {"type": "alert", "message": "LFL-ALERT", "default_prompt": None},
}
_DIALOG_CLOSED = {"schema": "smc.browser_dialog_state.v0.1", "open": False, "dialog": None}


# ---------------------------------------------------------------------------
# Section 1: the read-only probe on the real mutation actuator.
# ---------------------------------------------------------------------------

_MUT_TARGET = {
    "id": "target-1",
    "type": "page",
    "url": "http://127.0.0.1/a",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
}


def _attest_dedicated(url: str):  # noqa: ANN001, ANN202 - S3b test stub
    from llm_loop.browser.attestation import AttestationVerdict

    return AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
    )


class _QuietWs:
    """Fake CDP websocket: records sends, never answers (quiet channel)."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.requests.append(json.loads(payload))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        raise TimeoutError("no pending message")

    def close(self) -> None:
        self.closed = True


def _actuator(ws: _QuietWs) -> CdpBrowserMutationActuator:
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id=_MUT_TARGET["id"],
        http_get_json=lambda url: json.loads(json.dumps([_MUT_TARGET])),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


def test_probe_closed_state_shape_and_zero_cdp_commands() -> None:
    ws = _QuietWs()
    actuator = _actuator(ws)
    state = actuator.dialog_state()
    assert state == {
        "schema": "smc.browser_dialog_state.v0.1",
        "open": False,
        "dialog": None,
    }
    # observation surface only: no session => no drain, and never a CDP command
    assert ws.requests == []


def test_probe_open_state_maps_detail_and_caps_message_at_300(tmp_path: Path) -> None:
    ws = _QuietWs()
    actuator = _actuator(ws)
    files_before = sorted(p.name for p in tmp_path.rglob("*"))
    # white-box seeding, same style the B5 lifecycle tests use for _dialog_open
    actuator._absorb_state_events(
        [
            {
                "method": "Page.javascriptDialogOpening",
                "params": {
                    "type": "prompt",
                    "message": "M" * 512,
                    "defaultPrompt": "yes",
                    "url": "http://127.0.0.1/a",
                },
            }
        ]
    )
    state = actuator.dialog_state()
    assert state["open"] is True
    assert state["dialog"] == {
        "type": "prompt",
        "message": "M" * 300,
        "default_prompt": "yes",
        "url": "http://127.0.0.1/a",
    }
    assert len(state["dialog"]["message"]) <= 300
    # B5: the dialog message is page content - nothing new lands on disk
    # (autouse fixtures may create their own tmp entries; only the DELTA matters)
    files_after = sorted(p.name for p in tmp_path.rglob("*"))
    assert files_after == files_before
    assert ws.requests == []


def test_probe_open_state_never_fabricates_missing_fields() -> None:
    actuator = _actuator(_QuietWs())
    actuator._absorb_state_events(
        [{"method": "Page.javascriptDialogOpening", "params": {}}]
    )
    state = actuator.dialog_state()
    assert state["open"] is True
    assert state["dialog"] == {
        "type": "unknown",
        "message": "",
        "default_prompt": None,
        "url": None,
    }


# ---------------------------------------------------------------------------
# Section 2: browser_perceive snapshot fast path.
# ---------------------------------------------------------------------------


class _ForbiddenBackend:
    """Capture must NOT run while the dialog blocks the page (any call fails)."""

    def __init__(self) -> None:
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        raise AssertionError("capture must not run while a dialog blocks the page")


class _FixtureBackend:
    def __init__(self) -> None:
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(FIXTURES["base"]))


def _perceive_tool(tmp_path: Path, backend: Any, dialog_state: Any) -> BrowserPerceiveTool:
    return BrowserPerceiveTool(
        adapter=BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p")),
        backend=backend,
        session_id_getter=lambda: "s1",
        dialog_state_getter=dialog_state,
    )


def test_perceive_snapshot_blocked_by_dialog_returns_facts_with_zero_capture(
    tmp_path: Path,
) -> None:
    backend = _ForbiddenBackend()
    tool = _perceive_tool(tmp_path, backend, lambda: _DIALOG_OPEN)
    result = tool.execute(action="snapshot")
    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["observation_status"] == "blocked_by_dialog"
    assert payload["blocked_reason"] == "dialog_open"
    assert payload["dialog"] == {
        "type": "alert",
        "message": "LFL-ALERT",
        "default_prompt": None,
    }
    assert payload["objects"] == []
    assert payload["degraded"] is False
    # a frozen page has no new observation: no fabricated versions
    assert "version" not in payload
    assert "world_version" not in payload
    assert "do=dialog" in payload["guidance"]
    assert backend.calls == 0


def test_perceive_snapshot_vision_evidence_reports_unavailable_no_fake_image(
    tmp_path: Path,
) -> None:
    backend = _ForbiddenBackend()
    tool = _perceive_tool(tmp_path, backend, lambda: _DIALOG_OPEN)
    result = tool.execute(action="snapshot", vision="evidence")
    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["vision"] == {"status": "capture_unavailable", "reason": "dialog_open"}
    assert payload["observation_status"] == "blocked_by_dialog"
    assert backend.calls == 0


def test_perceive_probe_error_falls_through_to_capture(tmp_path: Path) -> None:
    backend = _FixtureBackend()

    def broken_probe() -> dict[str, Any]:
        raise RuntimeError("probe channel dead")

    tool = _perceive_tool(tmp_path, backend, broken_probe)
    result = tool.execute(action="snapshot")
    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["objects"]  # the original snapshot path ran
    assert backend.calls == 1


def test_perceive_closed_dialog_receipt_matches_original_on_key_fields(
    tmp_path: Path,
) -> None:
    # pre-R5 tool (probe unwired) vs R5 tool with a closed-dialog probe. A
    # live snapshot receipt is not byte-stable across captures (per-capture
    # snapshot ids / grounding refs), so the contract is pinned on the
    # stable key fields: identical key set, identical projection facts, and
    # none of the fast-path-only keys.
    reference_backend = _FixtureBackend()
    reference = BrowserPerceiveTool(
        adapter=BrowserPerceptionAdapter(
            store=BrowserPerceptionStore(tmp_path / "ref")
        ),
        backend=reference_backend,
        session_id_getter=lambda: "s1",
    )
    backend = _FixtureBackend()
    tool = _perceive_tool(tmp_path / "r5", backend, lambda: _DIALOG_CLOSED)
    reference_result = reference.execute(action="snapshot")
    result = tool.execute(action="snapshot")
    assert result.status == reference_result.status
    reference_payload = json.loads(reference_result.content)
    payload = json.loads(result.content)
    assert sorted(payload) == sorted(reference_payload)
    for fast_path_key in ("observation_status", "blocked_reason", "dialog", "guidance", "degraded"):
        assert fast_path_key not in payload
    assert payload["action"] == reference_payload["action"] == "snapshot"
    assert payload["objects_projection"] == reference_payload["objects_projection"]

    def _scope_shape(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # scope refs carry a per-capture salt (scope_ref AND parent_scope_ref);
        # compare kind + lineage generations only
        keys = ("kind", "runtime_generation", "page_generation", "document_generation")
        return [{k: fact.get(k) for k in keys} for fact in facts]

    assert _scope_shape(payload["scope_facts"]) == _scope_shape(
        reference_payload["scope_facts"]
    )
    # object ids are per-capture salts and projection order is not stable
    # across captures; the stable identity is the (kind, name) MULTISET
    assert sorted(
        (o["kind"], (o.get("attributes") or {}).get("name")) for o in payload["objects"]
    ) == sorted(
        (o["kind"], (o.get("attributes") or {}).get("name"))
        for o in reference_payload["objects"]
    )
    # content_sha256 embeds per-capture salts too (ids/refs); the stable
    # snapshot facts are schema/domain/completeness and the object count
    assert payload["snapshot"]["schema"] == reference_payload["snapshot"]["schema"]
    assert payload["snapshot"]["domain"] == reference_payload["snapshot"]["domain"]
    assert payload["snapshot"]["completeness"] == reference_payload["snapshot"]["completeness"]
    assert len(payload["objects"]) == len(reference_payload["objects"])
    assert backend.calls == 1
    assert reference_backend.calls == 1


# ---------------------------------------------------------------------------
# Section 3: browser_operate _ground_page fast path.
# ---------------------------------------------------------------------------


class _DialogHandlingActuator:
    """Stub: dialog dispatch acknowledges and unfreezes the renderer."""

    def __init__(self, backend: Any) -> None:
        self.backend = backend
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        self.backend.dialog_open = False
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


class _FrozenUntilHandledBackend:
    """Renderer held by a modal: capture while dialog_open is a test failure
    (live: it burns the full recv timeout); after the handle it recovers."""

    def __init__(self) -> None:
        self.dialog_open = True
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if self.dialog_open:
            raise AssertionError("capture must not run while a dialog blocks the page")
        return json.loads(json.dumps(FIXTURES["base"]))

    def probe_page_target(self) -> dict[str, Any]:
        return {"target_id": "TARGET-1", "url": "http://127.0.0.1:8903/", "type": "page"}


def _operate_stack(tmp_path: Path, backend: Any, actuator: Any, dialog_state: Any):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
        dialog_state_probe=dialog_state,
    )
    execute = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action, session_id_getter=lambda: "s1"
    )
    tool = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    if dialog_state is not None:
        tool.attach_dialog_state_probe(dialog_state)
    return perception, action, tool


def test_ground_page_dialog_open_grounds_on_latest_world_zero_capture(
    tmp_path: Path,
) -> None:
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, _, tool = _operate_stack(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])  # the prior world

    ref, meta = tool._ground_page("s1", {"kind": "page"})

    assert ref == first["resource_ref"]
    assert meta == {}
    assert backend.calls == 0  # no capture attempt at all


def test_ground_page_dialog_open_without_prior_world_contract_error(
    tmp_path: Path,
) -> None:
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)
    _, _, tool = _operate_stack(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    # empty store: no prior world to ground against -> deterministic contract
    # error, never a fabricated world
    with pytest.raises(BrowserSemanticOperationContractError, match="dialog_open_no_prior_world"):
        tool._ground_page("s1", {"kind": "page"})
    assert backend.calls == 0


def test_ground_page_closed_dialog_and_probe_error_keep_original_path(
    tmp_path: Path,
) -> None:
    backend = _FixtureBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, _, tool = _operate_stack(tmp_path, backend, actuator, lambda: _DIALOG_CLOSED)
    first = perception.snapshot("s1", FIXTURES["base"])
    ref, meta = tool._ground_page("s1", {"kind": "page"})
    # original path: a FRESH capture grounds the page (per-capture resource
    # ref, not the stale first-snapshot ref), exactly one capture paid
    assert ref.startswith("grounding://browser/v0.1/")
    assert ref != first["resource_ref"]
    assert meta.get("resource_ref") == ref
    assert backend.calls == 1

    def broken_probe() -> dict[str, Any]:
        raise RuntimeError("probe channel dead")

    backend2 = _FixtureBackend()
    actuator2 = _DialogHandlingActuator(backend2)
    perception2, _, tool2 = _operate_stack(tmp_path / "b", backend2, actuator2, broken_probe)
    perception2.snapshot("s1", FIXTURES["base"])
    ref2, meta2 = tool2._ground_page("s1", {"kind": "page"})
    assert ref2.startswith("grounding://browser/v0.1/")
    assert meta2.get("resource_ref") == ref2
    assert backend2.calls == 1


def test_operate_dialog_end_to_end_pays_one_capture_total(tmp_path: Path) -> None:
    """Goals B + C together: with the probe wired to BOTH the operate tool and
    the adapter, a frozen do=dialog chain captures exactly once (the post
    dispatch observation after the handle) instead of the pre-R5 three."""
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)

    def probe() -> dict[str, Any]:
        return {
            "schema": "smc.browser_dialog_state.v0.1",
            "open": backend.dialog_open,
            "dialog": {"type": "alert", "message": "LFL-ALERT"},
        }

    perception, _, tool = _operate_stack(tmp_path, backend, actuator, probe)
    first = perception.snapshot("s1", FIXTURES["base"])  # the prior world

    result = tool.execute(do="dialog", action="accept")
    assert result.status.value == "success", result.content[:1500]
    payload = json.loads(result.content)
    assert payload["status"] == "completed", result.content[:1500]
    assert [call["verb"] for call in actuator.calls] == ["dialog"]
    assert first["resource_ref"]
    # grounding capture skipped + adapter pre-capture skipped; only the
    # post-dispatch observation (dialog already handled) captured once
    assert backend.calls == 1


# ---------------------------------------------------------------------------
# Section 4: BrowserActionAdapter pre-observation fast path.
# ---------------------------------------------------------------------------


def _page_scope(first: dict[str, Any]) -> dict[str, Any]:
    return next(f for f in first["scope_facts"] if f.get("kind") == "page")


def _dialog_action(first: dict[str, Any], *, action_id: str = "act-dialog-fp-1") -> dict[str, Any]:
    page_scope = _page_scope(first)
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": page_scope["scope_ref"],
        "action_id": action_id,
        "verb": "dialog",
        "target_id": page_scope["scope_ref"],
        "args": {"action": "accept"},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "resource",
        "version_precondition": "required",
    }


def _adapter(tmp_path: Path, backend: Any, actuator: Any, dialog_state: Any):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    adapter = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
        dialog_state_probe=dialog_state,
    )
    return perception, adapter


def test_adapter_dialog_verb_open_dialog_zero_pre_capture_light_mode(
    tmp_path: Path,
) -> None:
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])

    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-dialog-0001"))

    assert result["status"] == "ok"
    assert result["pre_observation_mode"] == "lightweight_probe"
    assert result["before_version"] == first["snapshot"]["snapshot_id"]
    assert [call["verb"] for call in actuator.calls] == ["dialog"]
    # zero captures while frozen; the single capture is the post-dispatch one
    assert backend.calls == 1


def test_adapter_dialog_probe_failure_falls_through_to_capture(tmp_path: Path) -> None:
    backend = _FixtureBackend()
    actuator = _DialogHandlingActuator(backend)

    def broken_probe() -> dict[str, Any]:
        raise RuntimeError("probe channel dead")

    perception, adapter = _adapter(tmp_path, backend, actuator, broken_probe)
    first = perception.snapshot("s1", FIXTURES["base"])
    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-fallth-0001"))
    assert result["status"] == "ok"
    assert "pre_observation_mode" not in result  # full observation path
    assert backend.calls == 2  # pre-dispatch + post-dispatch


def test_adapter_click_verb_with_open_dialog_still_captures(tmp_path: Path) -> None:
    backend = _FixtureBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = next(
        obj
        for obj in first["objects"]
        if (obj.get("attributes") or {}).get("name") == "Submit"
    )
    click = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": "act-fp-click-0001",
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }
    result = adapter.execute("s1", click)
    assert result["status"] == "ok"
    assert backend.calls == 2  # the fast path is dialog-verb only
    assert [call["verb"] for call in actuator.calls] == ["click"]


def test_adapter_dialog_closed_dialog_still_captures(tmp_path: Path) -> None:
    backend = _FixtureBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_CLOSED)
    first = perception.snapshot("s1", FIXTURES["base"])
    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-closed-0001"))
    assert result["status"] == "ok"
    assert "pre_observation_mode" not in result
    assert backend.calls == 2


def test_adapter_fast_path_probe_target_failure_still_rejects(tmp_path: Path) -> None:
    class _NoProbeBackend(_ForbiddenBackend):
        def probe_page_target(self) -> dict[str, Any]:
            raise RuntimeError("probe dead")

    backend = _NoProbeBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])
    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-probef-0001"))
    assert result["status"] == "rejected"
    assert "pre_dispatch_observation_failed:dialog_open_fast_path" in result["retry"]["reason"]
    assert "lightweight_probe_failed:RuntimeError" in result["retry"]["reason"]
    assert actuator.calls == []


def test_adapter_fast_path_without_probe_capability_still_rejects(tmp_path: Path) -> None:
    class _BareBackend(_ForbiddenBackend):
        pass  # no probe_page_target at all

    backend = _BareBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])
    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-bare-0001"))
    assert result["status"] == "rejected"
    assert "lightweight_probe_unavailable" in result["retry"]["reason"]
    assert actuator.calls == []


# ---------------------------------------------------------------------------
# Section 5/6: regression pins - the timeout-paid light-mode fallback stays.
# ---------------------------------------------------------------------------


class _StructurallyFailingBackend:
    """Live shape of a frozen renderer: capture degrades structurally, the
    browser-process probe channel stays alive (pre-R5 light-mode entry)."""

    def __init__(self) -> None:
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        raise RuntimeError(
            "capture_channel_degraded[mode=timeout]; CDP observation timed out; "
            "session kept (dialog-capable); error_type=TimeoutError"
        )

    def probe_page_target(self) -> dict[str, Any]:
        return {"target_id": "TARGET-1", "url": "http://127.0.0.1:8903/", "type": "page"}


class _PlainAckActuator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def test_regression_capture_failure_light_mode_fallback_unchanged_dialog(
    tmp_path: Path,
) -> None:
    """Probe NOT wired (default): a structurally failing capture still falls
    back to the light-mode probe for verb=dialog, unchanged from pre-R5."""
    backend = _StructurallyFailingBackend()
    actuator = _PlainAckActuator()
    perception, adapter = _adapter(tmp_path, backend, actuator, None)
    first = perception.snapshot("s1", FIXTURES["base"])
    result = adapter.execute("s1", _dialog_action(first, action_id="act-reg-lm-0001"))
    assert result["status"] == "ok"
    assert result["pre_observation_mode"] == "lightweight_probe"
    # the doomed pre-capture was still attempted (and paid) once, plus the
    # honest post-dispatch attempt - unchanged from pre-R5
    assert backend.calls == 2
    assert [call["verb"] for call in actuator.calls] == ["dialog"]


def test_regression_navigate_light_mode_fallback_unchanged(tmp_path: Path) -> None:
    backend = _StructurallyFailingBackend()
    actuator = _PlainAckActuator()
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])
    page_scope = _page_scope(first)
    navigate = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": page_scope["scope_ref"],
        "action_id": "act-reg-nav-0001",
        "verb": "navigate",
        "target_id": page_scope["scope_ref"],
        "args": {"url": "http://127.0.0.1:8903/"},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "resource",
        "version_precondition": "required",
    }
    # even with an OPEN dialog probe, navigate must not take the R5 fast path
    result = adapter.execute("s1", navigate)
    assert result["status"] == "ok"
    assert result["pre_observation_mode"] == "lightweight_probe"
    assert backend.calls >= 1
    assert [call["verb"] for call in actuator.calls] == ["navigate"]


def test_dialog_action_enum_rejected_before_any_cdp_command() -> None:
    """REVISE P2-3：actuator 边界只接受 accept|dismiss，其它值零 CDP 拒绝。"""
    ws = _QuietWs()
    actuator = _actuator(ws)
    with pytest.raises(RuntimeError, match="invalid_argument"):
        actuator.dispatch(verb="dialog", physical_target=None, args={"action": "maybe"})
    assert ws.requests == []
    assert actuator.dialog_state()["open"] is False


def test_ground_page_non_capture_failure_propagates_instead_of_stale_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REVISE P2-1：回退只对 capture_channel_degraded 生效，其它异常必须透传。"""
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, _, tool = _operate_stack(tmp_path, backend, actuator, lambda: _DIALOG_CLOSED)
    perception.snapshot("s1", FIXTURES["base"])  # a prior world exists to fall back to

    def _boom(_session_id: str) -> dict[str, Any]:
        raise RuntimeError("perception boom")

    monkeypatch.setattr(tool, "_snapshot", _boom)
    with pytest.raises(RuntimeError, match="perception boom"):
        tool._ground_page("s1", {"kind": "page"})


def test_attach_dialog_probes_wires_both_tools() -> None:
    """REVISE P2-4：工厂接线单点必须同时挂到观察面与门控面。"""
    from llm_loop.factory import _attach_dialog_probes

    class _Sink:
        def __init__(self) -> None:
            self.probe: Any = None

        def attach_dialog_state_probe(self, probe: Any) -> None:
            self.probe = probe

    class _Actuator:
        def dialog_state(self) -> dict[str, Any]:
            return _DIALOG_CLOSED

    actuator = _Actuator()
    perceive, operate = _Sink(), _Sink()
    _attach_dialog_probes(perceive, operate, actuator)
    assert perceive.probe is not None and operate.probe is not None
    assert perceive.probe() == _DIALOG_CLOSED
    assert operate.probe.__self__ is actuator




def test_probe_state_clears_on_javascript_dialog_closed() -> None:
    """REVISE P1-1 (2026-10-28): navigating away dismisses the dialog inside
    Chrome and emits Page.javascriptDialogClosed without this host sending any
    handle. The tracked flag must follow Chrome, otherwise every later perceive
    keeps reporting blocked_by_dialog for a dialog that no longer exists."""
    actuator = _actuator(_QuietWs())
    actuator._absorb_state_events(
        [{"method": "Page.javascriptDialogOpening", "params": {"type": "alert", "message": "m"}}]
    )
    assert actuator.dialog_state()["open"] is True

    actuator._absorb_state_events(
        [{"method": "Page.javascriptDialogClosed", "params": {"result": False, "userInput": ""}}]
    )

    assert actuator.dialog_state() == {
        "schema": "smc.browser_dialog_state.v0.1",
        "open": False,
        "dialog": None,
    }


def test_adapter_light_mode_dialog_bundle_miss_is_recorded_on_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REVISE P1-2 (2026-10-28): the light-mode + dialog bundle miss degrades to
    an empty mechanical floor; that degradation must be visible on the receipt
    instead of being swallowed silently."""
    backend = _FrozenUntilHandledBackend()
    actuator = _DialogHandlingActuator(backend)
    perception, adapter = _adapter(tmp_path, backend, actuator, lambda: _DIALOG_OPEN)
    first = perception.snapshot("s1", FIXTURES["base"])

    real_load = perception.store.load_snapshot_bundle

    def flaky_load(session_id: str, snapshot_id: str) -> dict[str, Any]:
        if snapshot_id == first["snapshot"]["snapshot_id"] and not getattr(
            flaky_load, "tripped", False
        ):
            flaky_load.tripped = True  # type: ignore[attr-defined]
            raise ValueError("bundle evicted between probe and pre-load")
        return real_load(session_id, snapshot_id)

    monkeypatch.setattr(perception.store, "load_snapshot_bundle", flaky_load)

    result = adapter.execute("s1", _dialog_action(first, action_id="act-fp-bundle-miss-0001"))

    # The empty floor can only end in the deterministic page-target rejection,
    # and the receipt must say WHY the bundle was empty.
    assert result["status"] == "rejected"
    assert result["retry"]["reason"] == "navigate_page_target_mismatch"
    assert result["completeness"]["reasons"] == [
        "navigate_page_target_mismatch",
        "snapshot_bundle_unavailable:ValueError",
    ]
