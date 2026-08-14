"""EVO-20260814: 统一事件流视图（对齐 Harness Trajectory）.

把分散的 append-only 审计流按时间序合并为单一轨迹视图——
可观测/回溯应看到"一条流"而非各文件分别查。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from llm_loop.introspection.registry_host import RegistryHost
from llm_loop.introspection.registry_introspection import execute as ri_execute
from llm_loop.introspection.search import RecordSearcher


def _seed(dirpath: Path) -> None:
    with (dirpath / "action_trace.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-08-14T10:00:00", "phase": "run",
                            "action_type": "tool.execute_command", "detail": "ls"}) + "\n")
        f.write(json.dumps({"ts": "2026-08-14T10:00:01", "phase": "run",
                            "action_type": "tool.edit_file", "detail": "修改 registry.py"}) + "\n")
    with (dirpath / "exception_log.jsonl").open("w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": "2026-08-14T10:00:02", "phase": "run",
                            "error_type": "TimeoutError", "detail": "工具超时"}) + "\n")


def _searcher() -> RecordSearcher:
    tmp = Path(tempfile.mkdtemp())
    _seed(tmp)
    return RecordSearcher(audit_dir=tmp)


class _Adapter:
    """可调用 + 方法双接口（同 factory 注入的适配器）. """

    def __init__(self, s: RecordSearcher) -> None:
        self._s = s

    def __call__(self, **kw):  # noqa: ANN002
        return self._s.search(**kw)

    def event_stream(self, **kw):  # noqa: ANN002
        return self._s.event_stream(**kw)


class _Host(RegistryHost):
    def __init__(self, s: RecordSearcher) -> None:
        self._s = s

    @property
    def search_records_fn(self):
        return _Adapter(self._s)


def test_event_stream_merges_all_streams_in_time_order():
    """全流合并按时间升序（旧→新轨迹）."""
    ev = _searcher().event_stream(streams="all", limit=50)
    assert len(ev) == 3
    assert [e["stream"] for e in ev] == ["action_trace", "action_trace", "exception_log"]
    assert ev[0]["ts"] <= ev[-1]["ts"]  # 升序


def test_event_stream_single_stream_with_query():
    """单流 + 关键词过滤."""
    ev = _searcher().event_stream(streams="exception_log", query="超时")
    assert len(ev) == 1 and ev[0]["stream"] == "exception_log"


def test_event_stream_since_filter():
    """since 时间下界过滤."""
    ev = _searcher().event_stream(streams="all", since="2026-08-14T10:00:01")
    assert len(ev) == 2
    assert all(e["ts"] >= "2026-08-14T10:00:01" for e in ev)


def test_event_stream_limit_keeps_most_recent():
    """limit 取最近 N 条（时间倒序截取再升序返回）."""
    ev = _searcher().event_stream(streams="all", limit=1)
    assert len(ev) == 1
    assert ev[0]["ts"] == "2026-08-14T10:00:02"  # 最近一条


def test_event_stream_empty_dir_returns_empty():
    """空审计目录如实返回空（不伪造视图）."""
    tmp = Path(tempfile.mkdtemp())
    assert RecordSearcher(audit_dir=tmp).event_stream() == []


def test_event_stream_unknown_stream_skipped():
    """未知流名跳过不阻断（fail-open）."""
    ev = _searcher().event_stream(streams="no_such_stream")
    assert ev == []


def test_event_stream_tool_registered_in_defs():
    """event_stream 已注册进 tool_defs."""
    from llm_loop.introspection import registry_introspection as ri

    names = [d["name"] for d in ri.tool_defs()]
    assert "event_stream" in names


def test_event_stream_dispatch_returns_success():
    """registry 分派 event_stream 返回成功回执."""
    s = _searcher()
    res = ri_execute("event_stream", {"streams": "all"}, _Host(s))
    assert res.status.value == "success"
    assert "统一事件流 3 条" in res.content
    assert "action_trace" in res.content and "exception_log" in res.content


def test_event_stream_dispatch_empty_dir_honest():
    """空目录分派返回'无匹配事件'（诚实空视图）."""
    s = RecordSearcher(audit_dir=Path(tempfile.mkdtemp()))
    res = ri_execute("event_stream", {"streams": "all"}, _Host(s))
    assert res.status.value == "success"
    assert "无匹配事件" in res.content
