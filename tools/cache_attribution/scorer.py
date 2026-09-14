#!/usr/bin/env python3
"""scorer.py — 离线事实重放器 + 机械分类器（Cache Attribution Scorer v0.1.0）.

角色锁死：它只重放冻结快照、按版本化规则分类、按版本化估算器记账。
它不是策略层：不读墙钟、不读环境、不产出任何"应该怎么办"。

输入：freeze.py 产出的冻结目录（manifest.json + extract.jsonl）。
输出：严格符合 schemas/cache_attribution_report.schema.json 的 JSONL。

版本化（任何变更必须显式 bump，否则 Golden Regression Gate 失败）：
  CLASSIFIER_VERSION  = "v1-precedence"    (C1–C7 + primary 优先级)
  ESTIMATOR_ID        = "v1-linear-append" (公式见 docs/cache-attribution/schema.md §5)

结构证据锁（不得用时间邻近证明因果；时间窗只生成 candidate）：
  - meta(N) ↔ usage(N) 按 seq 配对（meta 在自身 usage 之前、上一 usage 之后），round 一致性校验。
  - C3 history_compaction：窗口 (prev_usage.seq, usage.seq] 内存在 history.compaction 事件（日志序证据，强于墙钟）。
  - C4 working_set_fold：paired meta 的 folded_results 相比上一 build 严格增加（执行证据）。
    fold_triggers 非空只是 armed 状态，不构成执行证据（11:51:30 / 13:31:11 实测教训）。
  - C5 provider_eviction：stable_prefix_fp 未变 ∧ prefix_changed=false ∧ 无 C1/C3/C4 证据
    ∧ (hit=0 ∨ hit < 0.5×stable_prefix_tokens)。
  - C7 unknown：input 回缩 (>growth_fallback) 但无任何结构证据；或 prefix_changed=true 而无 C1。

记账锁：v1 的 boundary_excess_miss 只记 primary，不做多机制比例分摊。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCORER_VERSION = "0.1.1"
CLASSIFIER_VERSION = "v1-precedence"
ESTIMATOR_ID = "v1-linear-append"
SCHEMA_VERSION = "1.0.0-draft2"

# 估算器参数（Golden 锁定；--stable-prefix-tokens 可覆盖，覆盖时必须重产 golden）
ESTIMATOR_PARAMS = {
    "block_allowance_tokens": 64,
    "growth_fallback_tokens": 512,
    "stable_prefix_tokens": 7488,
    "stable_prefix_source": "observed_min_cold_start_hit_fallback",
}

BOUNDARY_ORDER = [  # primary 优先级（schema.md §4）
    "route_switch",
    "new_run_cold_start",
    "history_compaction",
    "working_set_fold",
    "provider_eviction",
    "append_only",
    "unknown",
]
CONTROLLABLE = {
    "history_compaction": "yes",
    "working_set_fold": "yes",
    "new_run_cold_start": "partial",
    "route_switch": "partial",
    "append_only": "no",
    "provider_eviction": "no",
    "unknown": "unknown",
}
CONFIDENCE = {  # high=直接事件证据 medium=结构推断 low=矛盾/fallback
    "route_switch": "high",
    "history_compaction": "high",
    "working_set_fold": "high",
    "new_run_cold_start": "medium",
    "provider_eviction": "medium",
    "append_only": "medium",
    "unknown": "low",
}
STORM_WINDOW_SECONDS = 180.0
TTL_GAP_SECONDS = 600.0


class ScorerError(RuntimeError):
    pass


# ── 冻结快照装载与 Snapshot Gate ────────────────────────────────────────────
def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_frozen(frozen_dir: Path) -> dict:
    manifest_path = frozen_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ScorerError(f"manifest.json not found in {frozen_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    extract = frozen_dir / manifest["extract"]["path"]
    if not extract.is_file():
        raise ScorerError(f"extract file missing: {extract}")
    digest = sha256_file(extract)
    if digest != manifest["extract"]["sha256"]:
        raise ScorerError(
            f"snapshot gate FAILED: extract sha256 mismatch "
            f"(manifest={manifest['extract']['sha256'][:16]}… actual={digest[:16]}…)"
        )
    events = []
    n = 0
    with open(extract, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            events.append(json.loads(line))
    if n != manifest["extract"]["event_count"]:
        raise ScorerError(
            f"snapshot gate FAILED: event_count mismatch "
            f"(manifest={manifest['extract']['event_count']} actual={n})"
        )
    seqs = [e["seq"] for e in events]
    if seqs != sorted(seqs):
        raise ScorerError("snapshot gate FAILED: extract seq not ascending")
    if seqs and (
        seqs[0] != manifest["extract"]["first_seq"]
        or seqs[-1] != manifest["extract"]["last_seq"]
    ):
        raise ScorerError("snapshot gate FAILED: seq watermark mismatch")
    return {"manifest": manifest, "events": events}


# ── 事件模型 ────────────────────────────────────────────────────────────────
@dataclass
class Build:
    """一次 provider 请求（usage 及其 paired meta、窗口内证据）。"""

    seq: int
    ts: str
    round: int
    tokens_in: int
    cache_hit: int
    stable_prefix_fp: str
    prefix_changed: bool
    prefix_change_reason: str
    run_generation: int = 0
    meta: dict | None = None
    prev: Build | None = None
    compactions: list = field(default_factory=list)  # 窗口内 history.compaction
    cc_marks: int = 0  # 窗口内 message.cache_compacted 条数
    fold_delta: int | None = None  # paired meta folded_results − prev paired meta
    boundary_types: list = field(default_factory=list)
    primary: str = ""
    classification_rule: str = ""
    evidence: list = field(default_factory=list)


def pair_builds(events: list) -> list[Build]:
    """按 seq 重放：meta(N) 在 usage(N) 之前。last preceding meta with same round。"""
    builds: list[Build] = []
    pending_meta: dict[int, dict] = {}  # round -> 最新 meta
    comp_queue: list = []
    last_usage_seq = 0
    prev_meta_ws_folded = None

    def usage_of(o: dict) -> Build:
        p = o["payload"]
        return Build(
            seq=o["seq"],
            ts=o["ts"],
            round=int(p.get("round") or 0),
            tokens_in=int(p.get("tokens_in") or 0),
            cache_hit=int(p.get("cache_hit") or 0),
            stable_prefix_fp=str(p.get("stable_prefix_fp") or ""),
            prefix_changed=bool(p.get("prefix_changed")),
            prefix_change_reason=str(p.get("prefix_change_reason") or ""),
        )

    for o in events:
        t = o.get("type")
        if t == "request.meta":
            pending_meta[int(o["payload"].get("round") or 0)] = o
        elif t == "history.compaction":
            comp_queue.append(o)
        elif t == "message.cache_compacted":
            pass  # 计数在 build 结算时按窗口统计
        elif t == "request.usage":
            b = usage_of(o)
            b.meta = pending_meta.pop(b.round, None) or (
                pending_meta.get(b.round)
            )
            ws = None
            if b.meta is not None:
                ing = (
                    (b.meta.get("payload", {}).get("influence") or {}).get("ingress") or {}
                )
                ws = (ing.get("tool_working_set") or {}).get("folded_results")
            b.fold_delta = (
                ws - prev_meta_ws_folded
                if ws is not None and prev_meta_ws_folded is not None
                else None
            )
            if ws is not None:
                prev_meta_ws_folded = ws
            b.compactions = [
                c for c in comp_queue if last_usage_seq < c["seq"] <= b.seq
            ]
            comp_queue = [c for c in comp_queue if c["seq"] > b.seq]
            builds.append(b)
            last_usage_seq = b.seq

    # message.cache_compacted 计数（窗口）
    cc_seqs = [o["seq"] for o in events if o.get("type") == "message.cache_compacted"]
    prev_seq = 0
    for b in builds:
        b.cc_marks = sum(1 for s in cc_seqs if prev_seq < s <= b.seq)
        prev_seq = b.seq

    # run_generation：round 重置（==1 或不再增长）即新 run
    rg = 0
    prev: Build | None = None
    for b in builds:
        if prev is None or b.round <= prev.round:
            rg += 1
        b.run_generation = rg
        b.prev = prev
        prev = b
    return builds


# ── 分类器 C1–C7（v1-precedence）────────────────────────────────────────────
def _route_fp(b: Build) -> tuple:
    """路由身份 = (model, provider)。

    实测教训：meta 的 provider_structure_fp 是逐请求指纹（整请求结构含消息），
    221 个请求 221 个值 —— 它不是路由判据，不得进入 C1（否则全场误判 route_switch）。
    """
    m = (b.meta or {}).get("payload", {})
    gc = m.get("generation_contract") or {}
    return (str(m.get("model") or ""), str(gc.get("provider") or ""))


def classify(b: Build, stable_prefix_tokens: int, growth_fallback: int) -> None:
    p = b.prev
    types: list[str] = []
    rules: list[str] = []

    route_change = False
    if (
        p is not None
        and b.meta is not None
        and p.meta is not None
        and _route_fp(b) != _route_fp(p)
    ):
        route_change = True
        types.append("route_switch")
        rules.append("C1-route-fp-change")
        b.evidence.append(f"request.meta:seq{b.meta['seq']}/route-fp")

    new_run = p is None or b.round <= p.round
    if new_run:
        types.append("new_run_cold_start")
        rules.append("C2-run-reset")

    if b.compactions:
        types.append("history_compaction")
        rules.append("C3-compaction-in-window")
        for c in b.compactions:
            b.evidence.append(f"history.compaction:seq{c['seq']}")

    fold_executed = (b.fold_delta or 0) > 0
    if fold_executed:
        types.append("working_set_fold")
        rules.append("C4-fold-executed-delta")
        if b.meta is not None:
            b.evidence.append(
                f"request.meta:seq{b.meta['seq']}/folded_results+{b.fold_delta}"
            )

    no_local_boundary = not (b.compactions or fold_executed)
    if (
        p is not None
        and not route_change
        and no_local_boundary
        and not b.prefix_changed
        and b.stable_prefix_fp == p.stable_prefix_fp
        and (
            b.cache_hit == 0
            or b.cache_hit < 0.5 * stable_prefix_tokens
        )
    ):
        types.append("provider_eviction")
        rules.append("C5-prefix-stable-full-miss")

    grew_ok = p is None or b.tokens_in >= p.tokens_in - growth_fallback
    if not types and grew_ok:
        types.append("append_only")
        rules.append("C6-no-boundary-append")
    if (
        (not types or (p is not None and b.prefix_changed and not route_change))
        and "unknown" not in types
    ):
        # 证据矛盾：回缩无证据 / prefix_changed 无 route 变化
        types.append("unknown")
        rules.append("C7-contradictory-evidence")

    b.boundary_types = types
    b.primary = next(t for t in BOUNDARY_ORDER if t in types)
    b.classification_rule = "+".join(rules) or "C6-no-boundary-append"


# ── 估算器 v1-linear-append ─────────────────────────────────────────────────
def expected_miss(b: Build, params: dict) -> int:
    p = b.prev
    blk = params["block_allowance_tokens"]
    gf = params["growth_fallback_tokens"]
    sp = params["stable_prefix_tokens"]
    if b.primary == "route_switch":
        return b.tokens_in
    if b.primary == "new_run_cold_start":
        return max(0, b.tokens_in - sp)
    if p is None:
        return max(0, b.tokens_in - sp)
    growth = max(0, b.tokens_in - p.tokens_in)
    if b.tokens_in >= p.tokens_in:
        return growth + blk
    return gf + blk  # 边界轮回缩：反事实=自然增长


def ts_gap(a: str, b: str) -> float:
    from datetime import datetime

    return round(
        (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 3
    )


# ── 记账与输出 ───────────────────────────────────────────────────────────────
def score(frozen_dir: Path, stable_prefix_tokens: int | None = None) -> list[dict]:
    frozen = load_frozen(frozen_dir)
    manifest = frozen["manifest"]
    params = dict(ESTIMATOR_PARAMS)
    if stable_prefix_tokens is not None:
        params["stable_prefix_tokens"] = stable_prefix_tokens
        params["stable_prefix_source"] = "cli_override"

    builds = pair_builds(frozen["events"])
    gf = params["growth_fallback_tokens"]
    records: list[dict] = []
    for b in builds:
        classify(b, params["stable_prefix_tokens"], gf)
        exp = expected_miss(b, params)
        observed = b.tokens_in - b.cache_hit
        excess = observed - exp
        clamp = max(0, -excess)
        excess = max(0, excess)
        gap = ts_gap(b.prev.ts, b.ts) if b.prev else None

        m = (b.meta or {}).get("payload", {})
        ws = (((m.get("influence") or {}).get("ingress") or {}).get("tool_working_set")) or {}

        rec = {
            "record_type": "request_attribution",
            "session_id": manifest["session_id"],
            "ts": b.ts,
            "seq": b.seq,
            "run_generation": b.run_generation,
            "round": b.round,
            "attempt_kind": str(m.get("attempt_kind") or "unresolved"),
            "provider_call_id": str(m.get("provider_call_id") or "unresolved"),
            "provider": str((m.get("generation_contract") or {}).get("provider") or "unresolved"),
            "model": str(m.get("model") or "unresolved"),
            "tokens_in": b.tokens_in,
            "cache_hit": b.cache_hit,
            "cache_miss": observed,
            "cache_hit_rate": round(b.cache_hit / b.tokens_in, 4) if b.tokens_in else 0.0,
            "stable_prefix_fp": b.stable_prefix_fp,
            "prefix_changed": b.prefix_changed,
            "prefix_change_reason": b.prefix_change_reason,
            "gap_seconds_since_prev": gap,
            "context_sizes": {
                "history_chars": m.get("history_chars"),
                "provider_visible_chars": m.get("provider_visible_chars"),
            }
            if m
            else None,
            "boundary": {
                "types": b.boundary_types,
                "primary": b.primary,
                "evidence_event_ids": b.evidence,
                "classification_rule": b.classification_rule,
            },
            "attribution": {
                "observed_miss": observed,
                "expected_append_miss": exp,
                "boundary_excess_miss": excess,
                "clamped_negative_tokens": clamp,
                # 铁律（Controllability Gate）：types 含 provider_eviction → 永不可控，
                # 即便 primary 是 new_run_cold_start（冷启动 + TTL 驱逐共现时，
                # excess 属服务端，不得经 partial 进入 controllable 语义）。
                "controllable": (
                    "no" if "provider_eviction" in b.boundary_types
                    else CONTROLLABLE[b.primary]
                ),
                "confidence": CONFIDENCE[b.primary],
                "estimator_id": ESTIMATOR_ID,
            },
        }
        if b.compactions:
            last = b.compactions[-1]["payload"]
            nxt = [x for x in builds if x.seq > b.seq and x.compactions]
            rec["history_compaction_detail"] = {
                "compaction_epoch": last.get("compaction_epoch"),
                "pre_chars": last.get("pre_history_chars"),
                "post_chars": last.get("post_chars"),
                "trigger": str(last.get("trigger") or ""),
                "archived_messages": b.cc_marks,
                "archived_groups": None,
                "low_water_target": None,
                "growth_guard": None,
                "convergence_ok": (
                    last.get("post_chars", 0)
                    <= last.get("compact_ratio", 0.85) * last.get("effective_budget_chars", 0)
                ),
                "rounds_until_next_compaction": (nxt[0].round - b.round) if nxt else None,
                "pending_fields": ["low_water_target", "growth_guard"],
            }
        if b.primary == "working_set_fold" or "working_set_fold" in b.boundary_types:
            rec["working_set_detail"] = {
                "raw_tool_chars": ws.get("raw_tool_chars"),
                "projected_tool_chars": ws.get("projected_tool_chars"),
                "folded_results": ws.get("folded_results"),
                "folded_groups": ws.get("folded_groups"),
                "fold_trigger": ",".join(ws.get("fold_triggers") or []),
                "net_gain_chars": (
                    (ws.get("raw_tool_chars") or 0) - (ws.get("projected_tool_chars") or 0)
                )
                or None,
                "working_set_projection_epoch": None,
                "previous_projection_fp": None,
                "pending_fields": [
                    "working_set_projection_epoch",
                    "previous_projection_fp",
                ],
            }
        if "provider_eviction" in b.boundary_types:
            rec["provider_eviction_detail"] = {
                "stable_prefix_unchanged": True,
                "no_local_projection_boundary": True,
                "full_miss": b.cache_hit == 0,
                "hit_drop_ratio": 0.0 if b.cache_hit == 0 else None,
                "gap_seconds": gap or 0.0,
                "ttl_suspected": bool(gap and gap > TTL_GAP_SECONDS),
            }
        records.append(rec)

    header = {
        "record_type": "snapshot_header",
        "schema_version": SCHEMA_VERSION,
        "session_id": manifest["session_id"],
        "log_snapshot_at": manifest["log_snapshot_at"],
        "sources": [
            {
                "path": f"{manifest['session_id']}/{manifest['extract']['path']}",
                "sha256": manifest["extract"]["sha256"],
                "first_seq": manifest["extract"]["first_seq"],
                "last_seq": manifest["extract"]["last_seq"],
                "event_count": manifest["extract"]["event_count"],
            }
        ],
        "generated_by": {
            "scorer": "cache-attribution-scorer",
            "version": SCORER_VERSION,
        },
        "estimator": {"estimator_id": ESTIMATOR_ID, "params": params},
        "surface": {
            "provider": "glm",
            "model": "glm/glm-5.3",
            "wire_protocol": "openai",
            "tools_count": 65,
            "stable_prefix_fp": builds[0].stable_prefix_fp if builds else "",
        },
        "notes": (
            "frozen extract; original source hashes in manifest; "
            "classifier=" + CLASSIFIER_VERSION
        ),
    }
    rollup = build_rollup(manifest["session_id"], records, builds)
    reconcile(records, rollup)
    return [header] + records + [rollup]


def build_rollup(session_id: str, records: list[dict], builds: list[Build]) -> dict:
    by: dict[str, dict] = {}
    for r in records:
        b = by.setdefault(
            r["boundary"]["primary"],
            {
                "type": r["boundary"]["primary"],
                "requests": 0,
                "observed_miss_sum": 0,
                "expected_append_miss_sum": 0,
                "boundary_excess_miss_sum": 0,
                "_controllability": set(),
            },
        )
        b["requests"] += 1
        b["observed_miss_sum"] += r["attribution"]["observed_miss"]
        b["expected_append_miss_sum"] += r["attribution"]["expected_append_miss"]
        b["boundary_excess_miss_sum"] += r["attribution"]["boundary_excess_miss"]
        b["_controllability"].add(r["attribution"]["controllable"])

    # A primary boundary bucket can contain different controllability outcomes when
    # boundary.types co-occur (e.g. new_run_cold_start + provider_eviction).
    # Never inherit the first record's label for the whole bucket.
    for b in by.values():
        controls = b.pop("_controllability")
        b["controllable"] = next(iter(controls)) if len(controls) == 1 else "mixed"

    totals = {
        "requests": len(records),
        "tokens_in": sum(r["tokens_in"] for r in records),
        "cache_hit": sum(r["cache_hit"] for r in records),
        "observed_miss": sum(r["attribution"]["observed_miss"] for r in records),
        "expected_append_miss": sum(
            r["attribution"]["expected_append_miss"] for r in records
        ),
        "boundary_excess_miss": sum(
            r["attribution"]["boundary_excess_miss"] for r in records
        ),
        "controllable_excess_miss": sum(
            r["attribution"]["boundary_excess_miss"]
            for r in records
            if r["attribution"]["controllable"] == "yes"
        ),
        "uncontrollable_excess_miss": sum(
            r["attribution"]["boundary_excess_miss"]
            for r in records
            if r["attribution"]["controllable"] == "no"
        ),
        "partial_excess_miss": sum(
            r["attribution"]["boundary_excess_miss"]
            for r in records
            if r["attribution"]["controllable"] == "partial"
        ),
        "unknown_excess_miss": sum(
            r["attribution"]["boundary_excess_miss"]
            for r in records
            if r["attribution"]["controllable"] == "unknown"
        ),
    }

    # storm 簇：history.compaction 事务链（相邻间隔 ≤ 180s）
    txns = sorted(
        (c for b in builds for c in b.compactions),
        key=lambda c: c["ts"],
    )
    clusters = []
    chain: list = []
    for c in txns:
        if chain and ts_gap(chain[-1]["ts"], c["ts"]) > STORM_WINDOW_SECONDS:
            if len(chain) >= 2:
                clusters.append(chain)
            chain = []
        chain.append(c)
    if len(chain) >= 2:
        clusters.append(chain)
    storm = []
    for ch in clusters:
        seqs = {c["seq"] for c in ch}
        excess = sum(
            r["attribution"]["boundary_excess_miss"]
            for r, b in zip(records, builds, strict=True)
            if b.primary == "history_compaction"
            and any(c["seq"] in seqs for c in b.compactions)
        )
        storm.append(
            {
                "boundary": "history_compaction",
                "start_ts": ch[0]["ts"],
                "end_ts": ch[-1]["ts"],
                "transactions": len(ch),
                "excess_miss_sum": excess,
                "definition": f">=2 history.compaction transactions within {STORM_WINDOW_SECONDS:.0f}s",
            }
        )

    rollup = {
        "record_type": "boundary_rollup",
        "session_id": session_id,
        "window": {
            "from_ts": records[0]["ts"],
            "to_ts": records[-1]["ts"],
        },
        "totals": totals,
        "by_boundary": [by[t] for t in BOUNDARY_ORDER if t in by],
        "notes": f"classifier={CLASSIFIER_VERSION} estimator={ESTIMATOR_ID}",
    }
    if storm:
        rollup["storm_clusters"] = storm
    return rollup


def reconcile(records: list[dict], rollup: dict) -> None:
    """Accounting Gate：任何违反即抛错（非零退出），不做静默改写。"""
    t = rollup["totals"]
    assert t["requests"] == len(records), "reconcile: request count"
    assert t["observed_miss"] == sum(
        r["attribution"]["observed_miss"] for r in records
    ), "reconcile: observed_miss"
    assert sum(b["observed_miss_sum"] for b in rollup["by_boundary"]) == t["observed_miss"], "reconcile: by_boundary observed"
    assert sum(b["boundary_excess_miss_sum"] for b in rollup["by_boundary"]) == t["boundary_excess_miss"], "reconcile: by_boundary excess"
    assert (
        t["controllable_excess_miss"]
        + t["uncontrollable_excess_miss"]
        + t["partial_excess_miss"]
        + t["unknown_excess_miss"]
        == t["boundary_excess_miss"]
    ), "reconcile: controllability split"
    for r in records:
        a = r["attribution"]
        assert a["boundary_excess_miss"] >= 0, "reconcile: negative excess"
        assert (
            a["observed_miss"] - a["expected_append_miss"] + a["clamped_negative_tokens"]
            == a["boundary_excess_miss"]
        ), "reconcile: per-record identity"
        if "provider_eviction" in r["boundary"]["types"]:
            assert a["controllable"] == "no", "reconcile: eviction must be uncontrollable"
        if "unknown" in r["boundary"]["types"] and r["boundary"]["primary"] == "unknown":
            assert a["controllable"] == "unknown", "reconcile: unknown not fixable"


# ── CLI ─────────────────────────────────────────────────────────────────────
def cmd_score(args) -> int:
    records = score(Path(args.frozen_dir), args.stable_prefix_tokens)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
    n_req = sum(1 for r in records if r["record_type"] == "request_attribution")
    print(f"[score] {n_req} request records -> {out}")
    return 0


def cmd_verify(args) -> int:
    load_frozen(Path(args.frozen_dir))
    print("[verify] snapshot gate OK")
    return 0


def cmd_golden(args) -> int:
    frozen = Path(args.frozen_dir)
    golden = Path(args.golden)
    records = score(frozen)
    produced = "".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in records
    )
    if args.update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(produced, encoding="utf-8")
        print(f"[golden] updated {golden}")
        return 0
    if not golden.is_file():
        print(f"[golden] FAIL: golden not found: {golden}", file=sys.stderr)
        return 1
    expected = golden.read_text(encoding="utf-8")
    if produced == expected:
        print("[golden] OK: byte-identical")
        return 0
    # 定位第一条差异记录
    pl, el = produced.splitlines(), expected.splitlines()
    for i, (a, b) in enumerate(zip(pl, el, strict=False)):
        if a != b:
            print(f"[golden] FAIL: first diff at record {i}", file=sys.stderr)
            print(f"  produced: {a[:200]}", file=sys.stderr)
            print(f"  golden:   {b[:200]}", file=sys.stderr)
            break
    else:
        print(f"[golden] FAIL: length differs ({len(pl)} vs {len(el)})", file=sys.stderr)
    print(
        "[golden] classifier/estimator 行为漂移；必须显式 bump CLASSIFIER_VERSION/"
        "ESTIMATOR_ID 并 --update 重产 golden",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("score", help="重放冻结快照产出报表")
    s.add_argument("frozen_dir")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--stable-prefix-tokens", type=int, default=None)
    s.set_defaults(func=cmd_score)

    v = sub.add_parser("verify", help="仅跑 Snapshot Gate")
    v.add_argument("frozen_dir")
    v.set_defaults(func=cmd_verify)

    g = sub.add_parser("golden", help="golden regression check / update")
    g.add_argument("frozen_dir")
    g.add_argument("golden")
    g.add_argument("--update", action="store_true")
    g.set_defaults(func=cmd_golden)

    args = ap.parse_args()
    try:
        return args.func(args)
    except ScorerError as e:
        print(f"[scorer] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
