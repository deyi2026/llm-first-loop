"""R2 收敛回执三件套纯函数组装器测试（antidrift_impl 批 1，T1-1~T1-6）.

契约源：design §2.4.2（回执文本格式）+ §2.2（CT-8 修正后截断契约逐字继承）。
"""

from __future__ import annotations

import re
from datetime import datetime

from llm_loop.core.loop.engine_services.convergence_receipt import (
    DEFAULT_MIRROR_BUDGET_CHARS,
    MirrorFacts,
    QueuePressureFacts,
    VitalsFacts,
    mirror_budget_chars,
    render_convergence_receipt_addendum,
)


def _vitals(**overrides) -> VitalsFacts:
    base = dict(rounds=7, wall_clock_s=123.0, tokens_in=4567, tokens_out=89)
    base.update(overrides)
    return VitalsFacts(**base)


def _render(vitals=None, entries=None, queue=None, *, budget_chars=8192) -> str:
    return render_convergence_receipt_addendum(
        vitals or _vitals(),
        MirrorFacts(entries=list(entries or [])),
        queue or QueuePressureFacts(count=0),
        budget_chars=budget_chars,
    )


# ---------------------------------------------------------------- T1-1 vitals

def test_t1_1_vitals_three_values_and_unavailable_reason():
    out = _render()
    assert (
        "[run_vitals] rounds=7; wall_clock_s=123; tokens_in=4567; tokens_out=89; "
        "source=request.usage"
    ) in out

    out_unavailable = _render(
        vitals=VitalsFacts(usage_available=False, unavailable_reason="usage_missing")
    )
    vitals_line = out_unavailable.split("[run_vitals]", 1)[1].splitlines()[0]
    assert vitals_line == " unavailable(reason=usage_missing)"
    # 禁默认值冒充：unavailable 行不得出现伪造三值
    assert "rounds=" not in vitals_line
    assert "tokens_in=" not in vitals_line


# ------------------------------------------------- T1-2 镜像逐字 + 发生顺序

def test_t1_2_mirror_verbatim_in_order_with_quotes_and_newlines():
    first = '含"双引号"与\n换行的原文甲'
    second = "含 '单引号' 的原文乙"
    out = _render(entries=[first, second])
    assert "[self_history_mirror] entries=2; truncated_oldest_count=0" in out
    # 逐字包含（引号/换行原样保真），不转义不重排
    assert f"1. {first}" in out
    assert f"2. {second}" in out
    # 按发生顺序投影
    assert out.index(first) < out.index(second)


# ------------------------------------------- T1-3 预算封顶从最旧截断 K=实际数

def test_t1_3_budget_truncates_oldest_and_count_is_exact(monkeypatch):
    monkeypatch.setenv("LFL_CONVERGENCE_MIRROR_BUDGET_CHARS", "100")
    assert mirror_budget_chars() == 100

    a, b, c = "甲" * 60, "乙" * 60, "丙" * 60
    out = _render(entries=[a, b, c], budget_chars=mirror_budget_chars())
    assert "[self_history_mirror] entries=3; truncated_oldest_count=2" in out
    assert c in out  # 最新条目保留
    assert a not in out and b not in out  # 最旧两条被截断

    # 部分截断：预算容纳最新 2 条（60+60<=100 放不下 3 条）
    out_partial = _render(entries=[a, b, c], budget_chars=130)
    assert "truncated_oldest_count=1" in out_partial
    assert b in out_partial and c in out_partial and a not in out_partial


def test_t1_3_budget_default_is_8192_and_env_parse_fails_open(monkeypatch):
    monkeypatch.delenv("LFL_CONVERGENCE_MIRROR_BUDGET_CHARS", raising=False)
    assert DEFAULT_MIRROR_BUDGET_CHARS == 8192
    assert mirror_budget_chars() == 8192
    monkeypatch.setenv("LFL_CONVERGENCE_MIRROR_BUDGET_CHARS", "not-a-number")
    assert mirror_budget_chars() == 8192


# --------------------------------------------------- T1-4 K=0 常驻（未截断）

def test_t1_4_truncated_field_always_present_zero_when_not_truncated():
    out_one = _render(entries=["仅一条"])
    assert "truncated_oldest_count=0" in out_one
    out_empty = _render(entries=[])
    assert "[self_history_mirror] entries=0; truncated_oldest_count=0" in out_empty


# --------------------------------------------- T1-5 单条超预算冻结（最新全文）

def test_t1_5_single_oversized_entry_keeps_latest_full_text():
    huge_old = "旧超长" + "甲" * 9000
    huge_new = "新超长" + "乙" * 9000
    out = _render(entries=[huge_old, huge_new], budget_chars=8192)
    assert "[self_history_mirror] entries=2; truncated_oldest_count=1" in out
    assert huge_new in out  # 仅剩最新 1 条时保留全文（预算穿透）
    assert huge_old not in out

    # 镜像只有 1 条且自身超预算：保留全文，K=0
    out_single = _render(entries=[huge_new], budget_chars=8192)
    assert "truncated_oldest_count=0" in out_single
    assert huge_new in out_single


# ------------------------------------------------------- T1-6 队列压力三态

def test_t1_6_queue_pressure_three_states():
    ts = 1758600000.0
    out_pressure = _render(queue=QueuePressureFacts(count=2, oldest_enqueued_at=ts))
    m = re.search(r"\[queue_pressure\] waiting_count=2; oldest_enqueued_at=(\S+)", out_pressure)
    assert m is not None
    assert m.group(1) == datetime.fromtimestamp(ts).isoformat()

    out_zero = _render(queue=QueuePressureFacts(count=0))
    assert "[queue_pressure] waiting_count=0; oldest_enqueued_at=none" in out_zero

    out_unavailable = _render(
        queue=QueuePressureFacts(count=0, unavailable_reason="no_queue_binding")
    )
    assert "[queue_pressure] unavailable(reason=no_queue_binding)" in out_unavailable


# --------------------------------------------------- 段布局：段间单个空行

def test_addendum_segment_layout_single_blank_line_between_segments():
    out = _render(
        entries=["一条事实"],
        queue=QueuePressureFacts(count=1, oldest_enqueued_at=1.0),
    )
    lines = out.split("\n")
    assert lines[0].startswith("[run_vitals]")
    assert lines[1] == ""
    assert lines[2].startswith("[self_history_mirror]")
    assert lines[3] == "1. 一条事实"
    assert lines[4] == ""
    assert lines[5].startswith("[queue_pressure]")
