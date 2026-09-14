from __future__ import annotations

import json
import math
from pathlib import Path

from llm_loop.core.loop.engine_services.token_budget import (
    ProjectionDensityTracker,
    reserve_history_after_tools,
)


def test_cold_start_density_is_configured_fallback_and_token_authority_is_external():
    tracker = ProjectionDensityTracker()
    d = tracker.decision("glm", "glm-5.3", "openai", fallback_chars_per_token=0.6)
    assert d.chars_per_token == 0.6
    assert d.source == "configured_fallback"
    assert d.samples == 0


def test_tool_schema_is_reserved_in_tokens_exactly_once_before_char_projection():
    result = reserve_history_after_tools(
        allowed_input_tokens=184_000,
        pre_tool_history_budget_chars=552_000,
        tool_schema_chars=24_881,
        projection_chars_per_token=3.0,
    )
    assert result.tool_schema_reserve_tokens == math.ceil(24_881 / 3.0)
    assert result.history_token_budget == 184_000 - result.tool_schema_reserve_tokens
    assert result.projected_history_chars == math.floor(result.history_token_budget * 3.0)
    assert result.effective_history_budget_chars == result.projected_history_chars


def test_explicit_history_char_cap_can_only_reduce_token_projected_char_cap():
    result = reserve_history_after_tools(
        allowed_input_tokens=184_000,
        pre_tool_history_budget_chars=50_000,
        tool_schema_chars=24_881,
        projection_chars_per_token=3.0,
    )
    assert result.history_token_budget == 184_000 - math.ceil(24_881 / 3.0)
    assert result.projected_history_chars > 50_000
    assert result.effective_history_budget_chars == 50_000


def test_density_requires_min_samples_and_cannot_jump_from_one_hot_window():
    tracker = ProjectionDensityTracker()
    key = ("glm", "glm-5.3", "openai")
    for _ in range(tracker.min_samples - 1):
        tracker.observe(*key, provider_visible_chars=33_000, prompt_tokens=10_000)
    before = tracker.decision(*key, fallback_chars_per_token=0.6)
    assert before.chars_per_token == 0.6
    assert before.source == "configured_fallback"

    tracker.observe(*key, provider_visible_chars=33_000, prompt_tokens=10_000)
    first = tracker.decision(*key, fallback_chars_per_token=0.6)
    assert first.samples == tracker.min_samples
    assert first.source == "observed_lower_bound"
    assert 0.6 < first.chars_per_token <= 0.75  # bounded +25% first upward step


def test_density_tightens_immediately_on_lower_evidence_but_raises_with_hysteresis():
    tracker = ProjectionDensityTracker()
    key = ("glm", "glm-5.3", "openai")
    high = 0.6
    for _ in range(24):
        tracker.observe(*key, provider_visible_chars=34_000, prompt_tokens=10_000)
        high = tracker.decision(*key, fallback_chars_per_token=0.6).chars_per_token
    assert high > 1.0

    # Low chars/token means more tokens per char, so safety requires an immediate decrease.
    low = high
    for _ in range(8):
        tracker.observe(*key, provider_visible_chars=12_000, prompt_tokens=10_000)
        low = tracker.decision(*key, fallback_chars_per_token=0.6).chars_per_token
    assert low < high


def _golden_ratios() -> list[float]:
    root = Path(__file__).resolve().parents[2]
    golden = root / "tools/cache_attribution/fixtures/golden/51da0a7a.golden.jsonl"
    ratios: list[float] = []
    for line in golden.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("record_type") != "request_attribution":
            continue
        sizes = row.get("context_sizes") or {}
        chars = sizes.get("provider_visible_chars")
        tokens = row.get("tokens_in")
        if isinstance(chars, int) and chars > 0 and isinstance(tokens, int) and tokens > 0:
            ratios.append(chars / tokens)
    return ratios


def test_frozen_glm_replay_density_is_deterministic_and_conservative():
    ratios = _golden_ratios()
    assert len(ratios) == 220

    def replay() -> tuple[float, int, str]:
        tracker = ProjectionDensityTracker()
        d = tracker.decision("glm", "glm-5.3", "openai", fallback_chars_per_token=0.6)
        for ratio in ratios:
            tracker.observe(
                "glm",
                "glm-5.3",
                "openai",
                provider_visible_chars=int(round(ratio * 1_000_000)),
                prompt_tokens=1_000_000,
            )
            d = tracker.decision("glm", "glm-5.3", "openai", fallback_chars_per_token=0.6)
        return d.chars_per_token, d.samples, d.source

    a = replay()
    b = replay()
    assert a == b
    # Full frozen workload is ~3.34 chars/token; lower-bound bridge must stay below that,
    # while materially relaxing the old 0.6 fallback after enough evidence.
    assert 2.0 < a[0] < 3.34
    assert a[1] == 220
    assert a[2] == "observed_lower_bound"

    # Qualification replay: token authority stays 184K while the char projector adapts.
    tracker = ProjectionDensityTracker()
    projected: list[int] = []
    for ratio in ratios:
        d = tracker.decision(
            "glm", "glm-5.3", "openai", fallback_chars_per_token=0.6
        )
        reserve = reserve_history_after_tools(
            allowed_input_tokens=184_000,
            pre_tool_history_budget_chars=int(184_000 * d.chars_per_token),
            tool_schema_chars=24_881,
            projection_chars_per_token=d.chars_per_token,
        )
        projected.append(reserve.effective_history_budget_chars)
        tracker.observe(
            "glm",
            "glm-5.3",
            "openai",
            provider_visible_chars=int(round(ratio * 1_000_000)),
            prompt_tokens=1_000_000,
        )
    final_density = tracker.decision(
        "glm", "glm-5.3", "openai", fallback_chars_per_token=0.6
    )
    final_reserve = reserve_history_after_tools(
        allowed_input_tokens=184_000,
        pre_tool_history_budget_chars=int(184_000 * final_density.chars_per_token),
        tool_schema_chars=24_881,
        projection_chars_per_token=final_density.chars_per_token,
    )
    assert projected[:8] == [85_518] * 8
    assert sum(value > 85_519 for value in projected) == 212
    assert final_reserve.history_token_budget == 174_496
    assert final_reserve.tool_schema_reserve_tokens == 9_504
    assert final_reserve.effective_history_budget_chars == 456_827


def test_density_surface_state_is_lru_bounded():
    tracker = ProjectionDensityTracker(max_surfaces=8)
    for idx in range(9):
        tracker.observe(
            "p", f"m{idx}", "openai", provider_visible_chars=30_000, prompt_tokens=10_000
        )
    first = tracker.decision("p", "m0", "openai", fallback_chars_per_token=0.6)
    newest = tracker.decision("p", "m8", "openai", fallback_chars_per_token=0.6)
    assert first.samples == 0
    assert newest.samples == 1
