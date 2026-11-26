"""P1 pressure-aware tool-history fold valve.

Static ``resource_safety_bytes`` valve (append-only mode) rewrites already-sent
mid-history messages whenever pending tool bytes cross ``batch_chars`` -- even
without real provider-visible pressure -- zeroing the prefix cache from the
rewrite point. The pressure-aware valve keeps the hard byte boundary as a
fallback (no pressure signal == legacy static behavior) and folds only on
real measured pressure (anchored view bytes >= budget * safety ratio).
"""

from types import SimpleNamespace

from llm_loop.config import HistoryPolicySettings
from llm_loop.core.episode_history import (
    FoldPressureSignal,
    fold_aware_stable_fp,
    project_active_tool_working_set_with_stats,
)
from llm_loop.core.message import (
    Message,
    MessageSource,
    ToolResultStatus,
)

RAW = 2500
POLICY = HistoryPolicySettings(
    working_set_receipts=True,
    working_set_batch_chars=4096,
    working_set_grace_groups=0,
)


def _assistant(call_id: str) -> Message:
    return Message(
        role="assistant",
        content="continue",
        source=MessageSource.USER,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": "read_file", "arguments": "{}"},
            }
        ],
        model_used="cognilocal/ornith",
        metadata={"answer_origin": "model"},
    )


def _tool(call_id: str, text: str, *, ref: str | None) -> Message:
    metadata = {}
    if ref:
        metadata = {
            "recoverability_status": "recorded",
            "evidence_ref": ref,
            "evidence_representation": "excerpt",
            "evidence_projection_complete": False,
            "evidence_source_label": "read_file:src/x.py",
            "evidence_coverage_label": "source_line:0-200",
        }
    return Message(
        role="tool",
        content=text,
        source=MessageSource.TOOL,
        tool_call_id=call_id,
        status=ToolResultStatus.SUCCESS,
        tool_name="read_file",
        metadata=metadata,
    )


def _messages(n: int) -> list[Message]:
    messages = [Message(role="user", content="task", source=MessageSource.USER)]
    for idx in range(1, n + 1):
        messages.extend(
            [
                _assistant(f"c{idx}"),
                _tool(f"c{idx}", chr(65 + idx % 26) * RAW, ref=f"evidence://v1/{idx}"),
            ]
        )
    return messages


def test_no_real_pressure_keeps_append_only_mid_history():
    """Pending bytes cross batch_chars but anchored-view pressure is absent: no fold."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
        pressure=FoldPressureSignal(chars_total=500_000, budget=1_000_000),
    )

    assert stats.folded_results == 0
    assert stats.fold_triggers == ()
    assert projected[2].content == "B" * RAW  # mid history stays byte-exact
    assert projected[4].content == "C" * RAW


def test_real_pressure_folds_via_resource_safety_valve():
    """Overloaded anchored view folds even in append-only mode: hard safety kept."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
        pressure=FoldPressureSignal(chars_total=980_000, budget=1_000_000),
    )

    assert stats.folded_results == 2
    assert stats.fold_triggers[0].startswith("resource_safety_bytes")
    assert "tool_result_receipt" in projected[2].content


def test_pressure_none_keeps_legacy_static_valve():
    """No pressure signal == legacy static batch valve (regression anchor)."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
    )

    assert stats.folded_results == 2
    assert stats.fold_triggers == ("resource_safety_bytes",)


def test_zero_budget_signal_is_treated_as_no_pressure():
    """A missing/zero budget must not invent pressure; keep append-only."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
        pressure=FoldPressureSignal(chars_total=999_999, budget=0),
    )

    assert stats.folded_results == 0
    assert stats.fold_triggers == ()


def test_fold_trigger_string_carries_measured_scope():
    """Fold evidence must carry the measured chars/budget scope (recoverable)."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
        pressure=FoldPressureSignal(chars_total=980_000, budget=1_000_000),
    )

    trigger = stats.fold_triggers[0]
    assert "chars=" in trigger
    assert "budget=" in trigger


def test_opportunistic_mode_ignores_pressure_parameter():
    """Aggressive mode folds by its own caps regardless of pressure (regression)."""
    messages = _messages(3)
    projected, stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=True,
        pressure=FoldPressureSignal(chars_total=1, budget=1_000_000),
    )

    assert stats.folded_results >= 1


def test_tool_pairing_untouched_by_pressure_aware_valve():
    """Pairing invariant: assistant(tool_calls) and tool(call_id) stay paired."""
    messages = _messages(3)
    projected, _stats = project_active_tool_working_set_with_stats(
        messages,
        policy=POLICY,
        allow_opportunistic_fold=False,
        pressure=FoldPressureSignal(chars_total=980_000, budget=1_000_000),
    )

    assert len(projected) == len(messages)
    for idx, original in enumerate(messages):
        if original.role == "assistant":
            assert projected[idx].tool_calls == original.tool_calls
        if original.role == "tool":
            assert projected[idx].tool_call_id == original.tool_call_id


def test_fold_aware_stable_fp_changes_only_when_folds_present():
    """cache-gate fp must reflect mid-history rewrites (fold-aware composition)."""
    base_fp = "a" * 64

    assert fold_aware_stable_fp(base_fp, None) == base_fp
    no_fold = SimpleNamespace(fold_boundaries=(), fold_triggers=())
    assert fold_aware_stable_fp(base_fp, no_fold) == base_fp

    folded = SimpleNamespace(
        fold_boundaries=(5,),
        fold_triggers=("resource_safety_bytes:chars=980000;budget=1000000",),
    )
    assert fold_aware_stable_fp(base_fp, folded) != base_fp
