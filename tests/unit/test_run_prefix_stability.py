"""EVO-20260917-2f5ae9cb（人工已审）P2: run 边界/wire 前缀字节一致性回归.

不变量（建议原文）: 相同会话状态下，构建的 provider wire 前缀逐字节稳定；
已知会打穿前缀的成因必须要么消除（P1 锚块移尾部），要么可观测（P0 归因日志）。

验收场景:
  1. 锚快照块字节变化（Goal/checkpoint 状态变化）不改变 wire 其余前缀——
     变化只落在尾部锚块（P1 方案 A 的核心断言）;
  2. 压缩轮一次性 [锚提示] 行消失后，稳态轮前缀与压缩轮一致（差仅在锚块尾部）;
  3. 状态冻结时跨 build（模拟 run 边界）全 wire 逐字节一致;
  4. P0: CacheHealthMonitor.note_prefix_disturbance 因素分类正确且单行日志可 grep.
"""

from __future__ import annotations

import logging

import pytest

from llm_loop.core.cache_health import CacheHealthMonitor
from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


@pytest.fixture(autouse=True)
def _pin_compact_ratio_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("COMPACT_RATIO", "1.0")


def _pair(i: int, chars: int = 260) -> list[Message]:
    return [
        Message(
            role="assistant",
            content="D" * chars,
            source=MessageSource.USER,
            tool_calls=[{"id": f"c{i}", "name": "read_file", "arguments": {"path": f"/tmp/{i}"}}],
        ),
        Message(
            role="tool",
            content="R" * chars,
            source=MessageSource.USER,
            tool_call_id=f"c{i}",
        ),
    ]


def _fixture() -> list[Message]:
    msgs: list[Message] = []
    msgs.append(Message(role="user", content="原始任务指令-锚A-迁移仓库并验证 1a2b", source=MessageSource.USER))
    for i in range(18):
        msgs.extend(_pair(i))
    msgs.append(Message(role="user", content="第二条用户指令-锚B-跑全量测试 3c4d", source=MessageSource.USER))
    for i in range(18, 28):
        msgs.extend(_pair(i))
    msgs.append(Message(role="user", content="最新用户指令-锚C-开始执行 5e6f", source=MessageSource.USER))
    msgs.extend(_pair(99))
    return msgs


_SNAPSHOT_V1 = (
    "[Goal G-1] objective: 目标A：完成迁移\n"
    "[Checkpoint] 已核状态 | next: 执行"
)
_SNAPSHOT_V2 = (
    "[Goal G-2] objective: 目标B：状态已变化\n"
    "[Checkpoint] 新检查点 | next: 验证"
)


def _build(msgs, *, anchor=0, snapshot=_SNAPSHOT_V1, sid="s-prefix-stab"):
    archived: list[Message] = []
    cache_box: list[Message] = []
    stats_box: list[dict] = []
    anchor_box: list[int] = []
    built = build_history_messages(
        msgs,
        "SYSTEM-PROMPT",
        max_chars=8000,
        session_id=sid,
        history_anchor=anchor,
        archive_sink=lambda _sid, m: archived.append(m),
        cache_archive_provider="glm",
        cache_compacted_out=cache_box,
        compact_view_stats=stats_box,
        anchor_out=anchor_box,
        task_anchor_pin_user_messages=2,
        task_anchor_snapshot_provider=lambda: snapshot,
    )
    return built, anchor_box, archived


def test_anchor_block_byte_change_keeps_prefix():
    """场景1: 锚块字节变化只落尾部，其余 wire 前缀逐字节一致."""
    msgs = _fixture()
    built1, anchor_box, archived = _build(msgs)
    assert archived, "前置: 压缩真实发生（压缩态窗口，锚块在场）"
    # 第二轮: 稳态锚 + 状态已变（快照 V2）
    built2, _, archived2 = _build(msgs, anchor=anchor_box[0], snapshot=_SNAPSHOT_V2)
    assert not archived2, "前置: 第二轮稳态不再归档"
    assert built1[:-1] == built2[:-1], "锚块变化不得打穿其余 wire 前缀"
    # 尾部确实是变化的锚块本身
    assert "目标A" in str(built1[-1].get("content", ""))
    assert "目标B" in str(built2[-1].get("content", ""))


def test_compaction_reminder_round_diff_only_in_tail_anchor():
    """场景2: 压缩轮的 [锚提示] 一次性行消失，差只在尾部锚块."""
    msgs = _fixture()
    built1, anchor_box, _ = _build(msgs)
    assert "[锚提示]" in str(built1[-1].get("content", ""))
    built2, _, _ = _build(msgs, anchor=anchor_box[0])
    assert built1[:-1] == built2[:-1], "锚提示消失不得打穿其余 wire 前缀"
    assert "[锚提示]" not in str(built2[-1].get("content", ""))


def test_run_boundary_prefix_byte_stability():
    """场景3: 状态冻结时跨 build（run 边界模拟）全 wire 逐字节一致."""
    msgs = _fixture()
    built1, anchor_box, _ = _build(msgs)
    built2, _, _ = _build(msgs, anchor=anchor_box[0])
    built3, _, _ = _build(msgs, anchor=anchor_box[0])
    assert built2 == built3, "同状态 run 边界 wire 应逐字节一致"
    # 压缩轮→稳态轮锚块行差异属预期，场景2已断言，此处不做冗余弱断言。


def test_p0_prefix_disturbance_attribution(caplog):
    """场景4: P0 成因分类——appeared/byte_change/vanished 分类正确且单行日志."""
    mon = CacheHealthMonitor()
    with caplog.at_level(logging.INFO, logger="llm_loop.core.cache_health"):
        mon.note_prefix_disturbance("s-x", anchor_block_sha="aa", anchor_arg_used=0)
        mon.note_prefix_disturbance("s-x", anchor_block_sha="bb", anchor_arg_used=5, marker_fold_count=2)
        mon.note_prefix_disturbance("s-x", anchor_block_sha=None, anchor_arg_used=5)
    lines = [r for r in caplog.messages if r.startswith("[prefix-disturbance]")]
    assert len(lines) == 3  # 首轮 appeared + byte_change 轮 + vanished 轮
    assert "anchor_block_appeared" in lines[0]
    assert "anchor_block_byte_change" in lines[1] and "anchor_advance" in lines[1] and "markers_folded" in lines[1]
    assert "anchor_block_vanished" in lines[2]
    # 稳态轮（无变化）不产日志
    with caplog.at_level(logging.INFO, logger="llm_loop.core.cache_health"):
        caplog.clear()
        mon.note_prefix_disturbance("s-x", anchor_block_sha=None, anchor_arg_used=5)
    assert not [r for r in caplog.messages if r.startswith("[prefix-disturbance]")]
