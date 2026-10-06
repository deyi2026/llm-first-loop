"""Readiness only: no installation, service restart, or model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def probe(executable: str, args: list[str]) -> dict:
    if shutil.which(executable) is None:
        return {"state": "missing", "version": None}
    try:
        result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"state": "unavailable", "error": type(exc).__name__}
    return {"state": "ready" if result.returncode == 0 else "unavailable",
            "version": result.stdout.strip() if result.returncode == 0 else None,
            "exit_code": result.returncode}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binaries = {name: probe(name, ["--version"]) for name in ("node", "npm", "pi", "opencode")}
    docker = probe("docker", ["info", "--format", "{{.ServerVersion}}"])
    provider_path = args.runtime_root / "data" / "providers.local.json"
    provider_state = "missing"
    profiles = {}
    if provider_path.is_file():
        try:
            providers = json.loads(provider_path.read_text(encoding="utf-8"))
            provider_state = "readable"
            for provider, model in (("glm", "glm-5.3"), ("deepseek", "deepseek-flash")):
                config = providers.get(provider, {})
                model_config = config.get("models", {}).get(model, {})
                profiles[f"{provider}/{model}"] = {
                    "registered": bool(model_config),
                    "max_tokens": config.get("max_tokens"),
                    "reasoning_control": model_config.get("reasoning_control"),
                    "reasoning_default_effort": model_config.get("reasoning_default_effort"),
                    "capability_tier": model_config.get("capability_tier"),
                    "actual_request_parity": "not_verified",
                }
        except (OSError, ValueError, AttributeError):
            provider_state = "unreadable"
    blockers = [f"{name}:{value['state']}" for name, value in binaries.items() if value["state"] != "ready"]
    if docker["state"] != "ready":
        blockers.append("sandbox:docker_daemon_unavailable")
    if provider_state != "readable" or not all(p["registered"] for p in profiles.values()) or len(profiles) != 2:
        blockers.append("provider_profiles:not_ready")
    blockers.extend(("adapter_request_receipts:not_verified", "task_bundle_and_oracles:not_frozen"))
    report = {
        "schema": "lfl.cross_harness_readiness.v1", "status": "BLOCKED" if blockers else "READY",
        "binaries": binaries, "docker": docker,
        "version_seeds": {"pi_package": "@earendil-works/pi-coding-agent@1.0.4",
                          "opencode_package": "opencode-ai@1.18.34"},
        "version_seed_source": "npm registry read-only lookup 2026-10-06; not installed or request-qualified",
        "provider_file_state": provider_state,
        "provider_file_sha256": hashlib.sha256(provider_path.read_bytes()).hexdigest() if provider_state == "readable" else None,
        "model_profile_seeds": profiles, "blockers": blockers,
        "model_calls": 0, "formal_results": None,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(report["status"], ", ".join(blockers))
    return 2 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
