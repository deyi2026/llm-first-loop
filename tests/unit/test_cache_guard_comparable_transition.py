from __future__ import annotations

from llm_loop.cache_guard.guard import PromptGuard


def _messages(extra: str = "") -> list[dict]:
    out = [{"role": "system", "content": "sys"}]
    if extra:
        out.append({"role": "user", "content": extra})
    return out


def _check(
    guard: PromptGuard,
    *,
    round_no: int,
    stable_fp: str,
    cache_epoch: int = 3,
    compact_epoch: int = 7,
    extra: str = "",
):
    return guard.check(
        session_id="s",
        system_text="sys",
        messages=_messages(extra),
        tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}],
        run_round=round_no,
        provider="glm",
        model="glm-5.3",
        stable_prefix_fp=stable_fp,
        cache_prefix_epoch=cache_epoch,
        compaction_epoch=compact_epoch,
    )


def test_comparable_absolute_hit_drop_is_regression(tmp_path) -> None:
    guard = PromptGuard(audit_file=tmp_path / "guard.jsonl")
    _check(guard, round_no=1, stable_fp="same")
    guard.record_result("s", 30_000, 28_000, provider="glm", model="glm-5.3")
    _check(guard, round_no=2, stable_fp="same", extra="x")
    guard.record_result("s", 32_000, 20_000, provider="glm", model="glm-5.3")

    health = guard.snapshot("s")["cache_health"]
    assert health["status"] == "regression"
    assert health["comparable_transition"] is True
    assert health["absolute_hit_delta"] == -8_000

    decision = _check(guard, round_no=3, stable_fp="same", extra="xy")
    assert decision.verdict == "WARN"
    assert decision.rule == "cache_hit_regression"


def test_changed_combined_prefix_is_warmup_not_regression(tmp_path) -> None:
    guard = PromptGuard(audit_file=tmp_path / "guard.jsonl")
    _check(guard, round_no=1, stable_fp="system-plus-tools-a")
    guard.record_result("s", 30_000, 28_000, provider="glm", model="glm-5.3")
    _check(guard, round_no=2, stable_fp="system-plus-tools-b", extra="x")
    guard.record_result("s", 32_000, 10_000, provider="glm", model="glm-5.3")

    health = guard.snapshot("s")["cache_health"]
    assert health["status"] == "warmup"
    assert health["reason"] == "stable_prefix_changed"
    assert health["comparable_transition"] is False


def test_compaction_epoch_change_is_warmup_not_regression(tmp_path) -> None:
    guard = PromptGuard(audit_file=tmp_path / "guard.jsonl")
    _check(guard, round_no=5, stable_fp="same", compact_epoch=7)
    guard.record_result("s", 33_955, 29_888, provider="glm", model="glm-5.3")
    _check(guard, round_no=6, stable_fp="same", compact_epoch=8, extra="x")
    guard.record_result("s", 19_432, 9_280, provider="glm", model="glm-5.3")

    health = guard.snapshot("s")["cache_health"]
    assert health["status"] == "warmup"
    assert health["reason"] == "compaction_epoch_changed"
    assert health["comparable_transition"] is False


def test_comparable_absolute_hit_non_decrease_is_healthy(tmp_path) -> None:
    guard = PromptGuard(audit_file=tmp_path / "guard.jsonl")
    _check(guard, round_no=1, stable_fp="same")
    guard.record_result("s", 30_000, 28_000, provider="glm", model="glm-5.3")
    _check(guard, round_no=2, stable_fp="same", extra="x")
    guard.record_result("s", 32_000, 29_000, provider="glm", model="glm-5.3")

    health = guard.snapshot("s")["cache_health"]
    assert health["status"] == "healthy"
    assert health["absolute_hit_delta"] == 1_000


def test_fallback_cache_shape_is_optional_duck_host_contract() -> None:
    from types import SimpleNamespace

    from llm_loop.core.loop.engine_services.fallback import FallbackService

    missing = FallbackService(SimpleNamespace())  # type: ignore[arg-type]
    assert missing._guard_cache_shape() == ("", None, None)

    state = SimpleNamespace(
        cache_gate_stable_fp="combined-fp",
        cache_prefix_epoch=4,
        compact_event_seq=9,
    )
    present = FallbackService(  # type: ignore[arg-type]
        SimpleNamespace(_run_state=lambda: state)
    )
    assert present._guard_cache_shape() == ("combined-fp", 4, 9)
