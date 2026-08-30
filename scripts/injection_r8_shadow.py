#!/usr/bin/env python3
"""R8 shadow-only injection-profile inventory.

Reads a provider-registry JSON file and emits a deterministic, sanitized
inventory of capability metadata -> recommended injection profile.  The output
contains no transport URLs, key env names, credentials, or local file paths.

This script is evidence tooling only: it never writes provider config and never
changes prompt behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from llm_loop.config import Settings
from llm_loop.core.injection_profile import recommend_injection_profile
from llm_loop.llm.providers import load_registry

SCHEMA = "injection-r8-shadow-v1"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _raw_model_entry(raw: dict[str, Any], provider_id: str, model_id: str) -> dict[str, Any]:
    provider = raw.get(provider_id)
    if not isinstance(provider, dict):
        return {}
    models = provider.get("models")
    if not isinstance(models, dict):
        return {}
    entry = models.get(model_id)
    return entry if isinstance(entry, dict) else {}


def _explicit_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if type(value) is int and value in (0, 1):  # bool is int; excluded above intentionally
        return True
    if isinstance(value, str):
        return value.strip().lower() in {
            "1", "0", "true", "false", "yes", "no", "on", "off"
        }
    return False


def build_shadow_inventory(raw: dict[str, Any], *, source_bytes: bytes) -> dict[str, Any]:
    """Build deterministic sanitized R8 inventory from provider config JSON."""
    settings = Settings(
        llm_api_key="unused",
        llm_base_url="http://127.0.0.1/unused",
        llm_model="unused",
        model_providers_raw=json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )
    registry = load_registry(settings)

    rows: list[dict[str, Any]] = []
    profile_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    classified = 0
    metadata_complete = 0

    for provider_id in sorted(registry.providers):
        provider = registry.providers[provider_id]
        for model_id in sorted(provider.models):
            spec = provider.models[model_id]
            model_label = f"{provider_id}/{model_id}"
            rec = recommend_injection_profile(model_label, registry)
            raw_entry = _raw_model_entry(raw, provider_id, model_id)
            tier_explicit = (
                "capability_tier" in raw_entry
                and str(raw_entry.get("capability_tier", "")).strip().lower()
                in {"strong", "weak", "unknown"}
            )
            reasoning_explicit = "reasoning" in raw_entry and _explicit_bool(raw_entry.get("reasoning"))
            tier_classified = rec.capability_tier in {"strong", "weak"}
            # Weak does not need reasoning metadata for R8 profile selection.
            model_metadata_complete = bool(
                tier_explicit
                and tier_classified
                and (rec.capability_tier == "weak" or reasoning_explicit)
            )
            if tier_classified:
                classified += 1
            if model_metadata_complete:
                metadata_complete += 1
            profile_counts[rec.profile.value] = profile_counts.get(rec.profile.value, 0) + 1
            tier_counts[rec.capability_tier] = tier_counts.get(rec.capability_tier, 0) + 1
            rows.append(
                {
                    "model": model_label,
                    "capability_tier": rec.capability_tier,
                    "capability_tier_explicit": tier_explicit,
                    "reasoning": bool(spec.reasoning),
                    "reasoning_explicit": reasoning_explicit,
                    "recommended_injection_profile": rec.profile.value,
                    "reason": rec.reason,
                    "metadata_complete_for_canary": model_metadata_complete,
                }
            )

    total = len(rows)
    canary_ready = bool(total > 0 and metadata_complete == total)
    return {
        "schema": SCHEMA,
        "mode": "shadow",
        "applied": False,
        "source": {
            "name": "providers.json",
            "sha256": _sha256_bytes(source_bytes),
        },
        "registry_degraded": bool(registry.degraded),
        "summary": {
            "models_total": total,
            "classified_models": classified,
            "unknown_models": total - classified,
            "metadata_complete_models": metadata_complete,
            "classified_coverage_pct": round((classified / total) * 100, 2) if total else 0.0,
            "metadata_complete_coverage_pct": round((metadata_complete / total) * 100, 2)
            if total
            else 0.0,
            "profile_counts": dict(sorted(profile_counts.items())),
            "capability_tier_counts": dict(sorted(tier_counts.items())),
            "canary_ready": canary_ready,
            "canary_block_reason": "" if canary_ready else "capability_metadata_incomplete",
        },
        "models": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_path = Path(args.providers_json)
    source_bytes = source_path.read_bytes()
    raw = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("providers JSON root must be an object")
    inventory = build_shadow_inventory(raw, source_bytes=source_bytes)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(inventory["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
