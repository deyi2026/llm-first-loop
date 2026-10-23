"""Regression: density recalibration must not reset the logical history contract.

The lower half pins the v2 logical-contract comparison semantics directly
(capacity inputs, char-cap selection, scope matching) so a future change to
``llm_loop.core.compaction_contract`` has to be a deliberate decision.
"""
from types import SimpleNamespace

import pytest

from llm_loop.config import HistoryPolicySettings
from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_build.context import BuildDecision
from llm_loop.core.prompt_build.stages.history_pipeline import run_history_pipeline

LABELS = ["minimax/MiniMax-M3.1-Flash-Preview", "glm/glm-5.3",
          "glm/glm-5.3-flash", "deepseek/deepseek-v4-flash", "cognilocal/qwen3.8-flash-next",
          "cognilocal/ornith-ai/Ornith-1.5-35B-A3B-MLX"]


def project(sess, budget, label, *, tokens=184000, events=None):
    pid = label.split("/")[0]
    return run_history_pipeline(
        sess=sess, provider_id=pid, sess_anchor=sess.history_anchors.get(pid, 0),
        max_chars=budget, base=list(sess.messages), system_prompt="",
        filtered_indices=list(range(len(sess.messages))), prefix_len=0,
        resolved_label=label, decision=BuildDecision(budget={
            "model": label, "allowed_input_tokens": tokens,
            "configured_global_budget": None, "provider_budget": None,
            "runtime_override": None,
        }),
        runtime_history_budget=lambda: budget, archive=object(),
        registry=SimpleNamespace(evidence_mode="off"),
        archive_sink_cb=lambda *_args: None, record_action=lambda *_args: None,
        settings=SimpleNamespace(history_policy=HistoryPolicySettings(), exact_duplicate_tool_fold=False),
        cache_monitor=CacheHealthMonitor(),
        event_append=lambda _sid, kind, payload: (events if events is not None else []).append((kind, payload)),
        provider_visible_chars_fn=lambda *_args: 0,
        growth_nudge_kind_fn=lambda *_args, **_kw: None,
        reasoning_tail_fn=lambda *_args, **_kw: 0,
    )


def session():
    return SimpleNamespace(
        session_id="density-incident",
        messages=[Message(role="assistant", content=f"{i}:" + "x" * 1000,
                          source=MessageSource.SYSTEM) for i in range(80)]
        + [Message(role="user", content="archive old sandbox sessions", source=MessageSource.USER)],
        history_anchors={}, history_anchor_scopes={},
    )


@pytest.mark.parametrize("label", LABELS)
def test_density_growth_does_not_reopen_compacted_history(label):
    sess = session()
    project(sess, 12000, label)
    events = []
    project(sess, 12001, label, events=events)
    assert not [p for kind, p in events if kind == "history.compaction_state_reset"]


def test_real_input_capacity_growth_still_reopens_history():
    sess = session()
    project(sess, 12000, LABELS[0])
    events = []
    project(sess, 100000, LABELS[0], tokens=900000, events=events)
    assert any(kind == "history.compaction_state_reset" for kind, _ in events)

def test_mixed_legacy_reset_preserves_valid_v2_markers():
    from llm_loop.core.history import mark_cache_compacted_for
    sess = session()
    project(sess, 12000, LABELS[0])
    pid = "minimax"
    original = [i for i, m in enumerate(sess.messages)
                if pid in m.metadata.get("cache_compacted_for", [])]
    mark_cache_compacted_for(sess.messages[-2], pid, model_ref=LABELS[0], effective_budget=12000)
    events = []
    project(sess, 12001, LABELS[0], events=events)
    assert all(pid in sess.messages[i].metadata.get("cache_compacted_for", []) for i in original)
    reset = next(p for kind, p in events if kind == "history.compaction_state_reset")
    assert reset["msg_seqs"] == [len(sess.messages) - 2]


def test_drift_roundtrip_and_shrink_preserve_history_scope():
    sess = session()
    project(sess, 12000, LABELS[0])
    events = []
    for budget in [12001, 11999, 14000, 10000, 14001]:
        project(sess, budget, LABELS[0], tokens=180000, events=events)
    assert not [kind for kind, _ in events if kind == "history.compaction_state_reset"]


def test_legacy_migration_occurs_only_once():
    from llm_loop.core.history import mark_cache_compacted_for
    sess = session()
    for m in sess.messages[:30]:
        mark_cache_compacted_for(m, "minimax", model_ref=LABELS[0], effective_budget=12000)
    events = []
    project(sess, 12000, LABELS[0], events=events)
    project(sess, 12001, LABELS[0], events=events)
    assert len([kind for kind, _ in events if kind == "history.compaction_state_reset"]) == 1


def test_contract_mutation_does_not_rewrite_marker():
    from llm_loop.core.compaction_contract import contract_from_budget
    from llm_loop.core.history import mark_cache_compacted_for
    contract = contract_from_budget({"allowed_input_tokens": 1000})
    m = session().messages[0]
    mark_cache_compacted_for(m, "minimax", model_ref=LABELS[0], effective_budget=12000,
                            compaction_contract=contract)
    contract["input_tokens"] = 2000
    contract["policy"]["compact_ratio"] = 0.1
    stored = m.metadata["cache_compaction_scope"]["minimax"]["logical_contract"]
    assert stored["input_tokens"] == 1000
    assert stored["policy"]["compact_ratio"] is None


def test_nonzero_anchor_survives_density_recalibration():
    from llm_loop.core.compaction_contract import contract_from_budget
    from llm_loop.core.prompt_build.stages.history_pipeline import _anchor_for_current_contract
    contract = contract_from_budget({"allowed_input_tokens": 184000})
    sess = session()
    sess.history_anchors["minimax"] = 20
    sess.history_anchor_scopes["minimax"] = {
        "version": 2, "model": LABELS[0], "effective_budget": 12000,
        "logical_contract": contract,
    }
    assert _anchor_for_current_contract(
        sess, provider_id="minimax", resolved_label=LABELS[0], sess_anchor=20,
        effective_budget=12001, compaction_contract=contract,
    ) == 20


def test_explicit_char_capacity_and_wire_changes():
    from llm_loop.core.compaction_contract import contract_from_budget, scope_matches
    old = contract_from_budget({"allowed_input_tokens": 1000, "configured_global_budget": 12000})
    scope = {"version": 2, "model": LABELS[0], "effective_budget": 12000, "logical_contract": old}
    small = contract_from_budget({"allowed_input_tokens": 900, "configured_global_budget": 10000})
    assert scope_matches(scope, model=LABELS[0], budget=14000, contract=small)
    larger = contract_from_budget({"allowed_input_tokens": 1000, "configured_global_budget": 14000})
    assert not scope_matches(scope, model=LABELS[0], budget=14000, contract=larger)
    wire = contract_from_budget({"allowed_input_tokens": 1000, "configured_global_budget": 12000},
                                wire_protocol="anthropic")
    assert not scope_matches(scope, model=LABELS[0], budget=12000, contract=wire)


def test_v2_marker_and_scoped_reset_replay_are_exact():
    from llm_loop.core.compaction_contract import contract_from_budget
    from llm_loop.event_log.model import Event
    from llm_loop.event_log.replay import replay_session
    contract = contract_from_budget({"allowed_input_tokens": 184000})
    rows = [
        ("message.appended", {"index": i, "role": "assistant", "content": str(i)})
        for i in range(3)
    ]
    rows += [("message.cache_compacted", {
        "msg_seq": i, "provider_id": "minimax", "marker_version": 2,
        "model": LABELS[0], "effective_budget": 12000, "logical_contract": contract,
    }) for i in range(3)]
    rows += [("history.compaction_state_reset", {"provider_id": "minimax", "msg_seqs": [1]})]
    events = [Event(event_id=str(i), session_id="s", seq=i+1, type=k,
                    ts="2026-10-20T00:00:00Z", payload=p) for i, (k, p) in enumerate(rows)]
    messages = replay_session(events)["messages"]
    assert [i for i, m in enumerate(messages) if "minimax" in m["metadata"].get("cache_compacted_for", [])] == [0, 2]
    assert messages[0]["metadata"]["cache_compaction_scope"]["minimax"]["logical_contract"] == contract


def test_incident_scale_677_messages_do_not_reopen_on_density_roundtrip():
    sess = session()
    sess.messages = [
        Message(role="assistant", content=f"source-{i}:" + "x" * 4000, source=MessageSource.SYSTEM)
        for i in range(677)
    ] + [Message(role="user", content="archive only sandbox sessions", source=MessageSource.USER)]
    original = [(m.role, m.content, m.reasoning_content, m.tool_calls) for m in sess.messages]
    events = []
    project(sess, 447331, LABELS[0], events=events)
    assert any(kind == "history.compaction" for kind, _ in events)
    events.clear()
    for budget in [447332, 626478, 558495, 447331]:
        project(sess, budget, LABELS[0], events=events)
    assert not any(kind == "history.compaction_state_reset" for kind, _ in events)
    assert [(m.role, m.content, m.reasoning_content, m.tool_calls) for m in sess.messages] == original


def _contract(*, policy=None, wire_protocol="openai", **overrides):
    """Build a v2 logical contract from budget info with test-friendly defaults."""
    from llm_loop.core.compaction_contract import contract_from_budget
    info = {"allowed_input_tokens": 1000, "configured_global_budget": 12000,
            "provider_budget": None, "runtime_override": None}
    info.update(overrides)
    return contract_from_budget(info, wire_protocol=wire_protocol, policy=policy)


def _scope(contract, *, version=2, model=None, effective_budget=12000):
    return {"version": version, "model": model or LABELS[0],
            "effective_budget": effective_budget, "logical_contract": contract}


def test_contract_rejects_unusable_capacity_inputs():
    from llm_loop.core.compaction_contract import contract_from_budget
    assert contract_from_budget(None) is None
    assert contract_from_budget("not-a-dict") is None
    assert contract_from_budget({}) is None
    assert contract_from_budget({"allowed_input_tokens": True}) is None
    assert contract_from_budget({"allowed_input_tokens": 0}) is None
    assert contract_from_budget({"allowed_input_tokens": -1}) is None
    assert contract_from_budget({"allowed_input_tokens": "1000"}) is None
    assert contract_from_budget({"allowed_input_tokens": 1000.0}) is None


def test_contract_char_limit_picks_explicit_then_provider_budget():
    assert _contract(runtime_override=5000, provider_budget=8000)["char_limit"] == 5000
    assert _contract(provider_budget=8000)["char_limit"] == 8000
    assert _contract(runtime_override=None, configured_global_budget=None,
                     provider_budget=None)["char_limit"] is None


def test_contract_falsy_explicit_override_suppresses_configured_fallback():
    # Characterization of current semantics: runtime_override=0 is not None, so it
    # wins over configured_global_budget and leaves "no explicit char cap".
    assert _contract(runtime_override=0, configured_global_budget=12000)["char_limit"] is None


def test_contract_records_wire_protocol_and_policy_snapshot():
    policy = SimpleNamespace(compact_ratio=0.5, compress_target_ratio=0.3)
    contract = _contract(policy=policy)
    assert contract["wire_protocol"] == "openai"
    assert contract["policy"]["compact_ratio"] == 0.5
    assert contract["policy"]["compress_target_ratio"] == 0.3
    assert contract["policy"]["head_keep_ratio"] is None
    assert _contract(wire_protocol="anthropic")["wire_protocol"] == "anthropic"


def test_scope_matches_rejects_foreign_and_malformed_scopes():
    from llm_loop.core.compaction_contract import scope_matches
    contract = _contract()
    assert not scope_matches(None, model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches("scope", model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope(contract, model="other/model"),
                             model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope(contract, version=1),
                             model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope("not-a-dict"),
                             model=LABELS[0], budget=12000, contract=contract)


def test_scope_matches_legacy_v1_scope_uses_effective_budget():
    from llm_loop.core.compaction_contract import scope_matches
    legacy = {"version": 1, "model": LABELS[0], "effective_budget": 12000}
    assert scope_matches(legacy, model=LABELS[0], budget=12000, contract=None)
    assert not scope_matches(legacy, model=LABELS[0], budget=12001, contract=None)
    assert not scope_matches(legacy, model=LABELS[0], budget=0, contract=None)
    assert not scope_matches(_scope(_contract()),
                             model=LABELS[0], budget=12000, contract=None)
    broken = {"version": "one", "model": LABELS[0], "effective_budget": 12000}
    assert not scope_matches(broken, model=LABELS[0], budget=12000, contract=None)


def test_scope_matches_treats_input_token_growth_as_reopen():
    from llm_loop.core.compaction_contract import scope_matches
    scope = _scope(_contract(allowed_input_tokens=1000))
    assert scope_matches(scope, model=LABELS[0], budget=12000,
                         contract=_contract(allowed_input_tokens=1000))
    assert scope_matches(scope, model=LABELS[0], budget=12000,
                         contract=_contract(allowed_input_tokens=900))
    assert not scope_matches(scope, model=LABELS[0], budget=12000,
                             contract=_contract(allowed_input_tokens=1001))


def test_scope_matches_char_cap_shrink_preserves_and_removal_reopens():
    from llm_loop.core.compaction_contract import scope_matches
    capped = _scope(_contract())
    uncapped = _contract(runtime_override=None, configured_global_budget=None,
                          provider_budget=None)
    # dropping an explicit char cap is an expansion -> reopen retired history
    assert not scope_matches(capped, model=LABELS[0], budget=12000, contract=uncapped)
    # gaining a char cap where none existed is a shrink -> keep retired history
    assert scope_matches(_scope(uncapped), model=LABELS[0], budget=12000,
                         contract=_contract(configured_global_budget=12000))


def test_scope_matches_rejects_bool_and_invalid_char_caps():
    from llm_loop.core.compaction_contract import scope_matches
    contract = _contract()
    assert not scope_matches(_scope({**contract, "input_tokens": True}),
                             model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope({**contract, "char_limit": -1}),
                             model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope({**contract, "char_limit": True}),
                             model=LABELS[0], budget=12000, contract=contract)
    assert not scope_matches(_scope(contract), model=LABELS[0], budget=12000,
                             contract={**contract, "char_limit": True})


def test_scope_matches_policy_change_counts_as_contract_change():
    from llm_loop.core.compaction_contract import scope_matches
    scope = _scope(_contract(policy=SimpleNamespace(compact_ratio=0.5)))
    assert scope_matches(scope, model=LABELS[0], budget=12000,
                         contract=_contract(policy=SimpleNamespace(compact_ratio=0.5)))
    assert not scope_matches(scope, model=LABELS[0], budget=12000,
                             contract=_contract(policy=SimpleNamespace(compact_ratio=0.9)))
