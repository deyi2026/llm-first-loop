"""err1210 P2 oracle 库单元测试（tasks 6.7；spec 5.2.1-2a"二分日志可复审计"）.

覆盖: 快照加载、骨架/二分变体构造（占位等长/role 保持/掩码组合）、mock 预检、
令牌桶限流节奏、预算中止、429 中止、判定矩阵四分支（mock client 模拟四种
复现组合）、二分收敛（单条定位/组合触发）、dry-run 零发送、报告落盘。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.eval.oracle_1210 import (
    OracleReport,
    OracleSample,
    ReplayVariant,
    Verdict,
    _TokenBucket,
    build_variants,
    load_snapshot,
    mock_preflight,
    run_oracle,
    verdict_matrix,
)
from llm_loop.llm.errors import LLMError, LLMHTTPError

_ERR1210_BODY = json.dumps({"error": {"code": "1210", "message": "API 调用参数有误"}})


def _make_sample(n_inject: int = 5, n_prefix: int = 4) -> OracleSample:
    """构造最小样本: 1 system + n_prefix 历史 + n_inject 尾部 user 注入群."""
    messages = [{"role": "system", "content": "S" * 50}]
    for i in range(n_prefix):
        messages.append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"hist-{i}-" + "x" * 80}
        )
    span_start = len(messages)
    for i in range(n_inject):
        messages.append({"role": "user", "content": f"inj-{i}-" + "y" * (60 + i * 10)})
    span = [
        {"msg_idx": span_start + i, "slot_kind": "INTEROP", "prefix_sha": f"sha{i}"}
        for i in range(n_inject)
    ]
    return OracleSample(
        snapshot={
            "schema": 1,
            "ts_utc": "2026-08-27T00:00:00+00:00",
            "session_id": "sess-oracle-test",
            "model": "glm-5.3",
            "is_compact_first": True,
            "messages": messages,
            "tools": [{"type": "function", "function": {"name": "noop"}}],
            "params": {"timeout_s": 30},
            "injection_span": span,
            "trace_key": {"session_id": "sess-oracle-test", "local_ts": "2026-08-27T19:02:30"},
        }
    )


class ScriptedClient:
    """行为可编程 mock client（chat duck-typing，与生产 client 协议一致）.

    behavior(messages) 返回 "ok" | "1210" | "429"；记录调用明细供断言。
    """

    def __init__(self, behavior) -> None:
        self.behavior = behavior
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools, timeout_s=None, model=None):
        self.calls.append(list(messages))
        action = self.behavior(messages)
        if action == "1210":
            raise LLMHTTPError(
                f"HTTP 400: bad request | {_ERR1210_BODY}",
                status_code=400,
                body=_ERR1210_BODY,
            )
        if action == "429":
            raise LLMError("HTTP 429: rate limit exceeded (quota)")
        return SimpleNamespace(content="回答", finish_reason="stop", prompt_tokens=10)


class FakeClock:
    """fake 时钟（time/sleep 注入——限流节奏断言不发真实等待）."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def time_fn(self):
        return self.t

    def sleep_fn(self, s: float) -> None:
        self.sleeps.append(round(s, 3))
        self.t += s


# ── 6.1 快照加载 ──


class TestLoadSnapshot:
    def test_ok(self, tmp_path: Path):
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(_make_sample().snapshot, ensure_ascii=False), encoding="utf-8")
        s = load_snapshot(p)
        assert s.session_id == "sess-oracle-test"
        assert s.span_idx == [5, 6, 7, 8, 9]

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(ValueError, match="快照不存在"):
            load_snapshot(tmp_path / "nope.json")

    def test_schema_mismatch(self, tmp_path: Path):
        snap = _make_sample().snapshot
        snap["schema"] = 99
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(snap), encoding="utf-8")
        with pytest.raises(ValueError, match="schema"):
            load_snapshot(p)

    def test_missing_key(self, tmp_path: Path):
        snap = _make_sample().snapshot
        del snap["model"]
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(snap), encoding="utf-8")
        with pytest.raises(ValueError, match="model"):
            load_snapshot(p)

    def test_empty_messages(self, tmp_path: Path):
        snap = _make_sample().snapshot
        snap["messages"] = []
        p = tmp_path / "snap.json"
        p.write_text(json.dumps(snap), encoding="utf-8")
        with pytest.raises(ValueError, match="messages"):
            load_snapshot(p)


# ── 6.2 变体构造 ──


class TestBuildVariants:
    def test_skeleton_placeholder_equal_length_role_preserved(self):
        sample = _make_sample()
        v = build_variants(sample, track="skeleton")[0]
        assert v.track == "skeleton" and len(v.messages) == len(sample.messages)
        for orig, skel in zip(sample.messages, v.messages, strict=True):
            assert orig["role"] == skel["role"]
            oc, sc = orig["content"], skel["content"]
            if isinstance(oc, str):
                assert len(sc) == len(oc), "占位必须等长（保 chars 分布）"
                assert set(sc) == {"注"}, "占位必须为确定性单字重复"
        # 原文不被篡改（copy-on-write）
        assert sample.messages[0]["content"] == "S" * 50

    def test_bisect_initial_variants(self):
        sample = _make_sample()
        vs = build_variants(sample, track="bisect")
        assert [v.label for v in vs] == ["keep_all", "strip_all"]
        assert len(vs[0].messages) == len(sample.messages), "keep_all 原样"
        assert len(vs[1].messages) == len(sample.messages) - 5, "strip_all 剥离全部注入"
        assert all(m["content"].startswith("inj-") for m in vs[0].messages[5:]), "保真轨内容原样"

    def test_mask_length_guard(self):
        sample = _make_sample()
        with pytest.raises(ValueError, match="keep_mask 长度"):
            build_variants  # noqa: B018 — 占位防误用；实际守卫在 _apply_mask
            from llm_loop.eval.oracle_1210 import _apply_mask

            _apply_mask(sample, (True, True))

    def test_unknown_track(self):
        with pytest.raises(ValueError, match="未知轨道"):
            build_variants(_make_sample(), track="both")


# ── 6.3 mock 预检 ──


class TestMockPreflight:
    def _variant(self, messages):
        return ReplayVariant(variant_id="t", track="skeleton", keep_mask=(), messages=messages)

    def test_valid(self):
        ok, reason = mock_preflight(
            self._variant(
                [
                    {"role": "system", "content": "s"},
                    {"role": "user", "content": "u"},
                ]
            )
        )
        assert ok and reason is None

    def test_invalid_role(self):
        ok, reason = mock_preflight(self._variant([{"role": "wizard", "content": "x"}]))
        assert not ok and "role 非法" in (reason or "")

    def test_orphan_tool(self):
        ok, reason = mock_preflight(
            self._variant(
                [
                    {"role": "user", "content": "u"},
                    {"role": "tool", "content": "r", "tool_call_id": "tc-404"},
                ]
            )
        )
        assert not ok and "孤儿 tool" in (reason or "")

    def test_paired_tool_ok(self):
        ok, _ = mock_preflight(
            self._variant(
                [
                    {"role": "user", "content": "u"},
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"id": "tc-1", "type": "function", "function": {"name": "f"}}
                        ],
                    },
                    {"role": "tool", "content": "r", "tool_call_id": "tc-1"},
                ]
            )
        )
        assert ok

    def test_empty_messages(self):
        ok, reason = mock_preflight(self._variant([]))
        assert not ok and "messages 为空" in (reason or "")


# ── 令牌桶限流（spec 5.2.1-3: QPS≤0.5 → 每 2s 至多 1 请求）──


class TestTokenBucket:
    def test_pacing(self):
        clock = FakeClock()
        bucket = _TokenBucket(0.5, time_fn=clock.time_fn, sleep_fn=clock.sleep_fn)
        bucket.acquire()  # 首令牌立即可用（_next_at = now）
        assert clock.sleeps == []
        bucket.acquire()
        assert clock.sleeps == [2.0], "QPS=0.5 → 第二次请求等待 2s"

    def test_burst_no_accumulate(self):
        clock = FakeClock()
        bucket = _TokenBucket(1.0, time_fn=clock.time_fn, sleep_fn=clock.sleep_fn)
        for _ in range(3):
            bucket.acquire()
        assert clock.sleeps == [1.0, 1.0], "连续 acquire 节奏恒定（不累积欠账）"


# ── 6.5 判定矩阵 ──


def _report_with(skel_outcome: str | None, bisect_outcome: str | None) -> OracleReport:
    variants = []
    if skel_outcome is not None:
        variants.append({"track": "skeleton", "label": "skeleton_full", "outcome": skel_outcome})
    if bisect_outcome is not None:
        variants.append({"track": "bisect", "label": "keep_all", "outcome": bisect_outcome})
        variants.append({"track": "bisect", "label": "strip_all", "outcome": "ok"})
    return OracleReport(sample_ref="s", variants=variants)


class TestVerdictMatrix:
    def test_four_branches(self):
        assert verdict_matrix(_report_with("err1210", "ok")) is Verdict.STRUCTURE_TRIGGER
        assert verdict_matrix(_report_with("ok", "err1210")) is Verdict.CONTENT_TRIGGER
        assert verdict_matrix(_report_with("err1210", "err1210")) is Verdict.COMPOUND_TRIGGER
        assert verdict_matrix(_report_with("ok", "ok")) is Verdict.NON_REPRODUCIBLE

    def test_single_track_forbidden(self):
        """R3 禁止项: 禁止仅骨架轨下结论（spec 5.2.1-5）."""
        with pytest.raises(ValueError, match="两轨数据齐备"):
            verdict_matrix(_report_with("err1210", None))


# ── 6.4 run_oracle 编排（判定/收敛/预算/中止/dry-run/落盘）──


class TestRunOracle:
    def _run(self, behavior, *, sample=None, budget=20, clock=None, data_dir=None, **kw):
        sample = sample or _make_sample()
        clock = clock or FakeClock()
        client_holder: dict = {}

        def factory():
            client_holder["c"] = ScriptedClient(behavior)
            return client_holder["c"]

        report = run_oracle(
            sample,
            budget=budget,
            qps=0.5,
            client_factory=factory,
            data_dir=data_dir,
            time_fn=clock.time_fn,
            sleep_fn=clock.sleep_fn,
            **kw,
        )
        return report, client_holder.get("c"), clock

    def test_structure_trigger(self, tmp_path):
        """仅骨架轨复现: 骨架占位即 1210，保真 keep_all 正常."""
        report, client, _ = self._run(
            lambda msgs: (
                "1210"
                if all(
                    isinstance(m.get("content"), str) and set(m["content"]) == {"注"}
                    for m in msgs
                    if m["role"] != "system"
                )
                and any(m["role"] == "user" for m in msgs)
                else "ok"
            ),
            data_dir=tmp_path,
        )
        assert report.verdict == "STRUCTURE_TRIGGER"
        assert report.confidence == "high"
        assert report.budget_used >= 3

    def test_content_trigger_single_message_located(self, tmp_path):
        """保真轨复现 + 二分收敛单条: 恰含 inj-3 的变体才 1210 → minimal_set=[8]."""

        def behavior(msgs):
            if any(
                isinstance(m.get("content"), str) and m["content"].startswith("inj-3-")
                for m in msgs
            ):
                return "1210"
            return "ok"

        report, client, _ = self._run(behavior, data_dir=tmp_path)
        assert report.verdict == "CONTENT_TRIGGER"
        assert report.minimal_set == [8], "inj-3 在 span_idx=[5..9] 中下标 8（单条定位）"
        bisect_rounds = [v for v in report.variants if v["round_no"] > 0]
        assert bisect_rounds, "二分轮必须留痕（spec 5.2.1-2a 可复审计）"

    def test_compound_trigger(self, tmp_path):
        """双轨均复现: 骨架 1210 + 保真 keep_all 1210（inj-1 触发）."""

        def behavior(msgs):
            if all(set(m.get("content", "注")) == {"注"} for m in msgs):
                return "1210"  # 骨架轨复现
            if any(
                isinstance(m.get("content"), str) and m["content"].startswith("inj-1-")
                for m in msgs
            ):
                return "1210"  # 保真轨含触发条目复现
            return "ok"

        report, _, _ = self._run(behavior, data_dir=tmp_path)
        assert report.verdict == "COMPOUND_TRIGGER"

    def test_combo_trigger_no_single_point(self, tmp_path):
        """组合触发: 注入群 ≥3 条共存时复现（任何半集/单条不复现）→ minimal_set=最小共存组合."""

        def behavior(msgs):
            inj = sum(
                1
                for m in msgs
                if isinstance(m.get("content"), str) and m["content"].startswith("inj-")
            )
            return "1210" if inj >= 3 else "ok"

        report, _, _ = self._run(behavior, data_dir=tmp_path)
        assert report.verdict == "CONTENT_TRIGGER"
        assert report.minimal_set == [5, 6, 7], (
            "二分应收敛到仍复现的最小共存组合（spec 5.2.1-2 收敛标准 b: 子集无单点复现）"
        )

    def test_non_reproducible(self, tmp_path):
        report, _, _ = self._run(lambda msgs: "ok", data_dir=tmp_path)
        assert report.verdict == "NON_REPRODUCIBLE"
        assert report.confidence == "medium-non-reproducible"

    def test_budget_abort(self, tmp_path):
        """预算 ≤20 跨两轨共享: budget=2 → 第 3 个变体起 skipped，实验不完整."""
        report, client, _ = self._run(
            lambda msgs: "1210",
            budget=2,
            data_dir=tmp_path,
        )
        assert report.budget_used == 2
        assert report.incomplete_reason == "budget_exhausted"
        assert report.confidence == "low-experiment-incomplete"
        assert report.verdict == ""  # 不完整不下结论（防止单轨/半途结论）
        assert len(client.calls) == 2, "真实发送数被预算闸硬限"

    def test_throttle_abort(self, tmp_path):
        """429 → 自动中止剩余变体（spec 5.2.3-1）."""
        report, _, _ = self._run(lambda msgs: "429", data_dir=tmp_path)
        assert report.incomplete_reason == "throttled"
        assert report.coverage, "报告须标注覆盖率（如 1/N）"

    def test_dry_run_no_send(self, tmp_path):
        sent: list[str] = []

        def factory():
            sent.append("constructed")
            return ScriptedClient(lambda m: "ok")

        report = run_oracle(
            _make_sample(),
            qps=0.5,
            client_factory=factory,
            data_dir=tmp_path,
            dry_run=True,
            time_fn=FakeClock().time_fn,
            sleep_fn=FakeClock().sleep_fn,
        )
        assert sent == [], "dry-run 不得构造/发送真实 client"
        assert report.dry_run and report.budget_used == 0
        assert report.confidence == "none-dry-run"
        assert any(v["track"] == "skeleton" for v in report.variants), "变体明细仍在（构造验证）"

    def test_report_written(self, tmp_path):
        report, _, _ = self._run(lambda msgs: "ok", data_dir=tmp_path)
        d = Path(report.report_dir)
        assert (d / "report.json").is_file() and (d / "report.md").is_file()
        data = json.loads((d / "report.json").read_text(encoding="utf-8"))
        for key in ("variants", "verdict", "budget_used", "qps_actual", "confidence"):
            assert key in data, f"report.json 缺字段 {key}"
        md = (d / "report.md").read_text(encoding="utf-8")
        assert "判定矩阵" in md and "NON_REPRODUCIBLE 不据此关闭 P1" in md

    def test_throttle_pacing_observed(self, tmp_path):
        """全实验限流节奏: 发送 N 次 → 等待次数 N-1、每次 2s（QPS=0.5）."""
        report, _, clock = self._run(lambda msgs: "ok", data_dir=tmp_path)
        n_sent = report.budget_used
        assert len(clock.sleeps) == n_sent - 1
        assert all(s == 2.0 for s in clock.sleeps)


# ── 7.1 支撑: 轨道子集 + 工单例外条款（spec 5.2.1-5b，tasks 8.2 收敛分支）──


class TestTrackSelection(TestRunOracle):
    def test_single_track_live_no_verdict(self, tmp_path):
        """单轨 live 运行不出 Verdict（R3 禁止项——禁止仅骨架轨下结论）."""
        for track in ("skeleton", "bisect"):
            report, client, _ = self._run(
                lambda msgs: "ok",
                track=track,
                data_dir=tmp_path,
            )
            assert report.verdict == "", f"单轨 {track} 不得产出 Verdict"
            assert report.confidence == "none-track-restricted"
            if track == "skeleton":
                assert all(v["track"] == "skeleton" for v in report.variants)
            else:
                assert all(v["track"] == "bisect" for v in report.variants)

    def test_ticket_evidence_compound(self, tmp_path):
        """工单证据 + 保真轨复现 → COMPOUND_TRIGGER（等效两轨，spec 5.2.1-5b）."""
        report, client, _ = self._run(
            lambda msgs: (
                "1210"
                if any(
                    isinstance(m.get("content"), str) and m["content"].startswith("inj-")
                    for m in msgs
                )
                else "ok"
            ),
            track="both",
            ticket_evidence={"ref": "T-1", "note": "官方确认连续 user 条数上限"},
            data_dir=tmp_path,
        )
        assert report.verdict == "COMPOUND_TRIGGER"
        assert any(v["outcome"] == "skipped_ticket" for v in report.variants)
        # 骨架轨未实跑（skipped_ticket 零预算）
        assert not any(
            v["track"] == "skeleton" and v["outcome"] == "err1210" for v in report.variants
        )

    def test_ticket_evidence_structure_only(self, tmp_path):
        """工单证据 + 保真轨不复现 → STRUCTURE_TRIGGER（工单为结构直接证据）."""
        report, _, _ = self._run(
            lambda msgs: "ok",
            track="both",
            ticket_evidence={"ref": "T-1", "note": "官方确认结构性限制"},
            data_dir=tmp_path,
        )
        assert report.verdict == "STRUCTURE_TRIGGER"
