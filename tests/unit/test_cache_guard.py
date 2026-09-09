"""cache_guard 规则引擎测试（MCP 出入口核心）."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from llm_loop.cache_guard.guard import PromptGuard, validate_request


def _sys(text: str) -> list[dict]:
    return [{"role": "system", "content": text}, {"role": "user", "content": "hi"}]


class TestValidateRequest:
    def test_allow_normal(self, tmp_path):
        d = validate_request(
            system_text="sys",
            messages=_sys("sys"),
            meta={},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "ALLOW"

    def test_system_stability_warn(self, tmp_path):
        d = validate_request(
            system_text="s" * 200,
            messages=_sys("s" * 200),
            baseline="s" * 100,
            meta={},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "system_stability"

    def test_injection_discipline_warn(self, tmp_path):
        msgs = [
            {"role": "system", "content": "a"},
            {"role": "user", "content": "b"},
            {"role": "system", "content": "mid"},
            {"role": "user", "content": "c"},
        ]
        d = validate_request(
            system_text="a", messages=msgs, meta={}, audit_file=tmp_path / "g.jsonl"
        )
        assert d.verdict == "WARN"
        assert d.rule == "injection_discipline"

    def test_tool_result_size_warn(self, tmp_path):
        msgs = [{"role": "system", "content": "a"}, {"role": "tool", "content": "x" * 300_000}]
        d = validate_request(
            system_text="a", messages=msgs, meta={}, audit_file=tmp_path / "g.jsonl"
        )
        assert d.verdict == "WARN"
        assert d.rule == "tool_result_size"

    def test_compress_storm_warn(self, tmp_path):
        d = validate_request(
            system_text="a",
            messages=_sys("a"),
            meta={"compress_count_this_run": 20},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "compress_storm"

    def test_privacy_block(self, tmp_path):
        d = validate_request(
            system_text="key sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890",
            messages=_sys("k"),
            meta={},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "privacy_leak"

    def test_audit_written(self, tmp_path):
        f = tmp_path / "g.jsonl"
        validate_request(
            system_text="a", messages=_sys("a"), meta={"session_id": "s1"}, audit_file=f
        )
        lines = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        assert len(lines) == 1
        assert lines[0]["session_id"] == "s1"
        assert lines[0]["verdict"] == "ALLOW"

    def test_guard_baseline(self, tmp_path):
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        d1 = g.check(session_id="s", system_text="sys-a", messages=_sys("sys-a"))
        assert d1.verdict == "ALLOW"
        # 稳定 → ALLOW 且基线更新
        d2 = g.check(session_id="s", system_text="sys-a", messages=_sys("sys-a"))
        assert d2.verdict == "ALLOW"
        # 变化 → WARN
        d3 = g.check(
            session_id="s", system_text="sys-a" + "x" * 100, messages=_sys("sys-a" + "x" * 100)
        )
        assert d3.verdict == "WARN"
        assert d3.rule == "system_stability"

    def test_submit_ratio_block(self, tmp_path, monkeypatch):
        """提交占比 >95% 预算 → BLOCK（不应出去的请求）——显式 breaker_active=False
        （非冻结期正常传递）维持拦截语义（on 态机制，R9-P0-01 批 3/3 钉住前提——
        模块级常量故用 setattr 而非 setenv）."""
        import llm_loop.cache_guard.guard as guard_mod

        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "on")
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 5000}]
        d = validate_request(
            system_text="s" * 1000,
            messages=msgs,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "submit_ratio"

    def test_submit_ratio_warn(self, tmp_path):
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 4200}]
        d = validate_request(
            system_text="s" * 1000,
            messages=msgs,
            meta={"history_budget": 6000},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "submit_ratio"

    def test_submit_ratio_allow(self, tmp_path):
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 2000}]
        d = validate_request(
            system_text="s" * 1000,
            messages=msgs,
            meta={"history_budget": 6000},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "ALLOW"

    def test_low_hit_rate_does_not_block_without_structural_drift(self, tmp_path):
        """低命中 + tokens_in 相近不能证明前缀漂移；provider 冷缓存/分片也会出现同形态。"""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-low", 10000, 1000)
        d = g.check(session_id="s-low", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate_provider"

    def test_low_hit_rate_warn(self, tmp_path):
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-warn", 10000, 4000)  # 40% —— WARN 区间
        d = g.check(session_id="s-warn", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate"

    def test_mid_hit_rate_warn(self, tmp_path):
        """2026-08-18 用户反馈（'78% 也低'）: 大型稳定会话 80% 也应 WARN（低于预期提示）.
        任务2（§5.2）适配: tokens_in=300K（≥200K → 自适应阈值 0.85）→ 80% 仍 WARN."""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-mid", 300000, 240000)  # 80% —— 大会话 <85% WARN 区间
        d = g.check(session_id="s-mid", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate"

    def test_high_hit_rate_allow(self, tmp_path):
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-ok", 10000, 9900)  # 99% —— 放行
        d = g.check(session_id="s-ok", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "ALLOW"

    def test_insufficient_sample(self, tmp_path):
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        g.record_result("s-1", 10000, 0)  # 仅 1 次——样本不足不判
        d = g.check(session_id="s-1", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "ALLOW"

    def test_cold_start_not_blocked(self, tmp_path):
        """冷启动（前缀构建——in 递增）低命中 → 不拦（仅 WARN）."""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        # 模拟冷启动：in 递增（10K→50K→100K——前缀在构建），命中 0
        for n in (10000, 50000, 100000):
            g.record_result("s-cold", n, 0)
        d = g.check(session_id="s-cold", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"  # 不拦（冷启动预期低）

    def test_similar_tokens_in_is_not_prefix_stability_proof(self, tmp_path):
        """tokens_in 恒定只证明尺寸相近，不证明字节前缀稳定；不得据此 BLOCK。"""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-bad", 100000, 5000)
        d = g.check(session_id="s-bad", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate_provider"

    def test_repeated_provider_low_hit_remains_warn(self, tmp_path):
        """连续 provider miss 不应制造 BLOCK/escape 循环；必须持续允许请求预热缓存。"""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-esc", 100000, 5000)
        for _ in range(4):
            d = g.check(session_id="s-esc", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate_provider"

    def test_reset_session(self, tmp_path):
        """reset_session（模型切换）清窗口——恢复不判（冷启动）."""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-r", 100000, 5000)
        g.reset_session("s-r")
        d = g.check(session_id="s-r", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "ALLOW"  # 窗口清空——样本不足——放行

    def test_fail_open(self, tmp_path, monkeypatch):
        """校验异常 → ALLOW（fail-open——不阻断主流程）."""
        import llm_loop.cache_guard.guard as mod

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "_check_system_stability", boom)
        d = validate_request(
            system_text="a", messages=_sys("a"), meta={}, audit_file=tmp_path / "g.jsonl"
        )
        assert d.verdict == "ALLOW"

    def test_ttl_expiry_warns_not_blocks(self, tmp_path):
        """EVO-20260818: 请求间隔 > provider 缓存 TTL（MiniMax ~130s 实测）→ 低命中
        属缓存过期——WARN 不 BLOCK（防误拦 TTL miss 的正常用户）."""
        import time

        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        now = time.time()
        # 直接注入窗口（模拟间隔 200s > minimax TTL 90s）: 前缀稳定（in 相近）+ 低命中
        g._hit_win["s-ttl"] = [
            (100000, 5000, now - 300),
            (100000, 5000, now - 200),
            (100000, 5000, now),  # 末次间隔 200s > minimax TTL 90s
        ]
        d = g.check(
            session_id="s-ttl",
            system_text="sys",
            messages=_sys("sys"),
            provider="minimax",
        )
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate_ttl"

    def test_ttl_within_window_still_warns_without_drift_evidence(self, tmp_path):
        """短间隔连续低命中仍可能是 provider 冷缓存/分片；无结构漂移证据不得 BLOCK。"""
        import time

        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        now = time.time()
        g._hit_win["s-hot"] = [
            (100000, 5000, now - 20),
            (100000, 5000, now - 10),
            (100000, 5000, now),  # 末次间隔 10s < TTL 90s
        ]
        d = g.check(
            session_id="s-hot",
            system_text="sys",
            messages=_sys("sys"),
            provider="minimax",
        )
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate_provider"

    # ── 任务2（§5.2）: WARN 阈值按会话规模自适应 ──

    def test_adaptive_warn_threshold_tiers(self):
        """2.1: _adaptive_warn_threshold 四段分段查表边界（纯函数）."""
        import llm_loop.cache_guard.guard as mod

        cases = [
            (0, 0.65),  # <30K → 0.65
            (29999, 0.65),  # 边界下
            (30000, 0.75),  # ≥30K → 0.75
            (79999, 0.75),
            (80000, 0.80),  # ≥80K → 0.80
            (199999, 0.80),
            (200000, 0.85),  # ≥200K → 默认 _HIT_RATE_WARN
            (10_000_000, 0.85),  # tier 耗尽
        ]
        for tokens_in, expected in cases:
            assert mod._adaptive_warn_threshold(tokens_in) == expected, (
                f"tokens_in={tokens_in} 应返回 {expected}"
            )

    def test_small_session_80pct_allowed(self, tmp_path):
        """2.2: 小型会话（10K tokens → 自适应阈值 0.65）80% 命中 → ALLOW——
        修复前固定 0.85 会误 WARN 刷屏（'WARN 阈值不敏感'问题）."""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-small", 10000, 8000)  # 80% —— 小型会话已达标
        d = g.check(session_id="s-small", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "ALLOW"

    def test_large_session_80pct_warns(self, tmp_path):
        """2.2: 大型会话（300K tokens → 自适应阈值 0.85）80% 命中 → WARN
        （大型稳定会话预期更高命中——仍提示）."""
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-large", 300000, 240000)  # 80%
        d = g.check(session_id="s-large", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert "自适应阈值" in d.detail and "tokens_in≈300000" in d.detail

    def test_adaptive_disabled_falls_back_fixed(self, tmp_path, monkeypatch):
        """2.2: 禁用自适应（CACHE_GUARD_HIT_WARN_ADAPTIVE=0）→ 回退固定 0.85——
        小型会话 80% 恢复 WARN（零回归路径）."""
        import llm_loop.cache_guard.guard as mod

        monkeypatch.setattr(mod, "_ADAPTIVE_ENABLED", False)
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-fixed", 10000, 8000)  # 80% —— 固定阈值 0.85 → WARN
        d = g.check(session_id="s-fixed", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"
        assert d.rule == "low_hit_rate"
