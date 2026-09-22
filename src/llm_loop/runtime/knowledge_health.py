"""Prompt-neutral health facts for LFL Rule/Experience/Method/Skill stores.

This module observes path identity and lightweight file-level reachability.  It does
not rank, select, copy, merge, or semantically validate knowledge.  When a legacy
cwd-bound mutable store contains data at a path different from the canonical state
binding, writes are quarantined rather than guessing which side should win.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from .paths import RuntimePaths

_RULE_RE = re.compile(r"^##\s+.*?RULE-AI-\d+(?:\.\d+)?", re.IGNORECASE | re.MULTILINE)


def _count_glob(root: Path, pattern: str) -> int:
    if not root.is_dir():
        return 0
    try:
        return sum(1 for p in root.glob(pattern) if p.is_file())
    except OSError:
        return 0


def _rule_count(docs_dir: Path) -> int:
    path = docs_dir / "ai_rules.md"
    try:
        return len(_RULE_RE.findall(path.read_text(encoding="utf-8")))
    except OSError:
        return 0


def _dir_facts(path: Path, *, records: int) -> dict[str, object]:
    exists = path.is_dir()
    readable = exists and os.access(path, os.R_OK)
    # Missing directories are writable only if their nearest existing parent is writable;
    # report this as a mechanical capability, not as permission to create them.
    parent = path
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    writable = os.access(parent, os.W_OK) if parent.exists() else False
    return {
        "path": str(path),
        "exists": exists,
        "readable": readable,
        "writable": writable,
        "records": records,
    }


def _has_mutable_records(path: Path, patterns: Iterable[str]) -> bool:
    return any(_count_glob(path, pattern) > 0 for pattern in patterns)


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0



def _baseline_path(paths: RuntimePaths) -> Path:
    return paths.data_dir / "runtime" / "knowledge_baseline.json"


def _load_baseline(paths: RuntimePaths) -> tuple[dict[str, object] | None, str]:
    path = _baseline_path(paths)
    if not path.is_file():
        return None, "absent"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None, "unreadable"
    if not isinstance(value, dict) or value.get("schema") != "lfl.knowledge_baseline.v1":
        return None, "unreadable"
    return value, "loaded"


def _first_relative(root: Path, pattern: str) -> str:
    if not root.is_dir():
        return ""
    try:
        paths = sorted(p for p in root.glob(pattern) if p.is_file())
    except OSError:
        return ""
    if not paths:
        return ""
    try:
        return str(paths[0].relative_to(root))
    except ValueError:
        return paths[0].name


def ensure_knowledge_baseline(
    paths: RuntimePaths,
    health: dict[str, object],
) -> dict[str, object] | None:
    """Create the durable store-identity baseline once, never overwrite it implicitly.

    Counts are initial anomaly signals only; they are not equality invariants.  One
    mechanically selected stable path probe per mutable store lets a later total
    loss/replacement become visible without choosing semantic importance.
    """
    if health.get("status") != "healthy":
        return None
    current, state = _load_baseline(paths)
    if state == "loaded":
        return current
    if state == "unreadable":
        return None

    stores = _as_dict(health.get("stores"))
    exp = (stores or {}).get("experience") if isinstance(stores, dict) else None
    meth = (stores or {}).get("runtime_method") if isinstance(stores, dict) else None
    baseline: dict[str, object] = {
        "schema": "lfl.knowledge_baseline.v1",
        "store_id": uuid.uuid4().hex,
        "generation": 1,
        "created_at": time.time(),
        "binding": {
            "data_dir": str(paths.data_dir),
            "state_root": str(paths.state_root),
            "experiences_dir": str(paths.experiences_dir),
            "methods_dir": str(paths.methods_dir),
        },
        "initial_counts": {
            "experience": int((exp or {}).get("records") or 0) if isinstance(exp, dict) else 0,
            "runtime_method": int((meth or {}).get("records") or 0) if isinstance(meth, dict) else 0,
        },
        "probes": {
            "experience": _first_relative(paths.experiences_dir, "EXPERIENCE-*.md"),
            "runtime_method": _first_relative(paths.methods_dir, "*/METHOD.md"),
        },
    }
    path = _baseline_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(baseline, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return baseline

def inspect_knowledge_health(paths: RuntimePaths) -> dict[str, object]:
    exp_records = _count_glob(paths.experiences_dir, "EXPERIENCE-*.md")
    runtime_method_records = _count_glob(paths.methods_dir, "*/METHOD.md")
    seed_method_records = _count_glob(paths.method_seed_dir, "*/METHOD.md")
    skill_records = _count_glob(paths.skills_dir, "*/SKILL.md")
    rule_records = _rule_count(paths.docs_dir)

    reasons: list[str] = []
    if paths.explicit_sidecar_state:
        reasons.append("explicit_sidecar_state_root")
    if rule_records == 0:
        reasons.append("rule_store_unavailable")
    if seed_method_records == 0:
        reasons.append("seed_method_store_unavailable")
    if skill_records == 0:
        reasons.append("skill_store_unavailable")
    if (
        paths.experiences_source == "data_dir_inferred"
        and paths.legacy_experiences_dir != paths.experiences_dir
        and _has_mutable_records(paths.legacy_experiences_dir, ("EXPERIENCE-*.md",))
    ):
        reasons.append("legacy_experience_divergence")
    if (
        paths.methods_source == "data_dir_inferred"
        and paths.legacy_methods_dir != paths.methods_dir
        and _has_mutable_records(paths.legacy_methods_dir, ("*/METHOD.md",))
    ):
        reasons.append("legacy_method_divergence")

    baseline, baseline_state = _load_baseline(paths)
    if baseline_state == "unreadable":
        reasons.append("baseline_unreadable")
    elif baseline is not None:
        binding = _as_dict(baseline.get("binding"))
        if (
            str((binding or {}).get("data_dir") or "") != str(paths.data_dir)
            or str((binding or {}).get("experiences_dir") or "") != str(paths.experiences_dir)
            or str((binding or {}).get("methods_dir") or "") != str(paths.methods_dir)
        ):
            reasons.append("baseline_binding_mismatch")
        counts = _as_dict(baseline.get("initial_counts"))
        probes = _as_dict(baseline.get("probes"))
        if _as_int(counts.get("experience")) > 0 and exp_records == 0:
            reasons.append("baseline_experience_empty_regression")
        if _as_int(counts.get("runtime_method")) > 0 and runtime_method_records == 0:
            reasons.append("baseline_method_empty_regression")
        exp_probe = str((probes or {}).get("experience") or "")
        method_probe = str((probes or {}).get("runtime_method") or "")
        if exp_probe and not (paths.experiences_dir / exp_probe).is_file():
            reasons.append("baseline_experience_probe_missing")
        if method_probe and not (paths.methods_dir / method_probe).is_file():
            reasons.append("baseline_method_probe_missing")

    # Divergent mutable stores are the one condition where automatic writing is unsafe:
    # the runtime can read the canonical DATA_DIR binding, but must not silently choose
    # how to merge legacy bytes.  Human/model reconciliation remains outside this module.
    quarantined = bool(reasons)
    status = "quarantined" if quarantined else "healthy"
    writes_enabled = not quarantined

    return {
        "schema": "lfl.knowledge_health.v1",
        "status": status,
        "writes_enabled": writes_enabled,
        "reasons": reasons,
        "binding": paths.binding_summary(),
        "baseline": {
            "path": str(_baseline_path(paths)),
            "state": baseline_state,
            "store_id": str((baseline or {}).get("store_id") or "") if isinstance(baseline, dict) else "",
            "generation": (baseline or {}).get("generation") if isinstance(baseline, dict) else None,
            "probes": (baseline or {}).get("probes", {}) if isinstance(baseline, dict) else {},
        },
        "stores": {
            "experience": _dir_facts(paths.experiences_dir, records=exp_records),
            "runtime_method": _dir_facts(paths.methods_dir, records=runtime_method_records),
            "seed_method": _dir_facts(paths.method_seed_dir, records=seed_method_records),
            "skill": _dir_facts(paths.skills_dir, records=skill_records),
            "rule": {
                "path": str(paths.docs_dir / "ai_rules.md"),
                "exists": (paths.docs_dir / "ai_rules.md").is_file(),
                "readable": os.access(paths.docs_dir / "ai_rules.md", os.R_OK),
                "writable": False,
                "records": rule_records,
            },
        },
    }



def run_preflight(
    paths: RuntimePaths,
    *,
    initialize_baseline: bool = False,
) -> dict[str, object]:
    """Run a no-LLM, no-semantic Knowledge preflight over exact runtime paths."""
    health = inspect_knowledge_health(paths)
    if initialize_baseline and health.get("status") == "healthy":
        ensure_knowledge_baseline(paths, health)
        health = inspect_knowledge_health(paths)
    return {"ok": health.get("status") == "healthy", "health": health}


def check_store_binding(paths: RuntimePaths) -> dict[str, object]:
    """Deployment-time store-binding policy check (read-only, never heals).

    R2 (SPEC-20260922-service-control-restart-fixpack-v1): knowledge stores are
    git-tracked, so a clean deploy worktree ships legacy store snapshots.  A
    dual-root shared-state deployment (linked worktree whose persistent DATA_DIR
    resolves outside the code root) MUST bind EXPERIENCES_DIR / METHODS_DIR
    explicitly to the canonical stores; inference from DATA_DIR is exactly the
    gen63 fork trigger.  Single-root and sidecar-state layouts are exempt
    (inferred binding cannot diverge from legacy there).
    """
    linked = paths.git_common_root is not None and paths.git_common_root != paths.code_root
    sidecar_state = False
    try:
        paths.data_dir.relative_to(paths.code_root)
        sidecar_state = True
    except ValueError:
        sidecar_state = False
    dual_root_shared_state = linked and not sidecar_state

    reasons: list[str] = []
    if dual_root_shared_state:
        for label, source, store in (
            ("experiences", paths.experiences_source, paths.experiences_dir),
            ("methods", paths.methods_source, paths.methods_dir),
        ):
            if source != "explicit_env":
                reasons.append(f"dual_root_store_binding_missing:{label}")
                continue
            if not store.is_dir():
                reasons.append(f"store_dir_missing:{label}")
            elif not os.access(store, os.W_OK):
                reasons.append(f"store_dir_not_writable:{label}")

    return {
        "schema": "lfl.knowledge_binding_check.v1",
        "ok": not reasons,
        "dual_root_shared_state": dual_root_shared_state,
        "reasons": reasons,
        "binding": paths.binding_summary(),
    }


def _paths_from_process_env() -> RuntimePaths:
    from llm_loop.config import load_env_file

    from .paths import resolve_runtime_paths

    load_env_file()
    code_root = Path(__file__).resolve().parents[3]
    data_dir_raw = str(os.environ.get("DATA_DIR", "") or "").strip()
    return resolve_runtime_paths(
        data_dir=data_dir_raw or None,
        code_root=code_root,
        env=os.environ,
        data_dir_explicit=bool(data_dir_raw),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LFL Knowledge Health preflight")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--check-binding", action="store_true")
    parser.add_argument("--initialize-baseline", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.preflight) == bool(args.check_binding):
        parser.error("exactly one of --preflight / --check-binding is required")
    if args.check_binding:
        result = check_store_binding(_paths_from_process_env())
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("ok") is True else 2
    result = run_preflight(
        _paths_from_process_env(), initialize_baseline=bool(args.initialize_baseline)
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") is True else 2

def write_recovery_receipt(
    data_dir: str | Path,
    paths: RuntimePaths,
    health: dict[str, object],
    *,
    service: str,
) -> dict[str, object] | None:
    """Persist a deduplicated receipt for a safe mechanical binding repair.

    A receipt is emitted only when the resolver changed the historical cwd-derived
    default to the canonical DATA_DIR binding and health is not quarantined.  It
    never copies or merges knowledge bytes.  Ambiguous/divergent stores therefore
    produce no recovery receipt and remain fail-closed for mutation.
    """
    if not paths.auto_rebind_applied or health.get("status") != "healthy":
        return None

    stores = _as_dict(health.get("stores"))
    before = {
        "experiences_dir": str(paths.legacy_experiences_dir),
        "methods_dir": str(paths.legacy_methods_dir),
    }
    after = {
        "experiences_dir": str(paths.experiences_dir),
        "methods_dir": str(paths.methods_dir),
        "state_root": str(paths.state_root),
    }
    baseline = _as_dict(health.get("baseline"))
    fingerprint_payload = {
        "service": service,
        "before": before,
        "after": after,
        "store_id": baseline.get("store_id"),
        "generation": baseline.get("generation"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    runtime_dir = Path(data_dir).expanduser().resolve() / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    current_path = runtime_dir / "knowledge_recovery.json"
    log_path = runtime_dir / "knowledge_recovery.jsonl"

    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        current = None
    if isinstance(current, dict) and current.get("fingerprint") == fingerprint:
        return current

    receipt: dict[str, object] = {
        "schema": "lfl.knowledge_recovery_receipt.v1",
        "ts": time.time(),
        "service": service,
        "action": "rebind",
        "status": "recovered",
        "fingerprint": fingerprint,
        "before": before,
        "after": after,
        "stores": stores,
    }
    tmp = current_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    tmp.replace(current_path)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
    return receipt


if __name__ == "__main__":
    raise SystemExit(main())
