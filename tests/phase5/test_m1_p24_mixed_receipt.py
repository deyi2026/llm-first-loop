"""Phase5 M1：P2-4 混合路径 interrupt_receipt 戳记时序（S18-M1/M2）。

设计依据：docs/phase5-stream-interrupt-design.md §2.1（r2）。
- S18-M1 正向：「同轮打断+剩余 skipped」混合路径，轮内尾段 gap 收割 ack
  必须读到本轮事实 interrupt_receipt=True（修复前置位在 ack 之后，读 False→red）。
- S18-M2 反向：同 run 后续轮纯 gap 收割（本轮无打断回执）必须读到 False
  （修复前读到上一轮置位残值 True→red）。
断言口径：mark_interject_received 仅在 True 时写字段，False=字段缺失，
故 False 断言用 `is not True`。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.core.message import ToolCall  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _LockedSleepTool,
    _wait_run_done,
    _wait_tool_started,
)

REPORT_DIR = Path(__file__).resolve().parents[2] / "reports" / "phase5"


def _wait_procs_idle(engine, timeout: float = 10.0) -> bool:
    """轮询所有 execute_command 在途进程退出（区分前后轮工具）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        procs = getattr(engine, "_active_procs", None) or {}
        if not procs:
            return True
        time.sleep(0.02)
    return False


def _enqueue_interjection(client, sid, runner) -> str:
    gen = (runner.get_handle(sid) or {}).get("run_generation")
    r1 = client.post(
        "/api/v1/chat/queue",
        json={"session_id": sid, "message": INTERJECT_TEXT},
    )
    assert r1.status_code == 202
    queue_id = r1.json()["queue_id"]
    r2 = _interject(client, sid, queue_id, gen)
    assert r2.status_code == 202
    return queue_id


def test_a_s18m1_mixed_receipt_true(build_test_engine):
    """S18-M1：混合路径（打断 c1 + c2 skipped）→ 尾段收割 ack interrupt_receipt=True。"""
    engine, fake = build_test_engine(
        [
            {
                "content": "先跑两条长命令",
                "tool_calls": [
                    ToolCall(id="s18m1-c1", name="execute_command",
                             arguments={"command": "sleep 2.0"}),
                    ToolCall(id="s18m1-c2", name="execute_command",
                             arguments={"command": "sleep 0.8"}),
                ],
            },
            {"content": "final-after-mixed"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "请依次执行两条命令")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(0.3)  # c1 在途，注入 → CK-C 打断 c1（interrupted 回执）+ c2 skipped
        qa = _enqueue_interjection(client, sid, runner)
        final = _wait_run_done(q, timeout=20)
        assert final.get("type") == "done"

        item = _hq_item(_hq_of(client, engine), sid, qa) or {}
        assert item.get("status") == "interject_received"
        assert item.get("consumed_via") == "gap_harvest"
        # P2-4 核心：本轮（打断回执在 recorded_results）事实必须被 ack 读到
        assert item.get("interrupt_receipt") is True, (
            f"S18-M1 混合路径 interrupt_receipt 应为 True（本轮含打断回执），"
            f"实际={item.get('interrupt_receipt')!r}（P2-4：ack 先于置位读到旧值）"
        )
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        assert any("interrupted_for_interjection" in t for t in texts), "c1 应有打断回执"
        assert any("skipped_for_interjection" in t for t in texts), "c2 应有 skipped 回执"
    finally:
        runner.cancel(sid)


def test_b_s18m2_residual_false(build_test_engine):
    """S18-M2：轮1 打断置 True → 轮2 纯 gap 收割（无打断）必须读到 False。"""
    engine, fake = build_test_engine(
        [
            {   # 轮1：c1 打断 + c2 skipped（置位 True）
                "content": "轮1：两条长命令",
                "tool_calls": [
                    ToolCall(id="s18m2-c1", name="execute_command",
                             arguments={"command": "sleep 2.0"}),
                    ToolCall(id="s18m2-c2", name="execute_command",
                             arguments={"command": "sleep 0.8"}),
                ],
            },
            {   # 轮2：c3 不可取消（revocable=False）自然完成 + c4 skipped
                # （纯 gap 收割，本轮无打断回执；注入时机无窗口约束——
                #   c3 不可取消必然自然完成，gate 等返回后收割剩余）
                "content": "轮2：两条命令",
                "tool_calls": [
                    ToolCall(id="s18m2-c3", name="phase4_locked_sleep",
                             arguments={"seconds": 0.8}),
                    ToolCall(id="s18m2-c4", name="execute_command",
                             arguments={"command": "sleep 2.0"}),
                ],
            },
            {"content": "final-after-residual"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    engine.registry.register(_LockedSleepTool())
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "请依次执行")
        # 轮1
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(0.3)
        qa = _enqueue_interjection(client, sid, runner)  # 打断 c1
        # 轮1 收割后轮2 启动：等轮1 进程清空 → c3 出现
        assert _wait_procs_idle(engine)
        assert _wait_tool_started(engine, "phase4_locked_sleep", "_active")
        time.sleep(0.2)  # c3 在途注入：不可取消 → gate 等返回 → c4 skipped
        qb = _enqueue_interjection(client, sid, runner)
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done"

        hq = _hq_of(client, engine)
        item_a = _hq_item(hq, sid, qa) or {}
        item_b = _hq_item(hq, sid, qb) or {}
        assert item_a.get("consumed_via") == "gap_harvest"
        assert item_a.get("interrupt_receipt") is True, (
            f"轮1 打断事实应为 True，实际={item_a.get('interrupt_receipt')!r}"
        )
        assert item_b.get("consumed_via") == "gap_harvest"
        # P2-4 残值：轮2 本轮无打断回执，必须读到 False（字段缺失即 False）
        assert item_b.get("interrupt_receipt") is not True, (
            f"S18-M2 轮2 纯 gap 收割 interrupt_receipt 应为 False，"
            f"实际={item_b.get('interrupt_receipt')!r}（读到轮1 置位残值）"
        )
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        assert any("interrupted_for_interjection" in t for t in texts)
        assert sum(1 for t in texts if "skipped_for_interjection" in t) == 2
    finally:
        runner.cancel(sid)
