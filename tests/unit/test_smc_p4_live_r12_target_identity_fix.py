"""Deterministic RED for the real P4-LIVE R12 target identity boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evals.smc_semantic_logic_p4_live.red_contracts import _fixtures
from llm_loop.browser.action_ref import (
    ActionRefBindingStore,
    ActionRefError,
    ActionRefIssueContext,
    ActionRefIssuer,
    ActionRefResolveContext,
    ActionRefResolver,
)
from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore


def _page(target_id: str) -> dict[str, str]:
    return {
        "id": target_id,
        "type": "page",
        "url": "http://127.0.0.1/",
        "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{target_id}",
    }


def test_r12_real_capture_target_token_binds_same_raw_cdp_target_without_dispatch(
    tmp_path: Path,
) -> None:
    clock = [1000.0]
    session_id = "r12-real-target-session"
    workspace = str(tmp_path.resolve())
    run_generation = "r12-real-target-run"
    perception_store = BrowserPerceptionStore(
        tmp_path / "browser", retention_seconds=60, now_fn=lambda: clock[0]
    )
    binding_store = ActionRefBindingStore(tmp_path / "action_refs", now_fn=lambda: clock[0])
    issuer = ActionRefIssuer(binding_store=binding_store, perception_store=perception_store)
    perception = BrowserPerceptionAdapter(
        store=perception_store,
        action_ref_issuer=issuer,
        action_ref_context_getter=lambda: ActionRefIssueContext(
            workspace_scope=workspace,
            origin_run_generation=run_generation,
        ),
    )
    capture = json.loads(json.dumps(_fixtures()["base"]))
    capture["page_token"] = "target:target-A"
    projection = perception.snapshot(session_id, capture, projection_limit=100)
    action_ref = str(projection["resource_action_ref"])
    resolution = ActionRefResolver(
        binding_store=binding_store,
        perception_store=perception_store,
    ).resolve(
        action_ref,
        expected_kind="resource",
        context=ActionRefResolveContext(
            session_id=session_id,
            workspace_scope=workspace,
            current_run_generation=run_generation,
            run_active=True,
        ),
    )

    ws_calls: list[str] = []
    actuator = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        http_get_json=lambda _url: [_page("target-A")],
        ws_connect=lambda url: ws_calls.append(url),  # type: ignore[arg-type,return-value]
    )
    actuator.bind_observed_target(resolution.browser_target_id_sha256)

    assert actuator.bound_target_id == "target-A"
    assert ws_calls == []


def test_r12_empty_prefixed_target_identity_fails_closed_at_issuance(tmp_path: Path) -> None:
    clock = [1000.0]
    store = BrowserPerceptionStore(
        tmp_path / "browser", retention_seconds=60, now_fn=lambda: clock[0]
    )
    issuer = ActionRefIssuer(
        binding_store=ActionRefBindingStore(
            tmp_path / "action_refs", now_fn=lambda: clock[0]
        ),
        perception_store=store,
    )
    perception = BrowserPerceptionAdapter(
        store=store,
        action_ref_issuer=issuer,
        action_ref_context_getter=lambda: ActionRefIssueContext(
            workspace_scope=str(tmp_path.resolve()),
            origin_run_generation="r12-empty-target-run",
        ),
    )
    capture = json.loads(json.dumps(_fixtures()["base"]))
    capture["page_token"] = "target:"
    with pytest.raises(ActionRefError) as exc:
        perception.snapshot("r12-empty-target-session", capture, projection_limit=100)
    assert exc.value.code == "action_ref_source_unavailable"


def test_r12_nonprefixed_synthetic_page_token_preserves_existing_digest(tmp_path: Path) -> None:
    clock = [1000.0]
    session_id = "r12-synthetic-session"
    workspace = str(tmp_path.resolve())
    run_generation = "r12-synthetic-run"
    store = BrowserPerceptionStore(
        tmp_path / "browser", retention_seconds=60, now_fn=lambda: clock[0]
    )
    bindings = ActionRefBindingStore(tmp_path / "action_refs", now_fn=lambda: clock[0])
    perception = BrowserPerceptionAdapter(
        store=store,
        action_ref_issuer=ActionRefIssuer(binding_store=bindings, perception_store=store),
        action_ref_context_getter=lambda: ActionRefIssueContext(
            workspace_scope=workspace, origin_run_generation=run_generation
        ),
    )
    capture = json.loads(json.dumps(_fixtures()["base"]))
    assert capture["page_token"] == "page-a"
    projection = perception.snapshot(session_id, capture, projection_limit=100)
    resolution = ActionRefResolver(
        binding_store=bindings, perception_store=store
    ).resolve(
        str(projection["resource_action_ref"]),
        expected_kind="resource",
        context=ActionRefResolveContext(
            session_id=session_id,
            workspace_scope=workspace,
            current_run_generation=run_generation,
            run_active=True,
        ),
    )
    assert resolution.browser_target_id_sha256 == hashlib.sha256(b"page-a").hexdigest()
