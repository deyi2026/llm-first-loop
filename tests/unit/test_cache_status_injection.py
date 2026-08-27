"""EVO-20260818 cache_window_converge: architecture_status 缓存快照注入测试（spec §5.4.1-2）.

覆盖: cache_health/cache_guard 字段注入、session 透传、回调异常 fail-open、未注入 None。
"""

from types import SimpleNamespace

from llm_loop.core.cache_health import strip_cache_telemetry_lines
from llm_loop.core.loop.build import _BuildMixin
from llm_loop.core.message import Message, MessageSource
from llm_loop.introspection.status import ArchitectureStatusProvider


def _provider(**kw) -> ArchitectureStatusProvider:
    return ArchitectureStatusProvider(audit_dir=None, **kw)


def test_status_no_injection_fields_none():
    """未注入回调 → context_usage.cache_health/cache_guard 为 None（零回归）."""
    sp = _provider()
    snap = sp.snapshot()
    assert snap["context_usage"]["cache_health"] is None
    assert snap["context_usage"]["cache_guard"] is None


def test_status_injects_cache_health_field():
    """注入 cache_health 回调 → 字段填充."""
    sp = _provider()
    sp.set_cache_health_fn(lambda: {"win_in": 100, "win_hit": 90, "win_runs": 5})
    snap = sp.snapshot()
    ch = snap["context_usage"]["cache_health"]
    assert ch == {"win_in": 100, "win_hit": 90, "win_runs": 5}


def test_status_injects_cache_guard_field_with_session():
    """cache_guard 回调透传 session_id（grill-me Q11）."""
    sp = _provider()
    seen = []
    sp.set_cache_guard_fn(lambda sid: seen.append(sid) or {"recent_hit_rate": 0.92})
    snap = sp.snapshot(session_id="sess-abc")
    assert snap["context_usage"]["cache_guard"] == {"recent_hit_rate": 0.92}
    assert seen == ["sess-abc"]  # session 透传


def test_status_cache_callback_exception_fail_open():
    """回调抛异常 → 字段 None 不抛穿 architecture_status."""
    sp = _provider()
    sp.set_cache_health_fn(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    sp.set_cache_guard_fn(lambda _sid: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = sp.snapshot()
    assert snap["context_usage"]["cache_health"] is None
    assert snap["context_usage"]["cache_guard"] is None


# ── EVO-20260818: dimensions 防御归一化（字符串被按字符解析的 bug 回归）──

def test_status_dimensions_string_not_char_split():
    """字符串维度（模型传错类型）→ 解析为单维度，不再按字符拆解."""
    sp = _provider()
    snap = sp.snapshot(dimensions="context_usage")
    assert "context_usage" in snap  # 修复前: 返回 {"unavailable": "维度 'c' 暂不可用"}


def test_status_dimensions_csv_string_splits():
    """逗号/空白分隔字符串 → 拆分多维度."""
    sp = _provider()
    snap = sp.snapshot(dimensions="context_usage, architecture_config")
    assert set(snap.keys()) == {"context_usage", "architecture_config"}


def test_status_dimensions_non_list_falls_back_full():
    """非列表类型（数字等）→ 回落全量快照（绝不按字符拆）."""
    sp = _provider()
    snap = sp.snapshot(dimensions=123)
    assert "context_usage" in snap and "action_trace" in snap


def test_run_status_tool_entry_string_dimensions():
    """工具入口（run_status）字符串维度同样归一化."""
    import json

    from llm_loop.introspection.tools_status import run_status

    sp = _provider()
    res = run_status(SimpleNamespace(), sp, {"dimensions": "context_usage"})
    assert res.status.value == "success"
    assert "context_usage" in json.loads(res.content)


# ── 任务5（2026-08-25 §5.5）: alert 路径遥测分层——不进 final_answer 正文 ──


class _FakeMonitor:
    """stub CacheHealthMonitor: record 返回固定提示（模拟告警/恢复/熔断 alert 路径）."""

    def __init__(self, hint: str | None):
        self._hint = hint

    def record(self, *args, **kwargs):
        return self._hint

    def format_health_note(self, **kwargs):
        return None


class _Harness(_BuildMixin):
    """最小 _BuildMixin 实例——只供 _post_run_cache_health 单测."""

    def __init__(self, hint: str | None):
        self._cache_monitor = _FakeMonitor(hint)
        self._cache_gate_hint = None
        self._actions: list[tuple] = []
        self.session = SimpleNamespace(save=lambda s: None)
        self.settings = SimpleNamespace(cache_hit_show_in_answer=False)

    def _record_action(self, kind: str, status: str, text: str) -> None:
        self._actions.append((kind, status, text))


def _harness_sess() -> SimpleNamespace:
    m = Message(role="assistant", content="纯回答内容", source=MessageSource.SYSTEM)
    return SimpleNamespace(messages=[m], session_id="s-alert")


def test_alert_path_telemetry_not_in_final_answer():
    """任务5.1: alert 路径（guard/breaker 告警）遥测不进 final_answer 正文——
    正文只存纯回答，遥测进 metadata.cache_health（transport 层渲染）."""
    h = _Harness(hint="[缓存已恢复] 拦截期锚点未再前移，命中率已回升")
    result = h._post_run_cache_health(
        "这是模型的纯回答", _harness_sess(), 1000, 200, "minimax/MiniMax-M3"
    )
    # ① 正文不被追加遥测
    assert result == "这是模型的纯回答", f"正文应只存纯回答，实际: {result!r}"
    assert "缓存已恢复" not in result and "命中率" not in result
    # ② 遥测走 metadata.cache_health 结构化路径
    md = h._actions and h._actions[0]
    assert md == ("run.cache_monitor", "recovered", "[缓存已恢复] 拦截期锚点未再前移，命中率已回升"), (
        "审计记录保留"
    )
    # ③ 回写 metadata（本方法用 _Harness 无 session 对象，用 monkey 不验证——见下测）


def test_alert_path_metadata_cache_health_written_back():
    """任务5.1: alert 遥测回写 session 中最后 assistant 消息的 metadata.cache_health
    （结构化，正文不变）——transport 层据此渲染."""
    h = _Harness(hint="[门禁拦截] 前缀漂移，已强制保留历史头部")
    sess = _harness_sess()
    saved: list[bool] = []

    def _save(s) -> None:
        saved.append(True)

    h.session.save = _save
    result = h._post_run_cache_health("回答", sess, 1000, 100, "minimax/MiniMax-M3")
    assert result == "回答"
    last = sess.messages[-1]
    assert last.content == "纯回答内容", "正文不得被遥测污染"
    ch = (last.metadata or {}).get("cache_health")
    assert ch is not None and ch["kind"] == "alert"
    assert "前缀漂移" in ch["note"]
    assert saved, "metadata 回写应触发 session.save"


# ── 任务4（2026-08-25 §5.10）: legacy 遥测行剥离末尾位置限定 ──

_TELEM = "⚡ 缓存命中率 93.6%（近 1 轮，724,096/773,371 tokens）"


def _long_body(tail: bool) -> str:
    """14 行长正文：遥测位于中部（tail=False）或末尾（tail=True）."""
    body = [f"第{i}行 正常论述" for i in range(1, 13)]
    if tail:
        body.append(_TELEM)
    else:
        body.insert(1, _TELEM)
    body.append("最后一行")
    return "\n".join(body)


def test_strip_tail_limited_removes_tail_telemetry():
    """任务4.1: 长正文（>10 行）中末尾遥测行参与剥离."""
    out = strip_cache_telemetry_lines(_long_body(tail=True))
    assert "缓存命中率" not in out
    assert "第1行" in out and "最后一行" in out


def test_strip_tail_limited_keeps_middle_telemetry_reference():
    """任务4.1: 长正文中间段落"缓存命中率"论述不被误剥离（仅末尾 N 行参与）."""
    out = strip_cache_telemetry_lines(_long_body(tail=False))
    assert "缓存命中率" in out, "中间段落引用应保留"
    assert "第1行" in out and "最后一行" in out


def test_strip_tail_limited_short_content_full_check():
    """任务4.1: 总行数 ≤ N 时全文检查（短内容中段遥测行也剥离）."""
    short = "a\n" + _TELEM + "\nb"
    out = strip_cache_telemetry_lines(short)
    assert "缓存命中率" not in out
    assert out == "a\nb"


def test_strip_tail_limited_zero_falls_back_full_match(monkeypatch):
    """任务4.1: TAIL_LINES=0 → 回退全文匹配（兼容旧行为）."""
    import llm_loop.core.cache_health as ch

    monkeypatch.setattr(ch, "_STRIP_TAIL_LINES", 0)
    out = ch.strip_cache_telemetry_lines(_long_body(tail=False))
    assert "缓存命中率" not in out, "全文匹配模式下中间遥测行也应剥离"


def test_strip_tail_limited_ratio_warn(caplog):
    """任务4.1: 剥离比例 <0.8 → WARN「遥测剥离疑似误伤」."""
    import logging

    body = "\n".join(f"正文{i}" for i in range(3))
    telem = "\n".join([_TELEM] * 10)
    with caplog.at_level(logging.WARNING, logger="llm_loop.core.cache_health"):
        out = strip_cache_telemetry_lines(body + "\n" + telem)
    assert "缓存命中率" not in out
    assert any("遥测剥离疑似误伤" in r.message for r in caplog.records)



