"""M2 goal binding: a claim is only valid for the goal it was observed against.

The M1 runner cached `tray_pos` once before the action loop and judged every
later placement against that first pose. When the tray moves (an external agent
may move it at any time) the cached pose silently becomes a *different* goal,
so a local verdict could be issued for a place that never happened, or a real
place could be rejected forever.

A GoalBinding is an observation-derived identity for the target:
  * `pos`         canonicalised pose (1e-6 m) — stable against float noise
  * `digest`      sha256 over (kind, pos) — tamper-evident in a receipt
  * `scene_epoch` the epoch the pose was observed in (reset invalidates it)
  * `version`     monotonic count of accepted rebinds within one episode

Binding is not verification: the digest proves *which* goal a claim is about,
never that the claim is true. Physical truth still comes only from the Oracle.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

GOAL_KIND = "tray_a"
_POS_DIGITS = 6


def canonical_pos(pos: Sequence[float]) -> list[float]:
    """Round to 1e-6 m so observation float noise cannot forge a goal change."""
    return [round(float(v), _POS_DIGITS) for v in list(pos)[:3]]


def goal_digest(kind: str, pos: Sequence[float]) -> str:
    payload = {"kind": str(kind), "pos": canonical_pos(pos)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class GoalBinding:
    kind: str
    pos: tuple[float, ...]
    digest: str
    scene_epoch: int
    version: int

    def receipt_fields(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "pos": list(self.pos),
            "digest": self.digest,
            "scene_epoch": int(self.scene_epoch),
            "version": int(self.version),
        }


def bind_goal(scene: Any, *, version: int) -> GoalBinding:
    """Observe the target now and bind it to the current scene epoch."""
    pos = tuple(canonical_pos(scene.observe()["tray_pos"]))
    return GoalBinding(
        kind=GOAL_KIND,
        pos=pos,
        digest=goal_digest(GOAL_KIND, pos),
        scene_epoch=int(scene.scene_epoch),
        version=int(version),
    )


def same_goal(a: GoalBinding, b: GoalBinding) -> bool:
    return a.digest == b.digest and int(a.scene_epoch) == int(b.scene_epoch)
