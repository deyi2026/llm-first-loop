from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "injection_r8_shadow.py"
    spec = importlib.util.spec_from_file_location("injection_r8_shadow", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_inventory_is_sanitized_deterministic_and_blocks_incomplete_canary() -> None:
    mod = _module()
    raw = {
        "p": {
            "base_url": "https://secret-transport.invalid/v1",
            "api_key_env": "SECRET_KEY_ENV",
            "models": {
                "weak": {"capability_tier": "weak", "reasoning": False},
                "strong": {"capability_tier": "strong", "reasoning": True},
                "unknown": {"reasoning": True},
            },
        }
    }
    source = json.dumps(raw, sort_keys=True).encode()
    first = mod.build_shadow_inventory(raw, source_bytes=source)
    second = mod.build_shadow_inventory(raw, source_bytes=source)
    assert first == second
    assert first["mode"] == "shadow" and first["applied"] is False
    assert first["summary"]["models_total"] == 3
    assert first["summary"]["classified_models"] == 2
    assert first["summary"]["metadata_complete_models"] == 2
    assert first["summary"]["canary_ready"] is False
    assert first["summary"]["canary_block_reason"] == "capability_metadata_incomplete"
    encoded = json.dumps(first, ensure_ascii=False)
    assert "secret-transport" not in encoded
    assert "SECRET_KEY_ENV" not in encoded
    assert "base_url" not in encoded
    assert "api_key" not in encoded


def test_inventory_requires_explicit_reasoning_for_strong_canary() -> None:
    mod = _module()
    raw = {
        "p": {
            "base_url": "http://x.invalid",
            "api_key_env": "",
            "models": {
                "strong-implicit": {"capability_tier": "strong"},
                "weak": {"capability_tier": "weak"},
            },
        }
    }
    inv = mod.build_shadow_inventory(raw, source_bytes=b"fixture")
    rows = {row["model"]: row for row in inv["models"]}
    assert rows["p/strong-implicit"]["recommended_injection_profile"] == "standard"
    assert rows["p/strong-implicit"]["metadata_complete_for_canary"] is False
    assert rows["p/weak"]["metadata_complete_for_canary"] is True
    assert inv["summary"]["canary_ready"] is False


def test_inventory_canary_ready_when_all_capabilities_are_explicit() -> None:
    mod = _module()
    raw = {
        "p": {
            "base_url": "http://x.invalid",
            "api_key_env": "",
            "models": {
                "weak": {"capability_tier": "weak"},
                "standard": {"capability_tier": "strong", "reasoning": False},
                "full": {"capability_tier": "strong", "reasoning": True},
            },
        }
    }
    inv = mod.build_shadow_inventory(raw, source_bytes=b"fixture")
    assert inv["summary"]["metadata_complete_models"] == 3
    assert inv["summary"]["metadata_complete_coverage_pct"] == 100.0
    assert inv["summary"]["canary_ready"] is True
    assert inv["summary"]["profile_counts"] == {
        "full": 1,
        "minimal": 1,
        "standard": 1,
    }
