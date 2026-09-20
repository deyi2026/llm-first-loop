"""Deterministic pre-GREEN structural probes for P4-LIVE G2-S4."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXPECTED_PATH = Path(__file__).with_name("GREEN2-S4-EXPECTED-FAILURES.v0.1.json")
MODULE = "llm_loop.tools.builtin.browser_action_ref_mutation"
TOOL_NAMES = (
    "browser_semantic_click",
    "browser_semantic_fill",
    "browser_semantic_select",
    "browser_semantic_scroll",
    "browser_semantic_navigate",
)


@dataclass(frozen=True)
class S4Probe:
    row_id: str
    contract_satisfied: bool
    failure_code: str
    facts: dict[str, Any]


def expected_failures() -> dict[str, str]:
    doc = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {str(row["id"]): str(row["code"]) for row in doc["rows"]}


S4_RED_IDS = tuple(expected_failures())


def _module_source() -> tuple[bool, str]:
    spec = importlib.util.find_spec(MODULE)
    if spec is None:
        return False, ""
    module = __import__(MODULE, fromlist=["*"])
    return True, inspect.getsource(module)


def probe_tools() -> S4Probe:
    present, source = _module_source()
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    declared = present and all(name in source for name in TOOL_NAMES)
    wired = all(f'"{name}"' in factory for name in TOOL_NAMES)
    ok = declared and wired
    return S4Probe(
        "G2S4-TYPED-TOOLS", ok,
        "contract_present" if ok else "actionref_typed_mutation_tools_absent",
        {"module_present": present, "all_five_declared": declared, "all_five_factory_wired": wired},
    )


def probe_gate() -> S4Probe:
    config = (ROOT / "src/llm_loop/config.py").read_text(encoding="utf-8")
    factory = (ROOT / "src/llm_loop/factory.py").read_text(encoding="utf-8")
    field = "browser_action_ref_mutation_enabled: bool = False" in config
    env = "LFL_BROWSER_ACTION_REF_MUTATION_ENABLED" in config
    used = "browser_action_ref_mutation_enabled" in factory
    ok = field and env and used
    return S4Probe(
        "G2S4-MUTATION-GATE", ok,
        "contract_present" if ok else "actionref_mutation_gate_absent",
        {"default_off_field": field, "env_loader": env, "factory_gate": used},
    )


def probe_kernel() -> S4Probe:
    present, source = _module_source()
    tokens = (
        "current_action_ref_effect_binding_authority",
        "ActionRefResolveContext",
        "compile_resolved",
        "prepare_current",
        "arm_receipt_cursor",
        "bind_observed_target",
        ".execute(",
    )
    ordered = present and all(token in source for token in tokens)
    forbidden = [
        token for token in ("selector", "similarity", "latest_target", "successor", "rebind_target")
        if token in source
    ]
    ok = ordered and not forbidden
    return S4Probe(
        "G2S4-ORDERED-KERNEL", ok,
        "contract_present" if ok else "actionref_ordered_mutation_kernel_absent",
        {"module_present": present, "required_tokens_present": ordered, "forbidden_tokens": forbidden},
    )


PROBES = {
    "G2S4-TYPED-TOOLS": probe_tools,
    "G2S4-MUTATION-GATE": probe_gate,
    "G2S4-ORDERED-KERNEL": probe_kernel,
}


def run_probe(row_id: str) -> S4Probe:
    try:
        return PROBES[row_id]()
    except Exception as exc:  # noqa: BLE001
        return S4Probe(row_id, False, "harness_error", {"error": f"{type(exc).__name__}: {exc}"})
