"""R0 Freeze Evidence 验收: wire fixtures 可加载、结构完整、已脱敏。

fixture 由 scripts/extract_wire_fixtures.py 从真实 1210 offending payload 生成
（data/audit/offending_payloads/，schema=2，content 截断脱敏）。
本测试是 R5/R7 wire contract / tail packet 测试的资产基座。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wire"
EXPECTED_CATEGORIES = {
    "tail1_compact": 1,
    "tail2_compact": 2,
    "tail3_compact": 3,
    "tail2_mem_compact": 2,
    "tail2_tool_user_compact": 2,
    "tail_tc_compact": 2,
    "old_ref_replay": 0,
}
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    # 凭据样值: key 名后跟 ≥12 位字母数字下划线连字符且非占位词（none/test/dummy/k 等）
    re.compile(
        r"(?i)(api[_-]?key|authorization|token)\s*[:=]\s*['\"]?(?!REDACTED)"
        r"(?!none\b|test\b|dummy\b|placeholder\b)[A-Za-z0-9_\-]{12,}"
    ),
)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _tail_user_run(msgs: list[dict]) -> int:
    n = 0
    for m in reversed(msgs):
        if m.get("role") == "user":
            n += 1
        else:
            break
    return n


def test_all_six_categories_present() -> None:
    files = {p.stem for p in FIXTURE_DIR.glob("*.json")}
    missing = set(EXPECTED_CATEGORIES) - files
    assert not missing, f"missing fixtures: {missing}"


@pytest.mark.parametrize("category,expect_run", sorted(EXPECTED_CATEGORIES.items()))
def test_fixture_meta_consistent(category: str, expect_run: int) -> None:
    fx = _load(category)
    assert fx["schema"] == 2
    assert fx["category"] == category
    meta = fx["meta"]
    assert meta["source_file"], "source_file 必填（可溯源）"
    assert meta["tail_user_run"] == expect_run == _tail_user_run(fx["messages"])
    assert len(meta["shape_tail4"]) == 4
    assert meta["msg_count"] == len(fx["messages"])
    assert meta["is_compact_first"] in (True, False, None)


@pytest.mark.parametrize("category", sorted(EXPECTED_CATEGORIES))
def test_fixture_structure_preserved(category: str) -> None:
    fx = _load(category)
    for m in fx["messages"]:
        assert m.get("role") in ("system", "user", "assistant", "tool"), m
        if m["role"] == "tool":
            assert isinstance(m.get("tool_call_id"), str) and m["tool_call_id"]
        for tc in m.get("tool_calls") or []:
            assert isinstance(tc["function"]["arguments"], str)  # INV-001 形态保留
    if category == "old_ref_replay":
        # 事件流重组源（D13③）：tool 定义面不在事件 payload 中——tool 形态经
        # messages.tool_calls 保留（上方断言已覆盖）；tools 空态为源类型如实声明
        assert fx["tools"] == []
    else:
        assert isinstance(fx["tools"], list) and fx["tools"]
        for t in fx["tools"]:
            assert t["function"]["name"]
    assert "model" in fx["params"]


@pytest.mark.parametrize("category", sorted(EXPECTED_CATEGORIES))
def test_fixture_sanitized_no_secrets(category: str) -> None:
    fx = _load(category)
    blob = json.dumps(fx, ensure_ascii=False)
    for pat in SECRET_PATTERNS:
        assert not pat.search(blob), f"{category}: secret leak {pat.pattern}"
    # 截断标记存在（证明长 content 被截断过）
    if fx["meta"]["msg_count"] > 20:
        assert "[TRUNCATED len=" in blob


def test_tail3_fixture_actually_has_three_tail_users() -> None:
    fx = _load("tail3_compact")
    roles = [m["role"] for m in fx["messages"][-3:]]
    assert roles == ["user", "user", "user"]


def test_old_ref_replay_scenario_preserved() -> None:
    """D13③/T5-E A-5：旧 ref 防重复消费实证场景入等价性覆盖（guard(r9) 只增不改）."""
    fx = _load("old_ref_replay")
    raw = json.dumps(fx["messages"], ensure_ascii=False)
    refs = re.findall(r"evidence://v1/[0-9a-f]{16,}", raw)
    assert len(refs) >= 7, f"重复请求实证不足: {len(refs)} < 7"
    assert len(set(refs)) == 1, "场景要求同一 evidence ref 重复出现"
    fails = [
        m
        for m in fx["messages"]
        if m["role"] == "tool" and str(m.get("content", "")).startswith("[状态: failure]")
    ]
    assert len(fails) >= 3, f"失败回环实证不足: {len(fails)} < 3"


def test_tail_tc_fixture_has_tool_calls_near_tail() -> None:
    fx = _load("tail_tc_compact")
    assert any(m.get("tool_calls") for m in fx["messages"][-10:] if m["role"] == "assistant")
