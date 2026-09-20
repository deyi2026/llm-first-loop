"""Deterministic pre-GREEN probes for P4-LIVE G2-S5 provider/discovery/execution scope."""

from __future__ import annotations

import importlib.util
import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus  # noqa: E402
from llm_loop.core.run_context import current_tool_discovery_scope  # noqa: E402
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry  # noqa: E402

EXPECTED_PATH = Path(__file__).with_name("GREEN2-S5-EXPECTED-FAILURES.v0.1.json")
CANARY_SCOPE_MODULE = "llm_loop.tools.p4_live_scope"


@dataclass(frozen=True)
class S5ProbeResult:
    channel_id: str
    state: str
    code: str
    facts: dict[str, Any]


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.parameters = {"type": "object", "properties": {}}
        self.calls = 0

    def execute(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.calls += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content="ok",
            tool_call_id="",
            tool_name=self.name,
        )


def load_expected() -> dict[str, Any]:
    return json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


def exact_canary_scope() -> frozenset[str]:
    return frozenset(str(name) for name in load_expected()["exact_canary_tools"])


def probe_provider_projection() -> S5ProbeResult:
    from llm_loop.core.loop.engine import LoopEngine

    source = inspect.getsource(LoopEngine._project_request_tools)
    reads_shared_scope = (
        "schemas_for_current_scope" in source
        or "current_tool_discovery_scope" in source
    )
    return S5ProbeResult(
        channel_id="G2S5-R13-PROVIDER",
        state="green" if reads_shared_scope else "red",
        code="contract_present" if reads_shared_scope else "main_provider_scope_bypass",
        facts={"main_projection_reads_shared_scope": reads_shared_scope},
    )


def probe_discovery() -> S5ProbeResult:
    reg = ToolRegistry()
    allowed = _Tool("browser_semantic_click")
    legacy = _Tool("browser_action")
    reg.register(allowed)
    reg.register(legacy)
    schema = GetToolSchemaTool(reg)
    token = current_tool_discovery_scope.set(frozenset({"browser_semantic_click"}))
    try:
        catalog = schema.execute(tool_name="*")
        denied = schema.execute(tool_name="browser_action")
    finally:
        current_tool_discovery_scope.reset(token)
    enforced = (
        "browser_semantic_click" in catalog.content
        and "browser_action" not in catalog.content
        and denied.status is ToolResultStatus.FAILURE
        and "当前执行域不可用" in denied.content
    )
    return S5ProbeResult(
        channel_id="G2S5-R13-DISCOVERY",
        state="green_prerequisite" if enforced else "red",
        code="discovery_scope_already_enforced" if enforced else "discovery_scope_bypass",
        facts={"get_tool_schema_scope_enforced": enforced},
    )


def probe_execution() -> S5ProbeResult:
    reg = ToolRegistry()
    allowed = _Tool("browser_semantic_click")
    legacy = _Tool("browser_action")
    reg.register(allowed)
    reg.register(legacy)
    token = current_tool_discovery_scope.set(frozenset({"browser_semantic_click"}))
    try:
        result = reg.execute(ToolCall(id="scope-bypass", name="browser_action", arguments={}))
    finally:
        current_tool_discovery_scope.reset(token)
    enforced = legacy.calls == 0 and result.status is ToolResultStatus.FAILURE
    return S5ProbeResult(
        channel_id="G2S5-R13-EXECUTION",
        state="green" if enforced else "red",
        code="contract_present" if enforced else "registry_execution_scope_bypass",
        facts={
            "legacy_tool_calls": legacy.calls,
            "registry_execution_scope_enforced": enforced,
            "result_status": result.status.value,
        },
    )


def probe_canary_scope_authority() -> S5ProbeResult:
    spec = importlib.util.find_spec(CANARY_SCOPE_MODULE)
    if spec is None:
        return S5ProbeResult(
            channel_id="G2S5-R13-CANARY-SCOPE",
            state="red",
            code="p4_live_canary_scope_authority_absent",
            facts={"module_present": False},
        )
    module = __import__(CANARY_SCOPE_MODULE, fromlist=["P4_LIVE_CANARY_TOOL_SCOPE"])
    actual = frozenset(getattr(module, "P4_LIVE_CANARY_TOOL_SCOPE", ()))
    exact = exact_canary_scope()
    valid = actual == exact
    return S5ProbeResult(
        channel_id="G2S5-R13-CANARY-SCOPE",
        state="green" if valid else "red",
        code="contract_present" if valid else "p4_live_canary_scope_authority_absent",
        facts={
            "module_present": True,
            "exact_scope_match": valid,
            "actual": sorted(actual),
            "expected": sorted(exact),
        },
    )


PROBES = (
    probe_provider_projection,
    probe_discovery,
    probe_execution,
    probe_canary_scope_authority,
)


def run_all() -> list[S5ProbeResult]:
    out: list[S5ProbeResult] = []
    for probe in PROBES:
        try:
            out.append(probe())
        except Exception as exc:  # noqa: BLE001 - harness errors must remain explicit.
            out.append(
                S5ProbeResult(
                    channel_id=probe.__name__,
                    state="harness_error",
                    code="harness_error",
                    facts={"exception_type": type(exc).__name__, "detail": str(exc)},
                )
            )
    return out
