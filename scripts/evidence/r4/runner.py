from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
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
from scripts.evidence._capsule_pin import pinned_capsule_on
from scripts.evidence.r4.fixtures import FIXTURES, R4Fixture

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = ROOT / "tests/fixtures/evidence_r4/fixtures_v1.json"
MATRIX_PATH = ROOT / "tests/fixtures/evidence_r4/matrix_v1.json"
FROZEN_PATH = ROOT / "tests/fixtures/evidence_r4/frozen_v1.1.json"
OUT_DIR = ROOT / "data/audit/evidence_r4"
REAL_ROWS_DIR = OUT_DIR / "real_runs_v1"
RUNTIME_DIR = OUT_DIR / "runtime"
LOCK_PATH = OUT_DIR / ".real_runner.lock"
MAX_ROUNDS = 14

PROVIDERS: dict[str, dict[str, Any]] = {
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "model": "MiniMax-M3",
        "api_key_env": "MINIMAX_API_KEY",
        "max_tokens": 65536,
        "thinking_supported": False,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "max_tokens": 16384,
        "thinking_supported": True,
    },
}


class RunnerLockError(RuntimeError):
    pass


@contextmanager
def runner_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RunnerLockError(f"another R4 runner already holds {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()} acquired_at={datetime.now(UTC).isoformat()}\n")
        handle.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_frozen_pack() -> dict[str, Any]:
    if not FROZEN_PATH.exists():
        raise RuntimeError(f"R4 frozen lock missing: {FROZEN_PATH}")
    frozen = json.loads(FROZEN_PATH.read_text(encoding="utf-8"))
    if frozen.get("schema") != "evidence-r4-frozen-v1.1":
        raise RuntimeError("R4 frozen lock schema mismatch")
    mismatches = []
    for rel, expected in frozen.get("artifacts", {}).items():
        path = ROOT / rel
        actual = _sha256(path) if path.exists() else "MISSING"
        if actual != expected:
            mismatches.append(f"{rel}: expected={expected} actual={actual}")
    if mismatches:
        raise RuntimeError("R4 frozen artifact mismatch: " + "; ".join(mismatches))
    return frozen


def require_all_credentials() -> None:
    missing = [
        profile["api_key_env"]
        for profile in PROVIDERS.values()
        if not os.environ.get(profile["api_key_env"], "")
    ]
    if missing:
        raise RuntimeError("R4 real execution preflight missing credentials: " + ", ".join(missing))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}


def _schema_to_param(schema: dict[str, Any]) -> dict[str, Any]:
    """Match production LoopEngine._schema_to_param wire shape exactly."""
    return {
        "type": "function",
        "function": {
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["parameters"],
        },
    }


def _assistant_tools_message(tool_calls: list[ToolCall], reasoning: str | None) -> dict[str, Any]:
    encoded = []
    for call in tool_calls:
        args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
        encoded.append(
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        )
    message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": encoded}
    if reasoning:
        message["reasoning_content"] = reasoning
    return message


def _extract_answer(text: str | None) -> str | None:
    if not text:
        return None
    try:
        payload = json.loads(text.strip())
        if isinstance(payload, dict) and isinstance(payload.get("answer"), str):
            return payload["answer"]
    except json.JSONDecodeError:
        pass
    match = re.search(r'"answer"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _build_client(provider: str) -> LLMClient:
    profile = PROVIDERS[provider]
    key = os.environ.get(profile["api_key_env"], "")
    if not key:
        raise RuntimeError(f"{profile['api_key_env']} not set")
    return LLMClient(
        api_key=key,
        base_url=profile["base_url"],
        model=profile["model"],
        provider=provider,
        timeout_s=300.0,
        max_tokens=profile["max_tokens"],
        wire_protocol="openai",
        thinking_supported=profile["thinking_supported"],
        guard_enabled=False,
    )


def _chat_once(
    llm: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    run_id: str,
    provider: str,
    model: str,
) -> LLMResponse:
    generator = llm.chat_stream(
        messages,
        tools,
        guard_context=GuardRequestContext(session_id=run_id, provider=provider, model=model),
    )
    iterator = iter(generator)
    while True:
        try:
            next(iterator)
        except StopIteration as exc:
            return exc.value


class R4FixtureObservationTool:
    description = "Acquire the specified frozen R4 fixture observation."
    parameters = {
        "type": "object",
        "properties": {"source": {"type": "string"}},
        "required": ["source"],
        "additionalProperties": False,
    }

    def __init__(self, fixture: R4Fixture) -> None:
        self.fixture = fixture
        self.name = "r4_issue_receipt" if fixture.source_kind == "action" else "r4_snapshot"
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
    source_attempt_count: int = 0
    source_execution_count: int = 0
    side_effect_duplicate_count: int = 0
    recovery_success_count: int = 0
    read_evidence_success_count: int = 0
    search_evidence_success_count: int = 0
    list_evidence_success_count: int = 0
    historical_access_success_count: int = 0
    stale_block_count: int = 0
    mutation_done: bool = False
    request_count: int = 0


class FakeR4LLM:
    def __init__(self, fixture: R4Fixture, source_path: str | None) -> None:
        self.fixture = fixture
        self.source_path = source_path
        self.step = 0

    def chat_stream(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kwargs: Any):
        response = self._response(messages)
        if False:  # pragma: no cover
            yield None
        return response

    @staticmethod
    def _tool_contents(messages: list[dict[str, Any]]) -> list[str]:
        return [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]

    @staticmethod
    def _latest_ref(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            match = re.search(r"evidence://v1/[0-9a-f]{64}", str(message.get("content") or ""))
            if match:
                return match.group(0)
        return ""

    @staticmethod
    def _latest_next_start(messages: list[dict[str, Any]]) -> int:
        for content in reversed(FakeR4LLM._tool_contents(messages)):
            body = content.split("] ", 1)[1] if content.startswith("[状态:") and "] " in content else content
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("kind") == "evidence_hydration":
                next_start = payload.get("range", {}).get("next_start")
                if isinstance(next_start, int):
                    return next_start
        return 0

    def _source_call(self) -> ToolCall:
        if self.fixture.source_kind == "file":
            return ToolCall(
                id=f"fake-source-{self.step}",
                name="read_file",
                arguments={"path": self.source_path, "full": True},
            )
        name = "r4_issue_receipt" if self.fixture.source_kind == "action" else "r4_snapshot"
        return ToolCall(
            id=f"fake-source-{self.step}",
            name=name,
            arguments={"source": f"fixture://r4/{self.fixture.seed_id.lower()}"},
        )

    def _tool(self, name: str, arguments: dict[str, Any]) -> LLMResponse:
        self.step += 1
        return LLMResponse(
            content=None,
            tool_calls=[ToolCall(id=f"fake-{name}-{self.step}", name=name, arguments=arguments)],
            provider="fake",
            prompt_tokens=10,
            completion_tokens=5,
        )

    def _final(self, answer: str) -> LLMResponse:
        self.step += 1
        return LLMResponse(
            content=json.dumps({"answer": answer}),
            tool_calls=[],
            provider="fake",
            prompt_tokens=10,
            completion_tokens=10,
        )

    def _response(self, messages: list[dict[str, Any]]) -> LLMResponse:
        contents = self._tool_contents(messages)
        if not contents:
            self.step += 1
            return LLMResponse(
                content=None,
                tool_calls=[self._source_call()],
                provider="fake",
                prompt_tokens=10,
                completion_tokens=5,
            )
        ref = self._latest_ref(messages)
        seed = self.fixture.seed_id
        joined = "\n".join(contents)

        if seed == "K1":
            if self.fixture.answer in joined:
                return self._final(self.fixture.answer)
            return self._tool(
                "read_evidence",
                {"evidence_ref": ref, "range_type": "text_char", "start": self._latest_next_start(messages), "limit": 4000},
            )
        if seed == "K2":
            if "R4-K2-LEFT:" not in joined:
                return self._tool("search_evidence", {"query": "R4-K2-LEFT", "limit": 5})
            if "R4-K2-RIGHT:" not in joined:
                return self._tool("search_evidence", {"query": "R4-K2-RIGHT", "limit": 5})
            return self._final(self.fixture.answer)
        if seed == "K3":
            if "ACTION BUSINESS RECEIPT:" not in joined:
                return self._tool("search_evidence", {"query": '"ACTION BUSINESS RECEIPT"', "limit": 5})
            return self._final(self.fixture.answer)
        if seed == "K4":
            if "content=blocked" not in joined and "evidence_hydration_blocked" not in joined:
                return self._tool("search_evidence", {"query": "R4-K4-CURRENT-VALUE", "limit": 5})
            source_results = [c for c in contents if "[evidence]" in c]
            if len(source_results) < 2:
                self.step += 1
                return LLMResponse(
                    content=None,
                    tool_calls=[self._source_call()],
                    provider="fake",
                    prompt_tokens=10,
                    completion_tokens=5,
                )
            if self.fixture.current_answer not in joined:
                return self._tool("search_evidence", {"query": "R4-K4-CURRENT-VALUE", "limit": 5})
            return self._final(self.fixture.answer)
        if seed == "K5":
            if self.fixture.initial_answer not in joined:
                return self._tool(
                    "search_evidence",
                    {"query": "R4-K5-FIRST-OBSERVATION", "limit": 5, "allow_stale": True},
                )
            return self._final(self.fixture.answer)
        if seed == "K6":
            if self.fixture.answer not in joined:
                return self._tool("search_evidence", {"query": "R4-K6-SNAPSHOT-VALUE", "limit": 5})
            return self._final(self.fixture.answer)
        return self._final("UNKNOWN")


def _task_prompt(fixture: R4Fixture, source_path: str | None) -> str:
    if fixture.source_kind == "file":
        source_note = f"Source file: {source_path}. The source tool is read_file."
    elif fixture.source_kind == "action":
        source_note = "Source action: r4_issue_receipt with source=fixture://r4/k3."
    else:
        source_note = "Source snapshot: r4_snapshot with source=fixture://r4/k6."
    return (
        f"R4 fresh holdout task {fixture.seed_id}.\n{source_note}\n{fixture.task}\n"
        "Inspect the evidence needed for the answer. Return only JSON: {\"answer\":\"<value>\"}. Do not guess."
    )


def _current_manifest(
    *,
    owner: OwnerScope,
    projector: ManifestProjector,
    freshness: EvidenceFreshness,
    limit: int = 8,
) -> str:
    manifest = projector.build_recent(owner=owner, limit=limit)
    for entry in manifest.entries:
        freshness.refresh(owner=owner, evidence_ref=entry.evidence_ref)
    return render_recovery_manifest(projector.build_recent(owner=owner, limit=limit))


def _build_registry(
    *, fixture: R4Fixture, owner: OwnerScope, run_dir: Path
) -> tuple[ToolRegistry, EvidenceLedgerStore, EvidenceFreshness, ManifestProjector, R4FixtureObservationTool | None]:
    blobs = BlobStore(run_dir / "evidence" / "blobs")
    ledger = EvidenceLedgerStore(run_dir / "evidence" / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    freshness = EvidenceFreshness(ledger)
    search = EvidenceSearch(blobs, ledger, snippet_chars=500)
    registry = ToolRegistry(
        max_output_chars=100000,
        failure_guidance_enabled=False,
    )
    source_tool: R4FixtureObservationTool | None = None
    if fixture.source_kind == "file":
        registry.register(ReadFileTool())
    else:
        source_tool = R4FixtureObservationTool(fixture)
        registry.register(source_tool)
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
    registry.register(
        EvidenceSearchTool(search, freshness=freshness, owner_resolver=lambda: owner)
    )
    registry.register(EvidenceListTool(ledger, freshness=freshness, owner_resolver=lambda: owner))
    registry.register(
        SearchArchiveCompatTool(search, freshness=freshness, owner_resolver=lambda: owner)
    )
    return registry, ledger, freshness, ManifestProjector(ledger), source_tool


def _result_trace(call: ToolCall, result: ToolResult, round_index: int) -> dict[str, Any]:
    args = call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments)
    row: dict[str, Any] = {
        "round": round_index,
        "tool": call.name,
        "arguments": args,
        "status": result.status.value,
        "content_head": result.content[:800],
        "evidence_ref": result.evidence_ref,
    }
    if call.name == "read_evidence" and result.status is ToolResultStatus.SUCCESS:
        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(result.content)
            if isinstance(payload, dict):
                row["freshness"] = payload.get("freshness")
                row["range"] = payload.get("range")
    if call.name in {"search_evidence", "search_archive"}:
        row["stale_blocked"] = "content=blocked" in result.content
    if result.status is ToolResultStatus.FAILURE and "evidence_hydration_blocked" in result.content:
        row["stale_blocked"] = True
    return row


def _source_call_name(fixture: R4Fixture) -> str:
    if fixture.source_kind == "file":
        return "read_file"
    if fixture.source_kind == "action":
        return "r4_issue_receipt"
    return "r4_snapshot"


def execute_run(row: dict[str, Any], *, dry: bool = False) -> dict[str, Any]:
    # R9-P0-01 批 1/3：R4 基准协议固化于 capsule=on 历史文本形状，回放钉住
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
    source_path: str | None = None
    if fixture.source_kind == "file":
        path = run_dir / f"{fixture.seed_id.lower()}-source.txt"
        path.write_text(fixture.initial_content, encoding="utf-8")
        source_path = str(path)

    owner = OwnerScope(workspace_id=str(run_dir), session_id=run_id)
    registry, ledger, freshness, projector, source_tool = _build_registry(
        fixture=fixture, owner=owner, run_dir=run_dir
    )
    persisted: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are solving a fresh evidence-inspection holdout. Use available tools as needed. "
                "Return only the requested JSON answer."
            ),
        },
        {"role": "user", "content": _task_prompt(fixture, source_path)},
    ]
    tools = [_schema_to_param(schema) for schema in registry.schemas(lazy=False)]
    llm: Any = FakeR4LLM(fixture, source_path) if dry else _build_client(provider)
    state = RunState()
    trace: list[dict[str, Any]] = []
    reasoning_parts: list[str] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    final_answer: str | None = None
    status = "COMPLETED"
    infra_error: str | None = None
    started = time.monotonic()
    source_name = _source_call_name(fixture)

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
            reasoning = getattr(response, "reasoning_content", None) or getattr(response, "reasoning", None)
            if reasoning:
                reasoning_parts.append(reasoning)
            if not response.tool_calls:
                final_answer = response.content
                break

            calls = [
                ToolCall(
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments if isinstance(call.arguments, dict) else _parse_args(call.arguments),
                )
                for call in response.tool_calls
            ]
            persisted.append(_assistant_tools_message(calls, reasoning))
            for call in calls:
                if call.name == source_name:
                    state.source_attempt_count += 1
            results = registry.execute_many(calls)
            for call, result in zip(calls, results, strict=True):
                if call.name == source_name and result.status is ToolResultStatus.SUCCESS:
                    state.source_execution_count += 1
                if call.name in {"read_evidence", "search_evidence", "list_evidence", "search_archive"}:
                    if result.status is ToolResultStatus.SUCCESS:
                        state.recovery_success_count += 1
                        if call.name == "read_evidence":
                            state.read_evidence_success_count += 1
                        elif call.name == "search_evidence":
                            state.search_evidence_success_count += 1
                        elif call.name == "list_evidence":
                            state.list_evidence_success_count += 1
                    args = call.arguments if isinstance(call.arguments, dict) else {}
                    if (
                        args.get("allow_stale") is True
                        and result.status is ToolResultStatus.SUCCESS
                        and ("historical_only" in result.content or '"state": "stale"' in result.content)
                    ):
                        state.historical_access_success_count += 1
                    if "content=blocked" in result.content or "evidence_hydration_blocked" in result.content:
                        state.stale_block_count += 1
                trace.append(_result_trace(call, result, round_index))
                persisted.append(result.to_message().to_llm_dict())

            if (
                fixture.mutate_after_first
                and not state.mutation_done
                and state.source_execution_count >= 1
                and source_path is not None
            ):
                Path(source_path).write_text(fixture.current_content, encoding="utf-8")
                state.mutation_done = True
            if source_tool is not None and fixture.side_effect:
                state.side_effect_duplicate_count = max(0, source_tool.execution_count - 1)
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
    exact = answer == fixture.answer
    transport_ref = bool(answer and answer.startswith("evidence://"))
    stale_as_current = fixture.seed_id == "K4" and answer == fixture.initial_answer
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
        "expected_answer": fixture.answer,
        "final_answer_exact": exact,
        "transport_ref_as_domain_answer": transport_ref,
        "stale_as_current": stale_as_current,
        "source_attempt_count": state.source_attempt_count,
        "source_execution_count": state.source_execution_count,
        "side_effect_duplicate_count": state.side_effect_duplicate_count,
        "recovery_success_count": state.recovery_success_count,
        "read_evidence_success_count": state.read_evidence_success_count,
        "search_evidence_success_count": state.search_evidence_success_count,
        "list_evidence_success_count": state.list_evidence_success_count,
        "historical_access_success_count": state.historical_access_success_count,
        "stale_block_count": state.stale_block_count,
        "mutation_done": state.mutation_done,
        "request_count": state.request_count,
        "reasoning": "\n".join(reasoning_parts) if reasoning_parts else None,
        "stats": stats,
        "trace": trace,
    }


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
            "wire_protocol": "openai",
            "fallback": "forbidden",
            "temperature": None,
            "top_p": None,
            "seed": None,
            "context_tokens_registry": 1000000,
        }
        for name, profile in PROVIDERS.items()
    }


def _load_matrix() -> list[dict[str, Any]]:
    payload = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return list(payload["runs"])


def _real_result_path(run_id: str) -> Path:
    return REAL_ROWS_DIR / f"{run_id}.json"


def _started_path(run_id: str) -> Path:
    return REAL_ROWS_DIR / f"{run_id}.started.json"


def _ensure_no_unresolved_started(rows: list[dict[str, Any]]) -> None:
    unresolved = []
    for row in rows:
        run_id = str(row["run_id"])
        started = _started_path(run_id)
        completed = _real_result_path(run_id)
        if started.exists() and not completed.exists():
            unresolved.append(run_id)
        elif started.exists() and completed.exists():
            started.unlink()
    if unresolved:
        raise RuntimeError(
            "R4 unresolved started rows; automatic replay is forbidden to avoid duplicate provider conversations: "
            + ", ".join(unresolved)
        )


def _execute_real_row(row: dict[str, Any]) -> dict[str, Any]:
    run_id = str(row["run_id"])
    journal = {
        "schema": "evidence-r4-started-v1",
        "run_id": run_id,
        "provider": row["provider"],
        "seed_id": row["seed_id"],
        "started_at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    _write_json_atomic(_started_path(run_id), journal)
    first = execute_run(row, dry=False)
    attempts = [first]
    result = first
    if first["status"] == "INFRA_FAILURE":
        second = execute_run(row, dry=False)
        attempts.append(second)
        result = second
    result = dict(result)
    result["attempt_count"] = len(attempts)
    result["infra_attempts"] = [
        {"status": item["status"], "infra_error": item.get("infra_error")}
        for item in attempts
    ]
    _write_json_atomic(_real_result_path(run_id), result)
    _started_path(run_id).unlink(missing_ok=True)
    return result


def _aggregate_real(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [json.loads(_real_result_path(str(row["run_id"])).read_text()) for row in rows]
    payload = {"schema": "evidence-r4-runs-v1", "count": len(results), "runs": results}
    _write_json_atomic(OUT_DIR / "runs_real_v1.json", payload)
    return payload


def run_rows(rows: list[dict[str, Any]], *, dry: bool) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    if dry:
        for row in rows:
            result = execute_run(row, dry=True)
            results.append(result)
            print(
                result["run_id"], result["provider"], result["seed_id"], result["status"],
                "exact=", result["final_answer_exact"], "src=", result["source_execution_count"],
                "recovery=", result["recovery_success_count"], "hist=", result["historical_access_success_count"],
            )
        payload = {"schema": "evidence-r4-runs-v1", "count": len(results), "runs": results}
        _write_json_atomic(OUT_DIR / "runs_dry_v1.json", payload)
        failed = [r for r in results if r["status"] != "COMPLETED" or not r["final_answer_exact"]]
        return results, 0 if not failed else 1

    REAL_ROWS_DIR.mkdir(parents=True, exist_ok=True)
    _ensure_no_unresolved_started(rows)
    for row in rows:
        run_id = str(row["run_id"])
        completed = _real_result_path(run_id)
        if completed.exists():
            result = json.loads(completed.read_text())
            print(run_id, "SKIP completed", result.get("status"))
            continue
        result = _execute_real_row(row)
        print(
            result["run_id"], result["provider"], result["seed_id"], result["status"],
            "exact=", result["final_answer_exact"], "src=", result["source_execution_count"],
            "recovery=", result["recovery_success_count"], "stale=", result["stale_as_current"],
        )
    payload = _aggregate_real(rows)
    unresolved = [r for r in payload["runs"] if r["status"] == "INFRA_FAILURE"]
    return list(payload["runs"]), 0 if not unresolved else 1


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
    matrix = _load_matrix()
    rows = matrix if args.all else [row for row in matrix if row["run_id"] == args.run]
    if not rows:
        raise SystemExit("select --all or a valid --run")
    if args.dry:
        _, rc = run_rows(rows, dry=True)
        return rc

    verify_frozen_pack()
    require_all_credentials()
    with runner_lock():
        _, rc = run_rows(rows, dry=False)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
