"""A2 Full-Slim confirmation treatments.

Full-Slim-v1 is mechanically fixed by frozen A1 result to Contract + DRU only.
"""

from __future__ import annotations

from scripts.calib.treatments import build_system_prompt
from scripts.calib.treatments_a1 import build_system_prompt_a1

A2_VARIANTS = [
    "B0-Baseline",
    "B1-Contract",
    "B2-Full-Slim-v1",
    "B3-Full-Reference",
]


def build_system_prompt_a2(variant: str) -> str:
    if variant == "B0-Baseline":
        return build_system_prompt("V0-Baseline")
    if variant == "B1-Contract":
        return build_system_prompt("V1-Contract")
    if variant == "B2-Full-Slim-v1":
        return build_system_prompt_a1("A2-Contract-DRU")
    if variant == "B3-Full-Reference":
        return build_system_prompt("V2-Full")
    raise ValueError(f"unknown A2 variant: {variant}")
