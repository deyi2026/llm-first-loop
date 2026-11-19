"""M1 real-provider usage is evidence, not guessed billing or zero on timeout."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts/embodied")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import m1_gate_c_episode as gate_c  # noqa: E402

from llm_loop.embodied_sim.paired_budget import PairedCostHold  # noqa: E402
from llm_loop.embodied_sim.usage import (  # noqa: E402
    estimate_usd,
    extract_usage,
    summarize_usage,
)


def test_provider_usage_preserves_exact_reported_numbers():
    usage = extract_usage({"prompt_tokens": 120, "completion_tokens": 24,
                           "total_tokens": 144,
                           "prompt_tokens_details": {"cached_tokens": 20}})
    assert usage == {"usage_status": "reported", "prompt_tokens": 120,
                     "completion_tokens": 24, "total_tokens": 144,
                     "cached_prompt_tokens": 20}
    assert summarize_usage([usage, usage], 2) == {
        "status": "provider_reported", "attempts": 2,
        "metered_attempts": 2, "unmetered_or_missing_attempts": 0,
        "prompt_tokens": 240, "completion_tokens": 48, "total_tokens": 288,
        "estimated_usd": None,
    }


@pytest.mark.parametrize("raw", [
    None, {}, {"prompt_tokens": 1, "completion_tokens": 2},
    {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
    {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 0},
    {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 2},
    {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3,
     "prompt_tokens_details": {"cached_tokens": 2}},
])
def test_missing_or_invalid_usage_never_becomes_zero(raw):
    fact = extract_usage(raw)
    assert fact["usage_status"] != "reported"
    assert fact["prompt_tokens"] is None
    assert summarize_usage([fact], 1)["status"] == "unknown"


def test_missing_attempt_prevents_aggregate_token_claim():
    one = extract_usage({"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
    assert summarize_usage([one], 2)["unmetered_or_missing_attempts"] == 1
    assert summarize_usage([one], 2)["total_tokens"] is None


def test_usd_estimate_requires_explicit_rates_and_provider_usage():
    usage = extract_usage({"prompt_tokens": 1000, "completion_tokens": 500,
                           "total_tokens": 1500})
    assert estimate_usd(usage, input_per_million="1", output_per_million="2") == "0.00200000"
    with pytest.raises(ValueError, match="unreported"):
        estimate_usd(extract_usage(None), input_per_million="1", output_per_million="2")
    with pytest.raises(ValueError, match="tariff"):
        estimate_usd(usage, input_per_million="NaN", output_per_million="2")


def _provider():
    provider = gate_c.GLMHttpProvider.__new__(gate_c.GLMHttpProvider)
    provider.wire_model = "glm-5.3-flash"
    provider.model_used = "glm/glm-5.3-flash"
    provider._api_key = "test-only"
    provider._base_url = "https://invalid.example"
    provider._timeout_s = 1.0
    provider._cost_gate = None
    provider.calls = []
    return provider


def test_paired_provider_requires_separate_standard_api_key(monkeypatch):
    class Registry:
        def resolve(self, _ref):
            return "glm", "glm-5.3-flash"

        def client_params(self, _pid, _mid):
            return {"model": "glm-5.3-flash", "api_key": "coding-plan-key",
                    "base_url": "https://open.bigmodel.cn/api/coding/paas/v4"}

    monkeypatch.setattr(gate_c, "load_settings", lambda: object())
    monkeypatch.setattr(gate_c, "load_registry", lambda _settings: Registry())
    monkeypatch.delenv("LFL_M1_STANDARD_API_KEY", raising=False)
    gate = _FakeCostGate()
    with pytest.raises(PairedCostHold, match="PAIRED_STANDARD_API_KEY_REQUIRED"):
        gate_c.GLMHttpProvider(cost_gate=gate)
    monkeypatch.setenv("LFL_M1_STANDARD_API_KEY", "coding-plan-key")
    with pytest.raises(PairedCostHold, match="PAIRED_STANDARD_API_KEY_NOT_SEPARATE"):
        gate_c.GLMHttpProvider(cost_gate=gate)
    assert gate.reserved == 0
    monkeypatch.setenv("LFL_M1_STANDARD_API_KEY", "separate-standard-key")
    provider = gate_c.GLMHttpProvider(cost_gate=gate)
    assert provider._base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert provider._api_key == "separate-standard-key"
    assert gate.reserved == 0


def test_real_provider_records_response_usage_without_raw_request(monkeypatch):
    body = {"choices": [{"message": {"content": '{"skill":"stop"}'},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 77, "completion_tokens": 11,
                      "total_tokens": 88}}
    monkeypatch.setattr(gate_c.httpx, "post",
                        lambda *_a, **_kw: SimpleNamespace(status_code=200,
                                                          json=lambda: body))
    provider = _provider()
    assert provider.decide("public observation") == '{"skill":"stop"}'
    assert len(provider.calls) == 1
    assert provider.calls[0]["usage_status"] == "reported"
    assert provider.calls[0]["prompt_tokens"] == 77
    assert "test-only" not in str(provider.calls)
    assert "public observation" not in str(provider.calls)


def test_transport_timeout_is_one_unmetered_attempt_not_zero(monkeypatch):
    def timeout(*_a, **_kw):
        raise httpx.ReadTimeout("simulated")

    monkeypatch.setattr(gate_c.httpx, "post", timeout)
    provider = _provider()
    with pytest.raises(httpx.ReadTimeout):
        provider.decide("public observation")
    assert len(provider.calls) == 1
    assert provider.calls[0]["status"] == "transport_error"
    assert provider.calls[0]["usage_status"] == "unreported"
    assert summarize_usage(provider.calls, 1)["status"] == "unknown"


def test_non_200_is_unmetered_and_keeps_attempt(monkeypatch):
    monkeypatch.setattr(gate_c.httpx, "post",
                        lambda *_a, **_kw: SimpleNamespace(status_code=429,
                                                          text="rate limited"))
    provider = _provider()
    with pytest.raises(RuntimeError, match="429"):
        provider.decide("public observation")
    assert len(provider.calls) == 1
    assert provider.calls[0]["usage_status"] == "unreported"


class _FakeCostGate:
    def __init__(self):
        self.reserved = 0
        self.settled = 0
        self.unknown = 0

    def reserve(self):
        self.reserved += 1
        return "reservation-id"

    def settle(self, call_id, usage):
        assert call_id == "reservation-id"
        assert usage["usage_status"] == "reported"
        self.settled += 1
        return "0.00200000"

    def mark_unknown(self, call_id):
        assert call_id == "reservation-id"
        self.unknown += 1


def test_paired_provider_settles_before_returning_model_decision(monkeypatch):
    body = {"choices": [{"message": {"content": '{"skill":"stop"}'},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                      "total_tokens": 1500}}
    monkeypatch.setattr(gate_c.httpx, "post",
                        lambda *_a, **_kw: SimpleNamespace(status_code=200,
                                                          json=lambda: body))
    provider = _provider()
    gate = _FakeCostGate()
    provider._cost_gate = gate
    assert provider.decide("public observation") == '{"skill":"stop"}'
    assert gate.reserved == 1 and gate.settled == 1 and gate.unknown == 0
    assert provider.calls[0]["cost_usd_estimate"] == "0.00200000"


def test_paired_transport_timeout_holds_and_marks_unknown(monkeypatch):
    def timeout(*_a, **_kw):
        raise httpx.ReadTimeout("simulated")

    monkeypatch.setattr(gate_c.httpx, "post", timeout)
    provider = _provider()
    gate = _FakeCostGate()
    provider._cost_gate = gate
    with pytest.raises(PairedCostHold, match="PROVIDER_TRANSPORT_BILLING_UNKNOWN") as exc:
        provider.decide("public observation")
    assert exc.value.provider_attempted
    assert gate.reserved == 1 and gate.unknown == 1 and gate.settled == 0
