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

    def test_fail_open(self, tmp_path, monkeypatch):
        """校验异常 → ALLOW（fail-open——不阻断主流程）."""
        import llm_loop.cache_guard.guard as mod

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "_check_system_stability", boom)
        d = validate_request(system_text="a", messages=_sys("a"), meta={}, audit_file=tmp_path / "g.jsonl")
        assert d.verdict == "ALLOW"
