"""Provider-reported M1 usage facts; never invent missing tokens or billing."""

from __future__ import annotations

from decimal import ROUND_UP, Decimal, InvalidOperation
from typing import Any


def extract_usage(raw: Any) -> dict[str, Any]:
    """Keep only numeric response usage; missing/invalid is NOT zero."""
    empty = {"usage_status": "unreported", "prompt_tokens": None,
             "completion_tokens": None, "total_tokens": None,
             "cached_prompt_tokens": None}
    if not isinstance(raw, dict):
        return empty
    prompt, completion, total = (raw.get(k) for k in (
        "prompt_tokens", "completion_tokens", "total_tokens"))
    if type(prompt) is not int or type(completion) is not int or type(total) is not int:
        return {**empty, "usage_status": "invalid"}
    if min(prompt, completion, total) < 0 or total < prompt + completion:
        return {**empty, "usage_status": "invalid"}
    details = raw.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if cached is not None and type(cached) is not int:
        return {**empty, "usage_status": "invalid"}
    if type(cached) is int and not 0 <= cached <= prompt:
        return {**empty, "usage_status": "invalid"}
    return {"usage_status": "reported", "prompt_tokens": prompt,
            "completion_tokens": completion, "total_tokens": total,
            "cached_prompt_tokens": cached}


def summarize_usage(calls: list[dict[str, Any]], expected_attempts: int) -> dict[str, Any]:
    """No aggregate total is asserted if even one real attempt is unmetered."""
    unknown = sum(c.get("usage_status") != "reported" for c in calls)
    if len(calls) != expected_attempts or unknown:
        return {"status": "unknown", "attempts": expected_attempts,
                "metered_attempts": len(calls) - unknown,
                "unmetered_or_missing_attempts": unknown + max(0, expected_attempts - len(calls)),
                "prompt_tokens": None, "completion_tokens": None,
                "total_tokens": None, "estimated_usd": None}
    estimates = [c.get("cost_usd_estimate") for c in calls]
    estimated = (str(sum((Decimal(str(v)) for v in estimates), Decimal(0)))
                 if all(isinstance(v, str) for v in estimates) else None)
    return {"status": "provider_reported", "attempts": expected_attempts,
            "metered_attempts": expected_attempts,
            "unmetered_or_missing_attempts": 0,
            "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
            "completion_tokens": sum(c["completion_tokens"] for c in calls),
            "total_tokens": sum(c["total_tokens"] for c in calls),
            "estimated_usd": estimated}


def estimate_usd(usage: dict[str, Any], *, input_per_million: str,
                 output_per_million: str) -> str:
    """Conservative rounded estimate from explicit USD tariff, never an invoice."""
    if usage.get("usage_status") != "reported":
        raise ValueError("provider usage unreported; USD cannot be qualified")
    try:
        in_rate, out_rate = Decimal(input_per_million), Decimal(output_per_million)
    except InvalidOperation as exc:
        raise ValueError("invalid USD tariff") from exc
    if (not in_rate.is_finite() or not out_rate.is_finite()
            or min(in_rate, out_rate) < 0 or max(in_rate, out_rate) == 0):
        raise ValueError("USD tariff must be finite, nonnegative and nonzero")
    total = (Decimal(usage["prompt_tokens"]) * in_rate
             + Decimal(usage["completion_tokens"]) * out_rate) / Decimal(1_000_000)
    return str(total.quantize(Decimal("0.00000001"), rounding=ROUND_UP))
