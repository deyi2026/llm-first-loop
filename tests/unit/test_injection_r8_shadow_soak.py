from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "injection_r8_shadow_soak.py"
    spec = importlib.util.spec_from_file_location("injection_r8_shadow_soak", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _raw() -> dict:
    return {
        "p": {
            "base_url": "https://secret.invalid/v1",
            "api_key_env": "SECRET_KEY",
            "models": {
                "weak": {"capability_tier": "weak"},
                "strong": {"capability_tier": "strong", "reasoning": True},
            },
        }
    }


def _profile(model: str, tier: str, profile: str, reason: str, **overrides):
    payload = {
        "round": 1,
        "attempt_kind": "primary",
        "attempt_index": 0,
        "model": model,
        "mode": "shadow",
        "recommended_injection_profile": profile,
        "applied": False,
        "model_capability_tier": tier,
        "source": "provider_registry",
        "reason": reason,
    }
    payload.update(overrides)
    return {"type": "injection.profile.shadow", "payload": payload}


def test_valid_live_primary_soak_passes_and_is_sanitized() -> None:
    mod = _module()
    records = {
        "strong": [
            {"type": "request.usage", "payload": {"tokens": 10}},
            _profile("p/strong", "strong", "full", "strong_reasoning_capability"),
        ],
        "weak": [
            {"type": "request.usage", "payload": {"tokens": 11}},
            _profile("p/weak", "weak", "minimal", "weak_capability"),
        ],
    }
    report = mod.analyze_live_soak(_raw(), source_bytes=b"provider-fixture", records_by_label=records)
    assert report["registry"]["metadata_gate_ready"] is True
    assert report["live_primary"]["summary"]["pass"] is True
    assert report["live_primary"]["summary"]["unattributed_primary_attempts"] == 0
    encoded = json.dumps(report, ensure_ascii=False)
    assert "secret.invalid" not in encoded
    assert "SECRET_KEY" not in encoded
    assert "tokens" not in encoded


def test_wrong_profile_or_applied_state_fails() -> None:
    mod = _module()
    records = {
        "bad": [
            {"type": "request.usage", "payload": {}},
            _profile("p/weak", "weak", "full", "weak_capability", applied=True),
        ]
    }
    report = mod.analyze_live_soak(_raw(), source_bytes=b"x", records_by_label=records)
    kinds = {v["kind"] for v in report["live_primary"]["violations"]}
    assert "attribution_mismatch" in kinds
    assert "applied_not_false" in kinds
    assert report["live_primary"]["summary"]["pass"] is False


def test_profile_churn_is_detected() -> None:
    mod = _module()
    records = {
        "churn": [
            {"type": "request.usage", "payload": {}},
            _profile("p/weak", "weak", "minimal", "weak_capability"),
            {"type": "request.usage", "payload": {}},
            _profile("p/weak", "weak", "minimal", "different_reason"),
        ]
    }
    report = mod.analyze_live_soak(_raw(), source_bytes=b"x", records_by_label=records)
    assert report["live_primary"]["summary"]["profile_churn_models"] == ["p/weak"]
    assert report["live_primary"]["summary"]["pass"] is False


def test_missing_profile_event_is_unattributed_attempt() -> None:
    mod = _module()
    records = {"missing": [{"type": "request.usage", "payload": {}}]}
    report = mod.analyze_live_soak(_raw(), source_bytes=b"x", records_by_label=records)
    assert report["live_primary"]["summary"]["unattributed_primary_attempts"] == 1
    assert report["live_primary"]["summary"]["pass"] is False
