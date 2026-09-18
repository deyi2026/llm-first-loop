#!/usr/bin/env python3
"""One-shot Method-sampling measurement over the LFL EventStore (read-only).

Slices data/event_logs (flat `<sid>.jsonl` and sharded `<sid>/<n>.jsonl`) from
a deployment-generation activation anchor
(earliest *succeeded* service-control restart carrying that
deployment_generation) and reports for the window:

  * runs (run.end) with model / reason breakdown
  * tool calls by name (tool.execution.declared; authoritative execution count)
  * search_records calls + kind breakdown, parsed from raw arguments in
    assistant message.appended tool_calls (the only place raw args persist;
    tool.execution.* events carry only args_sha256)
  * method-facing counters: kind=method searches, method_manage calls
  * data/methods/usage.jsonl growth + decision distribution (if present)

Usage:
  python3 tools/measure_method_sampling.py --from-gen 37
  python3 tools/measure_method_sampling.py --from-gen 33 --until 2026-09-18T15:39:53+00:00
  python3 tools/measure_method_sampling.py --since 2026-09-18T15:39:53+00:00 [--out report.json]

stdout is a pretty JSON summary; --out additionally writes the same JSON.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVENT_DIR = os.path.join(ROOT, "data", "event_logs")
ACTIONS_DIR = os.path.join(ROOT, "data", "runtime", "service-control-actions")
USAGE_PATH = os.path.join(ROOT, "data", "methods", "usage.jsonl")

PRE_FILTERS = ('"type": "run.end"', '"type": "tool.execution.declared"', '"tool_calls": [')


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def gen_anchors() -> dict[int, datetime]:
    anchors: dict[int, datetime] = {}
    for path in glob.glob(os.path.join(ACTIONS_DIR, "svc-*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                action = json.load(fh)
        except (OSError, ValueError):
            continue
        if action.get("status") != "succeeded":
            continue
        gen = action.get("deployment_generation")
        updated = action.get("updated_at")
        if gen is None or not updated:
            continue
        try:
            ts = parse_ts(updated)
        except ValueError:
            continue
        if gen not in anchors or ts < anchors[gen]:
            anchors[int(gen)] = ts
    return anchors


def scan_window(since: datetime, until: datetime) -> dict:
    stats = {
        "files_scanned": 0,
        "unreadable_files": 0,
        "malformed_lines": 0,
        "args_parse_fail": 0,
        "run_end_total": 0,
        "run_end_by_model": Counter(),
        "run_end_by_reason": Counter(),
        "declared_total": 0,
        "declared_by_name": Counter(),
        "sr_total": 0,
        "sr_kind_breakdown": Counter(),
        "method_search_total": 0,
        "sessions_run_end": set(),
        "sessions_any_event": set(),
        "sessions_search_records": set(),
        "sessions_method_search": set(),
        "per_session": {},
    }
    def session_stat(sid: str) -> dict:
        return stats["per_session"].setdefault(
            sid, {"declared": 0, "search_records": 0, "method_search": 0,
                  "run_end": 0, "models": set(), "first_ts": None, "last_ts": None})
    # Sessions appear in two shapes: flat `<sid>.jsonl` and sharded `<sid>/<n>.jsonl`.
    paths = sorted(glob.glob(os.path.join(EVENT_DIR, "*.jsonl")))
    paths += sorted(glob.glob(os.path.join(EVENT_DIR, "*", "*.jsonl")))
    for path in paths:
        stats["files_scanned"] += 1
        parent = os.path.dirname(path)
        session_id = (os.path.basename(parent) if parent != EVENT_DIR
                      else os.path.basename(path)[: -len(".jsonl")])
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            stats["unreadable_files"] += 1
            continue
        with fh:
            for raw in fh:
                if not any(marker in raw for marker in PRE_FILTERS):
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    stats["malformed_lines"] += 1
                    continue
                ts_raw = event.get("ts")
                if not ts_raw:
                    continue
                try:
                    ts = parse_ts(ts_raw)
                except ValueError:
                    continue
                if ts < since or ts > until:
                    continue
                etype = event.get("type")
                payload = event.get("payload") or {}
                stats["sessions_any_event"].add(session_id)
                sstat = session_stat(session_id)
                ts_iso = ts.isoformat()
                if sstat["first_ts"] is None or ts_iso < sstat["first_ts"]:
                    sstat["first_ts"] = ts_iso
                if sstat["last_ts"] is None or ts_iso > sstat["last_ts"]:
                    sstat["last_ts"] = ts_iso
                if etype == "run.end":
                    stats["run_end_total"] += 1
                    stats["sessions_run_end"].add(session_id)
                    model = payload.get("model_used") or "unknown"
                    stats["run_end_by_model"][model] += 1
                    stats["run_end_by_reason"][payload.get("reason") or "unknown"] += 1
                    sstat["run_end"] += 1
                    sstat["models"].add(model)
                elif etype == "tool.execution.declared":
                    stats["declared_total"] += 1
                    name = payload.get("tool_name") or "unknown"
                    stats["declared_by_name"][name] += 1
                    sstat["declared"] += 1
                    if name == "search_records":
                        stats["sr_total"] += 1
                        stats["sessions_search_records"].add(session_id)
                        sstat["search_records"] += 1
                elif etype == "message.appended" and payload.get("role") == "assistant":
                    for call in payload.get("tool_calls") or []:
                        fn = call.get("function") or {}
                        name = fn.get("name")
                        if name != "search_records":
                            continue
                        args_raw = fn.get("arguments")
                        try:
                            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                        except ValueError:
                            stats["args_parse_fail"] += 1
                            continue
                        if not isinstance(args, dict):
                            stats["args_parse_fail"] += 1
                            continue
                        kind = str(args.get("kind", "<omitted>"))
                        stats["sr_kind_breakdown"][kind] += 1
                        if kind == "method":
                            stats["method_search_total"] += 1
                            stats["sessions_method_search"].add(session_id)
                            sstat["method_search"] += 1
    return stats


def usage_jsonl_stats(since: datetime, until: datetime) -> dict:
    result = {"exists": os.path.exists(USAGE_PATH), "total_lines": 0, "in_window": 0,
              "decisions": {}, "ts_field": None, "parse_fail": 0}
    if not result["exists"]:
        return result
    decisions = Counter()
    for line in open(USAGE_PATH, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        result["total_lines"] += 1
        try:
            record = json.loads(line)
        except ValueError:
            result["parse_fail"] += 1
            continue
        ts_raw = record.get("ts") or record.get("timestamp") or record.get("created_at")
        if ts_raw and result["ts_field"] is None:
            result["ts_field"] = "ts" if record.get("ts") else ("timestamp" if record.get("timestamp") else "created_at")
        if ts_raw:
            try:
                if since <= parse_ts(ts_raw) <= until:
                    result["in_window"] += 1
                    decision = record.get("decision") or record.get("use_decision") or "unknown"
                    decisions[decision] += 1
            except ValueError:
                result["parse_fail"] += 1
    result["decisions"] = dict(decisions)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from-gen", type=int, default=None, help="window start = activation time of this generation")
    parser.add_argument("--since", default=None, help="explicit window start (ISO8601, tz-aware)")
    parser.add_argument("--until", default=None, help="window end (ISO8601); default = now UTC")
    parser.add_argument("--out", default=None, help="also write JSON summary to this path")
    args = parser.parse_args()

    until = parse_ts(args.until) if args.until else datetime.now(timezone.utc)
    anchors = gen_anchors()
    anchor_note = None
    if args.since:
        since = parse_ts(args.since)
    elif args.from_gen is not None:
        if args.from_gen not in anchors:
            print(json.dumps({"error": f"no succeeded restart anchor for generation {args.from_gen}",
                              "available_anchors": {str(k): v.isoformat() for k, v in sorted(anchors.items())}},
                             ensure_ascii=False, indent=1))
            return 2
        since = anchors[args.from_gen]
        anchor_note = f"gen{args.from_gen} activation = earliest succeeded restart completion {since.isoformat()}"
    else:
        parser.error("need --from-gen or --since")

    stats = scan_window(since, until)
    usage = usage_jsonl_stats(since, until)

    top_names = dict(stats["declared_by_name"].most_common(15))
    sr_sessions = len(stats["sessions_search_records"])
    summary = {
        "window": {"since": since.isoformat(), "until": until.isoformat(),
                   "anchor": anchor_note or "explicit --since"},
        "sessions": {"active_any_event": len(stats["sessions_any_event"]),
                     "with_run_end": len(stats["sessions_run_end"]),
                     "with_search_records": sr_sessions,
                     "with_method_search": len(stats["sessions_method_search"])},
        "runs": {"run_end_total": stats["run_end_total"],
                 "by_model": dict(stats["run_end_by_model"]),
                 "by_reason": dict(stats["run_end_by_reason"])},
        "tool_calls": {"declared_total": stats["declared_total"], "by_name_top": top_names,
                       "search_records": stats["sr_total"]},
        "search_records_kind_breakdown": dict(stats["sr_kind_breakdown"]),
        "method": {"searches_kind_method": stats["method_search_total"],
                   "usage_jsonl": usage},
        "per_session": {sid: {**detail, "models": sorted(detail["models"])}
                        for sid, detail in sorted(stats["per_session"].items(),
                                                  key=lambda kv: -kv[1]["declared"])},
        "integrity": {"files_scanned": stats["files_scanned"],
                      "unreadable_files": stats["unreadable_files"],
                      "malformed_lines": stats["malformed_lines"],
                      "args_parse_fail": stats["args_parse_fail"]},
    }
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
