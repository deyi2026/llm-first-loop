"""R8.24 D'-3.1: cache BLOCK 行为分类对照断言（D-G4 / D-G5——用户指定验证门）.

双态对照:
- flag=on（默认）: 性能类 BLOCK 保留（行为与现状逐字节一致——既有 test_cache_guard
  用例零回归由其自身文件守护，此处只断言 on 态关键字段）。
- flag=enforce: 性能类 BLOCK count=0（25→0 方向，D-G4）——submit_ratio 场景降级
  WARN + would_block 观测在场。
- privacy/safety 硬阻断在【双态】均保留（D-G5 一票否决项——本断言不绿全组不得提交）。

既有 test_cache_guard.py 为 M 状态红线——本文件独立，fixture 复制脱敏（不引用不改写）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
import llm_loop.cache_guard.guard as guard_mod
from llm_loop.cache_guard.guard import validate_request


def _sys(text: str) -> list[dict]:
    return [{"role": "system", "content": text}, {"role": "user", "content": "hi"}]


def _over_ratio_msgs() -> tuple[list[dict], str]:
    """构造 ratio>95% 场景（复制脱敏自 test_cache_guard.test_submit_ratio_block 口径）."""
    msgs = [
        {"role": "system", "content": "s" * 1000},
        {"role": "user", "content": "u" * 5000},
    ]
    return msgs, "s" * 1000


class TestDG4PerfBlockReclassified:
    """D-G4: enforce 态性能类 BLOCK count=0（对照基线 25 次 submit_ratio BLOCK）."""

    def test_on_state_keeps_block(self, tmp_path, monkeypatch):
        """flag=on: 非 breaker 期 >95% 维持现状 BLOCK（逐字节一致回滚锚点）."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "on")
        msgs, sys_text = _over_ratio_msgs()
        d = validate_request(
            system_text=sys_text,
            messages=msgs,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "submit_ratio"

    def test_enforce_state_perf_block_count_zero(self, tmp_path, monkeypatch):
        """D-G4 主断言: enforce 态同一场景 BLOCK → WARN（性能 BLOCK count=0）."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        msgs, sys_text = _over_ratio_msgs()
        d = validate_request(
            system_text=sys_text,
            messages=msgs,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "submit_ratio_perf"
        assert d.audit.get("would_block") is True

    def test_enforce_state_no_advisory_wording(self, tmp_path, monkeypatch):
        """enforce 态 WARN 文案为陈述式事实——决策指令文案（建议先压缩/换会话）退出."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        msgs, sys_text = _over_ratio_msgs()
        d = validate_request(
            system_text=sys_text,
            messages=msgs,
            meta={"history_budget": 6000, "breaker_active": False},
            audit_file=tmp_path / "g.jsonl",
        )
        for advisory in ("建议", "请先", "推荐"):
            assert advisory not in d.detail

    def test_enforce_state_unifies_breaker_branches(self, tmp_path, monkeypatch):
        """enforce 态 breaker_active 三分支（None/True/False）收编统一 submit_ratio_perf."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        msgs, sys_text = _over_ratio_msgs()
        for ba in (None, True, False):
            d = validate_request(
                system_text=sys_text,
                messages=msgs,
                meta={"history_budget": 6000, "breaker_active": ba},
                audit_file=tmp_path / "g.jsonl",
            )
            assert d.verdict == "WARN", f"breaker_active={ba}"
            assert d.rule == "submit_ratio_perf", f"breaker_active={ba}"
            assert d.audit.get("would_block") is True

    def test_enforce_state_would_block_logged(self, tmp_path, monkeypatch, caplog):
        """shadow/enforce 观测: event=guard.would_block 日志事件在场（对照清单数据源）."""
        import logging

        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        msgs, sys_text = _over_ratio_msgs()
        with caplog.at_level(logging.INFO, logger="llm_loop.cache_guard.guard"):
            validate_request(
                system_text=sys_text,
                messages=msgs,
                meta={"history_budget": 6000, "breaker_active": False},
                audit_file=tmp_path / "g.jsonl",
            )
        joined = caplog.text
        assert "event=guard.would_block" in joined
        assert "rule=submit_ratio_perf" in joined

    def test_enforce_state_warn_band_unchanged(self, tmp_path, monkeypatch):
        """85%~95% WARN 带（性能观察带）双态语义不变——不属 BLOCK 改造面."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        msgs = [
            {"role": "system", "content": "s" * 1000},
            {"role": "user", "content": "u" * 4200},
        ]
        d = validate_request(
            system_text="s" * 1000,
            messages=msgs,
            meta={"history_budget": 6000},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "WARN"
        assert d.rule == "submit_ratio"


class TestDG5PrivacyBlockRetained:
    """D-G5: privacy 硬阻断双态保留（一票否决项——15 次口径照常）."""

    def test_privacy_block_on_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "on")
        d = validate_request(
            system_text="key sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890",
            messages=_sys("k"),
            meta={},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "privacy_leak"

    def test_privacy_block_enforce_state(self, tmp_path, monkeypatch):
        """D-G5 主断言: enforce 态（性能退出）privacy BLOCK 原样保留——开关不作用于硬清单."""
        monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", "enforce")
        d = validate_request(
            system_text="key sk-ABCDEFGHIJKLMNOPQRSTUVWX1234567890",
            messages=_sys("k"),
            meta={},
            audit_file=tmp_path / "g.jsonl",
        )
        assert d.verdict == "BLOCK"
        assert d.rule == "privacy_leak"

    def test_privacy_env_leak_block_both_states(self, tmp_path, monkeypatch):
        """敏感 env 值泄漏（规则 E 第二路径）双态 BLOCK."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-secret-value-1234567890")
        for mode in ("on", "enforce"):
            monkeypatch.setattr(guard_mod, "_PERF_BLOCK_MODE", mode)
            d = validate_request(
                system_text="contains sk-test-secret-value-1234567890 inside",
                messages=_sys("k"),
                meta={},
                audit_file=tmp_path / "g.jsonl",
            )
            assert d.verdict == "BLOCK", f"mode={mode}"
            assert d.rule == "privacy_leak", f"mode={mode}"

    def test_perf_flag_does_not_touch_privacy_code(self):
        """静态断言: 硬 BLOCK 清单注释在场 + _check_privacy 内无 _PERF_BLOCK_MODE 消费."""
        import inspect

        src = inspect.getsource(guard_mod._check_privacy)
        assert "_PERF_BLOCK_MODE" not in src
        doc = inspect.getdoc(guard_mod._check_privacy) or ""
        assert "D-D3 硬 BLOCK 清单成员" in doc or "D-D3" in src


class TestPerfBlockModeSourceComments:
    """分类改造的声明面静态断言（回执可追溯）."""

    def test_hit_rate_block_has_no_block_verdict(self):
        """规则 G（hit rate）全路径 WARN-only——性能 BLOCK 不存在于规则 G."""
        import inspect

        src = inspect.getsource(guard_mod.PromptGuard._check_hit_rate)
        assert 'verdict="BLOCK"' not in src

    def test_perf_mode_default_is_on(self):
        """默认 on=现状（enforce 切换留待 D'-1.3 观测达标——回执声明）.

        注: 不用 importlib.reload 验证——reload 会重定义 guard 模块内全部类
        对象（CacheGuardBlockedError 等），使进程内先期绑定的类引用
        （pytest.raises / except 匹配）失效，污染同进程后续测试。
        """
        import inspect

        src = inspect.getsource(guard_mod)
        assert 'os.environ.get("CACHE_GUARD_PERF_BLOCK", "on")' in src
