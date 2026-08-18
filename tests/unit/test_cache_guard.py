"""cache_guard 规则引擎测试（MCP 出入口核心）. """

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from llm_loop.cache_guard.guard import PromptGuard, validate_request


def _sys(text: str) -> list[dict]:
    return [{"role": "system", "content": text}, {"role": "user", "content": "hi"}]


class TestValidateRequest:
    def test_allow_normal(self, tmp_path):
        d = validate_request(
            system_text="sys", messages=_sys("sys"),
            meta={}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "ALLOW"

    def test_system_stability_warn(self, tmp_path):
        d = validate_request(
            system_text="s" * 200, messages=_sys("s" * 200),
            baseline="s" * 100, meta={}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "system_stability"

    def test_injection_discipline_warn(self, tmp_path):
        msgs = [{"role": "system", "content": "a"}, {"role": "user", "content": "b"},
                {"role": "system", "content": "mid"}, {"role": "user", "content": "c"}]
        d = validate_request(system_text="a", messages=msgs, meta={}, audit_file=tmp_path / "g.jsonl")
        assert d.verdict == "WARN"
        assert d.rule == "injection_discipline"

    def test_tool_result_size_warn(self, tmp_path):
        msgs = [{"role": "system", "content": "a"}, {"role": "tool", "content": "x" * 300_000}]
        d = validate_request(system_text="a", messages=msgs, meta={}, audit_file=tmp_path / "g.jsonl")
        assert d.verdict == "WARN"
        assert d.rule == "tool_result_size"

    def test_compress_storm_warn(self, tmp_path):
        d = validate_request(
            system_text="a", messages=_sys("a"),
            meta={"compress_count_this_run": 20}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "compress_storm"

    def test_privacy_block(self, tmp_path):
        d = validate_request(
            system_text="key sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890", messages=_sys("k"),
            meta={}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "privacy_leak"

    def test_audit_written(self, tmp_path):
        f = tmp_path / "g.jsonl"
        validate_request(system_text="a", messages=_sys("a"), meta={"session_id": "s1"}, audit_file=f)
        lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
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
        d3 = g.check(session_id="s", system_text="sys-a" + "x" * 100, messages=_sys("sys-a" + "x" * 100))
        assert d3.verdict == "WARN"
        assert d3.rule == "system_stability"

    def test_submit_ratio_block(self, tmp_path):
        """提交占比 >95% 预算 → BLOCK（不应出去的请求）. """
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 5000}]
        d = validate_request(
            system_text="s" * 1000, messages=msgs,
            meta={"history_budget": 6000}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "submit_ratio"

    def test_submit_ratio_warn(self, tmp_path):
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 4200}]
        d = validate_request(
            system_text="s" * 1000, messages=msgs,
            meta={"history_budget": 6000}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "submit_ratio"

    def test_submit_ratio_allow(self, tmp_path):
        msgs = [{"role": "system", "content": "s" * 1000}, {"role": "user", "content": "u" * 2000}]
        d = validate_request(
            system_text="s" * 1000, messages=msgs,
            meta={"history_budget": 6000}, audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "ALLOW"

    def test_low_hit_rate_block(self, tmp_path):
        """规则 G: 会话近期命中率低 → BLOCK（闭环——不应出去的）. """
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        # 灌入低命中历史（3 次——命中率 10%）
        for _ in range(3):
            g.record_result("s-low", 10000, 1000)
        d = g.check(session_id="s-low", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "BLOCK"
        assert d.rule == "low_hit_rate"

    def test_low_hit_rate_warn(self, tmp_path):
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-warn", 10000, 4000)  # 40% —— WARN 区间
        d = g.check(session_id="s-warn", system_text="sys", messages=_sys("sys"))
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
        """冷启动（前缀构建——in 递增）低命中 → 不拦（仅 WARN）. """
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        # 模拟冷启动：in 递增（10K→50K→100K——前缀在构建），命中 0
        for i, n in enumerate((10000, 50000, 100000)):
            g.record_result("s-cold", n, 0)
        d = g.check(session_id="s-cold", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"  # 不拦（冷启动预期低）

    def test_stable_prefix_low_hit_blocked(self, tmp_path):
        """前缀稳定（in 相近）却低命中 → BLOCK（真异常）. """
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-bad", 100000, 5000)  # in 恒定 + 低命中
        d = g.check(session_id="s-bad", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "BLOCK"
        assert d.rule == "low_hit_rate"

    def test_block_escape(self, tmp_path):
        """连续 BLOCK 达上限 → 自动降级 WARN（防死锁）. """
        g = PromptGuard(audit_file=tmp_path / "g.jsonl")
        for _ in range(3):
            g.record_result("s-esc", 100000, 5000)  # 稳定前缀低命中
        for _ in range(4):  # 连续 4 次（>3 逃生上限）
            d = g.check(session_id="s-esc", system_text="sys", messages=_sys("sys"))
        assert d.verdict == "WARN"  # 逃生降级
        assert d.rule == "low_hit_rate_escape"

    def test_reset_session(self, tmp_path):
        """reset_session（模型切换）清窗口——恢复不判（冷启动）. """
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
        d = validate_request(system_text="a", messages=_sys("a"), meta={}, audit_file=tmp_path / "g.jsonl")
        assert d.verdict == "ALLOW"
