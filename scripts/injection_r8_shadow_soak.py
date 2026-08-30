#!/usr/bin/env python3
"""R8.3 bounded live-shadow soak analyzer.

Consumes only provider capability metadata plus selected event-log JSONL files.
The output is sanitized: no prompt/message content, provider endpoint, credential
name/value, local path, or raw model answer is persisted.

This tool is evidence-only. It never changes provider config, registry state,
prompt construction, routing, session state, or LLM behavior.
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

SCHEMA = "injection-r8-shadow-soak-v1"
_PROFILE_EVENT = "injection.profile.shadow"
_USAGE_EVENT = "request.usage"


def _registry(raw: dict[str, Any]):
    settings = Settings(
        llm_api_key="unused",
        llm_base_url="http://127.0.0.1/unused",
        llm_model="unused",
        model_providers_raw=json.dumps(raw, ensure_ascii=False, sort_keys=True),
    )
    return load_registry(settings)


def _expected_models(raw: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    registry = _registry(raw)
    expected: dict[str, dict[str, Any]] = {}
    metadata_complete = 0
    unknown = 0
    profile_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    for pid in sorted(registry.providers):
        provider = registry.providers[pid]
        raw_provider_value = raw.get(pid)
        raw_provider: dict[str, Any] = raw_provider_value if isinstance(raw_provider_value, dict) else {}
        raw_models_value = raw_provider.get("models")
        raw_models: dict[str, Any] = raw_models_value if isinstance(raw_models_value, dict) else {}
        for mid in sorted(provider.models):
            label = f"{pid}/{mid}"
            rec = recommend_injection_profile(label, registry)
            raw_entry_value = raw_models.get(mid)
            raw_entry: dict[str, Any] = raw_entry_value if isinstance(raw_entry_value, dict) else {}
            tier_explicit = str(raw_entry.get("capability_tier", "")).strip().lower() in {
                "strong", "weak", "unknown"
            }
            reasoning_explicit = "reasoning" in raw_entry
            complete = bool(
                tier_explicit
                and rec.capability_tier in {"strong", "weak"}
                and (rec.capability_tier == "weak" or reasoning_explicit)
            )
            metadata_complete += int(complete)
            unknown += int(rec.capability_tier == "unknown")
            profile_counts[rec.profile.value] = profile_counts.get(rec.profile.value, 0) + 1
            tier_counts[rec.capability_tier] = tier_counts.get(rec.capability_tier, 0) + 1
            expected[label] = {
                "tier": rec.capability_tier,
                "profile": rec.profile.value,
                "reason": rec.reason,
                "metadata_complete": complete,
            }
    total = len(expected)
    registry_summary = {
        "models_total": total,
        "metadata_complete_models": metadata_complete,
        "metadata_complete_coverage_pct": round(metadata_complete * 100 / total, 2) if total else 0.0,
        "unknown_models": unknown,
        "profile_counts": dict(sorted(profile_counts.items())),
        "capability_tier_counts": dict(sorted(tier_counts.items())),
        "registry_degraded": bool(registry.degraded),
        "metadata_gate_ready": bool(total and metadata_complete == total and unknown == 0 and not registry.degraded),
    }
    return expected, registry_summary


def read_event_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if isinstance(item, dict):
            records.append(item)
    return records


def analyze_live_soak(
    raw: dict[str, Any],
    *,
    source_bytes: bytes,
    records_by_label: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    expected, registry_summary = _expected_models(raw)
    sessions: list[dict[str, Any]] = []
    sanitized_events: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    observed_by_model: dict[str, set[tuple[str, str, str]]] = {}
    profile_events_total = 0
    usage_events_total = 0
    nonprimary_live_attempts = 0

    for label in sorted(records_by_label):
        records = records_by_label[label]
        usages = [r for r in records if r.get("type") == _USAGE_EVENT]
        profiles = [r for r in records if r.get("type") == _PROFILE_EVENT]
        usage_events_total += len(usages)
        profile_events_total += len(profiles)
        models: set[str] = set()
        profiles_seen: set[str] = set()
        tiers_seen: set[str] = set()

        for index, event in enumerate(profiles, start=1):
            payload_value = event.get("payload")
            payload: dict[str, Any] = payload_value if isinstance(payload_value, dict) else {}
            model = str(payload.get("model", ""))
            tier = str(payload.get("model_capability_tier", ""))
            profile = str(payload.get("recommended_injection_profile", ""))
            reason = str(payload.get("reason", ""))
            mode = payload.get("mode")
            applied = payload.get("applied")
            source = payload.get("source")
            attempt_kind = str(payload.get("attempt_kind", ""))
            attempt_index = payload.get("attempt_index")
            models.add(model)
            profiles_seen.add(profile)
            tiers_seen.add(tier)
            nonprimary_live_attempts += int(attempt_kind != "primary")
            observed_by_model.setdefault(model, set()).add((tier, profile, reason))
            exp = expected.get(model)
            if exp is None:
                violations.append({"label": label, "event_index": index, "kind": "model_not_in_registry", "model": model})
            else:
                if tier != exp["tier"] or profile != exp["profile"] or reason != exp["reason"]:
                    violations.append({
                        "label": label,
                        "event_index": index,
                        "kind": "attribution_mismatch",
                        "model": model,
                        "observed": {"tier": tier, "profile": profile, "reason": reason},
                        "expected": {"tier": exp["tier"], "profile": exp["profile"], "reason": exp["reason"]},
                    })
            if mode != "shadow":
                violations.append({"label": label, "event_index": index, "kind": "mode_not_shadow", "model": model})
            if applied is not False:
                violations.append({"label": label, "event_index": index, "kind": "applied_not_false", "model": model})
            if source != "provider_registry":
                violations.append({"label": label, "event_index": index, "kind": "source_mismatch", "model": model})
            sanitized_events.append({
                "label": label,
                "event_index": index,
                "round": payload.get("round"),
                "attempt_kind": attempt_kind,
                "attempt_index": attempt_index,
                "model": model,
                "capability_tier": tier,
                "recommended_profile": profile,
                "mode": mode,
                "applied": applied,
                "source": source,
                "reason": reason,
            })

        sessions.append({
            "label": label,
            "request_usage_events": len(usages),
            "profile_events": len(profiles),
            "models": sorted(models),
            "profiles": sorted(profiles_seen),
            "capability_tiers": sorted(tiers_seen),
        })

    churn_models = sorted(model for model, values in observed_by_model.items() if len(values) > 1)
    # The bounded live samples are deliberately primary-only. For these sessions,
    # one request.usage corresponds to one provider call, so a missing profile
    # event is directly measurable as an unattributed provider attempt.
    unattributed_primary_attempts = max(usage_events_total - profile_events_total, 0)
    passed = bool(
        registry_summary["metadata_gate_ready"]
        and profile_events_total > 0
        and usage_events_total == profile_events_total
        and nonprimary_live_attempts == 0
        and not churn_models
        and not violations
    )
    return {
        "schema": SCHEMA,
        "mode": "shadow",
        "applied": False,
        "providers_source": {
            "name": "providers.json",
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
        },
        "registry": registry_summary,
        "live_primary": {
            "summary": {
                "sessions": len(sessions),
                "request_usage_events": usage_events_total,
                "profile_events": profile_events_total,
                "unattributed_primary_attempts": unattributed_primary_attempts,
                "nonprimary_attempts": nonprimary_live_attempts,
                "profile_churn_models": churn_models,
                "violations": len(violations),
                "pass": passed,
            },
            "sessions": sessions,
            "events": sanitized_events,
            "violations": violations,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers-json", required=True)
    parser.add_argument("--event", action="append", default=[], help="LABEL=event-log.jsonl")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_path = Path(args.providers_json)
    source_bytes = source_path.read_bytes()
    raw = json.loads(source_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("providers JSON root must be an object")
    records_by_label: dict[str, list[dict[str, Any]]] = {}
    for item in args.event:
        label, sep, path = item.partition("=")
        if not sep or not label.strip() or not path.strip():
            raise ValueError("--event must be LABEL=PATH")
        records_by_label[label.strip()] = read_event_records(Path(path.strip()))
    report = analyze_live_soak(raw, source_bytes=source_bytes, records_by_label=records_by_label)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["live_primary"]["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["live_primary"]["summary"]["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
