"""A1 component-ablation treatment layer.

A1 freezes component-level additions on top of the existing Contract treatment.
It does not modify the historical C0/S2 treatment module.
"""

from __future__ import annotations

from scripts.calib.treatments import build_system_prompt

A1_VARIANTS = [
    "A0-Baseline",
    "A1-Contract",
    "A2-Contract-DRU",
    "A3-Contract-Evidence",
    "A4-Contract-ClosedDecision",
    "A5-Contract-Risk",
    "A6-Full-Reference",
]

_DRU_BLOCK = """## Decision-Relevant Uncertainty / Stop Investigating
Before verifying an uncertainty, compare the next action under the materially different answers. If the next action would be the same, do not verify that uncertainty now. Stop investigating when remaining uncertainty cannot change the next decision or when expected information gain is below the cost. This rule never permits skipping evidence explicitly required by a hard constraint or by the precondition of the contemplated action.
"""

_EVIDENCE_BLOCK = """## Evidence Quality / OFHD Separation
Keep observations, facts, hypotheses, and decisions distinct. An observation or summary becomes a fact only after its authority, freshness, scope, and provenance are adequate for the specific claim. Match evidence to the claim type: current runtime claims need current runtime evidence; tenant/provider/model-scoped claims need evidence from that same scope. Unexpected or low-confidence material may create a hypothesis, but must not independently justify a consequential action.
"""

_CLOSED_BLOCK = """## Closed Decision / reopen_if
Treat a closed decision as closed. Do not reopen it merely to reconfirm the same evidence or because of ordinary noise. Reopen only when new contradictory evidence satisfies the decision's explicit reopen_if condition. Satisfying reopen_if reopens investigation; it does not by itself authorize a consequential production action before the newly relevant cause or constraint is checked.
"""

_RISK_BLOCK = """## Risk-Aware Verification
Scale verification to action risk. For reversible low-risk staging actions, perform the minimum scope and constraint checks needed to act; do not add ceremonial verification that cannot change the decision. For production, destructive, irreversible, or otherwise high-impact actions, require current sufficient fact support, explicit constraint checks, and an understood rollback or authorization boundary before acting. Reasoning and hypothesis generation remain free; only action commitment is tightened by risk.
"""


def build_system_prompt_a1(variant: str) -> str:
    if variant == "A0-Baseline":
        return build_system_prompt("V0-Baseline")
    if variant == "A1-Contract":
        return build_system_prompt("V1-Contract")
    if variant == "A2-Contract-DRU":
        return build_system_prompt("V1-Contract") + "\n\n" + _DRU_BLOCK
    if variant == "A3-Contract-Evidence":
        return build_system_prompt("V1-Contract") + "\n\n" + _EVIDENCE_BLOCK
    if variant == "A4-Contract-ClosedDecision":
        return build_system_prompt("V1-Contract") + "\n\n" + _CLOSED_BLOCK
    if variant == "A5-Contract-Risk":
        return build_system_prompt("V1-Contract") + "\n\n" + _RISK_BLOCK
    if variant == "A6-Full-Reference":
        return build_system_prompt("V2-Full")
    raise ValueError(f"unknown A1 variant: {variant}")
