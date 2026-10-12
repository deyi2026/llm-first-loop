#!/usr/bin/env python3
"""freeze.py — 冻结事件日志快照（Cache Attribution Scorer 的唯一合法输入形态).

从源目录读取 *.jsonl（按文件名序），过滤出 scorer 消费的事件类型，按 seq 升序写出
extract.jsonl，并生成 manifest.json：
  - sources[]: 原始文件 sha256/bytes/mtime（真源取证）
  - extract: 过滤副本的 sha256/event_count/first_seq/last_seq（scorer 校验对象）
  - log_snapshot_at = max(source mtime) —— 不是墙钟，重跑不变

设计锁（docs/cache-attribution/schema.md §0）：
  - 冻结副本与 manifest 是不可变输入；源日志之后继续增长不影响已冻结结果。
  - 本工具不修改源文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# scorer 消费的事件类型（过滤白名单；其余类型与分类无关，减重用）
CONSUMED_TYPES = (
    "request.usage",
    "request.meta",
    "history.compaction",
    "message.cache_compacted",
)

# Privacy-safe mechanical projection. The scorer never needs raw messages/tool payloads;
# keeping only structural counters/ids makes committed fixtures small and auditable.
USAGE_FIELDS = (
    "round", "tokens_in", "cache_hit", "stable_prefix_fp",
    "prefix_changed", "prefix_change_reason",
)
META_FIELDS = (
    "round", "model", "attempt_kind", "provider_call_id",
    "history_chars", "provider_visible_chars", "tools_count",
)
GENERATION_CONTRACT_FIELDS = ("provider", "model", "wire_protocol")
WORKING_SET_FIELDS = (
    "raw_tool_chars", "projected_tool_chars", "folded_results", "folded_groups",
    "fold_triggers", "soft_result_cap", "hard_result_cap", "min_net_gain_chars",
)
RUN_INTEGRITY_FIELDS = (
    "background_run_generation", "run_generation_state", "workspace_epoch",
    "routing_epoch", "routing_transition", "provider_call_id",
)
COMPACTION_FIELDS = (
    "compaction_epoch", "pre_history_chars", "pre_chars", "post_chars",
    "trigger", "compact_ratio", "effective_budget_chars", "trigger_limit_chars",
    "archive_target_ratio", "archive_target_chars", "archived_count",
    "archived_group_count", "head_keep_chars", "cache_boundary_mode",
)
MARKER_FIELDS = ("msg_seq", "marker_version", "provider_id", "model")
PROJECTION_ID = "cache-attribution/v1-minimal"


def _pick(src: dict, fields: tuple[str, ...]) -> dict:
    return {k: src[k] for k in fields if k in src}


def project_event(event: dict) -> dict:
    """Return the minimal privacy-safe event shape consumed by scorer/replay."""
    out = {k: event[k] for k in ("seq", "ts", "type") if k in event}
    payload = event.get("payload") or {}
    event_type = event.get("type")
    if event_type == "request.usage":
        projected = _pick(payload, USAGE_FIELDS)
    elif event_type == "request.meta":
        projected = _pick(payload, META_FIELDS)
        gc = _pick(payload.get("generation_contract") or {}, GENERATION_CONTRACT_FIELDS)
        if gc:
            projected["generation_contract"] = gc
        ws = _pick(
            ((((payload.get("influence") or {}).get("ingress") or {}).get("tool_working_set")) or {}),
            WORKING_SET_FIELDS,
        )
        if ws:
            projected["influence"] = {"ingress": {"tool_working_set": ws}}
        run_integrity = _pick(payload.get("run_integrity_receipt") or {}, RUN_INTEGRITY_FIELDS)
        if run_integrity:
            projected["run_integrity_receipt"] = run_integrity
    elif event_type == "history.compaction":
        projected = _pick(payload, COMPACTION_FIELDS)
    elif event_type == "message.cache_compacted":
        projected = _pick(payload, MARKER_FIELDS)
    else:
        projected = {}
    out["payload"] = projected
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iso_mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source_dir", help="包含原始 *.jsonl 事件日志的目录")
    ap.add_argument("out_dir", help="冻结快照输出目录（不存在则创建）")
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    src = Path(args.source_dir)
    out = Path(args.out_dir)
    if not src.is_dir():
        print(f"[freeze] source dir not found: {src}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.glob("*.jsonl") if p.is_file())
    if not files:
        print(f"[freeze] no *.jsonl in {src}", file=sys.stderr)
        return 2

    sources = []
    kept = []
    for p in files:
        sources.append(
            {
                "path": p.name,
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size,
                "mtime": iso_mtime(p),
            }
        )
        with open(p, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if o.get("type") in CONSUMED_TYPES and isinstance(o.get("seq"), int):
                    kept.append(project_event(o))

    kept.sort(key=lambda o: o["seq"])
    extract = out / "extract.jsonl"
    with open(extract, "w", encoding="utf-8") as f:
        for o in kept:
            f.write(json.dumps(o, ensure_ascii=False, separators=(",", ":")) + "\n")

    manifest = {
        "manifest_version": "1",
        "session_id": args.session_id,
        "source_dir": f"event_logs/{args.session_id}",
        "log_snapshot_at": max(s["mtime"] for s in sources),
        "sources": sources,
        "extract": {
            "path": extract.name,
            "sha256": sha256_file(extract),
            "event_count": len(kept),
            "first_seq": kept[0]["seq"] if kept else 0,
            "last_seq": kept[-1]["seq"] if kept else 0,
            "filter": list(CONSUMED_TYPES),
            "projection": PROJECTION_ID,
            "provenance": (
                "privacy-safe field projection of source logs; seq/ts preserved verbatim; "
                "scorer verifies this file only"
            ),
        },
        "notes": args.notes,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"[freeze] {len(kept)} events ({manifest['extract']['first_seq']}.."
        f"{manifest['extract']['last_seq']}) -> {extract}  snapshot_at={manifest['log_snapshot_at']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
