"""err1210 blind retry（原样重发）测试（GOAL-20260829-a9a6c0f0）.

覆盖:
- blind 成功: 原样重发（messages 与首调逐字节一致）、零剥离、恢复合流
- blind 仍 1210: 回退既有 strip/aggregate 路径（保底语义保留，strip 剥离版核对）
- blind 关闭(ERR1210_BLIND_RETRY=0): 行为回退 9088d4e（剥离重试，无 blind 调用）
- blind 非 1210 二次异常（网络）: 回退 strip 路径，原 1210 语义不被掩盖

零真实网络（_FakeLLMClient 可编程异常队列，复用 test_err1210_recovery helpers）。
"""

from __future__ import annotations

from llm_loop.llm.errors import LLMHTTPError

from .test_err1210_recovery import _arm_compact_first, _e1210, _mk, _resp

_NET_ERR = LLMHTTPError("503 upstream unavailable", status_code=503, body="")


class TestBlindRetry:
    def test_blind_success_no_strip(self, tmp_path, monkeypatch):
        """首调 1210 → 原样重发成功: calls[1].messages == calls[0].messages（零剥离）."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "长任务继续")
        assert "恢复后的正常回答" in result.final_answer
        assert result.truncated is False
        assert len(fake.calls) == 2  # 原始失败 + blind 重发（恰好 1 次额外）
        orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
        assert retry == orig  # 核心语义: 原样重发，不剥离/不聚合
        # blind 成功 → 耗尽标记已写（本 run 不再二次降级）
        assert engine._err1210_attempted.get(sid) == engine._err1210_run_seq

    def test_blind_1210_fallback_strip(self, tmp_path, monkeypatch):
        """blind 仍 1210 → 回退剥离路径: 原始+blind+strip 重试 = 3 次调用、strip 剥离版核对."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "任务")
        assert "恢复后的正常回答" in result.final_answer
        assert len(fake.calls) == 3
        orig = fake.calls[0]["messages"]
        blind = fake.calls[1]["messages"]
        stripped = fake.calls[2]["messages"]
        assert blind == orig  # blind 原样
        n_inj = len(engine._last_build_injections)
        assert n_inj >= 1
        assert stripped == orig[: len(orig) - n_inj]  # strip 剥离版（回退路径生效）
        # strip 成功 → defer 回存: gate_note 复位可重注入（与 T5.1 语义一致）
        assert engine._cache_monitor.take_gate_note(sid) is True

    def test_blind_env_off_legacy_behavior(self, tmp_path, monkeypatch):
        """ERR1210_BLIND_RETRY=0 → 回退 9088d4e 行为（剥离重试，无 blind 调用）."""
        monkeypatch.setenv("ERR1210_BLIND_RETRY", "0")
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        engine._cache_monitor._get_bucket(sid).gate_note_pending = True
        result = engine.run(sid, "任务")
        assert "恢复后的正常回答" in result.final_answer
        assert len(fake.calls) == 2
        orig, retry = fake.calls[0]["messages"], fake.calls[1]["messages"]
        n_inj = len(engine._last_build_injections)
        assert retry == orig[: len(orig) - n_inj]  # 剥离版（旧行为零变化）

    def test_blind_net_err_fallback_strip(self, tmp_path, monkeypatch):
        """blind 遇非 1210 异常（网络 503）→ 回退 strip 路径恢复，原 1210 语义不被掩盖."""
        engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210(), _NET_ERR, _resp()])
        sid = engine.session.create()
        _arm_compact_first(engine, sid)
        result = engine.run(sid, "任务")
        assert "恢复后的正常回答" in result.final_answer
        assert len(fake.calls) == 3  # 原始失败 + blind(网络异常) + strip 重试
