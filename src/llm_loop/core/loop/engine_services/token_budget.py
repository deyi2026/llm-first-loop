"""Token-native input budget helpers.

This module owns only mechanical capacity projection:
- input tokens remain the authority;
- chars/token is an observed projection bridge for the existing char history projector;
- no semantic history/tool selection happens here.
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectionDensityDecision:
    chars_per_token: float
    source: str
    samples: int


@dataclass(slots=True)
class _DensityState:
    ratios: deque[float]
    ewma: float | None = None
    applied: float | None = None
    total_samples: int = 0


class ProjectionDensityTracker:
    """Bounded provider/model/wire chars-per-token calibration.

    Lower chars/token is the conservative direction because the same char payload then
    represents more tokens. A lower observed candidate therefore tightens immediately,
    while upward relaxation is delayed and step-bounded.
    """

    def __init__(
        self,
        *,
        window: int = 32,
        min_samples: int = 8,
        ewma_alpha: float = 0.2,
        ewma_lower_factor: float = 0.90,
        upper_deadband: float = 0.05,
        max_up_step: float = 0.25,
        max_surfaces: int = 64,
    ) -> None:
        self.window = max(8, int(window))
        self.min_samples = max(2, int(min_samples))
        self.ewma_alpha = min(1.0, max(0.01, float(ewma_alpha)))
        self.ewma_lower_factor = min(1.0, max(0.1, float(ewma_lower_factor)))
        self.upper_deadband = min(1.0, max(0.0, float(upper_deadband)))
        self.max_up_step = min(1.0, max(0.01, float(max_up_step)))
        self.max_surfaces = max(8, int(max_surfaces))
        self._states: OrderedDict[tuple[str, str, str], _DensityState] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(provider: str, model: str, wire_protocol: str) -> tuple[str, str, str]:
        return (
            str(provider or "").strip().lower(),
            str(model or "").strip().lower(),
            str(wire_protocol or "openai").strip().lower(),
        )

    @staticmethod
    def _p20(values: deque[float]) -> float:
        ordered = sorted(values)
        idx = int((len(ordered) - 1) * 0.20)
        return ordered[idx]

    def observe(
        self,
        provider: str,
        model: str,
        wire_protocol: str,
        *,
        provider_visible_chars: int,
        prompt_tokens: int,
    ) -> None:
        chars = int(provider_visible_chars or 0)
        tokens = int(prompt_tokens or 0)
        if chars <= 0 or tokens <= 0:
            return
        ratio = chars / tokens
        if not math.isfinite(ratio) or ratio <= 0:
            return
        key = self._key(provider, model, wire_protocol)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _DensityState(ratios=deque(maxlen=self.window))
                self._states[key] = state
                while len(self._states) > self.max_surfaces:
                    self._states.popitem(last=False)
            else:
                self._states.move_to_end(key)
            state.ratios.append(ratio)
            state.total_samples += 1
            state.ewma = (
                ratio
                if state.ewma is None
                else (self.ewma_alpha * ratio) + ((1.0 - self.ewma_alpha) * state.ewma)
            )

    def decision(
        self,
        provider: str,
        model: str,
        wire_protocol: str,
        *,
        fallback_chars_per_token: float,
    ) -> ProjectionDensityDecision:
        fallback = max(0.01, float(fallback_chars_per_token or 0.01))
        key = self._key(provider, model, wire_protocol)
        with self._lock:
            state = self._states.get(key)
            if state is not None:
                self._states.move_to_end(key)
            recent_samples = len(state.ratios) if state is not None else 0
            total_samples = state.total_samples if state is not None else 0
            if state is None or recent_samples < self.min_samples or state.ewma is None:
                return ProjectionDensityDecision(fallback, "configured_fallback", total_samples)
            candidate = min(
                self._p20(state.ratios),
                state.ewma * self.ewma_lower_factor,
            )
            candidate = max(0.01, candidate)
            current = state.applied if state.applied is not None else fallback
            if candidate < current:
                applied = candidate
            elif candidate <= current * (1.0 + self.upper_deadband):
                applied = current
            else:
                applied = min(candidate, current * (1.0 + self.max_up_step))
            state.applied = applied
            return ProjectionDensityDecision(
                applied,
                "observed_lower_bound",
                total_samples,
            )


@dataclass(frozen=True, slots=True)
class ToolBudgetReservation:
    tool_schema_reserve_tokens: int
    history_token_budget: int
    projected_history_chars: int
    effective_history_budget_chars: int


def reserve_history_after_tools(
    *,
    allowed_input_tokens: int | None,
    pre_tool_history_budget_chars: int,
    tool_schema_chars: int,
    tool_schema_tokens: int | None = None,
    projection_chars_per_token: float,
) -> ToolBudgetReservation:
    """Reserve tool-schema capacity in tokens, then bridge remaining history to chars.

    ``tool_schema_tokens`` is an optional provider/tokenizer authority.  When present it
    owns the schema reserve directly; ``projection_chars_per_token`` remains only the
    bridge for the history projector.  When absent, preserve the historical conservative
    char-density fallback for providers without tokenizer authority.
    """
    pre_tool_chars = max(1, int(pre_tool_history_budget_chars or 0))
    allowed = int(allowed_input_tokens or 0)
    cpt = float(projection_chars_per_token or 0)
    if allowed <= 0 or cpt <= 0 or not math.isfinite(cpt):
        return ToolBudgetReservation(
            tool_schema_reserve_tokens=0,
            history_token_budget=max(0, allowed),
            projected_history_chars=pre_tool_chars,
            effective_history_budget_chars=pre_tool_chars,
        )
    if isinstance(tool_schema_tokens, int) and tool_schema_tokens >= 0:
        tool_tokens = tool_schema_tokens
    else:
        tool_tokens = max(0, math.ceil(max(0, int(tool_schema_chars or 0)) / cpt))
    history_tokens = max(0, allowed - tool_tokens)
    projected_chars = max(1, math.floor(history_tokens * cpt))
    return ToolBudgetReservation(
        tool_schema_reserve_tokens=tool_tokens,
        history_token_budget=history_tokens,
        projected_history_chars=projected_chars,
        effective_history_budget_chars=min(pre_tool_chars, projected_chars),
    )
