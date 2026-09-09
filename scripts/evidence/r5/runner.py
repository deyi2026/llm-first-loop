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
from llm_loop.tools.evidence_tools import (
    EvidenceListTool,
    EvidenceReadTool,
    EvidenceSearchTool,
    SearchArchiveCompatTool,
)
from llm_loop.tools.registry import ToolRegistry
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
from scripts.evidence.r5.fixtures import FIXTURES, R5Fixture

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "tests/fixtures/evidence_r5/matrix_v1.json"
FROZEN_PATH = ROOT / "tests/fixtures/evidence_r5/frozen_v1.json"
OUT_DIR = ROOT / "data/audit/evidence_r5"
REAL_ROWS_DIR = OUT_DIR / "real_runs_v1"
RUNTIME_DIR = OUT_DIR / "runtime"
LOCK_PATH = OUT_DIR / ".real_runner.lock"
MAX_ROUNDS = 12


class R5SnapshotTool:
    name = "r5_snapshot"
    description = "Acquire the R5 runtime snapshot source."
    parameters = {
        "type": "object",
        "properties": {"source": {"type": "string"}},
        "required": ["source"],
        "additionalProperties": False,
    }

    def __init__(self, fixture: R5Fixture) -> None:
        self.fixture = fixture
        self.execution_count = 0

    def execute(self, **kwargs: Any) -> ToolResult:
        self.execution_count += 1
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=self.fixture.initial_content,
            tool_call_id="",
            tool_name=self.name,
        )


@dataclass
class RunState:
    preacquire_count: int = 0
    model_source_attempt_count: int = 0
    model_source_execution_count: int = 0
    exact_source_args_repeat_count: int = 0
    redundant_overlap_count: int = 0
    recovery_success_count: int = 0
    read_evidence_success_count: int = 0
    search_evidence_success_count: int = 0
    historical_access_success_count: int = 0
    stale_block_count: int = 0
    request_count: int = 0
    source_key_counts: Counter[str] = field(default_factory=Counter)
    successful_intervals: list[tuple[int, int | None]] = field(default_factory=list)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_pack() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError(f"R5 frozen lock missing: {FROZEN_PATH}")
    frozen = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if frozen.get("schema") != "evidence-r5-frozen-v1":
        raise RuntimeError("R5 frozen lock schema mismatch")
    mismatches = []
    for rel, expected in frozen.get("artifacts", {}).items():
        path = ROOT / rel
        actual = _sha256(path) if path.exists() else "MISSING"
        if actual != expected:
            mismatches.append(f"{rel}: expected={expected} actual={actual}")
    if mismatches:
        raise RuntimeError("R5 frozen artifact mismatch: " + "; ".join(mismatches))
    return frozen


def require_all_credentials() -> None:
    missing = [
        profile["api_key_env"]
        for profile in PROVIDERS.values()
        if not os.environ.get(profile["api_key_env"], "")
    ]
    if missing:
        raise RuntimeError("R5 real execution preflight missing credentials: " + ", ".join(missing))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _build_registry(
    *, fixture: R5Fixture, owner: OwnerScope, run_dir: Path
) -> tuple[
    ToolRegistry, EvidenceLedgerStore, EvidenceFreshness, ManifestProjector, R5SnapshotTool | None
]:
    blobs = BlobStore(run_dir / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(run_dir / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    search = EvidenceSearch(blobs, ledger, snippet_chars=500)
    registry = ToolRegistry(
        max_output_chars=100000,
        failure_guidance_enabled=False,
    )
    snapshot_tool: R5SnapshotTool | None = None
    if fixture.source_kind == "file":
        registry.register(ReadFileTool())
    else:
        snapshot_tool = R5SnapshotTool(fixture)
        registry.register(snapshot_tool)
    registry.set_evidence_enforcer(
        EvidenceEnforcer(
            capture,
            projection=ProjectionEngine(),
            owner_resolver=lambda: owner,
            projection_budget_chars=900,
        )
    )
    registry.register(
        EvidenceReadTool(blobs, ledger, freshness=freshness, owner_resolver=lambda: owner)
    )
    registry.register(EvidenceSearchTool(search, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(
        SearchArchiveCompatTool(search, freshness=freshness, owner_resolver=lambda: owner)
    )
    return registry, ledger, freshness, ManifestProjector(ledger), snapshot_tool


def _current_manifest(
    *, owner: OwnerScope, projector: ManifestProjector, freshness: EvidenceFreshness
) -> str:
    manifest = projector.build_recent(owner=owner, limit=8)
    for entry in manifest.entries:
        freshness.refresh(owner=owner, evidence_ref=entry.evidence_ref)
    return render_recovery_manifest(projector.build_recent(owner=owner, limit=8))


def _source_name(fixture: R5Fixture) -> str:
    return "read_file" if fixture.source_kind == "file" else "r5_snapshot"


def _source_call(fixture: R5Fixture, source_path: str | None, *, call_id: str) -> ToolCall:
    if fixture.source_kind == "file":
        return ToolCall(id=call_id, name="read_file", arguments={"path": source_path, "full": True})
    return ToolCall(
        id=call_id,
        name="r5_snapshot",
        arguments={"source": "fixture://r5/j4"},
    )


def _task_prompt(fixture: R5Fixture, source_path: str | None) -> str:
    if fixture.source_kind == "file":
        source_note = f"Current source file path: {source_path}."
    else:
        source_note = "The runtime snapshot source tool is r5_snapshot with source=fixture://r5/j4."
    return (
        f"R5 freshness holdout {fixture.seed_id}.\n{source_note}\n{fixture.task}\n"
        "A prior source observation was already acquired before this task, but its raw tool result is not in this conversation. "
        'Use the available recovery/source tools as needed. Return only JSON: {"answer":"<value>"}.'
    )


def _canonical_source_key(call: ToolCall, fixture: R5Fixture) -> str:
    args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
    if fixture.source_kind == "file":
        path = str(args.get("path") or "")
        offset = int(args.get("offset", 0) or 0)
        limit_raw = args.get("limit")
        limit = None if limit_raw is None else int(limit_raw)
        return json.dumps(
            {"tool": "read_file", "path": path, "offset": offset, "limit": limit},
            ensure_ascii=False,
            sort_keys=True,
        )
    return json.dumps(
        {"tool": "r5_snapshot", "source": str(args.get("source") or "")},
        ensure_ascii=False,
        sort_keys=True,
    )


def _file_interval(call: ToolCall) -> tuple[int, int | None]:
    args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
    start = max(0, int(args.get("offset", 0) or 0))
    limit_raw = args.get("limit")
    if limit_raw is None:
        return start, None
    limit = max(0, int(limit_raw))
    return start, start + limit


def _intervals_overlap(a: tuple[int, int | None], b: tuple[int, int | None]) -> bool:
    a_start, a_end = a
    b_start, b_end = b
    a_hi = float("inf") if a_end is None else a_end
    b_hi = float("inf") if b_end is None else b_end
    return a_start < b_hi and b_start < a_hi


def _record_source_success(state: RunState, call: ToolCall, fixture: R5Fixture) -> None:
    key = _canonical_source_key(call, fixture)
    if state.source_key_counts[key] > 0:
        state.exact_source_args_repeat_count += 1
    state.source_key_counts[key] += 1
    if fixture.source_kind == "file":
        interval = _file_interval(call)
        if any(_intervals_overlap(interval, prior) for prior in state.successful_intervals):
            state.redundant_overlap_count += 1
        state.successful_intervals.append(interval)


def _result_trace(call: ToolCall, result: ToolResult, round_index: int) -> dict[str, Any]:
    row: dict[str, Any] = {
        "round": round_index,
        "tool": call.name,
        "arguments": call.arguments
        if isinstance(call.arguments, dict)
        else _parse_args(call.arguments),
        "status": result.status.value,
        "content_head": result.content[:900],
        "evidence_ref": result.evidence_ref,
    }
    if "content=blocked" in result.content or "evidence_hydration_blocked" in result.content:
        row["stale_blocked"] = True
    return row


class FakeR5LLM:
    def __init__(self, fixture: R5Fixture, source_path: str | None) -> None:
        self.fixture = fixture
        self.source_path = source_path
        self.counter = 0

    def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kwargs: Any
    ):
        response = self._response(messages)
        if False:  # pragma: no cover
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

    def _final(self, answer: str) -> LLMResponse:
        self.counter += 1
        return LLMResponse(
            content=json.dumps({"answer": answer}),
            tool_calls=[],
            provider="fake",
            prompt_tokens=10,
            completion_tokens=10,
        )

    @staticmethod
    def _tool_contents(messages: list[dict[str, Any]]) -> str:
        return "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "tool")

    def _response(self, messages: list[dict[str, Any]]) -> LLMResponse:
        joined = self._tool_contents(messages)
        fixture = self.fixture
        if fixture.seed_id in {"J1", "J3"}:
            if fixture.current_answer in joined:
                return self._final(fixture.expected_answer)
            if "content=blocked" not in joined:
                return self._tool("search_evidence", {"query": fixture.target_field, "limit": 5})
            source_calls = joined.count("[read_file]")
            if source_calls == 0:
                return self._tool("read_file", {"path": self.source_path, "full": True})
            return self._tool("search_evidence", {"query": fixture.target_field, "limit": 5})
        if fixture.seed_id == "J2":
            if fixture.expected_answer in joined:
                return self._final(fixture.expected_answer)
            return self._tool(
                "search_evidence",
                {"query": fixture.target_field, "limit": 5, "allow_stale": True},
            )
        if fixture.seed_id == "J4":
            if fixture.expected_answer in joined:
                return self._final(fixture.expected_answer)
            return self._tool("search_evidence", {"query": fixture.target_field, "limit": 5})
        return self._final("UNKNOWN")


def execute_run(row: dict[str, Any], *, dry: bool = False) -> dict[str, Any]:
    run_id = str(row["run_id"])
    provider = str(row["provider"])
    fixture = FIXTURES[str(row["seed_id"])]
    profile = PROVIDERS[provider]
    run_dir = RUNTIME_DIR / ("dry" if dry else "real") / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    source_path: str | None = None
    if fixture.source_kind == "file":
        path = run_dir / f"{fixture.seed_id.lower()}-source.txt"
        path.write_text(fixture.initial_content, encoding="utf-8")
        source_path = str(path)

    owner = OwnerScope(workspace_id=str(run_dir), session_id=run_id)
    registry, ledger, freshness, projector, snapshot_tool = _build_registry(
        fixture=fixture, owner=owner, run_dir=run_dir
    )
    state = RunState()

    pre_call = _source_call(fixture, source_path, call_id=f"preacquire-{run_id}")
    pre_result = registry.execute(pre_call)
    if pre_result.status is not ToolResultStatus.SUCCESS or not pre_result.evidence_ref:
        return {
            "run_id": run_id,
            "provider": provider,
            "seed_id": fixture.seed_id,
            "status": "INFRA_FAILURE",
            "infra_error": "mechanical pre-acquisition did not produce durable Evidence",
            "preacquire_count": 0,
            "trace": [],
        }
    state.preacquire_count = 1

    if fixture.mutate_after_preacquire and source_path is not None:
        source_file = Path(source_path)
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
    llm: Any = FakeR5LLM(fixture, source_path) if dry else _build_client(provider)
    source_name = _source_name(fixture)
    trace: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    final_answer: str | None = None
    status = "COMPLETED"
    infra_error: str | None = None
    started = time.monotonic()

    try:
        for round_index in range(1, MAX_ROUNDS + 1):
            wire_messages = list(persisted)
            manifest = _current_manifest(owner=owner, projector=projector, freshness=freshness)
            if manifest:
                wire_messages.append({"role": "user", "content": manifest})
            state.request_count += 1
            response = _chat_once(
                llm,
                wire_messages,
                tools,
                run_id=run_id,
                provider=provider,
                model=profile["model"],
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
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments
                    if isinstance(call.arguments, dict)
                    else _parse_args(call.arguments),
                )
                for call in response.tool_calls
            ]
            persisted.append(_assistant_tools_message(calls, reasoning))
            for call in calls:
                if call.name == source_name:
                    state.model_source_attempt_count += 1
            results = registry.execute_many(calls)
            for call, result in zip(calls, results, strict=True):
                if call.name == source_name and result.status is ToolResultStatus.SUCCESS:
                    state.model_source_execution_count += 1
                    _record_source_success(state, call, fixture)
                if call.name in {
                    "read_evidence",
                    "search_evidence",
                    "list_evidence",
                    "search_archive",
                }:
                    if result.status is ToolResultStatus.SUCCESS:
                        state.recovery_success_count += 1
                        if call.name == "read_evidence":
                            state.read_evidence_success_count += 1
                        if call.name == "search_evidence":
                            state.search_evidence_success_count += 1
                    args = call.arguments if isinstance(call.arguments, dict) else {}
                    if (
                        args.get("allow_stale") is True
                        and result.status is ToolResultStatus.SUCCESS
                        and "historical_only" in result.content
                    ):
                        state.historical_access_success_count += 1
                    if (
                        "content=blocked" in result.content
                        or "evidence_hydration_blocked" in result.content
                    ):
                        state.stale_block_count += 1
                trace.append(_result_trace(call, result, round_index))
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
    stale_as_current = (
        fixture.seed_id in {"J1", "J3"}
        and fixture.historical_answer is not None
        and answer == fixture.historical_answer
    )
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
        "stale_as_current": stale_as_current,
        "preacquire_count": state.preacquire_count,
        "model_source_attempt_count": state.model_source_attempt_count,
        "model_source_execution_count": state.model_source_execution_count,
        "exact_source_args_repeat_count": state.exact_source_args_repeat_count,
        "redundant_overlap_count": state.redundant_overlap_count,
        "recovery_success_count": state.recovery_success_count,
        "read_evidence_success_count": state.read_evidence_success_count,
        "search_evidence_success_count": state.search_evidence_success_count,
        "historical_access_success_count": state.historical_access_success_count,
        "stale_block_count": state.stale_block_count,
        "request_count": state.request_count,
        "snapshot_execution_count_total": None
        if snapshot_tool is None
        else snapshot_tool.execution_count,
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
            "R5 unresolved started rows; automatic replay forbidden: " + ", ".join(unresolved)
        )


def _execute_real_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row["run_id"])
    _write_json_atomic(
        _started_path(run_id),
        {
            "schema": "evidence-r5-started-v1",
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
        {"status": attempt["status"], "infra_error": attempt.get("infra_error")}
        for attempt in attempts
    ]
    _write_json_atomic(_result_path(run_id), result)
    _started_path(run_id).unlink(missing_ok=True)
    return result


def _aggregate_real(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [json.loads(_result_path(str(row["run_id"])).read_text()) for row in rows]
    payload = {"schema": "evidence-r5-runs-v1", "count": len(results), "runs": results}
    _write_json_atomic(OUT_DIR / "runs_real_v1.json", payload)
    return payload


def run_rows(rows: list[dict[str, Any]], *, dry: bool) -> tuple[list[dict[str, Any]], int]:
    if dry:
        results = [execute_run(row, dry=True) for row in rows]
        _write_json_atomic(
            OUT_DIR / "runs_dry_v1.json",
            {"schema": "evidence-r5-runs-v1", "count": len(results), "runs": results},
        )
        for result in results:
            print(
                result["run_id"],
                result["provider"],
                result["seed_id"],
                result["status"],
                "exact=",
                result.get("final_answer_exact"),
                "source=",
                result.get("model_source_execution_count"),
                "repeat=",
                result.get("exact_source_args_repeat_count"),
                "overlap=",
                result.get("redundant_overlap_count"),
                "hist=",
                result.get("historical_access_success_count"),
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
        result = _execute_real_row(row)
        print(
            result["run_id"],
            result["provider"],
            result["seed_id"],
            result["status"],
            "exact=",
            result.get("final_answer_exact"),
            "source=",
            result.get("model_source_execution_count"),
            "repeat=",
            result.get("exact_source_args_repeat_count"),
            "overlap=",
            result.get("redundant_overlap_count"),
            "stale=",
            result.get("stale_as_current"),
        )
    payload = _aggregate_real(rows)
    unresolved = [r for r in payload["runs"] if r["status"] == "INFRA_FAILURE"]
    return list(payload["runs"]), 0 if not unresolved else 1


def snapshot_providers() -> dict[str, Any]:
    return {
        name: {
            "provider": name,
            "base_url": profile["base_url"],
            "model": profile["model"],
            "api_key_env": profile["api_key_env"],
            "api_key_set": bool(os.environ.get(profile["api_key_env"], "")),
            "max_tokens": profile["max_tokens"],
            "thinking_supported": profile["thinking_supported"],
            "fallback": "forbidden",
            "temperature": None,
            "top_p": None,
            "seed": None,
        }
        for name, profile in PROVIDERS.items()
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
