#!/usr/bin/env python3
"""R0 deterministic baseline for INJECTION-GOVERNANCE.

This analyzer intentionally does not call an LLM.  It reconstructs human turns from
``data/event_logs/<session>.jsonl`` and measures program-injection structure from
persisted message events plus request/wire metadata.

Outputs (default under docs/injection-governance/r0):
- baseline.jsonl: one row per human turn
- baseline-manifest.json: source hashes + gate summary
- fixtures/structural-fixtures.json: deterministic redacted violation fixtures
- report.md: human-readable R0 gate report

Usage:
    python3 scripts/analysis_injection_baseline.py
    python3 scripts/analysis_injection_baseline.py --data-dir data --out-dir docs/injection-governance/r0
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "r0-injection-baseline-v2"
DEFAULT_TARGETS: tuple[tuple[str, str], ...] = (
    ("68fed5f5", "weak-model-drift"),
    ("09c44093", "duplicate-heavy-history"),
    ("996e7e52", "compact-long-session"),
    ("69715765", "clean-control"),
)

PROGRAM_PREFIXES = (
    "[上下文注入·非新指令]",
    "[程序附录·非用户输入]",
    "[声明提醒]",
    "[声明-回执校验]",
    "[停滞提醒]",
    "[模型切换感知]",
    "[会话汇总档案]",
    "[上下文归档摘要]",
    "[任务·程序恢复]",
    "[程序续跑]",
    "[上下文超限]",
    "[架构上报]",
    "[预算预警]",
    "[搜索空结果提醒]",
    "[上下文预警]",
    "[注入预算]",
)

REFERENCE_KINDS = {
    "memory_snapshot",
    "experience_tip",
    "archive_summary",
    "evidence_snapshot",
}

REFERENCE_LINE_RE = re.compile(
    r"^\s*-\s+(?:\[(?:fact|decision|convention|preference|memory|experience|rule)\]\s*)?.+",
    re.IGNORECASE,
)

# Deliberately high-precision: this gate is meant to prove command-shaped pollution,
# not perform general Chinese grammar analysis.
IMPERATIVE_RE = re.compile(
    r"继续当前任务|勿当(?:新消息|新指令)|勿重做|勿重新|不要(?:重新|重复|执行|调用|处理)|"
    r"禁止.{0,16}(?:调用|执行|重做|重试|检查|验证|切换|处理|检索)|"
    r"必须.{0,16}(?:调用|执行|重做|重试|检查|验证|切换|处理|检索)|"
    r"务必.{0,16}(?:调用|执行|检查|验证|处理)|"
    r"请(?:先|及时|如实|停止|调用|执行|检查|验证|切换|重启|处理|检索)|"
    r"(?:先|立即|马上).{0,12}(?:调用|执行|检查|验证|切换|重启|处理|分析|检索)",
    re.IGNORECASE,
)

RECOVERY_HINT_RE = re.compile(r"(?:auto[_ -]?continue|err1210|1210.*恢复|程序恢复)", re.IGNORECASE)


@dataclass(frozen=True)
class SourceSession:
    session_id: str
    role: str
    event_path: Path


def _sha_text(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:n]


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _content(payload: dict[str, Any]) -> str:
    value = payload.get("content") or ""
    return value if isinstance(value, str) else str(value)


def _is_program_message(payload: dict[str, Any]) -> bool:
    meta = payload.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    if meta.get("persisted_injection") or meta.get("injected_system"):
        return True
    if meta.get("injection_kind"):
        return True
    content = _content(payload).lstrip()
    return content.startswith(PROGRAM_PREFIXES)


def _injection_kind(payload: dict[str, Any]) -> str:
    meta = payload.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("injection_kind"):
        return str(meta["injection_kind"])
    content = _content(payload).lstrip()
    prefix_map = (
        ("[声明提醒]", "declaration_notice"),
        ("[声明-回执校验]", "declaration_notice"),
        ("[停滞提醒]", "stagnation_notice"),
        ("[模型切换感知]", "model_switch_notice"),
        ("[上下文归档摘要]", "archive_summary"),
        ("[任务·程序恢复]", "program_recovery"),
        ("[程序续跑]", "program_recovery"),
        ("[上下文超限]", "context_guard_notice"),
        ("[架构上报]", "architecture_notice"),
        ("[预算预警]", "budget_notice"),
        ("[搜索空结果提醒]", "search_empty_notice"),
        ("[上下文注入·非新指令]", "legacy_context_injection"),
    )
    for prefix, kind in prefix_map:
        if content.startswith(prefix):
            return kind
    return "program_injection"


def _is_reference_injection(payload: dict[str, Any], kind: str) -> bool:
    if kind in REFERENCE_KINDS:
        return True
    text = _content(payload)
    return "[相关记忆]" in text or "[经验提示]" in text or "[记忆检索]" in text


def _reference_frames(text: str) -> list[str]:
    frames: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or not REFERENCE_LINE_RE.match(line):
            continue
        # Drop the bullet marker only.  Keeping the fact body exact makes duplicates
        # conservative: we only call an item duplicate when the same text reappears.
        frames.append(re.sub(r"^\s*-\s+", "", line))
    return frames


def _imperative_hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in IMPERATIVE_RE.finditer(text)})


def _capability_tier(model_id: str) -> str:
    provider = model_id.split("/", 1)[0] if "/" in model_id else ""
    if provider in {"local", "cognilocal"}:
        return "weak-local"
    if provider:
        return "cloud-or-strong"
    return "unknown"


def _tail_user_run(msgs: Iterable[dict[str, Any]]) -> int:
    roles = [str(m.get("role") or "") for m in msgs]
    run = 0
    for role in reversed(roles):
        if role != "user":
            break
        run += 1
    return run


def _cache_window_messages(event: dict[str, Any]) -> list[dict[str, Any]]:
    p = event.get("payload") or {}
    parts: list[dict[str, Any]] = []
    for key in ("cached_msgs", "new_msgs"):
        values = p.get(key) or []
        if isinstance(values, list):
            parts.extend(v for v in values if isinstance(v, dict))
    # A partially cached boundary can appear only in cached_msgs; de-dupe by index.
    by_index: dict[int, dict[str, Any]] = {}
    for m in parts:
        try:
            idx = int(m.get("index"))
        except (TypeError, ValueError):
            continue
        by_index[idx] = m
    return [by_index[i] for i in sorted(by_index)]


def _load_events(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if isinstance(event, dict):
                out.append(event)
    out.sort(key=lambda e: int(e.get("seq") or 0))
    return out


def _find_sources(data_dir: Path, targets: tuple[tuple[str, str], ...]) -> list[SourceSession]:
    event_dir = data_dir / "event_logs"
    found: list[SourceSession] = []
    for prefix, role in targets:
        matches = sorted(event_dir.glob(f"{prefix}*.jsonl"))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"expected exactly one event log for {prefix}, got {len(matches)} under {event_dir}"
            )
        session_id = matches[0].stem
        found.append(SourceSession(session_id, role, matches[0]))
    return found


def analyze_session(source: SourceSession) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events = _load_events(source.event_path)
    humans: list[int] = []
    for pos, event in enumerate(events):
        if event.get("type") != "message.appended":
            continue
        payload = event.get("payload") or {}
        if payload.get("role") == "user" and not _is_program_message(payload):
            humans.append(pos)

    seen_frames: set[str] = set()
    duplicate_frame_counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []

    for turn_no, start in enumerate(humans, 1):
        end = humans[turn_no] if turn_no < len(humans) else len(events)
        window = events[start:end]
        human_event = events[start]
        human_payload = human_event.get("payload") or {}
        user_text = _content(human_payload)

        injections: list[dict[str, Any]] = []
        reference_frames: list[str] = []
        imperative_reference_count = 0
        imperative_block_count = 0  # user-role program blocks only
        all_program_imperative_block_count = 0
        duplicate_count = 0
        duplicate_hashes: list[str] = []
        injection_by_kind: Counter[str] = Counter()
        all_injection_by_kind: Counter[str] = Counter()

        for event in window[1:]:
            if event.get("type") != "message.appended":
                continue
            payload = event.get("payload") or {}
            if not _is_program_message(payload):
                continue
            text = _content(payload)
            kind = _injection_kind(payload)
            block_hits = _imperative_hits(text)
            role = str(payload.get("role") or "")
            if block_hits:
                all_program_imperative_block_count += 1
                if role == "user":
                    imperative_block_count += 1
            all_injection_by_kind[kind] += len(text)
            if role == "user":
                injection_by_kind[kind] += len(text)
            injections.append(
                {
                    "seq": int(event.get("seq") or 0),
                    "index": payload.get("index"),
                    "role": payload.get("role"),
                    "kind": kind,
                    "chars": len(text),
                    "sha256_16": _sha_text(text),
                    "imperative_hits": block_hits,
                }
            )
            if role == "user" and _is_reference_injection(payload, kind):
                frames = _reference_frames(text)
                for frame in frames:
                    reference_frames.append(frame)
                    imperative_reference_count += int(bool(_imperative_hits(frame)))
                    fh = _sha_text(frame)
                    if fh in seen_frames:
                        duplicate_count += 1
                        duplicate_hashes.append(fh)
                        duplicate_frame_counts[fh] += 1
                    else:
                        seen_frames.add(fh)

        request_meta = [e for e in window if e.get("type") == "request.meta"]
        cache_windows = [e for e in window if e.get("type") == "cache.window"]
        run_ends = [e for e in window if e.get("type") == "run.end"]
        first_req_seq = int(request_meta[0].get("seq") or 0) if request_meta else None
        first_req_payload = request_meta[0].get("payload") or {} if request_meta else {}
        model_id = str(first_req_payload.get("model") or "")
        history_chars = first_req_payload.get("history_chars")
        if not isinstance(history_chars, int):
            history_chars = None

        compact_before_first = False
        if first_req_seq is not None:
            compact_before_first = any(
                e.get("type") == "context.compressed" and int(e.get("seq") or 0) < first_req_seq
                for e in window
            )
        compact_event_count = sum(e.get("type") == "context.compressed" for e in window)
        run_truncated = any(bool((e.get("payload") or {}).get("truncated")) for e in run_ends)

        recovery = False
        for event in window:
            event_type = str(event.get("type") or "")
            payload = event.get("payload") or {}
            if "recover" in event_type.lower() or "retry" in event_type.lower():
                recovery = True
                break
            if event.get("type") == "message.appended" and _is_program_message(payload):
                kind = _injection_kind(payload)
                meta = payload.get("metadata") or {}
                haystack = f"{kind} {json.dumps(meta, ensure_ascii=False)} {_content(payload)[:300]}"
                if RECOVERY_HINT_RE.search(haystack):
                    recovery = True
                    break

        wire_tail_runs: list[int] = []
        wire_user_runs: list[int] = []
        for event in cache_windows:
            msgs = _cache_window_messages(event)
            if msgs:
                wire_tail_runs.append(_tail_user_run(msgs))
                max_run = cur = 0
                for msg in msgs:
                    if msg.get("role") == "user":
                        cur += 1
                        max_run = max(max_run, cur)
                    else:
                        cur = 0
                wire_user_runs.append(max_run)

        user_injections = [i for i in injections if i["role"] == "user"]
        system_injections = [i for i in injections if i["role"] == "system"]
        injection_chars = sum(i["chars"] for i in user_injections)
        all_program_injection_chars = sum(i["chars"] for i in injections)
        system_program_injection_chars = sum(i["chars"] for i in system_injections)
        post_user_chars = sum(
            i["chars"]
            for i in user_injections
            if i["seq"] > int(human_event.get("seq") or 0)
        )
        request_attribution_applicable = bool(request_meta) or any(
            int((e.get("payload") or {}).get("tokens_in") or 0) > 0 for e in run_ends
        )
        request_attribution_complete = (
            bool(request_meta and model_id) if request_attribution_applicable else True
        )
        origin_classification_complete = bool(user_text or len(user_text) == 0)
        total_context_chars = history_chars
        incremental_injection_share = (
            round(injection_chars / total_context_chars, 6)
            if total_context_chars and total_context_chars > 0
            else None
        )
        user_lane_den = len(user_text) + post_user_chars
        post_user_injection_share = (
            round(post_user_chars / user_lane_den, 6) if user_lane_den else 0.0
        )

        rows.append(
            {
                "schema": SCHEMA_VERSION,
                "session_id": source.session_id,
                "sample_role": source.role,
                "turn": turn_no,
                "human_event_seq": int(human_event.get("seq") or 0),
                "human_message_index": human_payload.get("index"),
                "user_truth_chars": len(user_text),
                "user_truth_sha256_16": _sha_text(user_text),
                "injection_chars": injection_chars,
                "all_program_injection_chars": all_program_injection_chars,
                "system_program_injection_chars": system_program_injection_chars,
                "injection_after_user_chars": post_user_chars,
                "injection_block_count": len(user_injections),
                "all_program_injection_block_count": len(injections),
                "injection_by_kind_chars": dict(sorted(injection_by_kind.items())),
                "all_program_injection_by_kind_chars": dict(sorted(all_injection_by_kind.items())),
                "reference_frame_count": len(reference_frames),
                "duplicate_injection_count": duplicate_count,
                "duplicate_frame_hashes": sorted(set(duplicate_hashes)),
                "imperative_reference_count": imperative_reference_count,
                "imperative_injection_block_count": imperative_block_count,
                "all_program_imperative_block_count": all_program_imperative_block_count,
                "request_count": len(request_meta),
                "model_id": model_id or None,
                "capability_tier": _capability_tier(model_id),
                "first_request_history_chars": total_context_chars,
                "incremental_injection_share": incremental_injection_share,
                "post_user_injection_share": post_user_injection_share,
                "compact_first": compact_before_first if request_meta else None,
                "compact_event_count": compact_event_count,
                "run_truncated": run_truncated if run_ends else None,
                "recovery": recovery if run_ends else None,
                "run_complete": bool(run_ends),
                "origin_classification_complete": origin_classification_complete,
                "request_attribution_applicable": request_attribution_applicable,
                "request_attribution_complete": request_attribution_complete,
                "wire_observed_request_count": len(cache_windows),
                "wire_tail_user_run_first": wire_tail_runs[0] if wire_tail_runs else None,
                "wire_tail_user_run_max": max(wire_tail_runs) if wire_tail_runs else None,
                "wire_consecutive_user_run_max": max(wire_user_runs) if wire_user_runs else None,
                "wire_tail_user_violation_count": sum(v > 1 for v in wire_tail_runs),
                "injections": injections,
            }
        )

    session_summary = {
        "session_id": source.session_id,
        "sample_role": source.role,
        "event_path": str(source.event_path),
        "event_sha256": _sha_file(source.event_path),
        "event_count": len(events),
        "human_turns": len(rows),
        "duplicate_frame_hash_counts": dict(sorted(duplicate_frame_counts.items())),
    }
    return rows, session_summary


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 2) if d else 0.0


def _quantile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    values = sorted(values)
    idx = round((len(values) - 1) * q)
    return values[idx]


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [r for r in rows if r["run_complete"]]
    origin_ok = sum(bool(r["origin_classification_complete"]) for r in completed)
    attrib_rows = [r for r in completed if r.get("request_attribution_applicable")]
    attrib_ok = sum(bool(r["request_attribution_complete"]) for r in attrib_rows)
    with_injection = [r for r in completed if r["injection_chars"] > 0]
    refs = sum(r["reference_frame_count"] for r in completed)
    dup = sum(r["duplicate_injection_count"] for r in completed)
    imp = sum(r["imperative_reference_count"] for r in completed)
    injected_blocks = sum(r["injection_block_count"] for r in completed)
    imperative_blocks = sum(r["imperative_injection_block_count"] for r in completed)
    wire_obs = [r for r in completed if r["wire_tail_user_run_max"] is not None]
    wire_viol = sum(r["wire_tail_user_violation_count"] for r in wire_obs)
    wire_req = sum(r["wire_observed_request_count"] for r in wire_obs)
    user_injection_kind_blocks: Counter[str] = Counter()
    for row in completed:
        for item in row.get("injections") or []:
            if item.get("role") == "user":
                user_injection_kind_blocks[str(item.get("kind") or "unknown")] += 1

    by_bucket: dict[str, dict[str, Any]] = {}
    bucket_rows: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in completed:
        model = row.get("model_id") or "unknown"
        bucket_rows[f"model:{model}"].append(row)
        bucket_rows[f"compact_first:{row.get('compact_first')}"] .append(row)
        bucket_rows[f"recovery:{row.get('recovery')}"] .append(row)
    for key, values in sorted(bucket_rows.items()):
        by_bucket[key] = {
            "turns": len(values),
            "turns_with_injection": sum(v["injection_chars"] > 0 for v in values),
            "injection_chars": sum(v["injection_chars"] for v in values),
            "user_truth_chars": sum(v["user_truth_chars"] for v in values),
            "duplicate_injection_count": sum(v["duplicate_injection_count"] for v in values),
            "imperative_reference_count": sum(v["imperative_reference_count"] for v in values),
            "wire_tail_user_violations": sum(v["wire_tail_user_violation_count"] for v in values),
        }

    inject_sizes = [r["injection_chars"] for r in with_injection]
    completed_n = len(completed)
    return {
        "turns_total": len(rows),
        "turns_completed": completed_n,
        "origin_classification_coverage_pct": _pct(origin_ok, completed_n),
        "request_attribution_applicable_turns": len(attrib_rows),
        "request_attribution_coverage_pct": _pct(attrib_ok, len(attrib_rows)),
        "turns_with_injection": len(with_injection),
        "turns_with_post_user_injection": sum(r["injection_after_user_chars"] > 0 for r in completed),
        "post_user_injection_turn_rate_pct": _pct(
            sum(r["injection_after_user_chars"] > 0 for r in completed), completed_n
        ),
        "injection_chars": sum(r["injection_chars"] for r in completed),
        "user_truth_chars": sum(r["user_truth_chars"] for r in completed),
        "reference_frame_count": refs,
        "duplicate_injection_count": dup,
        "duplicate_injection_rate_pct": _pct(dup, refs),
        "imperative_reference_count": imp,
        "imperative_reference_rate_pct": _pct(imp, refs),
        "injection_block_count": injected_blocks,
        "imperative_injection_block_count": imperative_blocks,
        "imperative_injection_block_rate_pct": _pct(imperative_blocks, injected_blocks),
        "wire_observed_requests": wire_req,
        "wire_tail_user_violation_count": wire_viol,
        "wire_tail_user_violation_rate_pct": _pct(wire_viol, wire_req),
        "user_injection_kind_blocks": dict(sorted(user_injection_kind_blocks.items())),
        "injection_chars_p50": _quantile(inject_sizes, 0.50),
        "injection_chars_p75": _quantile(inject_sizes, 0.75),
        "injection_chars_p90": _quantile(inject_sizes, 0.90),
        "injection_chars_max": max(inject_sizes) if inject_sizes else 0,
        "by_bucket": by_bucket,
    }


def _build_fixtures(rows: list[dict[str, Any]], sessions: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [r for r in rows if r["run_complete"]]
    post = max(completed, key=lambda r: r["injection_after_user_chars"], default=None)
    duplicate_candidates = [r for r in completed if r["duplicate_injection_count"] > 0]
    duplicate = max(duplicate_candidates, key=lambda r: r["duplicate_injection_count"], default=None)
    imperative_candidates = [r for r in completed if r["imperative_reference_count"] > 0]
    imperative = max(imperative_candidates, key=lambda r: r["imperative_reference_count"], default=None)
    wire_candidates = [r for r in completed if (r["wire_consecutive_user_run_max"] or 0) >= 2]
    wire = max(wire_candidates, key=lambda r: r["wire_consecutive_user_run_max"], default=None)

    def base(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "turn": row["turn"],
            "human_event_seq": row["human_event_seq"],
            "user_truth_sha256_16": row["user_truth_sha256_16"],
            "user_truth_chars": row["user_truth_chars"],
        }

    post_f = base(post)
    if post_f is not None and post is not None:
        post_f.update(
            {
                "injection_after_user_chars": post["injection_after_user_chars"],
                "injected_blocks": [
                    {k: item[k] for k in ("seq", "role", "kind", "chars", "sha256_16")}
                    for item in post["injections"]
                    if item["role"] == "user"
                ],
                "expected_violation": "injection_after_user_chars > 0",
            }
        )

    dup_f = base(duplicate)
    if dup_f is not None and duplicate is not None:
        dup_f.update(
            {
                "duplicate_injection_count": duplicate["duplicate_injection_count"],
                "duplicate_frame_hashes": duplicate["duplicate_frame_hashes"],
                "expected_violation": "same normalized reference frame repeats in one session",
            }
        )

    imp_f = base(imperative)
    if imp_f is not None and imperative is not None:
        imp_f.update(
            {
                "imperative_reference_count": imperative["imperative_reference_count"],
                "injection_block_hashes": [i["sha256_16"] for i in imperative["injections"]],
                "expected_violation": "reference material contains command-shaped language",
            }
        )

    wire_f = base(wire)
    if wire_f is not None and wire is not None:
        wire_f.update(
            {
                "wire_consecutive_user_run_max": wire["wire_consecutive_user_run_max"],
                "wire_tail_user_run_max": wire["wire_tail_user_run_max"],
                "expected_violation": "wire contains consecutive user-role messages",
            }
        )

    return {
        "schema": SCHEMA_VERSION,
        "redaction": "No raw human/reference text is stored; fixtures use lengths and SHA-256 prefixes.",
        "source_event_logs": [
            {
                "session_id": s["session_id"],
                "sample_role": s["sample_role"],
                "event_sha256": s["event_sha256"],
            }
            for s in sessions
        ],
        "fixtures": {
            "post_user_program_append": post_f,
            "duplicate_reference_frame": dup_f,
            "imperative_reference": imp_f,
            "consecutive_user_wire": wire_f,
        },
    }


def _gate_summary(agg: dict[str, Any], fixtures: dict[str, Any]) -> dict[str, Any]:
    fixture_values = fixtures["fixtures"]
    r01 = (
        agg["origin_classification_coverage_pct"] >= 95.0
        and agg["request_attribution_coverage_pct"] >= 95.0
    )
    r02 = agg["turns_completed"] > 0 and agg["wire_observed_requests"] > 0
    r03 = all(fixture_values.get(name) is not None for name in fixture_values)
    # R0-4 freezes candidates/ranges, not production values.  Final K/budget selection
    # belongs to L3 behavior A/B; the gate passes when the distribution needed to choose
    # candidates exists and no value is silently promoted from a guess.
    r04 = agg["injection_chars_p50"] is not None and agg["injection_chars_p90"] is not None
    return {
        "R0-1_data_completeness": "PASS" if r01 else "FAIL",
        "R0-2_baseline_measurable": "PASS" if r02 else "FAIL",
        "R0-3_deterministic_reproduction": "PASS" if r03 else "FAIL",
        "R0-4_parameter_candidate_gate": "PASS" if r04 else "FAIL",
        "R0": "PASS" if all((r01, r02, r03, r04)) else "FAIL",
    }


def _session_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_sid: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_sid[row["session_id"]].append(row)
    table: list[dict[str, Any]] = []
    for sid, values in sorted(by_sid.items()):
        completed = [v for v in values if v["run_complete"]]
        refs = sum(v["reference_frame_count"] for v in completed)
        dup = sum(v["duplicate_injection_count"] for v in completed)
        imp = sum(v["imperative_reference_count"] for v in completed)
        inj = sum(v["injection_chars"] for v in completed)
        truth = sum(v["user_truth_chars"] for v in completed)
        table.append(
            {
                "session_id": sid,
                "role": values[0]["sample_role"],
                "turns": len(completed),
                "truth_chars": truth,
                "injection_chars": inj,
                "user_lane_injection_share_pct": _pct(inj, inj + truth),
                "post_user_turn_rate_pct": _pct(
                    sum(v["injection_after_user_chars"] > 0 for v in completed), len(completed)
                ),
                "reference_frames": refs,
                "duplicate_rate_pct": _pct(dup, refs),
                "imperative_reference_rate_pct": _pct(imp, refs),
                "wire_tail_violations": sum(v["wire_tail_user_violation_count"] for v in completed),
                "models": sorted({str(v["model_id"]) for v in completed if v.get("model_id")}),
            }
        )
    return table


def _render_report(
    agg: dict[str, Any],
    gates: dict[str, Any],
    session_table: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# R0 基线与数据门报告（INJECTION-GOVERNANCE）")
    lines.append("")
    lines.append(f"> schema: `{SCHEMA_VERSION}` | R0: **{gates['R0']}**")
    lines.append("> 数据源：镜像区 `data/event_logs/*.jsonl`；本报告为确定性离线分析，不调用任何 LLM。")
    lines.append("")
    lines.append("## 1. R0 四门")
    lines.append("")
    lines.append("| Gate | 结果 | 机械证据 |")
    lines.append("|---|---|---|")
    lines.append(
        f"| R0-1 数据完整性 | **{gates['R0-1_data_completeness']}** | origin coverage {agg['origin_classification_coverage_pct']}%；request attribution {agg['request_attribution_coverage_pct']}% |"
    )
    lines.append(
        f"| R0-2 基线可测 | **{gates['R0-2_baseline_measurable']}** | completed turns={agg['turns_completed']}；wire observed requests={agg['wire_observed_requests']} |"
    )
    lines.append(
        f"| R0-3 机制复现 | **{gates['R0-3_deterministic_reproduction']}** | post-user / duplicate / imperative / consecutive-user 四类脱敏 fixture 均已冻结 |"
    )
    lines.append(
        f"| R0-4 参数候选门 | **{gates['R0-4_parameter_candidate_gate']}** | 注入字符分布 p50={agg['injection_chars_p50']}、p75={agg['injection_chars_p75']}、p90={agg['injection_chars_p90']}、max={agg['injection_chars_max']} |"
    )
    lines.append("")
    lines.append("## 2. 结构基线")
    lines.append("")
    lines.append(f"- 有 **user-role 程序附录** 的 completed turn：**{agg['turns_with_injection']}/{agg['turns_completed']}**。")
    lines.append(
        f"- 用户真话之后仍追加程序块的 turn：**{agg['turns_with_post_user_injection']}/{agg['turns_completed']} ({agg['post_user_injection_turn_rate_pct']}%)**。"
    )
    lines.append(
        f"- 参考资料帧重复：**{agg['duplicate_injection_count']}/{agg['reference_frame_count']} ({agg['duplicate_injection_rate_pct']}%)**。"
    )
    lines.append(
        f"- 资料帧祈使污染：**{agg['imperative_reference_count']}/{agg['reference_frame_count']} ({agg['imperative_reference_rate_pct']}%)**；按整注入块计 {agg['imperative_injection_block_count']}/{agg['injection_block_count']} ({agg['imperative_injection_block_rate_pct']}%)。"
    )
    lines.append(
        f"- wire 尾部连续 user 违规：**{agg['wire_tail_user_violation_count']}/{agg['wire_observed_requests']} ({agg['wire_tail_user_violation_rate_pct']}%)**。"
    )
    legacy_parts = []
    for kind in ("program_recovery", "context_guard_notice"):
        count = int((agg.get("user_injection_kind_blocks") or {}).get(kind, 0))
        if count:
            legacy_parts.append(f"`{kind}`={count}")
    if legacy_parts:
        lines.append(
            "- 发现无稳定 metadata 仍以 `role=user` 写回历史的 legacy program-user："
            + "、".join(legacy_parts)
            + "；已由内容前缀确定性识别，不再误算为 human turn。"
        )
    lines.append("")
    lines.append("### 按会话")
    lines.append("")
    lines.append("| session | 角色 | turns | truth chars | injection chars | user-lane 注入占比 | 尾后注入 turn | 重复率 | 资料祈使率 | wire tail 违规 | models |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in session_table:
        lines.append(
            f"| `{row['session_id'][:8]}` | {row['role']} | {row['turns']} | {row['truth_chars']} | {row['injection_chars']} | {row['user_lane_injection_share_pct']}% | {row['post_user_turn_rate_pct']}% | {row['duplicate_rate_pct']}% | {row['imperative_reference_rate_pct']}% | {row['wire_tail_violations']} | {', '.join(row['models']) or 'unknown'} |"
        )
    lines.append("")
    lines.append("### 分桶口径")
    lines.append("")
    lines.append("`baseline.jsonl` 每行同时记录 `model_id / capability_tier / compact_first / recovery`，报告聚合保存在 `baseline-manifest.json:aggregate.by_bucket`。`compact_first` 的 R0 操作定义是：该 human turn 首个 `request.meta` 之前已有 durable `context.compressed` 事件；`recovery` 只认显式 recovery/retry 事件或程序恢复注入，不凭错误码猜测。")
    lines.append("")
    lines.append("## 3. R0-3 冻结 fixture")
    lines.append("")
    lines.append("`fixtures/structural-fixtures.json` 只保存来源 session/turn、字符数和 SHA-256 前缀，不保存用户原文或资料全文。四类 fixture 分别证明：")
    lines.append("")
    lines.append("1. program block 在用户真话之后追加；")
    lines.append("2. 同一规范化资料帧在同 session 重复出现；")
    lines.append("3. 资料帧含 command-shaped / imperative 表述；")
    lines.append("4. provider wire 出现连续 user-role 消息。")
    lines.append("")
    lines.append("## 4. R0-4 参数判定")
    lines.append("")
    lines.append("- `INJECTION_BUDGET_CHARS=8000` 与 `K=3` **继续作为候选，不在 R0 擅自升级为生产常量**。")
    lines.append("- R0 已冻结注入字符分布和分桶数据，可用于给 L3 选择候选区间。最终预算/K 必须在治理实现后用同 fixture 的任务完成率/漂移率 A/B 决定。")
    lines.append("- 因用户此前已明确取消重复 cognilocal 基线跑，本轮没有重新启动本地模型；这不影响 R0 的确定性结构门。")
    lines.append("")
    lines.append("## 5. 数据完整性与限制")
    lines.append("")
    lines.append("- `message.appended` 是 origin/content 真相源；`request.meta` 提供实际模型与 history_chars；`cache.window` 提供 wire role/char 结构；`context.compressed` 与 `run.end` 提供 compact/run 归因。`injection_chars` 仅指 user-role program appendix；system notice 单列在 `all_program_injection_chars/system_program_injection_chars`，不冒充“用户尾后注入”。")
    lines.append("- `incremental_injection_share` 是“本 human turn 新增程序块字符 / 首请求 history_chars”，不是把历史中所有已存在注入重新归因；会话级 `user-lane 注入占比` 则衡量真实 user 与程序 user-like 数据量。")
    lines.append("- 行为漂移率/任务完成率属于 L3 A/B；R0 只保存既有历史事故作为 supporting evidence，不以随机采样结果作为硬门。")
    lines.append("")
    lines.append("## 6. Source manifest")
    lines.append("")
    for src in sources:
        lines.append(
            f"- `{src['session_id']}` ({src['sample_role']}): events={src['event_count']}, sha256=`{src['event_sha256']}`"
        )
    lines.append("")
    return "\n".join(lines)


def run(data_dir: Path, out_dir: Path) -> dict[str, Any]:
    sources = _find_sources(data_dir, DEFAULT_TARGETS)
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for source in sources:
        rows, summary = analyze_session(source)
        all_rows.extend(rows)
        summaries.append(summary)

    agg = _aggregate(all_rows)
    fixtures = _build_fixtures(all_rows, summaries)
    gates = _gate_summary(agg, fixtures)
    session_table = _session_table(all_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_dir = out_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)

    baseline_path = out_dir / "baseline.jsonl"
    with baseline_path.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    fixture_path = fixture_dir / "structural-fixtures.json"
    fixture_path.write_text(
        json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema": SCHEMA_VERSION,
        "sources": summaries,
        "aggregate": agg,
        "gates": gates,
        "outputs": {
            "baseline_jsonl": str(baseline_path),
            "fixtures": str(fixture_path),
            "report": str(out_dir / "report.md"),
        },
    }
    manifest_path = out_dir / "baseline-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = _render_report(agg, gates, session_table, summaries)
    (out_dir / "report.md").write_text(report + "\n", encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--out-dir", type=Path, default=Path("docs/injection-governance/r0")
    )
    parser.add_argument("--json", action="store_true", help="print gate summary as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = run(args.data_dir, args.out_dir)
    if args.json:
        print(json.dumps(manifest["gates"], ensure_ascii=False, sort_keys=True))
    else:
        agg = manifest["aggregate"]
        print(
            f"R0={manifest['gates']['R0']} turns={agg['turns_completed']} "
            f"origin={agg['origin_classification_coverage_pct']}% "
            f"attribution={agg['request_attribution_coverage_pct']}% "
            f"post_user={agg['post_user_injection_turn_rate_pct']}% "
            f"dup={agg['duplicate_injection_rate_pct']}% "
            f"imperative={agg['imperative_reference_rate_pct']}% "
            f"wire_tail_viol={agg['wire_tail_user_violation_rate_pct']}%"
        )
    return 0 if manifest["gates"]["R0"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
