"""I0 closed contracts for an *unwired* task-root budget authority.

These types do not grant provider, tool, schedule or cancellation authority.
Missing resource limits mean NOT QUALIFIED, never an assumed infinite balance.
See docs/DESIGN-20261009-provider-tool-budget-authority-v1.md.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"{name} must be a non-empty, bounded identifier")


def _text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"{name} must be non-empty text of at most 256 chars")


def _ceiling(name: str, value: int | None) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{name} must be a non-negative integer or unqualified (None)")


class BudgetDimension(StrEnum):
    LOGICAL_CALLS = "logical_calls"
    PHYSICAL_ATTEMPTS = "physical_attempts"
    ROUNDS = "rounds"
    TOOL_INVOCATIONS = "tool_invocations"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    PAYLOAD_BYTES = "payload_bytes"


ACTION_DIMENSIONS = frozenset({
    BudgetDimension.LOGICAL_CALLS,
    BudgetDimension.PHYSICAL_ATTEMPTS,
    BudgetDimension.ROUNDS,
    BudgetDimension.TOOL_INVOCATIONS,
})
MEASURE_DIMENSIONS = frozenset({
    BudgetDimension.INPUT_TOKENS,
    BudgetDimension.OUTPUT_TOKENS,
    BudgetDimension.PAYLOAD_BYTES,
})


class BudgetPhase(StrEnum):
    ISSUED = "issued"
    ACTIVE = "active"
    STOP_REQUESTED = "stop_requested"
    SETTLING = "settling"
    CLOSED_UNCERTAIN = "closed_uncertain"
    # I1 deliberately has NO transition to closed_verified: physical
    # transport, external effects and cancelled workers aren't wired yet.


class ReservationPhase(StrEnum):
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    SETTLED = "settled"
    UNKNOWN = "unknown"
    ABORTED_BEFORE_DISPATCH = "aborted_before_dispatch"


@dataclass(frozen=True)
class TaskBudgetLimits:
    logical_calls: int | None = None
    physical_attempts: int | None = None
    rounds: int | None = None
    tool_invocations: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    payload_bytes: int | None = None

    def __post_init__(self) -> None:
        for d in BudgetDimension:
            _ceiling(d.value, getattr(self, d.value))

    def to_dict(self) -> dict[str, int | None]:
        return {d.value: getattr(self, d.value) for d in BudgetDimension}

    @classmethod
    def from_dict(cls, value: Any) -> TaskBudgetLimits:
        if not isinstance(value, dict) or set(value) != {d.value for d in BudgetDimension}:
            raise ValueError("invalid budget limit fields")
        return cls(**value)

    def tighter_than(self, old: TaskBudgetLimits) -> bool:
        for dimension in BudgetDimension:
            before, after = getattr(old, dimension.value), getattr(self, dimension.value)
            if before is not None and (after is None or after > before):
                return False
        return True


@dataclass(frozen=True)
class TaskBudgetCapabilities:
    # None: not restricted by THIS layer; frozenset(): explicit deny-all.
    # This distinction is necessary even though no tool gate is wired in I1.
    allowed_tools: frozenset[str] | None = frozenset()
    allow_wake: bool = False
    allow_subagents: bool = False

    def __post_init__(self) -> None:
        if self.allowed_tools is not None:
            if not isinstance(self.allowed_tools, frozenset):
                raise TypeError("allowed_tools must be frozenset or None")
            for name in self.allowed_tools:
                _identifier("tool id", name)
        if type(self.allow_wake) is not bool or type(self.allow_subagents) is not bool:
            raise TypeError("capability flags must be actual booleans")

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed_tools": (
                None if self.allowed_tools is None else sorted(self.allowed_tools)
            ),
            "allow_wake": self.allow_wake,
            "allow_subagents": self.allow_subagents,
        }

    @classmethod
    def from_dict(cls, value: Any) -> TaskBudgetCapabilities:
        if not isinstance(value, dict) or set(value) != {
            "allowed_tools", "allow_wake", "allow_subagents"
        }:
            raise ValueError("invalid capability fields")
        names = value["allowed_tools"]
        if names is not None and (
            not isinstance(names, list)
            or any(not isinstance(name, str) or not _ID_PATTERN.fullmatch(name) for name in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("allowed_tools must be distinct names or null")
        return cls(
            allowed_tools=None if names is None else frozenset(names),
            allow_wake=value["allow_wake"],
            allow_subagents=value["allow_subagents"],
        )

    def tighter_than(self, old: TaskBudgetCapabilities) -> bool:
        if old.allowed_tools is not None and (
            self.allowed_tools is None or not self.allowed_tools <= old.allowed_tools
        ):
            return False
        return (
            (old.allow_wake or not self.allow_wake)
            and (old.allow_subagents or not self.allow_subagents)
        )


@dataclass(frozen=True)
class TaskBudgetGrant:
    budget_id: str
    issuer: str
    authority_source: str
    workspace_scope: str
    session_id: str
    human_turn_ref: str
    surface: str
    profile: str
    policy_version: str
    deadline_epoch_s: float
    limits: TaskBudgetLimits
    capabilities: TaskBudgetCapabilities
    generation: int = 1
    provider_identity: str = ""
    exact_model_ref: str = ""

    def __post_init__(self) -> None:
        for name in ("budget_id", "workspace_scope", "session_id", "human_turn_ref"):
            _identifier(name, getattr(self, name))
        for name in ("issuer", "authority_source", "surface", "profile", "policy_version"):
            _text(name, getattr(self, name))
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be positive integer")
        if (
            isinstance(self.deadline_epoch_s, bool)
            or not isinstance(self.deadline_epoch_s, (int, float))
            or not math.isfinite(self.deadline_epoch_s)
            or self.deadline_epoch_s <= 0
        ):
            raise ValueError("deadline_epoch_s must be a finite positive epoch")
        if not isinstance(self.limits, TaskBudgetLimits):
            raise TypeError("limits must be TaskBudgetLimits")
        if not isinstance(self.capabilities, TaskBudgetCapabilities):
            raise TypeError("capabilities must be TaskBudgetCapabilities")
        if (
            not isinstance(self.provider_identity, str)
            or not isinstance(self.exact_model_ref, str)
            or len(self.provider_identity) > 256
            or len(self.exact_model_ref) > 256
        ):
            raise ValueError("provider/model labels must be bounded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "issuer": self.issuer,
            "authority_source": self.authority_source,
            "workspace_scope": self.workspace_scope,
            "session_id": self.session_id,
            "human_turn_ref": self.human_turn_ref,
            "surface": self.surface,
            "profile": self.profile,
            "policy_version": self.policy_version,
            "deadline_epoch_s": self.deadline_epoch_s,
            "limits": self.limits.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "generation": self.generation,
            "provider_identity": self.provider_identity,
            "exact_model_ref": self.exact_model_ref,
        }

    @classmethod
    def from_dict(cls, value: Any) -> TaskBudgetGrant:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid grant fields")
        return cls(
            **{
                **value,
                "limits": TaskBudgetLimits.from_dict(value["limits"]),
                "capabilities": TaskBudgetCapabilities.from_dict(value["capabilities"]),
            }
        )


@dataclass(frozen=True)
class TaskBudgetMember:
    member_id: str
    parent_id: str
    workspace_scope: str
    session_id: str
    run_generation: str
    ingress_ref: str
    ingress_kind: str
    schedule_sid: str = ""

    def __post_init__(self) -> None:
        for name in ("member_id", "parent_id", "workspace_scope", "session_id"):
            _identifier(name, getattr(self, name))
        for name in ("run_generation", "ingress_ref", "ingress_kind"):
            _text(name, getattr(self, name))
        if self.ingress_kind == "scheduled:schedule_wake":
            _identifier("schedule_sid", self.schedule_sid)
        elif self.schedule_sid:
            raise ValueError("schedule_sid requires scheduled:schedule_wake ingress")

    def to_dict(self) -> dict[str, str]:
        return {
            "member_id": self.member_id,
            "parent_id": self.parent_id,
            "workspace_scope": self.workspace_scope,
            "session_id": self.session_id,
            "run_generation": self.run_generation,
            "ingress_ref": self.ingress_ref,
            "ingress_kind": self.ingress_kind,
            "schedule_sid": self.schedule_sid,
        }

    @classmethod
    def from_dict(cls, value: Any) -> TaskBudgetMember:
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ValueError("invalid member fields")
        return cls(**value)
