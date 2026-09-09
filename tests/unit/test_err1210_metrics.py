"""err1210 指标重算脚本测试（tasks 7.3；spec 5.4.1-1a/3a、6.1/6.2、5.1.3-5d）.

覆盖: compact 首请求识别（骤降 ≥30% 且 ≥8 条）、±6s 归因窗口与 UTC→本地 +8
换算、__global__ 排除、payload_trace*.jsonl 通配聚合（活跃+分片）、--as-of
时点过滤、重试成功率三文件口径（exhausted/无脚印推断）、defer 回放完整率
（[r3-P2] 口径——lost_on_reinject 单列不计入）、未回放候选单列、CLI 输出。
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.err1210_metrics import compute_metrics, main, render_summary


def _write_audit(
    tmp_path: Path,
    *,
    trace_rows: list[dict],
    exceptions: list[dict],
    defer_rows: list[dict] | None = None,
    shard_rows: list[dict] | None = None,
) -> Path:
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "payload_trace.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in trace_rows) + "\n",
        encoding="utf-8",
    )
    if shard_rows:
        (audit / "payload_trace-20260827.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in shard_rows) + "\n",
            encoding="utf-8",
        )
    (audit / "exception_log.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in exceptions) + "\n",
        encoding="utf-8",
    )
    if defer_rows:
        (audit / "defer_trace.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in defer_rows) + "\n",
            encoding="utf-8",
        )
    return tmp_path


def _trace(ts: str, session_id: str, n: int) -> dict:
    return {
        "ts": ts,
        "session_id": session_id,
        "provider": "openai-compat",
        "model": "m",
        "msgs": [{"i": i, "role": "user", "chars": 10, "h": f"h{i}"} for i in range(n)],
    }


def _exc(ts_utc: str, code: str = "1210") -> dict:
    body = f'HTTP 400: Bad Request | {{"error":{{"code":"{code}","message":"参数有误"}}}}'
    return {
        "ts": ts_utc,
        "phase": "llm_call",
        "error_type": "LLMHTTPError",
        "error_message": body,
    }


def _defer(ts: str, event: str, session_id: str, slot: str, count: int | None = None) -> dict:
    payload = {"count": count} if count is not None else {}
    return {
        "ts": ts,
        "event": event,
        "session_id": session_id,
        "slot_kind": slot,
        "payload": payload,
    }


def _fixture(tmp_path: Path) -> Path:
    """合成审计数据: 2 个 compact 首请求（10:00:30 / 10:01:30）均 1210."""
    return _write_audit(
        tmp_path,
        trace_rows=[
            _trace("2026-08-27T10:00:00", "sess-A", 100),
            _trace("2026-08-27T10:00:30", "sess-A", 40),  # 骤降 60% → CF
            _trace("2026-08-27T10:01:00", "sess-A", 41),
            _trace("2026-08-27T10:01:20", "sess-A", 100),
            _trace("2026-08-27T10:01:30", "sess-A", 45),  # 骤降 55% → CF
            _trace("2026-08-27T10:00:30", "__global__", 1),  # 干扰项排除
            _trace("2026-08-27T10:02:00", "sess-B", 50),
        ],
        exceptions=[
            _exc("2026-08-27T02:00:30.123456+00:00"),  # 本地 10:00:30 → CF 命中
            _exc("2026-08-27T02:01:30.000000+00:00"),  # 本地 10:01:30 → CF 命中
            _exc("2026-08-27T02:02:00.000000+00:00"),  # 本地 10:02:00 → 非 CF（attributed_plain）
            _exc("2026-08-27T02:05:00.000000+00:00"),  # 本地 10:05:00 → 无行（不可归因）
            _exc("2026-08-27T02:00:40.000000+00:00", code="1211"),  # 非 1210 忽略
            {
                "ts": "2026-08-27T02:00:41+00:00",
                "phase": "llm_call",
                "error_type": "LLMTimeoutError",
                "error_message": "timeout",
            },  # 非 HTTP 忽略
        ],
        defer_rows=[
            _defer("2026-08-27T10:00:35", "defer_stored", "sess-A", "interop", 2),
            _defer("2026-08-27T10:00:36", "defer_exhausted", "sess-A", "all"),
            _defer("2026-08-27T10:01:35", "defer_stored", "sess-A", "tip", 1),
            _defer("2026-08-27T10:01:36", "defer_replayed", "sess-A", "tip", 1),
            _defer("2026-08-27T10:02:40", "defer_dropped", "sess-B", "hotcard", 1),
            _defer("2026-08-27T10:02:45", "defer_stored", "sess-B", "gate_note"),
            _defer("2026-08-27T10:03:00", "defer_lost_on_reinject", "sess-C", "all"),
            _defer("2026-08-27T10:04:00", "defer_stored", "sess-D", "gate_note"),
        ],
    )


class TestMetricsRecompute:
    def test_four_metrics(self, tmp_path):
        r = compute_metrics(_fixture(tmp_path))
        m = r["metrics"]
        # ① compact 首请求 1210 发生率: 2 CF 全命中 = 100%
        assert m["compact_first_total"] == 2
        assert m["compact_first_1210_count"] == 2
        assert m["compact_first_1210_rate"] == 1.0
        # ② P0 触发次数
        assert m["p0_trigger_count"] == 2
        # ③ 重试成功率: T1 有 defer 脚印+exhausted → 失败; T2 有脚印无 exhausted → 成功
        assert m["retry_attempted"] == 2
        assert m["retry_failed_1210"] == 1
        assert m["retry_success"] == 1
        assert m["retry_success_rate"] == 0.5
        # ④ defer 回放完整率: replayed=1 / (stored=5 − dropped=1) = 0.25
        #    stored=5（interop2+tip1+B.gate_note1+D.gate_note1）；lost_on_reinject 单列不计入
        assert m["defer_stored_count"] == 5
        assert m["defer_dropped_count"] == 1
        assert m["defer_replayed_count"] == 1
        assert m["defer_replay_completeness"] == 0.25
        assert m["defer_lost_on_reinject_count"] == 1
        # 未回放候选（单列）: sess-A interop 2 条 + sess-B gate_note 1 条 + sess-D gate_note 1 条
        cands = {c["session_id"]: c["unreplayed"] for c in m["defer_unreplayed_candidates"]}
        assert cands == {"sess-A": 2, "sess-B": 1, "sess-D": 1}

    def test_attribution_details(self, tmp_path):
        r = compute_metrics(_fixture(tmp_path))
        d = r["details"]
        cf = d["compact_first_rows"]
        assert [x["session_id"] for x in cf] == ["sess-A", "sess-A"]
        assert len(d["attributed_1210_plain"]) == 1  # sess-B 非 CF
        assert d["attributed_1210_plain"][0]["session_id"] == "sess-B"
        assert len(d["unattributed_1210"]) == 1  # 10:05:00
        assert d["unattributed_1210"][0]["local_ts"] == "2026-08-27T10:05:00"

    def test_wildcard_aggregation(self, tmp_path):
        """payload_trace*.jsonl 通配聚合（活跃 + 历史分片）."""
        p = _fixture(tmp_path)
        shard = [
            _trace("2026-08-27T09:00:00", "sess-Z", 80),
            _trace("2026-08-27T09:00:30", "sess-Z", 30),  # 骤降 → CF（分片内）
        ]
        _write_audit(
            p,
            trace_rows=[],
            exceptions=[_exc("2026-08-27T01:00:30+00:00")],
            shard_rows=shard,
        )
        r = compute_metrics(p)
        assert r["inputs"]["payload_trace_rows"] == 2
        assert len(r["inputs"]["payload_trace_files"]) == 2
        assert r["metrics"]["compact_first_total"] == 1
        assert r["metrics"]["compact_first_1210_count"] == 1

    def test_as_of_snapshot(self, tmp_path):
        """--as-of 时点快照对账: 10:01:00 截止 → 仅 T1 在窗内（1/1=100%）."""
        r = compute_metrics(_fixture(tmp_path), as_of="2026-08-27T10:01:00")
        m = r["metrics"]
        assert m["compact_first_total"] == 1
        assert m["compact_first_1210_count"] == 1
        assert m["compact_first_1210_rate"] == 1.0
        assert m["p0_trigger_count"] == 1
        # 窗内 defer 事件: 仅 10:00:35/36 两个（stored2+exhausted）
        assert m["defer_stored_count"] == 2
        assert r["as_of"] == "2026-08-27T10:01:00"

    def test_as_of_aware_utc(self, tmp_path):
        """--as-of 带偏移（UTC）→ 换算本地后过滤."""
        r = compute_metrics(_fixture(tmp_path), as_of="2026-08-27T02:01:00+00:00")
        assert r["metrics"]["compact_first_total"] == 1  # 本地 10:01:00 截止

    def test_attribution_window_edge(self, tmp_path):
        """±6s 窗口: 距 CF 行 5s 的 1210 归因命中; 10s 的不可归因."""
        p = _write_audit(
            tmp_path,
            trace_rows=[
                _trace("2026-08-27T10:00:00", "sess-A", 100),
                _trace("2026-08-27T10:00:30", "sess-A", 40),  # CF
                _trace("2026-08-27T10:01:00", "sess-A", 41),
            ],
            exceptions=[
                _exc("2026-08-27T02:00:35+00:00"),  # 本地 10:00:35 → CF 行 5s → 命中
                _exc("2026-08-27T02:00:40+00:00"),  # 本地 10:00:40 → 距行 10s/20s → 不可归因
            ],
        )
        r = compute_metrics(p)
        assert r["metrics"]["compact_first_1210_count"] == 1
        assert len(r["details"]["unattributed_1210"]) == 1


class TestMetricsCli:
    def test_main_output_and_json(self, tmp_path, capsys):
        p = _fixture(tmp_path)
        out_json = tmp_path / "report.json"
        code = main(["--data-dir", str(p), "--output", str(out_json)])
        text = capsys.readouterr().out
        assert code == 0
        assert "compact 首请求 1210 发生率: 2/2 = 1.0" in text
        assert "P0 触发次数: 2" in text
        assert out_json.exists()
        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["metrics"]["compact_first_1210_rate"] == 1.0
        # v1.1（verdict_p1 B-3）: schema 升级 + 新键（裸数值键零变更）
        assert data["schema"] == "err1210_metrics_v1.1"
        assert data["metrics"]["compact_first_1210_rate_detail"] == {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0,
        }
        assert "aggregated_tail_user_max" in data["metrics"]
        assert "aggregated_tail_user_fallback_rounds" in data["metrics"]

    def test_render_summary_none_rates(self):
        """无样本场景: 发生率/成功率/完整率均为 n/a（非除零崩溃）."""
        report = {
            "as_of": None,
            "generated_at": "t",
            "inputs": {
                "exception_log": {"rows_1210": 0, "unattributable": 0},
                "payload_trace_files": [],
                "payload_trace_rows": 0,
                "defer_trace_rows": 0,
            },
            "metrics": {
                "compact_first_total": 0,
                "compact_first_1210_count": 0,
                "compact_first_1210_rate": None,
                "p0_trigger_count": 0,
                "triggers": 0,
                "no_retry_inferred": 0,
                "retry_attempted": 0,
                "retry_failed_1210": 0,
                "retry_success": 0,
                "retry_success_rate": None,
                "defer_stored_count": 0,
                "defer_dropped_count": 0,
                "defer_replayed_count": 0,
                "defer_replay_completeness": None,
                "defer_exhausted_count": 0,
                "defer_lost_on_reinject_count": 0,
                "defer_unreplayed_candidates": [],
            },
            "details": {
                "compact_first_rows": [],
                "attributed_1210_plain": [],
                "unattributed_1210": [],
                "caveats": [],
            },
        }
        text = render_summary(report)
        assert "n/a" in text


def _write_causal_requests(tmp_path: Path, rows: list[tuple[str, str, int, int]]) -> None:
    """Write request.meta events: (UTC ISO ts, session, messages_count, tail_user_run)."""
    root = tmp_path / "event_logs"
    root.mkdir(parents=True, exist_ok=True)
    by_session: dict[str, list[dict]] = {}
    for idx, (ts, sid, n, tail) in enumerate(rows, start=1):
        by_session.setdefault(sid, []).append(
            {
                "event_id": f"e-{sid}-{idx}",
                "session_id": sid,
                "seq": idx,
                "type": "request.meta",
                "ts": ts,
                "payload": {
                    "round": idx,
                    "model": "m",
                    "messages_count": n,
                    "tail_user_run": tail,
                    "generation_contract": {"provider": "openai-compat", "model": "m"},
                },
            }
        )
    for sid, events in by_session.items():
        (root / f"{sid}.jsonl").write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
            encoding="utf-8",
        )


def test_causal_request_rows_replace_future_payload_trace_metrics(tmp_path) -> None:
    p = _write_audit(
        tmp_path,
        trace_rows=[],
        exceptions=[_exc("2026-08-27T02:00:30+00:00")],
    )
    _write_causal_requests(
        p,
        [
            ("2026-08-27T02:00:00+00:00", "sess-A", 100, 1),
            ("2026-08-27T02:00:30+00:00", "sess-A", 40, 1),
        ],
    )
    report = compute_metrics(p)
    assert report["inputs"]["payload_trace_rows"] == 0
    assert report["inputs"]["causal_request_rows"] == 2
    assert report["inputs"]["legacy_payload_rows_used"] == 0
    assert report["inputs"]["request_rows_total"] == 2
    assert report["inputs"]["request_source_mode"] == "causal"
    assert report["metrics"]["compact_first_total"] == 1
    assert report["metrics"]["compact_first_1210_count"] == 1
    assert report["metrics"]["aggregated_tail_user_max"] == 1
    assert report["metrics"]["aggregated_tail_user_fallback_rounds"] == 0


def test_hybrid_request_rows_keep_pre_causal_history_without_overlap(tmp_path) -> None:
    p = _write_audit(
        tmp_path,
        trace_rows=[
            _trace("2026-08-27T09:00:00", "sess-Z", 80),
            _trace("2026-08-27T09:00:30", "sess-Z", 30),
            # Same session/time range later covered by causal request.meta and must not double count.
            _trace("2026-08-27T10:00:00", "sess-A", 100),
            _trace("2026-08-27T10:00:30", "sess-A", 40),
        ],
        exceptions=[
            _exc("2026-08-27T01:00:30+00:00"),
            _exc("2026-08-27T02:00:30+00:00"),
        ],
    )
    _write_causal_requests(
        p,
        [
            ("2026-08-27T02:00:00+00:00", "sess-A", 100, 1),
            ("2026-08-27T02:00:30+00:00", "sess-A", 40, 1),
        ],
    )
    report = compute_metrics(p)
    assert report["inputs"]["payload_trace_rows"] == 4
    assert report["inputs"]["causal_request_rows"] == 2
    assert report["inputs"]["legacy_payload_rows_used"] == 2
    assert report["inputs"]["request_rows_total"] == 4
    assert report["inputs"]["request_source_mode"] == "hybrid"
    assert report["metrics"]["compact_first_total"] == 2
    assert report["metrics"]["compact_first_1210_count"] == 2
