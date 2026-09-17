"""EVO-20260916-ccc978b2（人工已审）: 压缩触发时任务锚点强制 pinning.

验收标准（建议原文）:
  1. 最近 N≥2 条用户消息原文在压缩后首个请求中逐字在场;
  2. Goal objective 文本在场（任务锚快照）;
  3. 事件流出现 history.compaction 且记录 pinned/summarized idx 范围;
  4. 直连调用默认参数零回归（N=0 且无 provider → 既有行为）。
"""

from __future__ import annotations

import pytest

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource


@pytest.fixture(autouse=True)
def _pin_compact_ratio_env(monkeypatch: pytest.MonkeyPatch):
    """同 test_compact_observability_r817: 阈值依赖 COMPACT_RATIO，显式钉住防环境漂移."""
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


def _user(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def _fixture() -> list[Message]:
    """锚区可容纳 + 总历史超限的体量布局.

    max_chars=8000: 锚区(锚B→最新端)约 6k chars < 8000（不触发既有"锚区超窗"
    退化防御）；总历史约 15k > 8000（真实触发压缩，锚A 被折叠）。
    """
    msgs: list[Message] = []
    msgs.append(_user("原始任务指令-锚A-把仓库迁移到新域名并验证 9f2a"))
    for i in range(18):
        msgs.extend(_pair(i))
    msgs.append(_user("第二条用户指令-锚B-先跑全量测试再动手 8b31"))
    for i in range(18, 28):
        msgs.extend(_pair(i))
    msgs.append(_user("最新用户指令-锚C-现在开始执行并汇报 7c04"))
    msgs.extend(_pair(99))
    return msgs


_SNAPSHOT = (
    "[Goal G-77] objective: 验收目标-OBJ9f：完成迁移且锚点存活\n"
    "[Checkpoint] 已核对仓库当前状态 | next: 执行迁移\n"
    "[Frontier] tasks: 2 open / 1"
)


def test_pin_last_two_user_messages_and_snapshot_survive_compaction():
    msgs = _fixture()
    idx_b = next(i for i, m in enumerate(msgs) if "锚B" in m.content)
    idx_c = next(i for i, m in enumerate(msgs) if "锚C" in m.content)
    archived: list[Message] = []
    cache_box: list[Message] = []
    stats_box: list[dict] = []
    anchor_box: list[int] = []

    built = build_history_messages(
        msgs,
        "SYSTEM-PROMPT",
        max_chars=8000,
        session_id="s-anchor-pin",
        archive_sink=lambda _sid, m: archived.append(m),
        cache_archive_provider="glm",
        cache_compacted_out=cache_box,
        compact_view_stats=stats_box,
        anchor_out=anchor_box,
        task_anchor_pin_user_messages=2,
        task_anchor_snapshot_provider=lambda: _SNAPSHOT,
    )
    view = "\n".join(str(m.get("content", "")) for m in built)

    # ① 压缩真实发生（旧指令被折叠，而非全量保留的空转）
    assert archived, "应发生归档压缩"
    assert "锚A" not in view, "最旧用户指令应被折叠（证明压缩非空转）"
    # ② 最近 2 条用户消息原文逐字在场
    assert "第二条用户指令-锚B-先跑全量测试再动手 8b31" in view
    assert "最新用户指令-锚C-现在开始执行并汇报 7c04" in view
    assert not any("锚B" in m.content or "锚C" in m.content for m in archived)
    # ③ 任务锚快照（Goal objective 逐字）+ 压缩轮一次性锚提示
    assert "验收目标-OBJ9f：完成迁移且锚点存活" in view
    assert "[任务锚点" not in view  # 直连 provider 不加头（engine 侧才加头）
    assert "[锚提示]" in view
    # ④ stats 携带 pinned 局部索引（base 编号=直连调用即列表位置）
    assert stats_box[0]["pinned_msg_seqs_local"] == [idx_b, idx_c]
    assert stats_box[0]["pinned_user_message_count"] == 2
    # EVO-20260917-2f5ae9cb P1: 锚块在 wire 尾部（而非首个非 system 位）——
    # 头部插入时锚块字节变化会打穿其后全部历史前缀，移尾部后变化只落末尾。
    # 直连调用不加 engine 侧头，锚块即 _SNAPSHOT 原文（+ 压缩轮一次性锚提示行）。
    last = built[-1]
    assert str(last.get("content", "")).startswith("[Goal G-77]")
    assert "验收目标-OBJ9f" in str(last.get("content", ""))


def test_steady_state_round_after_compaction_keeps_snapshot_without_reminder():
    msgs = _fixture()
    archived: list[Message] = []
    cache_box: list[Message] = []
    stats_box: list[dict] = []
    anchor_box: list[int] = []

    build_history_messages(
        msgs,
        "SYSTEM-PROMPT",
        max_chars=8000,
        session_id="s-anchor-pin-2",
        archive_sink=lambda _sid, m: archived.append(m),
        cache_archive_provider="glm",
        cache_compacted_out=cache_box,
        compact_view_stats=stats_box,
        anchor_out=anchor_box,
        task_anchor_pin_user_messages=2,
        task_anchor_snapshot_provider=lambda: _SNAPSHOT,
    )
    # 第二轮：锚点已前移（压缩稳态），本轮无需再归档
    built2 = build_history_messages(
        msgs,
        "SYSTEM-PROMPT",
        max_chars=8000,
        session_id="s-anchor-pin-2",
        history_anchor=anchor_box[0],
        archive_sink=lambda _sid, m: archived.append(m),
        cache_archive_provider="glm",
        task_anchor_pin_user_messages=2,
        task_anchor_snapshot_provider=lambda: _SNAPSHOT,
    )
    view2 = "\n".join(str(m.get("content", "")) for m in built2)
    # 快照持续在场（稳态不消失），但一次性锚提示不再重复
    assert "验收目标-OBJ9f" in view2
    assert "[锚提示]" not in view2


def test_postprocess_event_records_pinned_and_summarized_ranges():
    from types import SimpleNamespace

    from llm_loop.core.prompt_build.stages.history_postprocess import run_history_postprocess

    class _Monitor:
        def note_build_result(self, **_kwargs):
            return None

        def note_anchor_moved(self, **_kwargs):
            return None

    events: list[tuple[str, dict]] = []
    sess = SimpleNamespace(
        session_id="s-compact-event-pin",
        messages=[Message(role="user", content="u", source=MessageSource.USER)],
        history_anchors={"glm": 0},
    )
    stats = {
        "trigger": "projected_history_over_compact_limit",
        "pre_history_chars": 1100,
        "pre_chars": 1200,
        "post_chars": 700,
        "drop_pct": 41.7,
        "effective_budget_chars": 1000,
        "compact_ratio": 1.0,
        "trigger_limit_chars": 1000,
        "trigger_excess_chars": 100,
        "archive_target_ratio": 0.6,
        "archive_target_chars": 600,
        "archived_count": 3,
        "archived_group_count": 2,
        "atomic_group_count": 8,
        "compaction_mode": "provider_contiguous_oldest",
        "head_keep_chars": 200,
        "head_keep_target_ratio": 0.5,
        "cache_boundary_mode": "epoch_reset",
        "cache_protected_messages": 2,
        "cache_protected_chars": 180,
        # EVO-20260916-ccc978b2（projection 段映射后字段）
        "pinned_msg_seqs": [7, 12],
        "pinned_user_message_count": 2,
        "summarized_msg_seqs": [1, 2, 3, 4, 5, 6],
    }
    out = run_history_postprocess(
        cache_compacted_source_box=[],
        compacted_box=[True],
        compact_view_box=[stats],
        anchor_box=[1],
        filtered_indices=[0],
        prefix_len=0,
        sess=sess,
        sess_anchor=0,
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        effective_budget=1000,
        compact_event_seq=4,
        compact_event_was_compacted=False,
        cache_monitor=_Monitor(),
        event_append=lambda _sid, typ, payload: events.append((typ, payload)),
        provider_visible_chars=lambda *_args: 1,
    )
    assert out.compact_event_seq == 5
    event = next(payload for typ, payload in events if typ == "history.compaction")
    assert event["compaction_epoch"] == 5
    # pinned（锚钉存活）/ summarized（被折叠）原 session 索引显式在场
    assert event["pinned_msg_seqs"] == [7, 12]
    assert event["pinned_user_message_count"] == 2
    assert event["summarized_msg_seqs"] == [1, 2, 3, 4, 5, 6]


def test_direct_call_defaults_zero_regression():
    """直连默认参数（N=0、无 provider）→ 既有行为，无锚块、无 pinned 字段干扰."""
    msgs = _fixture()
    archived: list[Message] = []
    cache_box: list[Message] = []
    stats_box: list[dict] = []
    anchor_box: list[int] = []

    built = build_history_messages(
        msgs,
        "SYSTEM-PROMPT",
        max_chars=8000,
        session_id="s-zero-reg",
        archive_sink=lambda _sid, m: archived.append(m),
        cache_archive_provider="glm",
        cache_compacted_out=cache_box,
        compact_view_stats=stats_box,
        anchor_out=anchor_box,
    )
    view = "\n".join(str(m.get("content", "")) for m in built)
    assert archived, "压缩仍应发生"
    # 既有语义：仅最后一条真实用户指令受锚组保护；倒数第二条可被折叠
    assert "锚C" in view
    assert "[锚提示]" not in view
    if stats_box:
        # N=0 时 pinned 审计仍如实记录既有锚组保护（最后一条真实 user 指令）
        idx_c = next(i for i, m in enumerate(msgs) if "锚C" in m.content)
        assert stats_box[0]["pinned_msg_seqs_local"] == [idx_c]
        assert stats_box[0]["pinned_user_message_count"] == 0
