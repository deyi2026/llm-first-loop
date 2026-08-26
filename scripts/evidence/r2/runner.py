from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceError,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    OwnerScope,
    Provenance,
    RangeType,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)
from scripts.evidence.r2.fixtures import FIXTURES, R2Fixture, task_prompt

ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = ROOT / "tests/fixtures/evidence_r2/matrix_v1.json"
FREEZE_PATH = ROOT / "tests/fixtures/evidence_r2/frozen_v1.json"
OUT_DIR = ROOT / "data/audit/evidence_r2"
MAX_ROUNDS = 8

PROVIDERS = {
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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_frozen_artifacts() -> None:
    if not FREEZE_PATH.exists():
        raise RuntimeError(f"R2 freeze manifest missing: {FREEZE_PATH}")
    freeze = json.loads(FREEZE_PATH.read_text())
    for rel, expected in freeze["artifacts"].items():
        path = ROOT / rel
        got = _sha256(path)
        if got != expected:
            raise RuntimeError(f"R2 frozen artifact drift: {rel}: {got} != {expected}")


def _require_provider_credentials(rows: list[dict[str, Any]]) -> None:
    required = sorted({str(row["provider"]) for row in rows})
    missing = [
        PROVIDERS[name]["api_key_env"]
        for name in required
        if not os.environ.get(PROVIDERS[name]["api_key_env"], "")
    ]
    if missing:
        raise RuntimeError("R2 real execution preflight missing credentials: " + ", ".join(missing))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def _real_run_path(run_id: str) -> Path:
    return OUT_DIR / "real_runs_v1" / f"{run_id}.json"


def source_tool_spec(fixture: R2Fixture) -> dict[str, Any]:
    descriptions = {
        "read_source": "Read the current content of the named fixture source.",
        "run_snapshot": "Execute the fixture snapshot action and return its historical output.",
        "perform_action": "Perform the fixture side-effect action and return its receipt/output.",
    }
    return {
        "type": "function",
        "function": {
            "name": fixture.source_tool,
            "description": descriptions[fixture.source_tool],
            "parameters": {
                "type": "object",
                "properties": {"source": {"type": "string"}},
                "required": ["source"],
                "additionalProperties": False,
            },
        },
    }


def read_evidence_tool_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "read_evidence",
            "description": "Hydrate an already acquired EvidenceRef exactly. This does not execute the original source action.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ref": {"type": "string"},
                    "start": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 4000},
                },
                "required": ["ref"],
                "additionalProperties": False,
            },
        },
    }


def _source_identity(f: R2Fixture, version: str) -> SourceIdentity:
    if f.source_kind == "file":
        return SourceIdentity(SourceKind.FILE, f.source_id, SourceVersionPolicy.PROBEABLE, version)
    if f.source_kind == "command":
        return SourceIdentity(SourceKind.COMMAND, f.source_id, SourceVersionPolicy.SNAPSHOT_ONLY)
    return SourceIdentity(
        SourceKind.RUNTIME_SNAPSHOT, f.source_id, SourceVersionPolicy.VERSIONED, version
    )


def _source_coverage() -> Coverage:
    return Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True)


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


def _assistant_tools_message(
    tool_calls: list[ToolCall], reasoning: str | None = None
) -> dict[str, Any]:
    encoded = []
    for tc in tool_calls:
        args = tc.arguments if isinstance(tc.arguments, dict) else _parse_args(tc.arguments)
        encoded.append(
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
        )
    msg: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": encoded}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return msg


def _manifest_view(f: R2Fixture, ref: EvidenceRef, freshness: str) -> str:
    return (
        "[Recovery Manifest]\n"
        f"ref={ref.ref}\n"
        f"source={f.source_id}\n"
        f"acquired_version={f.initial_version}\n"
        f"freshness={freshness}\n"
        "representation=ref_only\n"
        "Exact prior observation can be hydrated with read_evidence."
    )


def _legacy_view(f: R2Fixture) -> str:
    return (
        "[context compacted]\n"
        f"An earlier observation from {f.source_id} was removed from active context.\n"
        "The exact prior bytes are not directly addressable in this condition."
    )


def _extract_answer(text: str | None) -> str | None:
    if not text:
        return None
    try:
        value = json.loads(text.strip())
        if isinstance(value, dict) and isinstance(value.get("answer"), str):
            return value["answer"]
    except json.JSONDecodeError:
        pass
    match = re.search(r'"answer"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _chat_once(
    llm: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    run_id: str,
    provider: str,
    model: str,
) -> LLMResponse:
    gen = llm.chat_stream(
        messages,
        tools,
        guard_context=GuardRequestContext(session_id=run_id, provider=provider, model=model),
    )
    it = iter(gen)
    while True:
        try:
            next(it)
        except StopIteration as exc:
            return exc.value


class FakeR2LLM:
    def __init__(self, fixture: R2Fixture, condition: str) -> None:
        self.fixture = fixture
        self.condition = condition
        self.step = 0

    @staticmethod
    def _latest_ref(messages: list[dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                m = re.search(r"ref=(evidence://v1/[0-9a-f]{64})", str(msg.get("content") or ""))
                if m:
                    return m.group(1)
        return ""

    def _source_response(self, call_no: int) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"fake-source-{call_no}",
                    name=self.fixture.source_tool,
                    arguments={"source": self.fixture.source_id},
                )
            ],
            provider="fake",
            prompt_tokens=20,
            completion_tokens=5,
        )

    def _hydrate_response(self, messages: list[dict[str, Any]], chunk: int) -> LLMResponse:
        return LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(
                    id=f"fake-hydrate-{chunk + 1}",
                    name="read_evidence",
                    arguments={
                        "ref": self._latest_ref(messages),
                        "start": chunk * 4000,
                        "limit": 4000,
                    },
                )
            ],
            provider="fake",
            prompt_tokens=20,
            completion_tokens=5,
        )

    def _final_response(self) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"answer": self.fixture.answer}),
            tool_calls=[],
            provider="fake",
            prompt_tokens=20,
            completion_tokens=8,
        )

    def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kwargs: Any
    ):
        self.step += 1
        if self.step == 1:
            resp = self._source_response(1)
        elif self.condition == "B0":
            # Dry B0 deliberately demonstrates a repeat action. Its behavioral outcome is a baseline,
            # not an E1 contract gate.
            resp = self._source_response(2) if self.step == 2 else self._final_response()
        elif self.fixture.seed_id == "F6":
            # First manifest is stale, so refresh source once; hydrate the newly captured v2 evidence.
            if self.step == 2:
                resp = self._source_response(2)
            elif 3 <= self.step <= 6:
                resp = self._hydrate_response(messages, self.step - 3)
            else:
                resp = self._final_response()
        else:
            # Exercise bounded hydration continuation across the whole ~13K fixture.
            resp = (
                self._hydrate_response(messages, self.step - 2)
                if 2 <= self.step <= 5
                else self._final_response()
            )
        if False:
            yield None
        return resp


@dataclass
class RunState:
    source_execution_count: int = 0
    evidence_hydration_attempt_count: int = 0
    evidence_hydration_count: int = 0
    freshness_probe_count: int = 0
    side_effect_duplicate_count: int = 0
    stale_used_as_current: bool = False
    first_evidence_ref: str | None = None
    current_version: str = ""


def _build_client(provider: str) -> LLMClient:
    p = PROVIDERS[provider]
    key = os.environ.get(p["api_key_env"], "")
    if not key:
        raise RuntimeError(f"{p['api_key_env']} is not set")
    return LLMClient(
        api_key=key,
        base_url=p["base_url"],
        model=p["model"],
        provider=provider,
        timeout_s=300.0,
        max_tokens=p["max_tokens"],
        wire_protocol="openai",
        thinking_supported=p["thinking_supported"],
        guard_enabled=False,
    )


def execute_run(row: dict[str, Any], *, dry: bool) -> dict[str, Any]:
    run_id = str(row["run_id"])
    provider = str(row["provider"])
    condition = str(row["condition"])
    fixture = FIXTURES[str(row["seed_id"])]
    p = PROVIDERS[provider]
    owner = OwnerScope(workspace_id="r2-fixture", session_id=run_id)
    temp = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=OUT_DIR))
    blobs = BlobStore(temp / "blobs")
    ledger = EvidenceLedgerStore(temp / "ledger")
    capture = EvidenceCapture(blobs, ledger)
    hydration = EvidenceHydration(blobs, ledger, max_limit=4000)
    state = RunState(current_version=fixture.initial_version)
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "You are evaluating supplied evidence. Use tools when evidence is needed. Return only the requested JSON answer.",
        },
        {"role": "user", "content": task_prompt(fixture.seed_id)},
    ]
    tools = [source_tool_spec(fixture)] + ([read_evidence_tool_spec()] if condition == "E1" else [])
    llm: Any = FakeR2LLM(fixture, condition) if dry else _build_client(provider)
    trace: list[dict[str, Any]] = []
    stats = {"prompt_tokens": 0, "completion_tokens": 0, "cache_hit_tokens": 0, "latency_s": 0.0}
    final: str | None = None
    status = "COMPLETED"
    infra_error = None
    t0 = time.monotonic()
    try:
        for round_index in range(1, MAX_ROUNDS + 1):
            resp = _chat_once(llm, messages, tools, run_id, provider, p["model"])
            stats["prompt_tokens"] += getattr(resp, "prompt_tokens", 0) or 0
            stats["completion_tokens"] += getattr(resp, "completion_tokens", 0) or 0
            stats["cache_hit_tokens"] += getattr(resp, "prompt_cache_hit_tokens", 0) or 0
            reasoning = getattr(resp, "reasoning_content", None) or getattr(resp, "reasoning", None)
            if not resp.tool_calls:
                final = resp.content
                break
            messages.append(_assistant_tools_message(list(resp.tool_calls), reasoning))
            for tc in resp.tool_calls:
                args = tc.arguments if isinstance(tc.arguments, dict) else _parse_args(tc.arguments)
                if tc.name == fixture.source_tool:
                    state.source_execution_count += 1
                    if fixture.side_effect and state.source_execution_count > 1:
                        state.side_effect_duplicate_count += 1
                    # F6 changes immediately after first acquisition; a legitimate second read sees v2.
                    if fixture.seed_id == "F6" and state.source_execution_count > 1:
                        raw = fixture.current_content
                        version = fixture.current_version
                    else:
                        raw = fixture.initial_content
                        version = fixture.initial_version
                    captured = capture.capture(
                        make_capture_request(
                            owner=owner,
                            stable_capture_id=tc.id,
                            raw_observation=raw,
                            acquired_at=datetime.now(UTC),
                            tool_name=tc.name,
                            tool_call_id=tc.id,
                            source=_source_identity(fixture, version),
                            coverage=_source_coverage(),
                            provenance=Provenance(
                                producer="r2_fixture", authority="frozen_fixture", scope=condition
                            ),
                        )
                    )
                    if state.first_evidence_ref is None:
                        state.first_evidence_ref = captured.evidence_ref.ref
                    if state.source_execution_count == 1 and fixture.freshness_case in {
                        "unchanged",
                        "changed",
                    }:
                        state.freshness_probe_count += 1
                    if fixture.seed_id == "F6" and state.source_execution_count == 1:
                        freshness = "stale"
                    elif fixture.source_kind == "file":
                        freshness = "verified_current"
                    else:
                        freshness = "unknown"
                    # Projection policy is invariant across executions. Re-running the source does not
                    # magically bypass projection; E1 gets a new stable ref, B0 gets the same legacy notice.
                    visible = (
                        _manifest_view(fixture, captured.evidence_ref, freshness)
                        if condition == "E1"
                        else _legacy_view(fixture)
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": visible})
                    trace.append(
                        {
                            "round": round_index,
                            "tool": tc.name,
                            "kind": "source",
                            "version": version,
                            "evidence_ref": captured.evidence_ref.ref,
                            "visible_chars": len(visible),
                        }
                    )
                elif tc.name == "read_evidence":
                    state.evidence_hydration_attempt_count += 1
                    try:
                        ref = EvidenceRef(str(args.get("ref") or ""))
                        start = max(0, int(args.get("start", 0) or 0))
                        limit = min(4000, max(1, int(args.get("limit", 4000) or 4000)))
                        result = hydration.read(
                            owner=owner,
                            evidence_ref=ref,
                            range_type=RangeType.TEXT_CHAR,
                            start=start,
                            limit=limit,
                        )
                    except (ValueError, EvidenceError) as exc:
                        # Invalid/unknown model-supplied tool arguments are behavioral tool failures,
                        # not runner/provider infrastructure failures. Return feedback and continue.
                        visible = (
                            f"[状态: failure] read_evidence rejected: {type(exc).__name__}: {exc}"
                        )
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": visible})
                        trace.append(
                            {
                                "round": round_index,
                                "tool": "read_evidence",
                                "kind": "hydrate_error",
                                "error_type": type(exc).__name__,
                            }
                        )
                        continue
                    state.evidence_hydration_count += 1
                    visible = result.content
                    if result.next_start is not None:
                        visible += f"\n[next_start={result.next_start}]"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": visible})
                    trace.append(
                        {
                            "round": round_index,
                            "tool": "read_evidence",
                            "kind": "hydrate",
                            "ref": ref.ref,
                            "start": start,
                            "limit": limit,
                            "chars": len(result.content),
                        }
                    )
                else:
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": "UNKNOWN_TOOL"}
                    )
                    trace.append({"round": round_index, "tool": tc.name, "kind": "unknown"})
        else:
            status = "ROUND_LIMIT"
    except Exception as exc:  # infra/protocol errors are kept distinct from behavioral score
        status = "INFRA_FAILURE"
        infra_error = f"{type(exc).__name__}: {exc}"
    finally:
        stats["latency_s"] = round(time.monotonic() - t0, 3)
        if not dry:
            with suppress(Exception):
                llm.close()
        shutil.rmtree(temp, ignore_errors=True)

    answer = _extract_answer(final)
    exact = answer == fixture.answer
    # Stale-as-current is mechanically detectable on F6 if final emits the frozen old answer.
    if fixture.seed_id == "F6" and answer == "OLD-103":
        state.stale_used_as_current = True
    if condition == "E1" and fixture.seed_id in {"F1", "F2", "F3", "F4", "F5"}:
        e1_success = (
            exact
            and state.source_execution_count == 1
            and state.evidence_hydration_count >= 1
            and state.side_effect_duplicate_count == 0
        )
    elif condition == "E1" and fixture.seed_id == "F6":
        e1_success = (
            exact
            and state.source_execution_count == 2
            and state.evidence_hydration_count >= 1
            and not state.stale_used_as_current
        )
    else:
        e1_success = None
    # B0 is observational: exact completion is useful, but it is never judged by E1's one-source rule.
    harness_success = status == "COMPLETED" and exact and (e1_success is not False)
    return {
        **row,
        "status": status,
        "infra_error": infra_error,
        "dry": dry,
        "model_used": "fake-dry" if dry else f"{provider}/{p['model']}",
        "final_answer": final,
        "answer": answer,
        "expected_answer": fixture.answer,
        "final_answer_exact": exact,
        "source_execution_count": state.source_execution_count,
        "evidence_hydration_attempt_count": state.evidence_hydration_attempt_count,
        "evidence_hydration_count": state.evidence_hydration_count,
        "freshness_probe_count": state.freshness_probe_count,
        "side_effect_duplicate_count": state.side_effect_duplicate_count,
        "stale_used_as_current": state.stale_used_as_current,
        "harness_success": harness_success,
        "e1_success": e1_success,
        "round_count": len({x["round"] for x in trace}),
        "trace": trace,
        "stats": stats,
    }


def snapshot_providers() -> dict[str, Any]:
    data = {}
    for name, p in PROVIDERS.items():
        data[name] = {
            "provider": name,
            "base_url": p["base_url"],
            "model": p["model"],
            "api_key_env": p["api_key_env"],
            "api_key_set": bool(os.environ.get(p["api_key_env"])),
            "max_tokens": p["max_tokens"],
            "thinking_supported": p["thinking_supported"],
            "wire_protocol": "openai",
            "fallback": "forbidden",
            "temperature": None,
            "top_p": None,
            "seed": None,
            "context_tokens_registry": 1000000,
        }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "provider_snapshot_v1.json").write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--run")
    ap.add_argument("--snapshot", action="store_true")
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.snapshot:
        print(json.dumps(snapshot_providers(), indent=2))
        return 0
    matrix = json.loads(MATRIX_PATH.read_text())["runs"]
    rows = matrix if args.all else [r for r in matrix if r["run_id"] == args.run]
    if not rows:
        raise SystemExit("select --all or valid --run")
    if not args.dry:
        # Atomic preflight: no real request is allowed until the frozen experiment is intact
        # and every provider needed by the selected matrix has credentials.
        _verify_frozen_artifacts()
        _require_provider_credentials(rows)
    results = []
    for row in rows:
        persisted = _real_run_path(str(row["run_id"]))
        if not args.dry and persisted.exists():
            existing = json.loads(persisted.read_text())
            if existing.get("status") == "COMPLETED":
                result = existing
                results.append(result)
                print(row["run_id"], "RESUME existing completed result")
                continue
        result = execute_run(row, dry=args.dry)
        attempts = 1
        if not args.dry and result["status"] == "INFRA_FAILURE":
            result = execute_run(row, dry=False)
            attempts = 2
        result["infra_attempts"] = attempts
        if not args.dry:
            _write_json_atomic(persisted, result)
        results.append(result)
        print(
            result["run_id"],
            result["provider"],
            result["seed_id"],
            result["condition"],
            result["status"],
            "harness=",
            result["harness_success"],
            "e1=",
            result["e1_success"],
            "src=",
            result["source_execution_count"],
            "hyd=",
            result["evidence_hydration_count"],
        )
    suffix = "dry" if args.dry else "real"
    out = OUT_DIR / f"runs_{suffix}_v1.json"
    _write_json_atomic(
        out, {"schema": "evidence-r2-runs-v1", "count": len(results), "runs": results}
    )
    if args.dry:
        failed = [r for r in results if r["status"] != "COMPLETED" or not r["harness_success"]]
    else:
        # Behavioral failures are R2 data and must not abort/erase the matrix. Only infra failure
        # makes the execution command fail; aggregate confirmatory gates are scored afterward.
        failed = [r for r in results if r["status"] != "COMPLETED"]
    print("summary", len(results) - len(failed), "/", len(results), "execution-pass", "output", out)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
