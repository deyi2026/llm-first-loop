"""Task browser mutation must not treat model scope_ref as a Host app identity."""

from __future__ import annotations

from typing import Any, cast

from llm_loop.browser.attestation import AttestationVerdict
from llm_loop.browser.channel_binding import BrowserChannelBindingCoordinator
from llm_loop.core.run_context import current_task_execution
from llm_loop.tools.task_execution import TaskExecutionError
from tests.unit.test_smc_browser_action_v01 import (
    FIXTURES,
    _click_action,
    _stack,
)


def test_task_browser_requires_host_cdp_process_binding_before_any_dispatch(tmp_path):
    perception, receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["base"]],
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    command = _click_action(first, action_id="task-action")
    # Even a model-invented bundle-looking scope_ref cannot mint app authority.
    command["scope_ref"] = "com.google.Chrome"
    token = current_task_execution.set(object())
    try:
        receipt = action.execute("s1", command)
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_binding_unavailable"
    assert len(receipts.list_action("s1", "task-action")) == 1
    assert backend.calls == 0
    assert actuator.calls == []


def test_legacy_browser_action_keeps_existing_dispatch_contract(tmp_path):
    perception, _receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["base"]],
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    assert current_task_execution.get() is None
    receipt = action.execute("s1", _click_action(first, action_id="legacy-action"))
    assert receipt["status"] == "ok"
    assert backend.calls == 2
    assert len(actuator.calls) == 1

# T2: the only permitted Task browser identity comes from two existing Host
# CDP bindings plus fresh OS process attestation, never the model scope_ref.


class _SignedAppLeaseProbe:
    def __init__(self, *, revoke_at: int = 0) -> None:
        self.calls: list[tuple[str, str, bool]] = []
        self.revoke_at = revoke_at

    def authorize_app(self, identity: str, *, verb: str, os_permission_granted: bool) -> None:
        self.calls.append((identity, verb, os_permission_granted))
        if self.revoke_at and len(self.calls) >= self.revoke_at:
            raise TaskExecutionError("task_lease_revoked")


def _attested_task_stack(tmp_path):
    perception, receipts, backend, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    ws = "ws://127.0.0.1:9222/devtools/page/target-1"
    coordinator = BrowserChannelBindingCoordinator()
    coordinator.require_match(
        "browser-uuid", "target-1", ws,
        argv_sha256="a" * 64, verdict="dedicated", checked_at=1.0,
    )
    host = cast(Any, backend)
    mutation = cast(Any, actuator)
    host._binding_coordinator = coordinator
    host._bound_target_id = "target-1"
    host._bound_websocket_url = ws
    host._session = object()
    host.debug_base_url = "http://127.0.0.1:9222"
    host._attest_fn = lambda _url: AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/dedicated", argv_sha256="a" * 64,
    )
    host._http_get_version_dict = lambda _url: {
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/browser-uuid"
    }
    mutation._binding_coordinator = coordinator
    mutation._bound_target_id = ""
    mutation._configured_target_id = ""
    mutation._session = None
    return perception, receipts, backend, actuator, action


def test_task_browser_attested_host_and_exact_signed_app_lease_dispatches(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    command = _click_action(first, action_id="task-attested")
    # Valid semantic scope_ref remains model data, never the signed Host identity.
    lease = _SignedAppLeaseProbe()
    token = current_task_execution.set(lease)
    try:
        receipt = action.execute("s1", command)
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "ok"
    assert len(actuator.calls) == 1
    assert backend.calls == 2
    assert len(lease.calls) == 2  # admission + immediately before physical dispatch
    identity, verb, os_permission = lease.calls[0]
    assert identity.startswith("lfl.cdp.") and len(identity) == len("lfl.cdp.") + 64
    assert identity != command["scope_ref"]
    assert lease.calls == [(identity, "edit", True)] * 2


def test_task_browser_revoke_between_preflight_and_dispatch_fails_closed(tmp_path):
    perception, receipts, _backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    lease = _SignedAppLeaseProbe(revoke_at=2)
    token = current_task_execution.set(lease)
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-revoked"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "failed"
    assert receipt["retry"]["reason"] == "dispatch_authority_lost"
    assert receipt["effect_fence_reason"] == "task_lease_revoked"
    assert actuator.calls == []
    assert [x["status"] for x in receipts.list_action("s1", "task-revoked")] == ["running", "failed"]


def test_task_browser_fresh_os_process_drift_rejected_before_capture(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    host: Any = backend
    host._attest_fn = lambda _url: AttestationVerdict(verdict="dedicated", user_data_dir="/tmp/dedicated", argv_sha256="b" * 64)
    token = current_task_execution.set(_SignedAppLeaseProbe())
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-pid-drift"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_attestation_stale"
    assert backend.calls == 0 and actuator.calls == []


def test_task_browser_new_browser_instance_rejected(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    host: Any = backend
    host._http_get_version_dict = lambda _url: {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/other-uuid"}
    token = current_task_execution.set(_SignedAppLeaseProbe())
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-ws-drift"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_process_changed"
    assert backend.calls == 0 and actuator.calls == []


def test_task_browser_cross_host_channel_mismatch_rejected(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    mutation: Any = actuator
    mutation._binding_coordinator = BrowserChannelBindingCoordinator()
    token = current_task_execution.set(_SignedAppLeaseProbe())
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-cross-host"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_binding_unavailable"
    assert backend.calls == 0 and actuator.calls == []


def test_task_browser_real_profile_never_becomes_task_authority(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    host: Any = backend
    binding = host._binding_coordinator
    # A real/default-profile browser cannot be turned into Task authority,
    # even when the Host policy for legacy actions separately permits it.
    binding._binding = None
    binding.require_match(
        "browser-uuid", "target-1", "ws://127.0.0.1:9222/devtools/page/target-1",
        argv_sha256="a" * 64, verdict="real", checked_at=1.0,
    )
    lease = _SignedAppLeaseProbe()
    token = current_task_execution.set(lease)
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-real-profile"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_browser_host_attestation_unavailable"
    assert lease.calls == [] and backend.calls == 0 and actuator.calls == []


def test_task_browser_missing_signed_app_scope_rejected(tmp_path):
    perception, _receipts, backend, actuator, action = _attested_task_stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    lease = _SignedAppLeaseProbe(revoke_at=1)
    token = current_task_execution.set(lease)
    try:
        receipt = action.execute("s1", _click_action(first, action_id="task-no-app-scope"))
    finally:
        current_task_execution.reset(token)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "task_lease_revoked"
    assert len(lease.calls) == 1 and backend.calls == 0 and actuator.calls == []
