"""M0-B in-memory gateway contract: provenance, catalog seal and no silent skill fallback.

This is a test double, not a deployed LFL tool or production signature system.
Only the gateway submit method is model-facing; the catalog authority and
executor are trusted test actors. M1 must replace them with real isolated actors.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from stubs import DeniedError, Observation, Receipt, StubExecutor


@dataclass(frozen=True, eq=False)
class CatalogSeal:
    digest: str


class CatalogAuthority:
    """Identity-bound in-memory seal: a caller cannot self-assert a valid digest."""

    def __init__(self) -> None:
        self._issued: set[CatalogSeal] = set()

    @staticmethod
    def digest(catalog: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(catalog, sort_keys=True).encode()).hexdigest()

    def sign(self, catalog: dict[str, Any]) -> CatalogSeal:
        seal = CatalogSeal(self.digest(catalog))
        self._issued.add(seal)
        return seal

    def verify(self, catalog: dict[str, Any], seal: CatalogSeal) -> bool:
        return seal in self._issued and seal.digest == self.digest(catalog)


@dataclass(frozen=True)
class CapabilityGap:
    code: str
    requested_id: str
    candidates: tuple[str, ...]


def trusted_catalog() -> dict[str, Any]:
    # Eight required contract groups; no model-generated registrations.
    return {
        skill: {
            "skill_id": skill,
            "version": "1",
            "params_schema": ["target_id"] if skill == "pick" else ["tray_id"],
            "required_grants": ["sim.arm.write"],
            "allowed_regions": ["tray-A", "tray-B"] if skill == "place" else [],
            "limits": {"max_force_n": 10},
            "stop_boundaries": ["before_action", "after_action"],
            "cost_hint": {"expected_actions": 1},
        }
        for skill in ("pick", "place")
    }


class SafeGateway:
    """One small model-facing entry; no text-to-permission or fuzzy skill routing."""

    def __init__(
        self,
        executor: StubExecutor,
        catalog: dict[str, Any],
        authority: CatalogAuthority,
        seal: CatalogSeal,
    ) -> None:
        self._executor = executor
        self._catalog = deepcopy(catalog)
        self._authority = authority
        self._seal = seal

    @staticmethod
    def data_only(text: str) -> dict[str, str]:
        return {"trust": "untrusted", "untrusted_text": text}

    @staticmethod
    def can_promote_experience(source: str) -> bool:
        # Positive trust allowlist: unknown sources are never promoted by default.
        return source in {"independent_oracle", "verified_simulator", "trusted_operator"}

    def submit(
        self,
        *,
        grant_version: int,
        observation: Observation,
        intent_key: str,
        semantic_fingerprint: str,
        skill: str,
        skill_version: str,
        params: dict[str, Any],
        parameter_sources: dict[str, str],
        untrusted_text: str = "",
    ) -> Receipt | CapabilityGap:
        del untrusted_text  # data only: cannot change authority, catalog, or parameters
        if not self._authority.verify(self._catalog, self._seal):
            raise DeniedError("CATALOG_INVALID")
        if skill not in self._catalog:
            return CapabilityGap("skill_not_found", skill, tuple(sorted(self._catalog)[:5]))
        entry = self._catalog[skill]
        required = {
            "skill_id", "version", "params_schema", "required_grants",
            "allowed_regions", "limits", "stop_boundaries", "cost_hint",
        }
        if not required <= entry.keys():
            raise DeniedError("CATALOG_INVALID")
        if entry["version"] != skill_version:
            raise DeniedError("SKILL_VERSION_MISMATCH")
        if any(key in params for key in ("joint", "joints", "torque", "speed", "trajectory")):
            raise DeniedError("LOW_LEVEL_CONTROL_REJECTED")
        if any(key in params for key in ("x", "y", "z", "coordinates", "raw_pose")):
            raise DeniedError("RAW_COORDINATES_REJECTED")
        if set(params) != set(entry["params_schema"]):
            raise DeniedError("PARAM_UNTRUSTED_SOURCE")
        for name, value in params.items():
            source = parameter_sources.get(name, "")
            if "*" in source or ".." in source or "[0]" in source:
                raise DeniedError("PARAM_UNTRUSTED_SOURCE")
            if name == "target_id":
                expected = f"observation/{observation.observation_ref}/objects[id={value}].id"
                if source != expected or value not in observation.visible["known_targets"]:
                    raise DeniedError("PARAM_UNTRUSTED_SOURCE")
            elif name == "tray_id":
                expected = f"catalog/skills[{skill}@{skill_version}]/allowed_regions[{value}]"
                if source != expected or value not in entry["allowed_regions"]:
                    raise DeniedError("PARAM_UNTRUSTED_SOURCE")
            else:
                raise DeniedError("PARAM_UNTRUSTED_SOURCE")
        return self._executor.execute_skill(
            grant_version=grant_version,
            scene_epoch=observation.scene_epoch,
            observation_ref=observation.observation_ref,
            intent_key=intent_key,
            semantic_fingerprint=semantic_fingerprint,
            skill=skill,
            params=params,
        )
