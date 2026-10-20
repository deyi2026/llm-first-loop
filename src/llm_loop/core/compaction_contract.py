"""Stable capacity provenance for history compaction, independent of density estimates."""
from __future__ import annotations

from typing import Any


def contract_from_budget(info: Any, *, wire_protocol: str = "openai", policy: Any = None) -> dict | None:
    """Capture configured capacity, excluding measured density and schema estimates."""
    if not isinstance(info, dict):
        return None
    tokens = info.get("allowed_input_tokens")
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
        return None
    explicit = info.get("runtime_override")
    if explicit is None:
        explicit = info.get("configured_global_budget")
    caps = [v for v in (explicit, info.get("provider_budget"))
            if isinstance(v, int) and not isinstance(v, bool) and v > 0]
    return {
        "input_tokens": tokens,
        "char_limit": min(caps) if caps else None,
        "wire_protocol": wire_protocol,
        "policy": {key: getattr(policy, key, None) for key in (
            "compact_ratio", "compress_target_ratio", "head_keep_ratio",
            "head_keep_force_ratio", "head_keep_target_ratio",
        )},
    }


def scope_matches(scope: Any, *, model: str, budget: int,
                  contract: dict | None = None) -> bool:
    """Shrinking capacity preserves old retirement; a real expansion reopens it."""
    if not isinstance(scope, dict) or scope.get("model") != model:
        return False
    try:
        if contract is None:
            return (int(scope.get("version", 0)) == 1
                    and 0 < budget <= int(scope.get("effective_budget", 0)))
        old = scope.get("logical_contract")
        if scope.get("version") != 2 or not isinstance(old, dict):
            return False
        if any(old.get(k) != contract.get(k) for k in ("wire_protocol", "policy")):
            return False
        before, now = old.get("input_tokens"), contract.get("input_tokens")
        if isinstance(before, bool) or isinstance(now, bool):
            return False
        if not isinstance(before, int) or not isinstance(now, int) or not 0 < now <= before:
            return False
        old_cap, cap = old.get("char_limit"), contract.get("char_limit")
        if old_cap is not None and (
            isinstance(old_cap, bool) or not isinstance(old_cap, int) or old_cap <= 0
        ):
            return False
        if cap is not None and (
            isinstance(cap, bool) or not isinstance(cap, int) or cap <= 0
        ):
            return False
        return old_cap is None or (cap is not None and cap <= old_cap)
    except (TypeError, ValueError):
        return False
