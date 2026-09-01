"""R8 shadow-only injection profile recommendation.

The recommendation is observational metadata only.  It must never mutate the
provider prompt, injection budget, reference-auto window, or wire projection.
Model capability comes exclusively from the ProviderRegistry/ModelSpec snapshot
used for routing; model names are never interpreted heuristically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from llm_loop.llm.providers import ProviderRegistry


class InjectionProfile(str, Enum):  # noqa: UP042 — StrEnum 的 str()/format() 语义差异敏感，留待 Phase 6+ 结构期评估
    """Recommended future injection density profile (R8 shadow vocabulary)."""

    MINIMAL = "minimal"
    STANDARD = "standard"
    FULL = "full"


@dataclass(frozen=True)
class InjectionProfileRecommendation:
    """One auditable shadow recommendation for a routed model."""

    profile: InjectionProfile
    capability_tier: str
    source: str
    reason: str
    mode: str = "shadow"
    applied: bool = False

    def event_payload(self) -> dict[str, object]:
        """Stable shadow recommendation fields, independent of event envelope."""
        return {
            "injection_profile_mode": self.mode,
            "recommended_injection_profile": self.profile.value,
            "injection_profile_applied": self.applied,
            "model_capability_tier": self.capability_tier,
            "injection_profile_source": self.source,
            "injection_profile_reason": self.reason,
        }


def _minimal(*, tier: str = "unknown", source: str, reason: str) -> InjectionProfileRecommendation:
    return InjectionProfileRecommendation(
        profile=InjectionProfile.MINIMAL,
        capability_tier=tier,
        source=source,
        reason=reason,
    )


def recommend_injection_profile(
    model_label: str,
    registry: ProviderRegistry | None,
) -> InjectionProfileRecommendation:
    """Recommend a future injection profile without applying it.

    Policy is deliberately conservative and monotonic with existing capability
    semantics:

    - weak -> minimal
    - unknown / missing / unresolved -> minimal (existing registry contract says
      unknown is conservatively treated as weak)
    - strong without explicit ``reasoning`` capability -> standard
    - strong + explicit ``reasoning`` capability -> full

    ``thinking``, context size, cost tier, provider id, and model name are not
    substitutes for the explicit capability metadata.  This prevents hidden
    model-name allowlists from emerging in prompt-governance code.
    """
    label = str(model_label or "").strip()
    if registry is None:
        return _minimal(source="registry_unavailable", reason="registry_unavailable")
    if not label:
        return _minimal(source="model_unresolved", reason="empty_model_label")

    try:
        provider_id, model_id = registry.resolve(label)
    except ValueError:
        return _minimal(source="model_unresolved", reason="model_unresolved")

    provider = registry.providers.get(provider_id)
    spec = provider.models.get(model_id) if provider is not None else None
    if spec is None:
        return _minimal(source="model_unresolved", reason="model_spec_missing")

    tier = str(spec.capability_tier or "unknown").strip().lower()
    if tier == "strong":
        if bool(spec.reasoning):
            return InjectionProfileRecommendation(
                profile=InjectionProfile.FULL,
                capability_tier="strong",
                source="provider_registry",
                reason="strong_reasoning_capability",
            )
        return InjectionProfileRecommendation(
            profile=InjectionProfile.STANDARD,
            capability_tier="strong",
            source="provider_registry",
            reason="strong_without_reasoning_capability",
        )
    if tier == "weak":
        return _minimal(
            tier="weak",
            source="provider_registry",
            reason="weak_capability",
        )
    if tier == "unknown":
        return _minimal(
            tier="unknown",
            source="provider_registry",
            reason="unknown_capability_conservative",
        )
    # Defensive for directly-constructed ModelSpec values that bypass parser.
    return _minimal(
        tier="unknown",
        source="provider_registry",
        reason="invalid_capability_conservative",
    )


def shadow_profile_event_payload(
    *,
    model_label: str,
    registry: ProviderRegistry | None,
    round_no: int,
    attempt_kind: str,
    attempt_index: int,
) -> dict[str, object]:
    """Build one R8 per-provider-attempt shadow event payload."""
    recommendation = recommend_injection_profile(model_label, registry)
    return {
        "round": int(round_no),
        "attempt_kind": str(attempt_kind),
        "attempt_index": int(attempt_index),
        "model": str(model_label or ""),
        "mode": recommendation.mode,
        "recommended_injection_profile": recommendation.profile.value,
        "applied": recommendation.applied,
        "model_capability_tier": recommendation.capability_tier,
        "source": recommendation.source,
        "reason": recommendation.reason,
    }
