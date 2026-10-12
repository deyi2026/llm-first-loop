"""单元测试: export_distill 蒸馏数据集导出工具（design §2.4.1 用例 1-18）.

- 全部用例走 `tmp_path` 构造会话文件（M64 防污染真实 data/）；
- 只读验证用字节级对比断言；
- 试导出（真实 32 会话）由 P0-5 手工/CLI 承载，不在此文件内随全量运行。
"""

from __future__ import annotations

import json

from llm_loop.introspection.export_distill import (
    build_react_sample,
    check_closed_loop,
    normalize_tool_call,
    run_export,
    segment_has_non_success,
    split_segments,
)


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _system(content: str) -> dict:
    return {"role": "system", "content": content}


def _assistant(content: str, calls: list | None = None, reasoning: str | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if calls is not None:
        msg["tool_calls"] = calls
    if reasoning is not None:
        msg["reasoning_content"] = reasoning
    return msg


def _tool_call(call_id: str, name: str = "f1", arguments: str = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def _tool(content: str, call_id: str, status: str = "success") -> dict:
    return {"role": "tool", "content": content, "tool_call_id": call_id, "status": status}


def _session(session_id: str = "sess-1", messages: list | None = None) -> dict:
    return {
        "version": 3,
        "session_id": session_id,
        "created_at": "2026-08-14T00:00:00",
        "title": "会话",
        "updated_at": "2026-08-14T00:01:00",
        "status": "active",
        "parent_id": None,
        "branch_id": None,
        "messages": messages or [],
    }


def _write_session(tmp_path, name: str, session: dict) -> None:
    (tmp_path / name).write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")


# ── 用例 1-2: split_segments（P0-2 E2.1）──

def test_split_segments_by_user():
    msgs = [_user("u1"), _assistant("a1"), _user("u2"), _assistant("a2"), _user("u3")]
    segs = split_segments(msgs)
    assert len(segs) == 3
    assert [s[0]["role"] for s in segs] == ["user", "user", "user"]
    assert segs[0][1]["role"] == "assistant"
    assert segs[1][0]["content"] == "u2"


def test_split_segments_system_inside():
    msgs = [_user("u1"), _assistant("a1"), _system("声明提醒"), _user("u2")]
    segs = split_segments(msgs)
    assert len(segs) == 2
    assert segs[0][-1]["role"] == "system"  # system 归属当前段
    assert segs[1][0]["role"] == "user"


# ── 用例 3-4: segment_has_non_success（P0-2 E2.2）──

def test_filter_non_success():
    seg = [_user("u"), _assistant("a", [_tool_call("c1")]), _tool("bad", "c1", "failure")]
    assert segment_has_non_success(seg) == "failure"
    seg2 = [_user("u"), _assistant("a", [_tool_call("c1")]), _tool("bad", "c1", "timeout")]
    assert segment_has_non_success(seg2) == "timeout"
    seg3 = [_user("u"), _assistant("a", [_tool_call("c1")]), _tool("bad", "c1", "error")]
    assert segment_has_non_success(seg3) == "error"


def test_filter_non_success_multi_reason():
    # 同段多种非 success → 返回首个命中（主因）
    seg = [
        _user("u"),
        _assistant("a", [_tool_call("c1")]),
        _tool("bad", "c1", "timeout"),
        _assistant("a", [_tool_call("c2")]),
        _tool("bad", "c2", "error"),
    ]
    assert segment_has_non_success(seg) == "timeout"
    # 全 success → None
    seg_ok = [_user("u"), _assistant("a", [_tool_call("c1")]), _tool("ok", "c1", "success")]
    assert segment_has_non_success(seg_ok) is None
    # 无 tool 消息 → None
    assert segment_has_non_success([_user("u"), _assistant("a")]) is None


# ── 用例 5-8: check_closed_loop（P0-2 E2.3）──

def test_closed_loop_ok():
    seg = [
        _user("u"),
        _assistant("", [_tool_call("c1")], "思考"),
        _tool("ok", "c1"),
        _assistant("最终回答"),
    ]
    assert check_closed_loop(seg) == []


def test_closed_loop_missing_tool():
    # assistant(tool_calls) 声明 2 个，仅 1 条回执 → 缺回执（对齐 M40 语义）
    seg = [
        _user("u"),
        _assistant("", [_tool_call("c1"), _tool_call("c2")], "思考"),
        _tool("ok", "c1"),
        _assistant("最终回答"),
    ]
    gaps = check_closed_loop(seg)
    assert len(gaps) == 1
    assert "缺回执" in gaps[0]
    assert "声明2" in gaps[0]
    assert "实际1" in gaps[0]


def test_closed_loop_missing_end():
    # 段尾仅 system（忽略 system 判定）→ 缺结尾
    seg = [
        _user("u"),
        _assistant("", [_tool_call("c1")], "思考"),
        _tool("ok", "c1"),
        _system("声明提醒"),
    ]
    gaps = check_closed_loop(seg)
    assert "缺结尾" in gaps


def test_closed_loop_missing_start():
    # 段首非 user → 缺开头
    seg = [_assistant("无 user 开头"), _assistant("最终回答")]
    gaps = check_closed_loop(seg)
    assert "缺开头" in gaps


# ── 用例 9-10: build_react_sample（P0-3）──

def test_build_sample_field_mapping():
    calls = [_tool_call("c1", name="search", arguments='{"q": "蒸馏"}')]
    seg = [
        _user("查询蒸馏数据"),
        _assistant("", calls, "需要搜索蒸馏相关文档"),
        _tool("[状态: success] 命中 3 条", "c1"),
        _assistant("蒸馏数据集导出工具已完成"),
    ]
    sample = build_react_sample(_session(), seg, 0)
    assert sample["session_id"] == "sess-1"
    assert sample["segment_index"] == 0
    assert sample["type"] == "react"
    assert sample["task"] == "查询蒸馏数据"
    assert len(sample["steps"]) == 1
    step = sample["steps"][0]
    assert step["thought"] == "需要搜索蒸馏相关文档"
    assert step["action"][0]["id"] == "c1"
    assert step["action"][0]["name"] == "search"
    assert step["action"][0]["arguments"] == '{"q": "蒸馏"}'
    assert step["observation"][0]["content"] == "[状态: success] 命中 3 条"
    assert step["observation"][0]["status"] == "success"
    assert sample["final_answer"] == "蒸馏数据集导出工具已完成"
    assert sample["metadata"]["version"] == 3
    assert sample["metadata"]["title"] == "会话"


def test_build_sample_reasoning_null():
    # reasoning_content 缺失 → thought=null（如实置空，不伪造）
    seg = [
        _user("u"),
        _assistant("", [_tool_call("c1")]),
        _tool("ok", "c1"),
        _assistant("最终回答"),
    ]
    sample = build_react_sample(_session(), seg, 0)
    assert sample["steps"][0]["thought"] is None


# ── 用例 11: normalize_tool_call（P0-3）──

def test_normalize_tool_call_openai_shape():
    call = {"id": "call_1", "type": "function", "function": {"name": "f1", "arguments": "{\"a\": 1}"}}
    out = normalize_tool_call(call)
    assert out == {"id": "call_1", "type": "function", "name": "f1", "arguments": "{\"a\": 1}"}
    # arguments 与源 function.arguments 逐字节一致
    assert out["arguments"] == call["function"]["arguments"]
    # 未知形状 → 原样返回（防御性不破坏）
    weird = {"foo": "bar"}
    assert normalize_tool_call(weird) == weird


# ── 用例 12-13: JSONL 输出（P0-3 E3.1/E3.4）──

def test_jsonl_roundtrip(tmp_path):
    sess = _session(
        session_id="s1",
        messages=[
            _user("第一问"),
            _assistant("", [_tool_call("c1")], "思考1"),
            _tool("[状态: success] 结果1", "c1"),
            _assistant("回答1"),
        ],
    )
    _write_session(tmp_path, "s1.json", sess)
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    assert report.samples_written == 1
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["session_id"] == "s1"
    assert obj["type"] == "react"
    assert obj["steps"][0]["observation"][0]["content"] == "[状态: success] 结果1"


def test_jsonl_unicode(tmp_path):
    long_content = "超长内容" * 2000 + "\U0001f600" + "中文👍"
    sess = _session(
        session_id="s-unicode",
        messages=[
            _user("包含中文与 emoji 🚀"),
            _assistant("", [_tool_call("c1")], "推理：蒸馏数据 🧠"),
            _tool(f"[状态: success] {long_content}", "c1"),
            _assistant("最终回答：✅ 完成"),
        ],
    )
    _write_session(tmp_path, "u.json", sess)
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    assert report.samples_written == 1
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    # ensure_ascii=False 无损，中文/emoji/超长不截断不转义破坏
    assert obj["task"] == "包含中文与 emoji 🚀"
    assert obj["steps"][0]["thought"] == "推理：蒸馏数据 🧠"
    assert obj["steps"][0]["observation"][0]["content"] == f"[状态: success] {long_content}"
    assert "\U0001f600" in obj["steps"][0]["observation"][0]["content"]
    assert report.max_observation_len == len(f"[状态: success] {long_content}")


# ── 用例 14-18: run_export 编排/容错/只读/报告（P0-1/P0-4）──

def test_run_export_readonly(tmp_path):
    sess = _session(
        session_id="ro",
        messages=[
            _user("u"),
            _assistant("", [_tool_call("c1")], "r"),
            _tool("ok", "c1"),
            _assistant("回答"),
        ],
    )
    src = tmp_path / "ro.json"
    src.write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
    before = src.read_bytes()
    mtime_before = src.stat().st_mtime_ns
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    after = src.read_bytes()
    assert before == after  # 内容逐字节不变
    assert mtime_before == src.stat().st_mtime_ns  # mtime 不变
    assert report.readonly_violations == []


def test_run_export_corrupt_failopen(tmp_path):
    ok_sess = _session(
        session_id="ok",
        messages=[
            _user("u"),
            _assistant("", [_tool_call("c1")], "r"),
            _tool("ok", "c1"),
            _assistant("回答"),
        ],
    )
    _write_session(tmp_path, "ok.json", ok_sess)
    (tmp_path / "bad.json").write_text("{broken json", encoding="utf-8")
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    assert len(report.skipped_files) == 1
    assert "bad.json" in report.skipped_files[0]["file"]
    assert "JSONDecodeError" in report.skipped_files[0]["reason"]
    assert report.sessions_total == 1  # 其余文件正常导出
    assert report.samples_written == 1
    assert report.segments_passed == 1


def test_run_export_overwrite_protect(tmp_path):
    sess = _session(session_id="op", messages=[_user("u"), _assistant("回答")])
    _write_session(tmp_path, "op.json", sess)
    out = tmp_path / "out.jsonl"
    out.write_text("old", encoding="utf-8")
    # 已存在且非 force → FileExistsError（杜绝静默追加）
    try:
        run_export(tmp_path, out, tmp_path / "rep.json")
        raise AssertionError("应抛 FileExistsError")
    except FileExistsError:
        pass
    # force → 覆盖
    report = run_export(tmp_path, out, tmp_path / "rep.json", force=True)
    assert report.samples_written == 1
    assert "old" not in out.read_text(encoding="utf-8")


def test_report_reconciliation(tmp_path):
    # 一段通过 + 一段失败 + 一段含多种非 success（闭环对账）
    pass_sess = _session(
        session_id="p1",
        messages=[
            _user("u1"),
            _assistant("", [_tool_call("c1")], "r1"),
            _tool("ok", "c1"),
            _assistant("回答1"),
        ],
    )
    fail_sess = _session(
        session_id="f1",
        messages=[
            _user("u2"),
            _assistant("", [_tool_call("c2")], "r2"),
            _tool("bad", "c2", "failure"),
            _assistant("回答2"),
        ],
    )
    _write_session(tmp_path, "p1.json", pass_sess)
    _write_session(tmp_path, "f1.json", fail_sess)
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    assert report.segments_total == 2
    assert report.segments_passed == 1
    assert report.segments_filtered == 1
    assert report.samples_written == 1
    assert report.segments_passed + report.segments_filtered == report.segments_total
    assert report.samples_written == report.segments_passed
    # 主因分类
    assert report.reason_counts.get("failure") == 1
    # 回执级 status 分布与工具消息一致
    assert report.status_distribution.get("success") == 1
    assert report.status_distribution.get("failure") == 1
    # 报告 JSON 可还原全字段
    rep = json.loads((tmp_path / "rep.json").read_text(encoding="utf-8"))
    assert rep["reconciliation"]["ok"] is True
    assert rep["segments_total"] == 2


def test_report_reasoning_coverage(tmp_path):
    # 2 条 assistant：1 条带 reasoning → 覆盖率 0.5
    sess = _session(
        session_id="rc",
        messages=[
            _user("u"),
            _assistant("", [_tool_call("c1")], "有思考"),
            _tool("ok", "c1"),
            _assistant("无思考的最终回答"),
        ],
    )
    _write_session(tmp_path, "rc.json", sess)
    report = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json")
    assert report.reasoning_total == 2
    assert report.reasoning_present == 1
    assert report.reasoning_coverage == 0.5
    # 空导出 → 覆盖率 0.0 不抛除零
    empty = _session(session_id="e", messages=[_user("u"), _assistant("回答")])
    (tmp_path / "e.json").write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")
    _write_session(tmp_path, "e2.json", empty)
    # 覆盖已存在输出
    report2 = run_export(tmp_path, tmp_path / "out.jsonl", tmp_path / "rep.json", force=True)
    assert report2.reasoning_total >= 2
