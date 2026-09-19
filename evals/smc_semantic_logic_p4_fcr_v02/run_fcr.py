#!/usr/bin/env python3
"""P4-FCR declaration-only paired runner.

`--preflight` is intentionally model-free and writes only plan/manifest/preflight facts.
Formal row execution, if separately authorized later, requests one model response and never
executes returned Browser/tool calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from protocol import (  # noqa: E402
    ARM_A,
    ARM_B,
    ARM_B_TOOLS,
    MODEL_REF,
    P4_PROTOCOL_SHA256,
    P4D_BASE,
    PARENT_NEGATIVE,
    SCHEMA,
    SHARED_TOOLS,
    TASKS,
    build_plan,
    plan_sha256,
    score_first_response,
    sha_json,
)

from llm_loop.core.prompt import build_system_prompt  # noqa: E402
from llm_loop.core.run_context import current_reasoning_effort, current_reasoning_mode  # noqa: E402
from llm_loop.llm.client import LLMClient  # noqa: E402
from llm_loop.llm.schemas import build_tools_schema  # noqa: E402
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool  # noqa: E402
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool  # noqa: E402
from llm_loop.tools.builtin.browser_wait import (  # noqa: E402
    BrowserWaitObjectStateTool,
    BrowserWaitObjectTextTool,
    BrowserWaitScopeCountTool,
    BrowserWaitScopeReadyTool,
    BrowserWaitScopeUrlTool,
)
from llm_loop.tools.registry import GetToolSchemaTool, ToolRegistry  # noqa: E402

MODEL_PORT = 8901


@dataclass(frozen=True)
class _SchemaTool:
    name: str
    description: str
    parameters: dict[str, Any]


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _runtime_root() -> Path:
    common = Path(_git("rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (REPO / common).resolve()
    return common.parent


def _providers_path() -> Path:
    return _runtime_root() / "data" / "providers.json"


def _tracked_dirty() -> list[str]:
    raw = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    )
    return [line for line in raw.splitlines() if line.strip()]


def _model_server_fact() -> dict[str, Any]:
    lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    matches = [
        line.strip() for line in lines if "mlx_lm.server" in line and f"--port {MODEL_PORT}" in line
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one mlx_lm.server on {MODEL_PORT}, observed={len(matches)}")
    pid_raw, command = matches[0].split(None, 1)
    parts = command.split()
    model_arg = parts[parts.index("--model") + 1] if "--model" in parts else ""
    fact = {
        "pid": int(pid_raw),
        "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "model_basename": Path(model_arg).name if model_arg else "",
        "prompt_concurrency_1": "--prompt-concurrency 1" in command,
        "decode_concurrency_1": "--decode-concurrency 1" in command,
        "max_tokens_16000": "--max-tokens 16000" in command,
    }
    if fact["model_basename"] != "Ornith-1.5-35B-A3B-MLX":
        raise RuntimeError(f"8901 is not frozen Ornith: {fact['model_basename']}")
    if not all(
        fact[key] for key in ("prompt_concurrency_1", "decode_concurrency_1", "max_tokens_16000")
    ):
        raise RuntimeError("8901 runtime config drift")
    return fact


def _established_8901() -> list[str]:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{MODEL_PORT}"], check=False, capture_output=True, text=True
    )
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _provider_contract() -> dict[str, Any]:
    doc = json.loads(_providers_path().read_text(encoding="utf-8"))
    providers = doc.get("providers", doc) if isinstance(doc, dict) else {}
    provider = providers.get("cognilocal", {}) if isinstance(providers, dict) else {}
    models = provider.get("models") or {}
    model = models.get("ornith-1.5-35b-a3b-mlx", {}) if isinstance(models, dict) else {}
    return {
        "base_url": provider.get("base_url"),
        "timeout_s": provider.get("timeout_s"),
        "max_input_tokens": provider.get("max_input_tokens"),
        "max_tokens": provider.get("max_tokens"),
        "temperature": model.get("temperature"),
        "top_p": model.get("top_p"),
        "top_k": model.get("top_k"),
        "min_p": model.get("min_p"),
        "wire_protocol": model.get("wire_protocol"),
        "reasoning_control": model.get("reasoning_control"),
        "reasoning_capable": model.get("reasoning_capable"),
    }


def _assert_provider_contract(provider: dict[str, Any]) -> None:
    expected = {
        "base_url": "http://localhost:8901/v1",
        "timeout_s": 1800,
        "max_input_tokens": 184000,
        "max_tokens": 16000,
        "temperature": 0.0,
        "top_p": 1.0,
        "top_k": 0,
        "min_p": 0.0,
        "wire_protocol": "openai",
        "reasoning_control": "chat_template",
        "reasoning_capable": True,
    }
    if provider != expected:
        raise RuntimeError(f"provider contract drift: {provider}")


def _class_schema_tool(cls: type[Any]) -> _SchemaTool:
    return _SchemaTool(
        name=str(cls.name),
        description=str(cls.description),
        parameters=json.loads(json.dumps(cls.parameters)),
    )


def _shared_schema_tools() -> list[_SchemaTool]:
    classes = [
        BrowserPerceiveTool,
        BrowserWaitScopeUrlTool,
        BrowserWaitScopeReadyTool,
        BrowserWaitScopeCountTool,
        BrowserWaitObjectStateTool,
        BrowserWaitObjectTextTool,
        GetToolSchemaTool,
    ]
    tools = [_class_schema_tool(cls) for cls in classes]
    if [tool.name for tool in tools] != SHARED_TOOLS:
        raise RuntimeError("shared surface order drift")
    return tools


def _arm_registry(arm: str) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in _shared_schema_tools():
        registry.register(tool)
    if arm == ARM_A:
        registry.register(_class_schema_tool(BrowserSemanticExecuteTool))
    elif arm == ARM_B:
        for name, spec in ARM_B_TOOLS.items():
            registry.register(
                _SchemaTool(
                    name=name,
                    description=str(spec["description"]),
                    parameters=json.loads(json.dumps(spec["parameters"])),
                )
            )
    else:
        raise KeyError(arm)
    return registry


def _surface(arm: str) -> dict[str, Any]:
    registry = _arm_registry(arm)
    lazy_defs = registry.schemas(lazy=True)
    full_defs = registry.schemas(lazy=False)
    names = [str(row.get("name") or "") for row in lazy_defs]
    expected_names = SHARED_TOOLS + (
        ["browser_semantic_execute"] if arm == ARM_A else list(ARM_B_TOOLS)
    )
    if names != expected_names:
        raise RuntimeError(f"arm {arm} surface names drift: {names}")
    return {
        "names": names,
        "lazy_defs": lazy_defs,
        "full_defs": full_defs,
        "wire": build_tools_schema(lazy_defs),
        "lazy_sha256": sha_json(lazy_defs),
        "full_sha256": sha_json(full_defs),
        "wire_sha256": sha_json(build_tools_schema(lazy_defs)),
        "lazy_json_chars": len(json.dumps(lazy_defs, ensure_ascii=False, sort_keys=True)),
        "wire_json_chars": len(
            json.dumps(build_tools_schema(lazy_defs), ensure_ascii=False, sort_keys=True)
        ),
        "tool_count": len(names),
        "tool_sha256": {str(row["name"]): sha_json(row) for row in lazy_defs},
    }


def _validate_surface_pair(a: dict[str, Any], b: dict[str, Any]) -> None:
    for shared in SHARED_TOOLS:
        if a["tool_sha256"].get(shared) != b["tool_sha256"].get(shared):
            raise RuntimeError(f"shared provider surface drift: {shared}")
    a_schema = next(row for row in a["lazy_defs"] if row["name"] == "browser_semantic_execute")
    if set((a_schema["parameters"] or {}).get("properties") or {}) != {
        "verb",
        "target_ref",
        "args",
    }:
        raise RuntimeError("Arm A semantic_execute contract drift")
    for name, frozen in ARM_B_TOOLS.items():
        b_schema = next(row for row in b["full_defs"] if row["name"] == name)
        if b_schema["parameters"] != frozen["parameters"]:
            raise RuntimeError(f"Arm B logical schema drift: {name}")


def _source_hashes() -> dict[str, str]:
    paths = [
        HERE / "protocol.py",
        HERE / "run_fcr.py",
        HERE / "analyze.py",
        HERE / "PROTOCOL.v0.2-ACTIONREF.json",
        HERE / "PLAN.v0.2-FCR.json",
        REPO / "docs/SMC-SEMANTIC-LOGIC-P4-FCR-v0.2-ACTIONREF-PROTOCOL-20260919.md",
        REPO / "tools/semantic_logic/p4d_typed_compiler.py",
        REPO / "tools/semantic_logic/p4_fcr_v02_actionref_compiler.py",
        REPO / "src/llm_loop/tools/builtin/browser_perceive.py",
        REPO / "src/llm_loop/tools/builtin/browser_wait.py",
        REPO / "src/llm_loop/tools/builtin/browser_semantic_execute.py",
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "src/llm_loop/llm/client.py",
        REPO / "src/llm_loop/llm/schemas.py",
        REPO / "src/llm_loop/core/prompt.py",
    ]
    return {str(path.relative_to(REPO)): _sha_file(path) for path in paths}


def execution_manifest(plan: list[dict[str, Any]]) -> dict[str, Any]:
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked working tree dirty: {dirty}")
    head = _git("rev-parse", "HEAD")
    if _git("merge-base", head, P4D_BASE) != P4D_BASE:
        raise RuntimeError("P4-FCR branch is not based on exact qualified P4-D")
    if _git("merge-base", head, PARENT_NEGATIVE) != PARENT_NEGATIVE:
        raise RuntimeError("P4-FCR v0.2 branch is not based on exact v0.1 negative result")
    protocol_path = HERE / "PROTOCOL.v0.2-ACTIONREF.json"
    if _sha_file(protocol_path) != P4_PROTOCOL_SHA256:
        raise RuntimeError("frozen P4-FCR v0.2 protocol hash drift")
    provider = _provider_contract()
    _assert_provider_contract(provider)
    server = _model_server_fact()
    if _established_8901():
        raise RuntimeError(
            "8901 has an established client; preflight refuses a contaminated window"
        )
    surface_a = _surface(ARM_A)
    surface_b = _surface(ARM_B)
    _validate_surface_pair(surface_a, surface_b)
    plan_hash = plan_sha256(plan)
    frozen_plan_path = HERE / "PLAN.v0.2-FCR.json"
    frozen_plan = json.loads(frozen_plan_path.read_text(encoding="utf-8"))
    if frozen_plan != plan:
        raise RuntimeError("generated plan differs from frozen PLAN.v0.2-FCR.json")
    return {
        "schema": SCHEMA + ".execution_manifest",
        "experiment_git_head": head,
        "p4d_base": P4D_BASE,
        "parent_negative": PARENT_NEGATIVE,
        "tracked_dirty": False,
        "protocol_sha256": P4_PROTOCOL_SHA256,
        "plan_sha256": plan_hash,
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "system_prompt_sha256": hashlib.sha256(build_system_prompt().encode("utf-8")).hexdigest(),
        "surfaces": {
            ARM_A: {
                k: v for k, v in surface_a.items() if k not in {"lazy_defs", "full_defs", "wire"}
            },
            ARM_B: {
                k: v for k, v in surface_b.items() if k not in {"lazy_defs", "full_defs", "wire"}
            },
        },
        "shared_surface_identical": True,
        "source_sha256": _source_hashes(),
        "task_prompt_sha256": {
            task_id: hashlib.sha256(task.prompt.encode("utf-8")).hexdigest()
            for task_id, task in TASKS.items()
        },
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "temperature": 0.0,
            "input_token_budget": 184000,
            "output_token_budget": 16000,
            "serial_requests": True,
            "tool_execution_total_required": 0,
            "browser_runtime_required": False,
            "fallbacks": 0,
            "normalization": False,
            "retry": False,
            "task_completion_judgment": False,
        },
    }


def _client(provider: dict[str, Any]) -> LLMClient:
    return LLMClient(
        api_key="",
        base_url=str(provider["base_url"]),
        model="ornith-1.5-35b-a3b-mlx",
        timeout_s=float(provider["timeout_s"]),
        max_tokens=int(provider["max_tokens"]),
        temperature=float(provider["temperature"]),
        top_p=float(provider["top_p"]),
        top_k=int(provider["top_k"]),
        min_p=float(provider["min_p"]),
        provider="cognilocal",
        wire_protocol=str(provider["wire_protocol"]),
        reasoning_capable=bool(provider["reasoning_capable"]),
        reasoning_control=str(provider["reasoning_control"]),
        guard_enabled=False,
    )


def run_row(row: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """One separately-authorized future FCR request; returned calls are never executed."""

    if _git("rev-parse", "HEAD") != manifest["experiment_git_head"] or _tracked_dirty():
        raise RuntimeError("experiment identity drift before model request")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 identity/config drift before model request")
    if _established_8901():
        raise RuntimeError("8901 has another established client; serial request refused")
    arm = str(row["arm"])
    task_id = str(row["task_id"])
    surface = _surface(arm)
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": TASKS[task_id].prompt},
    ]
    client = _client(manifest["provider_contract"])
    mode_token = current_reasoning_mode.set("on")
    effort_token = current_reasoning_effort.set("medium")
    started = time.monotonic()
    try:
        response = client.chat(messages, surface["wire"], timeout_s=1800)
    finally:
        current_reasoning_effort.reset(effort_token)
        current_reasoning_mode.reset(mode_token)
        client.close()
    calls = [{"name": call.name, "arguments": call.arguments} for call in response.tool_calls]
    score = score_first_response(task_id=task_id, arm=arm, calls=calls)
    return {
        **row,
        "schema": SCHEMA + ".row",
        "score": score,
        "raw_first_tool_calls": calls,
        "tool_execution_count": 0,
        "browser_runtime_used": False,
        "fallback_used": False,
        "provider": response.provider,
        "finish_reason": response.finish_reason,
        "truncated": bool(response.truncated),
        "tokens_in": int(response.prompt_tokens or 0),
        "tokens_out": int(response.completion_tokens or 0),
        "cache_hit_tokens": int(response.prompt_cache_hit_tokens or 0),
        "wall_s": round(time.monotonic() - started, 3),
    }


def _atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--max-new-rows", type=int, default=1)
    args = parser.parse_args()
    if args.max_new_rows < 0:
        parser.error("--max-new-rows must be >= 0")
    root = Path(args.workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    plan = build_plan()
    manifest = execution_manifest(plan)
    plan_path = root / "plan.json"
    manifest_path = root / "execution-manifest.json"
    if plan_path.exists() and json.loads(plan_path.read_text(encoding="utf-8")) != plan:
        raise RuntimeError("plan drift; refusing to mix evidence")
    if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
        raise RuntimeError("manifest drift; refusing to mix evidence")
    _atomic_json(plan_path, plan)
    _atomic_json(manifest_path, manifest)
    if args.preflight:
        summary = {
            "schema": SCHEMA + ".preflight",
            "preflight": True,
            "model_requests": 0,
            "tool_execution_total": 0,
            "browser_runtime_used": False,
            "experiment_git_head": manifest["experiment_git_head"],
            "p4d_base": manifest["p4d_base"],
            "parent_negative": manifest["parent_negative"],
            "plan_rows": manifest["plan_rows"],
            "plan_sha256": manifest["plan_sha256"],
            "surface_a_sha256": manifest["surfaces"][ARM_A]["wire_sha256"],
            "surface_b_sha256": manifest["surfaces"][ARM_B]["wire_sha256"],
            "shared_surface_identical": manifest["shared_surface_identical"],
            "results_present": (root / "results.jsonl").exists(),
            "qualification_gate_present": (root / "fcr-gate.json").exists(),
            "measured_row_dirs": len(
                [p for p in root.iterdir() if p.is_dir() and p.name.startswith("row-")]
            ),
        }
        _atomic_json(root / "preflight.json", summary)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
        return 0

    results_path = root / "results.jsonl"
    existing = []
    if results_path.exists():
        existing = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    done = {int(row["index"]) for row in existing}
    pending = [row for row in plan if int(row["index"]) not in done][: args.max_new_rows]
    for row in pending:
        record = run_row(row, manifest)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        print(
            json.dumps({"index": row["index"], "task": row["task_id"], "arm": row["arm"]}),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
