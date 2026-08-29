"""FR-3 前缀命中埋点测试（SDD-20260830）: 理论前缀计算正确性 + 消息级断点定位."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from llm_loop.llm.client import _PREFIX_TRACE_STATE, _trace_payload_fingerprint


def _run_trace(tmp: Path, messages: list[dict], sess: str = "s1", model: str = "m1") -> dict:
    _PREFIX_TRACE_STATE.pop((sess, model), None)
    path = tmp / "trace.jsonl"
    os.environ["LLM_PAYLOAD_TRACE_PATH"] = str(path)
    os.environ["LLM_PAYLOAD_TRACE"] = "1"
    _trace_payload_fingerprint(
        {"messages": messages, "tools": []}, messages, session_id=sess, provider="p", model=model
    )
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return json.loads(lines[-1])


def test_prefix_hit_pure_append(tmp_path):
    """纯追加序列: 公共前缀 = 全部旧消息（增量=唯一 miss 源，FR-1.2 语义）."""
    m1 = [{"role": "system", "content": "S"}, {"role": "user", "content": "U1"}]
    m2 = m1 + [{"role": "assistant", "content": "A"}, {"role": "user", "content": "U2"}]
    _run_trace(tmp_path, m1)
    r2 = _run_trace(tmp_path, m2)  # 注: _run_trace 内 pop 清状态——需绕过
    # 状态被 pop 后第二轮无 prev → 无 prefix 字段；改为连续调用验证
    _PREFIX_TRACE_STATE.pop(("s2", "m1"), None)
    p = tmp_path / "t2.jsonl"
    os.environ["LLM_PAYLOAD_TRACE_PATH"] = str(p)
    _trace_payload_fingerprint({"messages": m1, "tools": []}, m1, session_id="s2", provider="p", model="m1")
    _trace_payload_fingerprint({"messages": m2, "tools": []}, m2, session_id="s2", provider="p", model="m1")
    last = json.loads([l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()][-1])
    assert last["prefix_hit_msgs"] == 2, "m2 前两条与 m1 完全一致 → 公共前缀=2"
    assert last["prefix_hit_chars"] == len("S") + len("U1")


def test_prefix_hit_breaks_at_first_diff(tmp_path):
    """中段插入场景: 断点=第一个不同消息索引（EVO-20260819 教训的定位能力）."""
    m1 = [{"role": "system", "content": "S"}, {"role": "user", "content": "U1"}, {"role": "user", "content": "U2"}]
    m2 = [{"role": "system", "content": "S"}, {"role": "user", "content": "CHANGED"}, {"role": "user", "content": "U2"}]
    _PREFIX_TRACE_STATE.pop(("s3", "m1"), None)
    p = tmp_path / "t3.jsonl"
    os.environ["LLM_PAYLOAD_TRACE_PATH"] = str(p)
    _trace_payload_fingerprint({"messages": m1, "tools": []}, m1, session_id="s3", provider="p", model="m1")
    _trace_payload_fingerprint({"messages": m2, "tools": []}, m2, session_id="s3", provider="p", model="m1")
    last = json.loads(p.read_text(encoding="utf-8").splitlines()[-1])
    assert last["prefix_hit_msgs"] == 1, "第 2 条(索引1)内容变化 → 断点前缀=1"
    assert last["prefix_hit_chars"] == len("S")


def test_first_round_no_theoretical_value(tmp_path):
    """冷启动首轮无 prev → 无 prefix 字段（不伪造理论值）."""
    r = _run_trace(tmp_path, [{"role": "user", "content": "x"}])
    assert "prefix_hit_msgs" not in r and "prefix_hit_chars" not in r
