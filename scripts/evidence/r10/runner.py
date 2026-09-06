from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.llm.client import LLMResponse
from llm_loop.llm.errors import LLMError
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceFreshness,
    EvidenceLedgerStore,
    EvidenceSearch,
    ManifestProjector,
    OwnerScope,
    ProjectionEngine,
    render_recovery_manifest,
)
from llm_loop.tools.builtin.read_file import ReadFileTool
from llm_loop.tools.evidence_enforce import EvidenceEnforcer
from llm_loop.tools.evidence_source_resolver import EvidenceSourceResolver
from llm_loop.tools.evidence_tools import (
    EvidenceListTool,
    EvidenceReadTool,
    EvidenceSearchTool,
    SearchArchiveCompatTool,
)
from llm_loop.tools.registry import ToolRegistry
from scripts.evidence._capsule_pin import pinned_capsule_on
from scripts.evidence.r4.runner import (
    PROVIDERS,
    _assistant_tools_message,
    _build_client,
    _chat_once,
    _extract_answer,
    _parse_args,
    _schema_to_param,
    runner_lock,
)
from scripts.evidence.r10.fixtures import FIXTURES, R10Fixture

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "tests/fixtures/evidence_r10/matrix_v1.json"
FROZEN_PATH = ROOT / "tests/fixtures/evidence_r10/frozen_v1.json"
OUT_DIR = ROOT / "data/audit/evidence_r10"
REAL_ROWS_DIR = OUT_DIR / "real_runs_v1"
RUNTIME_DIR = OUT_DIR / "runtime"
LOCK_PATH = OUT_DIR / ".real_runner.lock"
MAX_ROUNDS = 12


@dataclass
class RunState:
    preacquire_count: int = 0
    preacquire_interval_seeded: bool = False
    model_source_attempt_count: int = 0
    physical_source_execution_count: int = 0
    evidence_reuse_count: int = 0
    physical_exact_source_args_repeat_count: int = 0
    physical_redundant_overlap_count: int = 0
    recovery_success_count: int = 0
    recovery_answer_hit_count: int = 0
    stale_block_count: int = 0
    request_count: int = 0
    source_key_counts: Counter[str] = field(default_factory=Counter)
    current_intervals: list[tuple[int, int | None]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_pack() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError(f"R10 frozen lock missing: {FROZEN_PATH}")
    frozen = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if frozen.get("schema") != "evidence-r10-frozen-v1":
        raise RuntimeError("R10 frozen lock schema mismatch")
    mismatches = []
    for rel, expected in frozen.get("artifacts", {}).items():
        path = ROOT / rel
        actual = _sha256(path) if path.exists() else "MISSING"
        if actual != expected:
            mismatches.append(f"{rel}: expected={expected} actual={actual}")
    if mismatches:
        raise RuntimeError("R10 frozen artifact mismatch: " + "; ".join(mismatches))
    return frozen


def require_all_credentials() -> None:
    missing = [
        p["api_key_env"] for p in PROVIDERS.values() if not os.environ.get(p["api_key_env"], "")
    ]
    if missing:
        raise RuntimeError(
            "R10 real execution preflight missing credentials: " + ", ".join(missing)
        )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _build_registry(
    owner: OwnerScope, run_dir: Path
) -> tuple[ToolRegistry, EvidenceFreshness, ManifestProjector]:
    blobs = BlobStore(run_dir / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(run_dir / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    search = EvidenceSearch(blobs, ledger, snippet_chars=500)
    registry = ToolRegistry(
        max_output_chars=100000, failure_guidance_enabled=False
    )
    registry.register(ReadFileTool())
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=900,
        )
    )
    registry.set_evidence_source_resolver(
        EvidenceSourceResolver(ledger, freshness=freshness, owner_resolver=lambda: owner)
    )
    registry.register(
        EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner)
    )
    registry.register(EvidenceSearchTool(search, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(
        SearchArchiveCompatTool(search, freshness=freshness, owner_resolver=lambda: owner)
    )
    return registry, freshness, ManifestProjector(ledger)


def _manifest(owner: OwnerScope, projector: ManifestProjector, freshness: EvidenceFreshness) -> str:
    first = projector.build_recent(owner=owner, limit=8)
    for entry in first.entries:
        freshness.refresh(owner=owner, evidence_ref=entry.evidence_ref)
    return render_recovery_manifest(projector.build_recent(owner=owner, limit=8))


def _task_prompt(fixture: R10Fixture, source_path: str) -> str:
    prior = ""
    if fixture.preacquire_mode != "none":
        prior = "A prior source observation was acquired before this task; its raw result is not in this conversation. "
    return (
        f"R10 covered-recovery efficiency holdout {fixture.seed_id}.\nCurrent source file path: {source_path}.\n"
        f"{fixture.task}\n{prior}Use the available recovery/source tools as needed. "
        'Return only JSON: {"answer":"<value>"}.'
    )


def _canonical_key(call: ToolCall) -> str:
    args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
    raw_limit = args.get("limit")
    limit = None if raw_limit is None else int(raw_limit)
    return json.dumps(
        {
            "tool": "read_file",
            "path": str(args.get("path") or ""),
            "offset": int(args.get("offset", 0) or 0),
            "limit": limit,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _interval(call: ToolCall) -> tuple[int, int | None]:
    args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
    start = max(0, int(args.get("offset", 0) or 0))
    raw = args.get("limit")
    return (start, None) if raw is None else (start, start + max(0, int(raw)))


def _overlap(a: tuple[int, int | None], b: tuple[int, int | None]) -> bool:
    ah = float("inf") if a[1] is None else a[1]
    bh = float("inf") if b[1] is None else b[1]
    return a[0] < bh and b[0] < ah


def _record_source_success(state: RunState, call: ToolCall) -> None:
    key = _canonical_key(call)
    if state.source_key_counts[key] > 0:
        state.physical_exact_source_args_repeat_count += 1
    state.source_key_counts[key] += 1
    iv = _interval(call)
    if any(_overlap(iv, prior) for prior in state.current_intervals):
        state.physical_redundant_overlap_count += 1
    state.current_intervals.append(iv)


def _trace(call: ToolCall, result: ToolResult, round_index: int) -> dict[str, Any]:
    return {
        "round": round_index,
        "tool": call.name,
        "arguments": call.arguments
        if isinstance(call.arguments, dict)
        else _parse_args(call.arguments),
        "status": result.status.value,
        "content_head": result.content[:1000],
        "evidence_ref": result.evidence_ref,
        "source_resolution_mode": result.source_resolution_mode,
        "source_execution_performed": result.source_execution_performed,
    }


class FakeR10LLM:
    def __init__(self, fixture: R10Fixture, source_path: str) -> None:
        self.fixture = fixture
        self.source_path = source_path
        self.counter = 0

    def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kwargs: Any
    ):
        response = self._response(messages)
        if False:
            yield None
        return response

    def _tool(self, name: str, arguments: dict[str, Any]) -> LLMResponse:
        self.counter += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id=f"fake-{name}-{self.counter}", name=name, arguments=arguments)],
            provider="fake",
            prompt_tokens=10,
            completion_tokens=5,
        )

    def _final(self) -> LLMResponse:
        self.counter += 1
        return LLMResponse(
            content=json.dumps({"answer": self.fixture.expected_answer}),
            tool_calls=[],
            provider="fake",
            prompt_tokens=10,
            completion_tokens=10,
        )

    def _response(self, messages: list[dict[str, Any]]) -> LLMResponse:
        tool_text = "\n".join(
            str(m.get("content") or "") for m in messages if m.get("role") == "tool"
        )
        f = self.fixture
        if f.expected_answer in tool_text:
            return self._final()
        if f.seed_id in {"T1", "T2"}:
            if "recover=read_evidence" not in tool_text:
                return self._tool("read_file", {"path": self.source_path, "full": True})
            return self._tool("search_evidence", {"query": f.target_field, "limit": 5})
        if f.seed_id == "T3":
            if "content=blocked" not in tool_text and "evidence_hydration_blocked" not in tool_text:
                return self._tool("search_evidence", {"query": f.target_field, "limit": 5})
            if "recover=read_evidence" not in tool_text:
                return self._tool("read_file", {"path": self.source_path, "full": True})
            # After the refresh, search the new Evidence.
            return self._tool("search_evidence", {"query": f.target_field, "limit": 5})
        if f.seed_id == "T4":
            if "未找到匹配" not in tool_text and f.expected_answer not in tool_text:
                return self._tool("search_evidence", {"query": f.target_field, "limit": 5})
            if f.expected_answer not in tool_text and "recover=read_evidence" not in tool_text:
                return self._tool(
                    "read_file", {"path": self.source_path, "offset": 112, "limit": 60}
                )
            if f.expected_answer not in tool_text:
                return self._tool("search_evidence", {"query": f.target_field, "limit": 5})
        return self._final()


def execute_run(row: dict[str, Any], *, dry: bool = False) -> dict[str, Any]:
    # R9-P0-01 批 1/3：R10 基准协议固化于 capsule=on 历史文本形状，回放钉住
    # 历史协议（scripts/evidence/_capsule_pin.py），不随生产默认漂移。
    with pinned_capsule_on():
        return _execute_run_locked(row, dry=dry)


def _execute_run_locked(row: dict[str, Any], *, dry: bool = False) -> dict[str, Any]:
    run_id = str(row["run_id"])
    provider = str(row["provider"])
    fixture = FIXTURES[str(row["seed_id"])]
    profile = PROVIDERS[provider]
    run_dir = RUNTIME_DIR / ("dry" if dry else "real") / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    source_file = run_dir / f"{fixture.seed_id.lower()}-source.txt"
    source_file.write_text(fixture.initial_content, encoding="utf-8")
    source_path = str(source_file)
    owner = OwnerScope(workspace_id=str(run_dir), session_id=run_id)
    registry, freshness, projector = _build_registry(owner, run_dir)
    state = RunState()

    if fixture.preacquire_mode != "none":
        args: dict[str, Any] = {"path": source_path}
        if fixture.preacquire_mode == "full":
            args["full"] = True
        else:
            args["offset"] = fixture.preacquire_offset
            args["limit"] = fixture.preacquire_limit
        pre = registry.execute(ToolCall(id=f"pre-{run_id}", name="read_file", arguments=args))
        if pre.status is not ToolResultStatus.SUCCESS or not pre.evidence_ref:
            return {
                "run_id": run_id,
                "provider": provider,
                "seed_id": fixture.seed_id,
                "status": "INFRA_FAILURE",
                "infra_error": "preacquire failed",
                "trace": [],
            }
        state.preacquire_count = 1
        if fixture.preacquire_mode == "partial" and not fixture.mutate_after_preacquire:
            end = fixture.preacquire_offset + int(fixture.preacquire_limit or 0)
            state.current_intervals.append((fixture.preacquire_offset, end))
            state.preacquire_interval_seeded = True

    if fixture.mutate_after_preacquire:
        before = source_file.stat()
        source_file.write_text(fixture.current_content, encoding="utf-8")
        after = source_file.stat()
        bumped = max(after.st_mtime_ns, before.st_mtime_ns + 1_000_000)
        os.utime(source_file, ns=(after.st_atime_ns, bumped))

    persisted: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "Solve the evidence task using available tools. Return only the requested JSON answer.",
        },
        {"role": "user", "content": _task_prompt(fixture, source_path)},
    ]
    tools = [_schema_to_param(schema) for schema in registry.schemas(lazy=False)]
    llm: Any = FakeR10LLM(fixture, source_path) if dry else _build_client(provider)
    trace: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    final_answer: str | None = None
    status = "COMPLETED"
    infra_error: str | None = None
    started = time.monotonic()
    try:
        for round_index in range(1, MAX_ROUNDS + 1):
            wire = list(persisted)
            manifest = _manifest(owner, projector, freshness)
            if manifest:
                wire.append({"role": "user", "content": manifest})
            state.request_count += 1
            response = _chat_once(
                llm, wire, tools, run_id=run_id, provider=provider, model=profile["model"]
            )
            stats["prompt_tokens"] += getattr(response, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(response, "completion_tokens", 0) or 0
            stats["cache_hit_tokens"] += getattr(response, "prompt_cache_hit_tokens", 0) or 0
            reasoning = getattr(response, "reasoning_content", None) or getattr(
                response, "reasoning", None
            )
            if reasoning:
                reasoning_parts.append(reasoning)
            if not response.tool_calls:
                final_answer = response.content
                break
            calls = [
                ToolCall(
                    id=c.id,
                    name=c.name,
                    arguments=c.arguments
                    if isinstance(c.arguments, dict)
                    else _parse_args(c.arguments),
                )
                for c in response.tool_calls
            ]
            persisted.append(_assistant_tools_message(calls, reasoning))
            state.model_source_attempt_count += sum(1 for c in calls if c.name == "read_file")
            results = registry.execute_many(calls)
            for call, result in zip(calls, results, strict=True):
                if call.name == "read_file" and result.status is ToolResultStatus.SUCCESS:
                    if result.source_execution_performed is True:
                        state.physical_source_execution_count += 1
                        _record_source_success(state, call)
                    elif result.source_execution_performed is False:
                        state.evidence_reuse_count += 1
                if call.name in {
                    "read_evidence",
                    "search_evidence",
                    "list_evidence",
                    "search_archive",
                }:
                    if result.status is ToolResultStatus.SUCCESS:
                        state.recovery_success_count += 1
                        if fixture.expected_answer in result.content:
                            state.recovery_answer_hit_count += 1
                    if (
                        "content=blocked" in result.content
                        or "evidence_hydration_blocked" in result.content
                    ):
                        state.stale_block_count += 1
                trace.append(_trace(call, result, round_index))
                persisted.append(result.to_message().to_llm_dict())
        else:
            status = "ROUND_LIMIT"
    except LLMError as exc:
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    finally:
        stats["latency_s"] = round(time.monotonic() - started, 3)
        if not dry:
            with contextlib.suppress(Exception):
                llm.close()

    answer = _extract_answer(final_answer)
    return {
        "run_id": run_id,
        "provider": provider,
        "model": "fake-dry" if dry else profile["model"],
        "seed_id": fixture.seed_id,
        "rep": int(row["rep"]),
        "status": status,
        "infra_error": infra_error,
        "final_answer": final_answer,
        "answer": answer,
        "expected_answer": fixture.expected_answer,
        "final_answer_exact": answer == fixture.expected_answer,
        "transport_ref_as_domain_answer": bool(answer and answer.startswith("evidence://")),
        "stale_as_current": fixture.seed_id == "T3" and answer == fixture.historical_answer,
        "preacquire_count": state.preacquire_count,
        "preacquire_interval_seeded": state.preacquire_interval_seeded,
        "model_source_attempt_count": state.model_source_attempt_count,
        "physical_source_execution_count": state.physical_source_execution_count,
        "evidence_reuse_count": state.evidence_reuse_count,
        "physical_exact_source_args_repeat_count": state.physical_exact_source_args_repeat_count,
        "physical_redundant_overlap_count": state.physical_redundant_overlap_count,
        "recovery_success_count": state.recovery_success_count,
        "recovery_answer_hit_count": state.recovery_answer_hit_count,
        "stale_block_count": state.stale_block_count,
        "request_count": state.request_count,
        "reasoning": "\n".join(reasoning_parts) if reasoning_parts else None,
        "stats": stats,
        "trace": trace,
    }


def _load_matrix() -> list[dict[str, Any]]:
    return list(json.loads(MATRIX_PATH.read_text(encoding="utf-8"))["runs"])


def _result_path(run_id: str) -> Path:
    return REAL_ROWS_DIR / f"{run_id}.json"


def _started_path(run_id: str) -> Path:
    return REAL_ROWS_DIR / f"{run_id}.started.json"


def _ensure_no_unresolved_started(rows: list[dict[str, Any]]) -> None:
    unresolved = []
    for row in rows:
        run_id = str(row["run_id"])
        started = _started_path(run_id)
        completed = _result_path(run_id)
        if started.exists() and not completed.exists():
            unresolved.append(run_id)
        elif started.exists() and completed.exists():
            started.unlink()
    if unresolved:
        raise RuntimeError(
            "R10 unresolved started rows; automatic replay forbidden: " + ", ".join(unresolved)
        )


def _execute_real_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row["run_id"])
    _write_json_atomic(
        _started_path(run_id),
        {
            "schema": "evidence-r10-started-v1",
            "run_id": run_id,
            "provider": row["provider"],
            "seed_id": row["seed_id"],
            "started_at": datetime.now(UTC).isoformat(),
            "pid": os.getpid(),
        },
    )
    attempts = [execute_run(row, dry=False)]
    if attempts[0]["status"] == "INFRA_FAILURE":
        attempts.append(execute_run(row, dry=False))
    result = dict(attempts[-1])
    result["attempt_count"] = len(attempts)
    result["infra_attempts"] = [
        {"status": a["status"], "infra_error": a.get("infra_error")} for a in attempts
    ]
    _write_json_atomic(_result_path(run_id), result)
    _started_path(run_id).unlink(missing_ok=True)
    return result


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [json.loads(_result_path(str(row["run_id"])).read_text()) for row in rows]
    payload = {"schema": "evidence-r10-runs-v1", "count": len(results), "runs": results}
    _write_json_atomic(OUT_DIR / "runs_real_v1.json", payload)
    return payload


def run_rows(rows: list[dict[str, Any]], *, dry: bool) -> tuple[list[dict[str, Any]], int]:
    if dry:
        results = [execute_run(row, dry=True) for row in rows]
        _write_json_atomic(
            OUT_DIR / "runs_dry_v1.json",
            {"schema": "evidence-r10-runs-v1", "count": len(results), "runs": results},
        )
        for r in results:
            print(
                r["run_id"],
                r["provider"],
                r["seed_id"],
                r["status"],
                "exact=",
                r["final_answer_exact"],
                "src=",
                r["physical_source_execution_count"],
                "repeat=",
                r["physical_exact_source_args_repeat_count"],
                "overlap=",
                r["physical_redundant_overlap_count"],
                "hit=",
                r["recovery_answer_hit_count"],
            )
        failed = [r for r in results if r["status"] != "COMPLETED" or not r["final_answer_exact"]]
        return results, 0 if not failed else 1
    REAL_ROWS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_no_unresolved_started(rows)
    for row in rows:
        run_id = str(row["run_id"])
        if _result_path(run_id).exists():
            print(run_id, "SKIP completed")
            continue
        r = _execute_real_row(row)
        print(
            r["run_id"],
            r["provider"],
            r["seed_id"],
            r["status"],
            "exact=",
            r.get("final_answer_exact"),
            "src=",
            r.get("model_source_execution_count"),
            "repeat=",
            r.get("exact_source_args_repeat_count"),
            "overlap=",
            r.get("redundant_overlap_count"),
            "stale=",
            r.get("stale_as_current"),
        )
    payload = _aggregate(rows)
    unresolved = [r for r in payload["runs"] if r["status"] == "INFRA_FAILURE"]
    return list(payload["runs"]), 0 if not unresolved else 1


def snapshot_providers() -> dict[str, Any]:
    return {
        name: {
            "provider": name,
            "base_url": p["base_url"],
            "model": p["model"],
            "api_key_env": p["api_key_env"],
            "api_key_set": bool(os.environ.get(p["api_key_env"], "")),
            "max_tokens": p["max_tokens"],
            "thinking_supported": p["thinking_supported"],
            "fallback": "forbidden",
            "temperature": None,
            "top_p": None,
            "seed": None,
        }
        for name, p in PROVIDERS.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--run")
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        print(json.dumps(snapshot_providers(), ensure_ascii=False, indent=2))
        return 0
    rows = _load_matrix()
    selected = rows if args.all else [row for row in rows if row["run_id"] == args.run]
    if not selected:
        raise SystemExit("select --all or valid --run")
    if args.dry:
        _, rc = run_rows(selected, dry=True)
        return rc
    verify_frozen_pack()
    require_all_credentials()
    with runner_lock(LOCK_PATH):
        _, rc = run_rows(selected, dry=False)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
