#!/usr/bin/env python3
"""FC2-C first-call-ready canary: observe one model declaration, execute no tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from protocol import (  # noqa: E402
    IMPLEMENTATION_COMMIT,
    MODEL_REF,
    SCHEMA,
    SEED,
    TASKS,
    build_plan,
    gate,
    judge,
    plan_sha256,
)

from llm_loop.browser.perception import SEMANTIC_OBJECT_KINDS  # noqa: E402
from llm_loop.core.prompt import build_system_prompt  # noqa: E402
from llm_loop.core.run_context import current_reasoning_effort, current_reasoning_mode  # noqa: E402
from llm_loop.llm.client import LLMClient  # noqa: E402
from llm_loop.llm.schemas import build_tools_schema  # noqa: E402
from llm_loop.tools.builtin.browser_semantic_operation import (  # noqa: E402
    BrowserSemanticOperationTool,
)
from llm_loop.tools.registry import ToolRegistry  # noqa: E402

PROVIDERS = REPO / "data" / "providers.json"
MODEL_PORT = 8901
V01_PLAN_SHA256 = "c802cf5137511c28a6875421ab18233c7976b79c12f82a10e5af380e4559d59c"


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha_bytes(raw)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def _tracked_dirty() -> list[str]:
    raw = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=REPO, text=True
    )
    return [line for line in raw.splitlines() if line.strip()]


def _model_server_fact() -> dict[str, Any]:
    lines = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines()
    matches = [line.strip() for line in lines if "mlx_lm.server" in line and f"--port {MODEL_PORT}" in line]
    if len(matches) != 1:
        raise RuntimeError(f"expected one mlx_lm.server on {MODEL_PORT}, observed={len(matches)}")
    pid_raw, command = matches[0].split(None, 1)
    parts = command.split()
    model_arg = parts[parts.index("--model") + 1] if "--model" in parts else ""
    return {
        "pid": int(pid_raw),
        "command_sha256": hashlib.sha256(command.encode()).hexdigest(),
        "model_basename": Path(model_arg).name if model_arg else "",
        "prompt_concurrency_1": "--prompt-concurrency 1" in command,
        "decode_concurrency_1": "--decode-concurrency 1" in command,
        "max_tokens_16000": "--max-tokens 16000" in command,
    }


def _established_8901() -> list[str]:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{MODEL_PORT}"], check=False, capture_output=True, text=True
    )
    return [line for line in proc.stdout.splitlines()[1:] if "LISTEN" not in line]


def _provider_contract() -> dict[str, Any]:
    doc = json.loads(PROVIDERS.read_text(encoding="utf-8"))
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


def _surface() -> dict[str, Any]:
    tool = BrowserSemanticOperationTool.__new__(BrowserSemanticOperationTool)
    reg = ToolRegistry()
    reg.register(tool)
    lazy_defs = reg.schemas(lazy=True)
    full_defs = reg.schemas(lazy=False)
    if [row["name"] for row in lazy_defs] != ["browser_semantic_operation"]:
        raise RuntimeError("FC2-C FCR surface must expose exactly browser_semantic_operation")
    tools = build_tools_schema(lazy_defs)
    params = lazy_defs[0]["parameters"]
    branches = params["properties"]["clauses"]["items"]["oneOf"]
    if len(branches) != 3:
        raise RuntimeError("FC2-C first-call branch count drift")
    if "input" not in SEMANTIC_OBJECT_KINDS or "textbox" in SEMANTIC_OBJECT_KINDS:
        raise RuntimeError("canonical semantic object kind vocabulary drift")
    return {
        "lazy_defs": lazy_defs,
        "full_defs": full_defs,
        "tools": tools,
        "lazy_sha256": _sha_json(lazy_defs),
        "full_sha256": _sha_json(full_defs),
        "wire_sha256": _sha_json(tools),
        "lazy_json_chars": len(json.dumps(lazy_defs, ensure_ascii=False, sort_keys=True)),
        "full_json_chars": len(json.dumps(full_defs, ensure_ascii=False, sort_keys=True)),
        "branch_count": len(branches),
        "canonical_kind_sha256": _sha_json(list(SEMANTIC_OBJECT_KINDS)),
        "canonical_kind_count": len(SEMANTIC_OBJECT_KINDS),
    }


def _source_hashes() -> dict[str, str]:
    paths = [
        HERE / "protocol.py",
        HERE / "PLAN.v0.2-FCR.json",
        HERE / "PROTOCOL.v0.2-FCR.md",
        HERE / "run_fcr.py",
        REPO / "src/llm_loop/browser/perception.py",
        REPO / "src/llm_loop/tools/builtin/browser_semantic_operation.py",
        REPO / "src/llm_loop/tools/registry.py",
        REPO / "src/llm_loop/llm/client.py",
        REPO / "src/llm_loop/llm/schemas.py",
        REPO / "src/llm_loop/core/prompt.py",
    ]
    return {str(path.relative_to(REPO)): _sha_file(path) for path in paths}


def execution_manifest(plan: list[dict[str, Any]]) -> dict[str, Any]:
    if plan_sha256(plan) != V01_PLAN_SHA256:
        raise RuntimeError("FC2-C FCR v0.2 matrix drifted from frozen v0.1")
    dirty = _tracked_dirty()
    if dirty:
        raise RuntimeError(f"tracked working tree dirty: {dirty}")
    head = _git("rev-parse", "HEAD")
    if _git("merge-base", head, IMPLEMENTATION_COMMIT) != IMPLEMENTATION_COMMIT:
        raise RuntimeError("experiment commit is not based on frozen FC2-C implementation")
    server = _model_server_fact()
    if server["model_basename"] != "Ornith-1.5-35B-A3B-MLX":
        raise RuntimeError(f"8901 is not frozen Ornith: {server['model_basename']}")
    if not all(server[key] for key in ("prompt_concurrency_1", "decode_concurrency_1", "max_tokens_16000")):
        raise RuntimeError("8901 runtime config drift")
    provider = _provider_contract()
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
    surface = _surface()
    return {
        "schema": SCHEMA + ".manifest",
        "experiment_git_head": head,
        "implementation_commit": IMPLEMENTATION_COMMIT,
        "tracked_dirty": False,
        "seed": SEED,
        "plan_sha256": plan_sha256(plan),
        "plan_rows": len(plan),
        "model_ref": MODEL_REF,
        "model_server": server,
        "provider_contract": provider,
        "surface": {key: value for key, value in surface.items() if key not in {"lazy_defs", "full_defs", "tools"}},
        "system_prompt_sha256": hashlib.sha256(build_system_prompt().encode()).hexdigest(),
        "source_sha256": _source_hashes(),
        "runtime": {
            "thinking_mode": "on",
            "reasoning_effort": "medium",
            "temperature": 0.0,
            "max_tokens": 16000,
            "serial_requests": True,
            "tool_execution": False,
            "fallbacks": 0,
        },
    }


def _client() -> LLMClient:
    provider = _provider_contract()
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
    if _git("rev-parse", "HEAD") != manifest["experiment_git_head"] or _tracked_dirty():
        raise RuntimeError("experiment identity drift before measured request")
    if _model_server_fact() != manifest["model_server"]:
        raise RuntimeError("8901 identity/config drift before measured request")
    if _established_8901():
        raise RuntimeError("8901 has another established client; serial FCR request refused")
    task = TASKS[str(row["task_id"])]
    surface = _surface()
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": task.prompt},
    ]
    client = _client()
    mode_token = current_reasoning_mode.set("on")
    effort_token = current_reasoning_effort.set("medium")
    started = time.monotonic()
    try:
        response = client.chat(messages, surface["tools"], timeout_s=1800)
    finally:
        current_reasoning_effort.reset(effort_token)
        current_reasoning_mode.reset(mode_token)
        client.close()
    calls = [{"name": call.name, "arguments": call.arguments} for call in response.tool_calls]
    oracle = judge(str(row["task_id"]), calls)
    status = "PASS" if oracle.get("pass") else "FCR_FAIL"
    return {
        **row,
        "schema": SCHEMA + ".row",
        "status": status,
        "oracle": oracle,
        "first_tool_calls": calls,
        "first_tool_call_count": len(calls),
        "tool_execution_count": 0,
        "fallback_used": False,
        "provider": response.provider,
        "finish_reason": response.finish_reason,
        "truncated": bool(response.truncated),
        "content_chars": len(response.content or ""),
        "content_sha256": hashlib.sha256((response.content or "").encode()).hexdigest(),
        "reasoning_chars": len(response.reasoning_content or ""),
        "reasoning_sha256": hashlib.sha256((response.reasoning_content or "").encode()).hexdigest(),
        "tokens_in": int(response.prompt_tokens or 0),
        "tokens_out": int(response.completion_tokens or 0),
        "cache_hit_tokens": int(response.prompt_cache_hit_tokens or 0),
        "reasoning_tokens": response.reasoning_tokens,
        "wall_s": round(time.monotonic() - started, 3),
    }


def _atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
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
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise RuntimeError("plan drift; refusing to mix evidence")
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise RuntimeError("manifest drift; refusing to mix evidence")
    _atomic_json(plan_path, plan)
    _atomic_json(manifest_path, manifest)
    if args.preflight:
        summary = {
            "preflight": True,
            "model_requests": 0,
            "experiment_git_head": manifest["experiment_git_head"],
            "implementation_commit": manifest["implementation_commit"],
            "plan_sha256": manifest["plan_sha256"],
            "lazy_surface_sha256": manifest["surface"]["lazy_sha256"],
            "wire_sha256": manifest["surface"]["wire_sha256"],
            "canonical_kind_count": manifest["surface"]["canonical_kind_count"],
            "tool_execution": False,
        }
        _atomic_json(root / "preflight.json", summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
        return 0

    results_path = root / "results.jsonl"
    rows = []
    if results_path.exists():
        rows = [json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]
    done = {int(row["index"]) for row in rows}
    pending = [row for row in plan if int(row["index"]) not in done][: args.max_new_rows]
    for row in pending:
        record = run_row(row, manifest)
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        rows.append(record)
        print(json.dumps({"index": row["index"], "task": row["task_id"], "repeat": row["repeat"], "status": record["status"], "oracle": record["oracle"].get("pass")}, sort_keys=True), flush=True)
    if len(rows) == len(plan):
        verdict = gate(rows)
        _atomic_json(root / "fcr-gate.json", verdict)
        print(json.dumps({"qualification_complete": True, "gate_pass": verdict["pass"]}, sort_keys=True), flush=True)
        return 0 if verdict["pass"] else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
