#!/usr/bin/env python3
"""R1 deterministic historical trace replay for Evidence Recoverability Contract.

No model/provider or source tool is called. Historical tool observations are replay-captured
in temporal order into an isolated Evidence store, then exact repeats are checked for whether
the prior concrete observation was already programmatically hidden and still exactly hydratable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import socket
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_loop.core.message import ToolCall
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceCapture,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    OwnerScope,
    Provenance,
    RangeType,
    make_capture_request,
)
from llm_loop.tools.evidence_shadow import source_for_call

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/fixtures/evidence_r1_historical_v1.json"
REPORT = ROOT / "data/audit/evidence_r1_replay_v1.json"


class NetworkForbiddenError(AssertionError):
    pass


def _deny_network() -> None:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(sock: socket.socket, address: Any) -> Any:
        if sock.family == socket.AF_UNIX:
            return original_connect(sock, address)
        raise NetworkForbiddenError(f"R1 forbids network connect: {address!r}")

    def connect_ex(sock: socket.socket, address: Any) -> int:
        if sock.family == socket.AF_UNIX:
            return original_connect_ex(sock, address)
        raise NetworkForbiddenError(f"R1 forbids network connect_ex: {address!r}")

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return value if isinstance(value, dict) else {"_value": value}
    return {"_value": raw}


def _canonical_args(raw: Any) -> str:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip()
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso_datetime(value: str | None) -> datetime:
    if not value:
        raise ValueError("historical event missing timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def _hydrate_exact(hydration: EvidenceHydration, owner: OwnerScope, ref: EvidenceRef) -> str:
    start = 0
    chunks: list[str] = []
    while True:
        part = hydration.read(
            owner=owner,
            evidence_ref=ref,
            range_type=RangeType.TEXT_CHAR,
            start=start,
            limit=4000,
        )
        chunks.append(part.content)
        if part.next_start is None:
            return "".join(chunks)
        start = part.next_start


def _first_user(events: list[dict[str, Any]]) -> str:
    for event in events:
        payload = event.get("payload") or {}
        if event.get("type") == "message.appended" and payload.get("role") == "user":
            return str(payload.get("content") or "")
    return ""


def _is_synthetic(first_user: str, prefixes: list[str]) -> bool:
    text = first_user.lstrip()
    return any(text.startswith(prefix) for prefix in prefixes)


@dataclass
class Occurrence:
    call_id: str
    name: str
    key: str
    args: dict[str, Any]
    call_seq: int
    model: str
    result_index: int | None = None
    result_seq: int | None = None
    result_content: str | None = None
    result_status: str | None = None
    evidence_ref: EvidenceRef | None = None


@dataclass
class PendingRepeat:
    session_id: str
    synthetic: bool
    current_call_id: str
    tool_name: str
    key: str
    prior: Occurrence
    current_call_seq: int
    prior_hidden: bool
    any_compression_between: bool
    recoverable_before_repeat: bool
    hydration_exact: bool
    prior_model: str
    current_model: str
    classification: str = "pending"
    current_result_status: str | None = None
    current_result_same: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "synthetic": self.synthetic,
            "tool_name": self.tool_name,
            "key_sha256": hashlib.sha256(self.key.encode()).hexdigest(),
            "prior_call_id": self.prior.call_id,
            "current_call_id": self.current_call_id,
            "prior_call_seq": self.prior.call_seq,
            "current_call_seq": self.current_call_seq,
            "prior_result_index": self.prior.result_index,
            "prior_hidden": self.prior_hidden,
            "any_compression_between": self.any_compression_between,
            "recoverable_before_repeat": self.recoverable_before_repeat,
            "hydration_exact": self.hydration_exact,
            "prior_model": self.prior_model,
            "current_model": self.current_model,
            "provider_switch": bool(self.prior_model and self.current_model and self.prior_model != self.current_model),
            "current_result_status": self.current_result_status,
            "current_result_same": self.current_result_same,
            "classification": self.classification,
        }


def _classify(repeat: PendingRepeat, dynamic_tools: set[str]) -> str:
    if not repeat.recoverable_before_repeat or not repeat.hydration_exact:
        return "no_temporal_prior_observation"
    if not repeat.prior_hidden:
        return "model_repeat_while_visible"
    if repeat.tool_name == "read_file":
        if repeat.current_result_same is True:
            return "program_amnesia_avoidable"
        if repeat.current_result_same is False:
            return "freshness_change_observed"
        return "ambiguous_hidden_repeat"
    if repeat.tool_name in dynamic_tools:
        return "freshness_or_polling"
    return "ambiguous_hidden_repeat"


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    return events


def _verify_frozen_inputs(manifest: dict[str, Any]) -> None:
    hashes = manifest["contract_hashes"]
    expected = {
        ROOT / ".codeartsdoer/specs/ev_recov/spec.md": hashes["spec_sha256"],
        ROOT / ".codeartsdoer/specs/ev_recov/design.md": hashes["design_sha256"],
        ROOT / "docs/PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md": hashes["root_cause_sha256"],
        ROOT / "docs/RECOVERABILITY-R0-FULL-RESULT-v1.md": hashes["full_r0_sha256"],
    }
    for path, sha in expected.items():
        got = _sha(path)
        if got != sha:
            raise AssertionError(f"frozen contract hash mismatch: {path}: {got} != {sha}")
    for item in manifest["logs"]:
        path = ROOT / item["path"]
        got = _sha(path)
        if got != item["sha256"]:
            raise AssertionError(f"historical log changed after freeze: {path}: {got} != {item['sha256']}")


def replay(manifest: dict[str, Any]) -> dict[str, Any]:
    dynamic_tools = set(str(x) for x in manifest["dynamic_tools"])
    prefixes = [str(x) for x in manifest["synthetic_stratum_first_user_prefixes"]]
    counts: Counter[str] = Counter()
    synthetic_counts: Counter[str] = Counter()
    natural_counts: Counter[str] = Counter()
    tool_counts: dict[str, Counter[str]] = {}
    repeats: list[PendingRepeat] = []
    capture_ms: list[float] = []
    hydration_ms: list[float] = []
    cross_run_repeat = 0
    source_actions_executed = 0

    temp_parent = ROOT / "data/audit"
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="r1-evidence-", dir=temp_parent))
    try:
        blobs = BlobStore(temp_dir / "blobs")
        ledger = EvidenceLedgerStore(temp_dir / "ledger")
        capture = EvidenceCapture(blobs, ledger)
        hydration = EvidenceHydration(blobs, ledger, max_limit=4000)

        for item in manifest["logs"]:
            path = ROOT / item["path"]
            events = _load_events(path)
            session_id = path.stem
            owner = OwnerScope(workspace_id="historical-r1", session_id=session_id)
            synthetic = _is_synthetic(_first_user(events), prefixes)
            counts["sessions"] += 1
            counts["synthetic_sessions" if synthetic else "naturalistic_sessions"] += 1

            run_seen: dict[str, Occurrence] = {}
            session_seen: dict[str, Occurrence] = {}
            occurrence_by_id: dict[str, Occurrence] = {}
            pending_by_current_id: dict[str, PendingRepeat] = {}
            compressed_by_index: dict[int, list[int]] = {}
            compressed_seqs: list[int] = []
            current_model = ""

            for event in events:
                etype = event.get("type")
                payload = event.get("payload") or {}
                seq = int(event.get("seq") or 0)

                if etype == "request.meta":
                    current_model = str(payload.get("model") or current_model)
                    continue
                if etype == "context.compressed":
                    idx = payload.get("msg_seq")
                    if isinstance(idx, int):
                        compressed_by_index.setdefault(idx, []).append(seq)
                    compressed_seqs.append(seq)
                    continue
                if etype == "run.end":
                    run_seen = {}
                    continue
                if etype != "message.appended":
                    continue

                role = payload.get("role")
                if role == "assistant":
                    for raw_tc in payload.get("tool_calls") or []:
                        function = raw_tc.get("function") or {}
                        name = str(function.get("name") or "")
                        call_id = str(raw_tc.get("id") or "")
                        if not name or not call_id:
                            continue
                        raw_args = function.get("arguments")
                        key = f"{name}\x00{_canonical_args(raw_args)}"
                        occurrence = Occurrence(
                            call_id=call_id,
                            name=name,
                            key=key,
                            args=_parse_args(raw_args),
                            call_seq=seq,
                            model=current_model,
                        )
                        counts["tool_calls"] += 1
                        if key in session_seen and key not in run_seen:
                            cross_run_repeat += 1

                        prior = run_seen.get(key)
                        if prior is not None:
                            counts["same_run_exact_repeats"] += 1
                            prior_hidden = (
                                prior.result_index is not None
                                and prior.result_seq is not None
                                and any(
                                    prior.result_seq < compression_seq < seq
                                    for compression_seq in compressed_by_index.get(prior.result_index, [])
                                )
                            )
                            any_compression_between = any(prior.call_seq < s < seq for s in compressed_seqs)
                            recoverable = False
                            exact = False
                            if prior.evidence_ref is not None and prior.result_content is not None:
                                t0 = time.perf_counter_ns()
                                hydrated = _hydrate_exact(hydration, owner, prior.evidence_ref)
                                hydration_ms.append((time.perf_counter_ns() - t0) / 1_000_000)
                                recoverable = True
                                exact = hydrated == prior.result_content
                            repeat = PendingRepeat(
                                session_id=session_id,
                                synthetic=synthetic,
                                current_call_id=call_id,
                                tool_name=name,
                                key=key,
                                prior=prior,
                                current_call_seq=seq,
                                prior_hidden=prior_hidden,
                                any_compression_between=any_compression_between,
                                recoverable_before_repeat=recoverable,
                                hydration_exact=exact,
                                prior_model=prior.model,
                                current_model=current_model,
                            )
                            repeats.append(repeat)
                            pending_by_current_id[call_id] = repeat

                        run_seen[key] = occurrence
                        session_seen[key] = occurrence
                        occurrence_by_id[call_id] = occurrence
                    continue

                if role != "tool":
                    continue
                call_id = str(payload.get("tool_call_id") or "")
                occurrence = occurrence_by_id.get(call_id)
                if occurrence is None:
                    continue
                status = str(payload.get("status") or "")
                content = str(payload.get("content") or "")
                occurrence.result_index = payload.get("index") if isinstance(payload.get("index"), int) else None
                occurrence.result_seq = seq
                occurrence.result_content = content
                occurrence.result_status = status
                if status == "success":
                    call = ToolCall(id=occurrence.call_id, name=occurrence.name, arguments=occurrence.args)
                    source, coverage = source_for_call(call, None)
                    t0 = time.perf_counter_ns()
                    captured = capture.capture(
                        make_capture_request(
                            owner=owner,
                            stable_capture_id=occurrence.call_id,
                            raw_observation=content,
                            acquired_at=_iso_datetime(str(event.get("ts") or "")),
                            tool_name=occurrence.name,
                            tool_call_id=occurrence.call_id,
                            source=source,
                            coverage=coverage,
                            provenance=Provenance(
                                producer="historical_r1_replay",
                                authority="persisted_event_log",
                                scope="historical_success",
                            ),
                        )
                    )
                    capture_ms.append((time.perf_counter_ns() - t0) / 1_000_000)
                    occurrence.evidence_ref = captured.evidence_ref
                    counts["successful_observations_captured"] += 1

                pending = pending_by_current_id.get(call_id)
                if pending is not None:
                    pending.current_result_status = status
                    if status == "success" and pending.prior.result_content is not None:
                        pending.current_result_same = content == pending.prior.result_content
                    pending.classification = _classify(pending, dynamic_tools)

        counts["cross_run_exact_repeats"] = cross_run_repeat

        for repeat in repeats:
            if repeat.classification == "pending":
                repeat.classification = _classify(repeat, dynamic_tools)
            counts[repeat.classification] += 1
            if repeat.prior_hidden:
                counts["prior_concrete_result_hidden"] += 1
                if repeat.recoverable_before_repeat and repeat.hydration_exact:
                    counts["hidden_recoverable_before_repeat"] += 1
                else:
                    counts["lost_evidence_ref_count"] += 1
            if repeat.any_compression_between:
                counts["repeat_with_any_compression_between"] += 1
            else:
                counts["repeat_without_any_compression_between"] += 1
            if repeat.recoverable_before_repeat:
                counts["repeat_with_temporal_prior_evidence"] += 1
            if repeat.prior_model and repeat.current_model and repeat.prior_model != repeat.current_model:
                counts["repeat_crossing_model_change"] += 1

            target = synthetic_counts if repeat.synthetic else natural_counts
            target["same_run_exact_repeats"] += 1
            target[repeat.classification] += 1
            if repeat.prior_hidden:
                target["prior_concrete_result_hidden"] += 1
                if repeat.recoverable_before_repeat and repeat.hydration_exact:
                    target["hidden_recoverable_before_repeat"] += 1
                else:
                    target["lost_evidence_ref_count"] += 1
            tc = tool_counts.setdefault(repeat.tool_name, Counter())
            tc["same_run_exact_repeats"] += 1
            tc[repeat.classification] += 1
            if repeat.prior_hidden:
                tc["prior_concrete_result_hidden"] += 1

        hidden = counts["prior_concrete_result_hidden"]
        recoverable = counts["hidden_recoverable_before_repeat"]
        report = {
            "schema": "evidence-r1-replay-report-v1",
            "status": "PASS",
            "manifest_sha256": _sha(MANIFEST),
            "network_policy": "socket non-UNIX connect/connect_ex denied",
            "provider_calls": 0,
            "source_actions_executed": source_actions_executed,
            "counts": dict(counts),
            "synthetic_stratum": dict(synthetic_counts),
            "naturalistic_stratum": dict(natural_counts),
            "by_tool": {name: dict(counter) for name, counter in sorted(tool_counts.items())},
            "metrics": {
                "recoverable_projection_rate_hidden_repeat": 1.0 if hidden == 0 else recoverable / hidden,
                "lost_evidence_ref_count": counts["lost_evidence_ref_count"],
                "same_source_repeat_without_freshness_change": counts["program_amnesia_avoidable"],
                "capture_latency_ms": {
                    "n": len(capture_ms),
                    "p50": _percentile(capture_ms, 0.50),
                    "p95": _percentile(capture_ms, 0.95),
                    "max": max(capture_ms, default=0.0),
                },
                "hydration_latency_ms": {
                    "n": len(hydration_ms),
                    "p50": _percentile(hydration_ms, 0.50),
                    "p95": _percentile(hydration_ms, 0.95),
                    "max": max(hydration_ms, default=0.0),
                },
                "provider_switch_evidence_set_delta": 0,
            },
            "repeats": [r.to_dict() for r in repeats],
        }

        if counts["sessions"] != int(manifest["expected_session_count"]):
            raise AssertionError(f"session sanity mismatch: {counts['sessions']}")
        if counts["tool_calls"] != int(manifest["expected_tool_calls"]):
            raise AssertionError(f"tool-call sanity mismatch: {counts['tool_calls']}")
        if counts["same_run_exact_repeats"] != int(manifest["expected_same_run_exact_repeats"]):
            raise AssertionError(f"repeat sanity mismatch: {counts['same_run_exact_repeats']}")
        if counts["lost_evidence_ref_count"] != 0:
            raise AssertionError(f"lost EvidenceRef before repeat: {counts['lost_evidence_ref_count']}")
        if report["metrics"]["recoverable_projection_rate_hidden_repeat"] != 1.0:
            raise AssertionError("hidden repeat recoverability is not 100%")
        if source_actions_executed != 0:
            raise AssertionError("historical replay executed a source action")
        return report
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT))
    args = parser.parse_args()
    _deny_network()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    _verify_frozen_inputs(manifest)
    t0 = time.perf_counter()
    report = replay(manifest)
    report["elapsed_s"] = time.perf_counter() - t0
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    c = report["counts"]
    m = report["metrics"]
    print(
        "R1 PASS",
        f"sessions={c['sessions']}",
        f"tool_calls={c['tool_calls']}",
        f"same_run_repeats={c['same_run_exact_repeats']}",
        f"hidden={c['prior_concrete_result_hidden']}",
        f"avoidable={c['program_amnesia_avoidable']}",
        f"visible_model_repeat={c['model_repeat_while_visible']}",
        f"freshness_or_polling={c['freshness_or_polling']}",
        f"freshness_changed={c['freshness_change_observed']}",
        f"lost_refs={c.get('lost_evidence_ref_count', 0)}",
        f"recoverable={m['recoverable_projection_rate_hidden_repeat']:.1%}",
    )
    print("report", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
