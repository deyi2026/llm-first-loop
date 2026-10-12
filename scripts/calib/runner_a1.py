"""A1 execution adapter.

Reuses the frozen provider/tool-loop mechanics from scripts.calib.runner while
swapping only the system-prompt builder inside this single-threaded process.
No historical runner source is modified.
"""
from __future__ import annotations

from scripts.calib import runner as base
from scripts.calib.treatments_a1 import build_system_prompt_a1


def execute_run_a1(*args, **kwargs):
    original = base.build_system_prompt
    base.build_system_prompt = build_system_prompt_a1
    try:
        return base.execute_run(*args, **kwargs)
    finally:
        base.build_system_prompt = original
