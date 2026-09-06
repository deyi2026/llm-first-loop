from __future__ import annotations

import json
from pathlib import Path

from llm_loop.config import Settings
from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.core.session import Session
from llm_loop.memory.evidence import EvidenceLedgerStore, OwnerScope

_ROOT = Path(__file__).parents[2]
_ORACLE = _ROOT / "tests" / "fixtures" / "evidence_recoverability_r0.json"
_GATE = _ROOT / "tests" / "fixtures" / "evidence_r0_phase7_gate_v1.json"
def _manifest(messages: list[dict]) -> str:
    rows = [
        str(row.get("content") or "")
        for row in messages
        if str(row.get("content") or "").startswith(
            "[上下文注入·Evidence Recovery Manifest·非新指令]"
        )
    ]
    assert len(rows) <= 1
    return rows[0] if rows else ""


def _manifest_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for token in text.replace("\n", " ").split():
        value = token.removeprefix("ref=").rstrip("|,;] )")
        if value.startswith("evidence://v1/"):
            refs.add(value)
    return refs


def test_phase7_gate_map_exactly_covers_frozen_oracle():
    oracle = json.loads(_ORACLE.read_text(encoding="utf-8"))
    gate = json.loads(_GATE.read_text(encoding="utf-8"))
    assert gate["version"] == "R0-PHASE7-GATE-v1"
    assert gate["network_policy"] == "deny"
    assert gate["all_cases_blocking"] is True
    assert [case["id"] for case in gate["cases"]] == [f"R0-{i}" for i in range(1, 13)]
    oracle_by_id = {case["id"]: case for case in oracle["cases"]}
    for case in gate["cases"]:
        assert set(case["covers"]) == set(oracle_by_id[case["id"]]["oracle"])
        assert case["selectors"]
        assert all(selector.startswith("tests/unit/test_evidence") for selector in case["selectors"])


def test_r0_09_provider_projection_switch_keeps_exact_evidence_set(tmp_path):
    from llm_loop.factory import build_engine

    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x.invalid/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        evidence_mode="enforce",
        tool_pipeline_enabled=False,
        history_max_chars=200000,
    )
    engine = build_engine(settings)
    sid = engine.session.create()
    engine.registry.set_session_id(sid)
    evidence_file = tmp_path / "provider-neutral.txt"
    evidence_file.write_text("provider-neutral source evidence", encoding="utf-8")
    result = engine.registry.execute(
        ToolCall(id="r0-9-tool", name="read_file", arguments={"path": str(evidence_file)})
    )
    assert result.evidence_ref

    sess = engine.session.load(sid)
    sess.messages.extend(
        [
            Message(
                role="user",
                content="MINIMAX_RAW_ONLY",
                source=MessageSource.USER,
                metadata={"cache_compacted_for": ["deepseek"]},
            ),
            Message(role="assistant", content="stable", source=MessageSource.SYSTEM),
        ]
    )
    owner = OwnerScope(workspace_id=str(Path.cwd()), session_id=sid)
    ledger = EvidenceLedgerStore(settings.evidence_dir / "ledger")
    refs_before = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    blobs_before = {r.evidence_ref.ref: r.blob_ref.ref for r in ledger.list_recent(owner, limit=100)}

    deepseek = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )
    refs_deepseek = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    minimax = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="minimax/model"
    )
    refs_minimax = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    deepseek_again = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )
    refs_deepseek_again = {r.evidence_ref.ref for r in ledger.list_recent(owner, limit=100)}
    blobs_after = {r.evidence_ref.ref: r.blob_ref.ref for r in ledger.list_recent(owner, limit=100)}

    # Legacy provider-only compaction markers are stale once a concrete model/budget
    # contract is known, so the message is deterministically reopened.
    assert "MINIMAX_RAW_ONLY" in str(deepseek)
    assert "MINIMAX_RAW_ONLY" in str(minimax)
    assert refs_before == refs_deepseek == refs_minimax == refs_deepseek_again
    assert blobs_before == blobs_after
    assert _manifest(deepseek) == _manifest(minimax) == _manifest(deepseek_again) == ""
    md = engine.registry.evidence_recovery_manifest(limit=100)
    md2 = engine.registry.evidence_recovery_manifest(limit=100)
    assert md and _manifest_refs(md) == _manifest_refs(md2) == refs_before


def test_r0_12_non_target_guardrails_and_no_provider_policy(monkeypatch):
    oracle = json.loads(_ORACLE.read_text(encoding="utf-8"))
    gate = json.loads(_GATE.read_text(encoding="utf-8"))
    assert oracle["provider_calls_allowed"] is False
    assert gate["network_policy"] == "deny"
    # Default rollout remains opt-in/off.
    monkeypatch.delenv("EVIDENCE_MODE", raising=False)
    from llm_loop.config import _env_evidence_mode

    assert _env_evidence_mode("EVIDENCE_MODE") == "off"

    # No R0 Action Guard or heuristic support extractor exists in production source.
    production = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (_ROOT / "src" / "llm_loop").rglob("*.py")
    )
    lowered = production.casefold()
    assert "action_guard" not in lowered
    assert "action guard" not in lowered
    assert "extract_supports" not in production

    # No anti-repeat prompt patch was introduced as the fix.
    prompt_text = (_ROOT / "src" / "llm_loop" / "core" / "prompt.py").read_text(
        encoding="utf-8"
    )
    for phrase in ("不要重复查", "不要重复", "勿重复", "重复查"):
        assert phrase not in prompt_text

    # fixed_summary/summary_chain remain inert persistence fields, not loop/build inputs.
    loop_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (_ROOT / "src" / "llm_loop" / "core" / "loop").rglob("*.py")
    )
    assert "fixed_summary" not in loop_text
    assert "summary_chain" not in loop_text
    session = Session(session_id="phase7-static")
    assert session.fixed_summary == ""
    assert session.summary_chain == []
