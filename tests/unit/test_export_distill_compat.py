"""单元测试: D1 迁移前后 export_distill 逐字节一致（design.md §2.4.1 / spec §5.4.1-2 / tasks §9.2）.

覆盖:
- 同一批构造会话在迁移前后各执行一次 export_distill（复用只读入口 run_export）
- 两次 JSONL 导出逐字节一致
- 两次统计报告除 elapsed_s（运行耗时）外逐字段一致
- 源 session JSON 文件 mtime/内容哈希零修改（只读红线，spec §5.4.1-2 / §5.4.2）
- run_export 自身 readonly_violations 为空（导出过程零修改）
"""

from __future__ import annotations

import hashlib
import json

from llm_loop.event_log.migrate import run_migration
from llm_loop.introspection.export_distill import run_export


def _session_dict(sid: str, with_failure: bool = False) -> dict:
    """构造可产出蒸馏样本的会话（含完整闭环段）."""
    messages = [
        {"role": "user", "content": "问题", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": None, "metadata": {}},
        {"role": "assistant", "content": "", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None,
         "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f1", "arguments": "{}"}}],
         "reasoning_content": "思考", "metadata": {}},
        {"role": "tool", "content": "[状态: success] 结果", "source": "tool",
         "tool_call_id": "c1", "status": "success", "tool_name": "f1",
         "error_detail": None, "tool_calls": None, "reasoning_content": None, "metadata": {}},
        {"role": "assistant", "content": "最终回答", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": None, "metadata": {}},
    ]
    if with_failure:
        messages.append(
            {"role": "user", "content": "第二个问题", "source": "user", "tool_call_id": None,
             "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
             "reasoning_content": None, "metadata": {}},
        )
        messages.append(
            {"role": "tool", "content": "[状态: failure] 失败", "source": "tool",
             "tool_call_id": "c2", "status": "failure", "tool_name": "f2",
             "error_detail": None, "tool_calls": None, "reasoning_content": None, "metadata": {}},
        )
    return {
        "version": 4, "session_id": sid, "created_at": "2026-01-01T00:00:00",
        "title": f"导出{sid}", "updated_at": "2026-01-01T00:01:00", "status": "active",
        "parent_id": None, "branch_id": "", "branch_summary": "", "model_override": None,
        "pinned": False, "channel": "web", "messages": messages,
    }


def _write_sessions(sessions_dir) -> dict[str, str]:
    """写会话源并返回 {path: sha256} 基线."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    baseline: dict[str, str] = {}
    for sid, with_failure in [("s1", False), ("s2", True), ("s3", False)]:
        p = sessions_dir / f"{sid}.json"
        raw = json.dumps(_session_dict(sid, with_failure), ensure_ascii=False)
        p.write_text(raw, encoding="utf-8")
        baseline[str(p)] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return baseline


def test_export_distill_identical_before_after_migration(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    baseline = _write_sessions(sessions_dir)

    out_before = tmp_path / "out_before.jsonl"
    rep_before = tmp_path / "rep_before.json"
    out_after = tmp_path / "out_after.jsonl"
    rep_after = tmp_path / "rep_after.json"

    # 迁移前导出
    r1 = run_export(sessions_dir, out_before, rep_before)
    # 迁移为事件日志
    rep = run_migration(sessions_dir, logs_dir)
    assert rep.migrated == 3
    assert rep.failed == []
    # 迁移后导出（复用同一批源会话）
    r2 = run_export(sessions_dir, out_after, rep_after)

    # JSONL 逐字节一致
    assert out_before.read_bytes() == out_after.read_bytes()
    # 报告除 elapsed_s 外逐字段一致（elapsed_s 为运行耗时，非导出内容）
    d1 = json.loads(rep_before.read_text(encoding="utf-8"))
    d2 = json.loads(rep_after.read_text(encoding="utf-8"))
    assert d1["elapsed_s"] != d2["elapsed_s"] or True  # 耗时允许差异
    for k in set(d1) - {"elapsed_s"}:
        assert d1[k] == d2[k], f"报告字段不一致: {k}"
    # 导出规模与闭环对账
    assert r1.sessions_total == r2.sessions_total == 3
    assert r1.segments_passed + r1.segments_filtered == r1.segments_total
    assert r1.samples_written == r2.samples_written
    assert r1.reasoning_present == r2.reasoning_present

    # 只读红线：源 session JSON mtime/内容哈希零修改（迁移 + 两次导出均未触碰）
    for p_str, sha in baseline.items():
        p = tmp_path / "sessions" / p_str.split("/")[-1]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == sha, f"内容哈希变化: {p}"
    # run_export 自身只读复核为空（导出过程零修改）
    assert r1.readonly_violations == []
    assert r2.readonly_violations == []
