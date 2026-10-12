from __future__ import annotations

from scripts.evidence.r11.long_session_stress import (
    CODES,
    STRESS_BUDGET,
    paired_gates,
    per_mode_gates,
    prepare_sources,
    scenario,
)


def _base(mode: str) -> dict:
    return {
        "mode": mode,
        "turn_count": 12,
        "turn_correct": 12,
        "final_all_codes": True,
        "api_requests": 20,
        "tools_count_values": [31 if mode == "off" else 35],
        "budget_values": [STRESS_BUDGET],
        "models": ["deepseek/deepseek-v4-flash"],
        "cache_hit_ratios": [0.2, 0.8] + [0.85] * 18,
        "postwarm_median_hit_ratio": 0.85,
        "prefix_cliff_count": 0,
        "unexplained_cache_boundary_backjumps": 0,
        "context_compressed_count": 4 if mode == "off" else 2,
        "max_compression_streak": 2,
        "max_compression_events_between_requests": 1,
        "physical_read_file_count": 12 if mode == "off" else 10,
        "physical_repeated_source_paths": 2 if mode == "off" else 0,
        "tool_protocol_errors": 0,
    }


def test_r11_sources_and_scenario_are_fresh_and_no_anti_repeat_instruction() -> None:
    hashes = prepare_sources()
    assert len(hashes) == 10
    assert len(set(hashes.values())) == 10
    rows = scenario()
    assert len(rows) == 12
    text = "\n".join(str(row["message"]) for row in rows).lower()
    assert all(code in {token for row in rows for token in row["expect"]} for code in CODES)
    for banned in ("do not reread", "never repeat", "不要重读", "禁止重读", "不要重复"):
        assert banned not in text


def test_r11_per_mode_gates_allow_compression_but_reject_unexplained_structure_drift() -> None:
    report = _base("enforce")
    assert all(per_mode_gates(report).values())
    report["unexplained_cache_boundary_backjumps"] = 1
    assert per_mode_gates(report)["no_unexplained_boundary_backjump"] is False


def test_r11_paired_gates_measure_physical_reads_not_declared_fallbacks() -> None:
    off = _base("off")
    enforce = _base("enforce")
    assert all(paired_gates(off, enforce).values())
    enforce["physical_repeated_source_paths"] = 3
    assert paired_gates(off, enforce)["enforce_physical_repeats_le_off"] is False
