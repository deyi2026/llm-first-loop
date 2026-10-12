"""A2 execution adapter; historical runner remains untouched."""

from __future__ import annotations

from scripts.calib import runner as base
from scripts.calib.treatments_a2 import build_system_prompt_a2


def execute_run_a2(*args, **kwargs):
    original = base.build_system_prompt
    base.build_system_prompt = build_system_prompt_a2
    try:
        return base.execute_run(*args, **kwargs)
    finally:
        base.build_system_prompt = original
