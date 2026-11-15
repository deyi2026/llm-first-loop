"""Mechanical, whole-surface schema representation under a model input budget.

No task-based tool selection: the caller has already applied TaskBudget and runtime
health. All eligible callable tool names/order stay unchanged, including on the
emergency index tier. The execution registry remains the argument authority.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_loop.core.history import stable_digest


@dataclass(frozen=True, slots=True)
class SchemaCapacityProjection:
    schemas: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    mode: str
    original_tokens: int | None
    selected_tokens: int | None
    threshold_tokens: int | None
    token_source: str
    reason: str

    @property
    def authoritative_tokens(self) -> int | None:
        return self.selected_tokens if self.token_source == "authoritative_tokenizer" else None


def select_schema_capacity_projection(
    *,
    registry: Any,
    eligible_schemas: list[dict[str, Any]],
    schema_to_param: Callable[[dict[str, Any]], dict[str, Any]],
    allowed_input_tokens: int | None,
    projection_chars_per_token: float | None,
    count_tool_schema_tokens: Callable[[list[dict[str, Any]]], int] | None,
) -> SchemaCapacityProjection:
    """Bound schema cost without hiding, ranking or promoting a single tool.

    The 50% share is a *representation* trigger, not a physical context limit.
    A valid get_tool_schema entry is required for index mode because its parameter
    contracts are discoverable rather than exposed in the initial callable schema.
    """
    original = [schema_to_param(row) for row in eligible_schemas]
    allowed = (
        allowed_input_tokens
        if isinstance(allowed_input_tokens, int) and not isinstance(allowed_input_tokens, bool) and allowed_input_tokens > 0
        else None
    )
    cpt = (
        float(projection_chars_per_token)
        if isinstance(projection_chars_per_token, (float, int))
        and projection_chars_per_token > 0
        else None
    )

    def measure(tools: list[dict[str, Any]]) -> tuple[int | None, str]:
        if callable(count_tool_schema_tokens):
            try:
                tokens = count_tool_schema_tokens(tools)
                if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                    return tokens, "authoritative_tokenizer"
            except Exception:  # noqa: BLE001 - optional tokenizer has conservative fallback
                pass
        if cpt is not None:
            chars = len(json.dumps({"tools": tools}, ensure_ascii=False, default=str))
            return math.ceil(chars / cpt), "projection_fallback"
        return None, "unknown"

    original_tokens, source = measure(original)
    threshold = allowed // 2 if allowed is not None else None

    def result(
        schemas: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        mode: str,
        tokens: int | None,
        reason: str,
        measurement_source: str = source,
    ) -> SchemaCapacityProjection:
        return SchemaCapacityProjection(
            schemas=tuple(schemas),
            tools=tuple(tools),
            mode=mode,
            original_tokens=original_tokens,
            selected_tokens=tokens,
            threshold_tokens=threshold,
            token_source=measurement_source,
            reason=reason,
        )

    if threshold is None or original_tokens is None:
        return result(eligible_schemas, original, "stable", original_tokens, "capacity_unknown")
    if original_tokens <= threshold:
        return result(eligible_schemas, original, "stable", original_tokens, "within_share")
    names = [str(row.get("name") or "") for row in eligible_schemas]
    if (
        not names
        or any(not name for name in names)
        or len(set(names)) != len(names)
        or "get_tool_schema" not in names
    ):
        return result(eligible_schemas, original, "stable", original_tokens, "discovery_unavailable")

    best: tuple[list[dict[str, Any]], list[dict[str, Any]], int, str, str] | None = None
    for desc_chars in (80, 48, 0):
        try:
            catalog = {row["name"]: row for row in registry.index_schemas(desc_chars=desc_chars)}
            if any(name not in catalog for name in names):
                return result(eligible_schemas, original, "stable", original_tokens, "index_incomplete")
            candidate_schemas = [catalog[name] for name in names]
            candidate_tools = [schema_to_param(row) for row in candidate_schemas]
        except (AttributeError, KeyError, TypeError, ValueError):
            # An incomplete or malformed discovery surface cannot authorize an
            # alternate provider representation. Keep the original safe path.
            return result(eligible_schemas, original, "stable", original_tokens, "index_invalid")
        measured, candidate_source = measure(candidate_tools)
        if measured is None or measured >= original_tokens:
            continue
        if best is None or measured < best[2]:
            best = (candidate_schemas, candidate_tools, measured, candidate_source, f"index_{desc_chars}")
        if measured <= threshold:
            return result(
                candidate_schemas,
                candidate_tools,
                f"index_{desc_chars}",
                measured,
                "schema_share_pressure",
                candidate_source,
            )
    if best is not None:
        return result(best[0], best[1], best[4], best[2], "index_still_over_share", best[3])
    return result(eligible_schemas, original, "stable", original_tokens, "no_smaller_representation")


def admit_request_schema_capacity(
    engine: Any,
    llm_client: Any,
    eligible_schemas: list[dict[str, Any]],
    original_tools: list[dict[str, Any]],
    session_id: str,
    rounds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], SchemaCapacityProjection]:
    """Single engine seam for mechanical schema selection, budget and cache audit."""
    budget = dict(engine._run_state().last_budget_info or {})
    chosen = select_schema_capacity_projection(
        registry=engine.registry,
        eligible_schemas=eligible_schemas,
        schema_to_param=engine._tool_cycle._schema_to_param,
        allowed_input_tokens=budget.get("allowed_input_tokens"),
        projection_chars_per_token=budget.get("projection_chars_per_token"),
        count_tool_schema_tokens=getattr(llm_client, "count_tool_schema_tokens", None),
    )
    schemas, tools = eligible_schemas, original_tools
    if chosen.mode != "stable":
        schemas, tools = list(chosen.schemas), list(chosen.tools)
        engine._run_state().cache_gate_tools_fp = stable_digest(tools)
    if (
        chosen.threshold_tokens is not None
        and chosen.original_tokens is not None
        and chosen.original_tokens > chosen.threshold_tokens
    ):
        engine._event_append(
            session_id,
            "request.schema_capacity",
            {
                "round": rounds,
                "mode": chosen.mode,
                "reason": chosen.reason,
                "original_schema_tokens": chosen.original_tokens,
                "selected_schema_tokens": chosen.selected_tokens,
                "share_target_tokens": chosen.threshold_tokens,
                "token_source": chosen.token_source,
                "callable_count": len(schemas),
            },
        )
    return schemas, tools, chosen
