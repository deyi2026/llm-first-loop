#!/usr/bin/env python3
"""P4-LIVE v0.2 zero-action preflight. No model request or Browser mutation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.target_identity import (
    browser_target_id_sha256,
    raw_browser_target_id_from_page_token,
)
from llm_loop.config import load_settings
from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.factory import build_engine
from llm_loop.tools.p4_live_scope import P4_LIVE_CANARY_TOOL_SCOPE, p4_live_canary_tool_scope
from scripts.qualification.smc_browser_live_navigation import (
    _free_loopback_port,
    _wait_page,
    chrome_args,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = "faffd569d6d5a99c6bde9fdf68348c56aef92df3"
NEGATIVE = "9a11fe4c43cc83f53bf2baf62d0782c91e1d4242"
EXPECTED_NEGATIVE_HASHES = {
    "evals/smc_semantic_logic_p4_live/results/P4-LIVE-QUALIFICATION-v0.1-20260920/LIVE-RESULT.json": "0c9d32e7d4c1fef7223c35a0f9c13e64c19b4cd1db9b1d21b8bbb763d2598689",
    "evals/smc_semantic_logic_p4_live/results/P4-LIVE-QUALIFICATION-v0.1-20260920/TARGET-IDENTITY-ADJUDICATION.json": "799bcec754a84471eb7a5bfec831f76172d8a863ee823e919c269401b93890d6",
}
EXPECTED_R12_SOURCE_HASHES = {
    "src/llm_loop/browser/action_ref.py": "c16d4d540ab3ff78ae99c0dc1d20fcb42820e2179f8034b676549d5c7dc6b65d",
    "src/llm_loop/browser/cdp_action_host.py": "594b41e7ed7955e5133e9ad9d2adf6a9abf6130a8f3351d9cbe68a6021c19cbb",
    "src/llm_loop/browser/target_identity.py": "bfed11a8f63de4c57db60ac2d5f00fe75ac554f2ecbf8a9bf1255d7423e76f44",
}
LEGACY = {"browser_action", "browser_semantic_execute", "browser_semantic_operation"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _model_server_fact() -> dict[str, Any]:
    matches: list[list[str]] = []
    for line in subprocess.check_output(["ps", "-axo", "pid=,command="], text=True).splitlines():
        parts = line.strip().split()
        if (
            len(parts) > 4
            and Path(parts[1]).name.lower() in {"python", "python3"}
            and parts[2:4] == ["-m", "mlx_lm.server"]
            and "--port" in parts
            and parts[parts.index("--port") + 1] == "8901"
        ):
            matches.append(parts)
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one mlx_lm.server on 8901, observed={len(matches)}")
    parts = matches[0]
    model = parts[parts.index("--model") + 1] if "--model" in parts else ""
    fact = {
        "count": 1,
        "model_basename": Path(model).name,
        "prompt_concurrency_1": "--prompt-concurrency" in parts and parts[parts.index("--prompt-concurrency") + 1] == "1",
        "decode_concurrency_1": "--decode-concurrency" in parts and parts[parts.index("--decode-concurrency") + 1] == "1",
        "max_tokens_16000": "--max-tokens" in parts and parts[parts.index("--max-tokens") + 1] == "16000",
    }
    if fact["model_basename"] != "Ornith-1.5-35B-A3B-MLX":
        raise RuntimeError(f"unexpected 8901 model: {fact}")
    if not fact["prompt_concurrency_1"] or not fact["decode_concurrency_1"]:
        raise RuntimeError(f"unexpected 8901 concurrency: {fact}")
    clients = subprocess.run(["lsof", "-nP", "-iTCP:8901"], check=False, capture_output=True, text=True).stdout.splitlines()[1:]
    established = [line for line in clients if "LISTEN" not in line]
    fact["established_client_count"] = len(established)
    if established:
        raise RuntimeError("8901 has an established client before preflight")
    return fact


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    args = parser.parse_args()

    protocol_path = ROOT / "evals/smc_semantic_logic_p4_live/PROTOCOL.v0.2-ACTIONREF.json"
    manifest_path = ROOT / "evals/smc_semantic_logic_p4_live/P4-LIVE-v0.2-EXECUTION-MANIFEST.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    head = _git("rev-parse", "HEAD")
    lineage_ok = subprocess.run(["git", "merge-base", "--is-ancestor", BASE, head], cwd=ROOT).returncode == 0
    negative_hashes = {rel: _sha(ROOT / rel) for rel in EXPECTED_NEGATIVE_HASHES}
    r12_hashes = {rel: _sha(ROOT / rel) for rel in EXPECTED_R12_SOURCE_HASHES}
    model = _model_server_fact()

    port = _free_loopback_port()
    debug = f"http://127.0.0.1:{port}"
    ws_calls: list[str] = []
    with tempfile.TemporaryDirectory(prefix="lfl-p4live-v02-preflight-") as profile:
        proc = subprocess.Popen(
            chrome_args(args.chrome, Path(profile), port),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        actuator: CdpBrowserMutationActuator | None = None
        try:
            target = _wait_page(debug)
            raw_target_id = str(target.get("id") or "").strip()
            if not raw_target_id:
                raise RuntimeError("explicit raw Browser target id unavailable")
            page_token = f"target:{raw_target_id}"
            mapped = raw_browser_target_id_from_page_token(page_token)
            expected_hash = browser_target_id_sha256(mapped)

            def forbid_ws(url: str) -> Any:
                ws_calls.append(url)
                raise AssertionError("zero-action preflight must not open mutation websocket")

            actuator = CdpBrowserMutationActuator(debug, target_id=raw_target_id, ws_connect=forbid_ws)
            actuator.bind_observed_target(expected_hash)

            env = dict(os.environ)
            env.update({
                "LLM_API_KEY": "qualification-local-placeholder",
                "LLM_BASE_URL": "http://localhost:8901/v1",
                "LLM_MODEL": "cognilocal/ornith-1.5-35b-a3b-mlx",
                "LFL_BROWSER_PERCEPTION_CDP_URL": debug,
                "LFL_BROWSER_PERCEPTION_TARGET_ID": raw_target_id,
                "LFL_BROWSER_ACTION_ENABLED": "1",
                "LFL_BROWSER_ACTION_REF_ENABLED": "1",
                "LFL_BROWSER_ACTION_REF_MUTATION_ENABLED": "1",
            })
            settings = load_settings(env)
            engine = build_engine(settings)
            with p4_live_canary_tool_scope():
                scoped = set(engine.registry.names_for_current_scope())
                schema_names = {str(x.get("name") or "") for x in engine.registry.schemas_for_current_scope(lazy=False)}
                discovery = engine.registry.get("get_tool_schema")
                legacy_discovery_blocked = {}
                legacy_direct_blocked = {}
                for name in sorted(LEGACY):
                    d = discovery.execute(tool_name=name)
                    legacy_discovery_blocked[name] = d.status is ToolResultStatus.FAILURE and "当前执行域不可用" in d.content
                    direct = engine.registry.execute(ToolCall(id=f"preflight-{name}", name=name, arguments={}))
                    legacy_direct_blocked[name] = direct.status is ToolResultStatus.FAILURE and "当前执行域不可用" in direct.content
                catalog = discovery.execute(tool_name="*")
                catalog_text = str(catalog.content)
                catalog_has_exact_scope = all(f"- {name} " in catalog_text for name in P4_LIVE_CANARY_TOOL_SCOPE) and all(name not in catalog_text for name in LEGACY)

            rows = list(manifest.get("row_order") or [])
            protocol_contract = {
                "schema_exact": protocol.get("schema") == "smc.semantic_logic_p4_live_actionref_protocol.v0.2",
                "base_exact": protocol.get("base_result_git_sha") == BASE,
                "prior_negative_immutable": bool((protocol.get("frozen_prior_negative_qualification") or {}).get("immutable")),
                "prior_l02_rerun_forbidden": (protocol.get("frozen_prior_negative_qualification") or {}).get("rerun_or_reclassify_old_l02") is False,
                "next_stop_exact": protocol.get("next_stop") == "HUMAN_CHECKPOINT_BEFORE_V02_L01_MODEL_REQUEST",
            }
            result = {
                "schema": "smc.semantic_logic_p4_live_v02_prelive_evidence.v0.2",
                "protocol_contract": protocol_contract,
                "qualification_id": manifest.get("qualification_id"),
                "git_head": head,
                "base_result_git_sha": BASE,
                "lineage_ok": lineage_ok,
                "protocol_sha256": _sha(protocol_path),
                "manifest_sha256": _sha(manifest_path),
                "prior_negative_git_sha": NEGATIVE,
                "prior_negative_hashes": negative_hashes,
                "prior_negative_hashes_exact": negative_hashes == EXPECTED_NEGATIVE_HASHES,
                "r12_source_hashes": r12_hashes,
                "r12_source_hashes_exact": r12_hashes == EXPECTED_R12_SOURCE_HASHES,
                "model_server": model,
                "runtime_flags": {
                    "browser_action_enabled": settings.browser_action_enabled,
                    "browser_action_ref_enabled": settings.browser_action_ref_enabled,
                    "browser_action_ref_mutation_enabled": settings.browser_action_ref_mutation_enabled,
                    "browser_target_id_nonempty": bool(settings.browser_perception_target_id),
                },
                "tool_scope": {
                    "count": len(scoped),
                    "exact": scoped == set(P4_LIVE_CANARY_TOOL_SCOPE),
                    "schemas_exact": schema_names == set(P4_LIVE_CANARY_TOOL_SCOPE),
                    "legacy_provider_visible": bool(scoped & LEGACY),
                    "legacy_discovery_blocked": legacy_discovery_blocked,
                    "legacy_direct_execution_blocked": legacy_direct_blocked,
                    "catalog_exact_scope": catalog_has_exact_scope,
                },
                "target_identity": {
                    "explicit_raw_target_id_nonempty": bool(raw_target_id),
                    "page_token_mapping_exact": mapped == raw_target_id,
                    "bound_target_exact": actuator.bound_target_id == raw_target_id,
                    "mutation_websocket_open_count": len(ws_calls),
                },
                "manifest": {
                    "row_count": len(rows),
                    "row_order_unique": len(rows) == len(set(rows)),
                    "all_rows_v02_namespaced": all(str(row).startswith("V02-L") for row in rows),
                    "prelive_only": manifest.get("prelive_only") is True,
                    "new_result_namespace": "P4-LIVE-v0.2-QUALIFICATION-20260920" in str(manifest.get("result_namespace") or ""),
                },
                "model_requests": 0,
                "browser_mutations": 0,
                "deployment_restart_merge": 0,
                "next_stop": "HUMAN_CHECKPOINT_BEFORE_V02_L01_MODEL_REQUEST",
            }
            checks = [
                result["lineage_ok"], result["prior_negative_hashes_exact"], result["r12_source_hashes_exact"],
                all(protocol_contract.values()),
                model["established_client_count"] == 0,
                all(result["runtime_flags"].values()), result["tool_scope"]["exact"], result["tool_scope"]["schemas_exact"],
                not result["tool_scope"]["legacy_provider_visible"], all(legacy_discovery_blocked.values()), all(legacy_direct_blocked.values()),
                result["tool_scope"]["catalog_exact_scope"], result["target_identity"]["explicit_raw_target_id_nonempty"],
                result["target_identity"]["page_token_mapping_exact"], result["target_identity"]["bound_target_exact"],
                result["target_identity"]["mutation_websocket_open_count"] == 0,
                result["manifest"]["row_count"] == 20, result["manifest"]["row_order_unique"], result["manifest"]["all_rows_v02_namespaced"],
                result["manifest"]["prelive_only"], result["manifest"]["new_result_namespace"],
            ]
            result["qualified_v02_pre_live_stop"] = all(checks)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0 if result["qualified_v02_pre_live_stop"] else 2
        finally:
            if actuator is not None:
                with suppress(Exception):
                    actuator.close()
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)

if __name__ == "__main__":
    raise SystemExit(main())
