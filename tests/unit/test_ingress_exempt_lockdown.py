"""antidrift 批 4: R3 任务源消息压缩豁免锁定 + 退化路径补齐（T4-1~T4-5）.

锁定对象=既有 preserve_active_ingress_message 机制（history.py :889-903 主链路 +
三条归档路径豁免）；四相邻机制（history_anchors/recent-pairs/fixed_summary/
summary_chain/hotcard）零触碰。T4-3（既有四套件零回归）由批 4 focused gate 落测。
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.core.prompt_build.stages.history_projection import run_history_projection


class _CacheMonitor:
    force_head_keep = False

    def breaker_freeze_compression(self, session_id):
        return False


def _tool_group(index: int) -> list[Message]:
    return [
        Message(
            role="assistant",
            content="",
            source=MessageSource.USER,
            tool_calls=[
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        ),
        Message(
            role="tool",
            content="X" * 300,
            source=MessageSource.TOOL,
            tool_call_id=f"call-{index}",
            tool_name="read_file",
            status=ToolResultStatus.SUCCESS,
        ),
    ]


def _project(
    base,
    *,
    current_turn_ref,
    session_id,
    frozen_run_ingress=None,
    r6_ingress_truth=None,
    sess_anchor=0,
    archive_sink=None,
):
    # T4-1/T4-2 为锁定绿：不传新参数即按 HEAD 现状运行；T4-4/T4-5 传入新参数（实现前红）
    _extra = (
        {} if frozen_run_ingress is None else {"frozen_run_ingress": frozen_run_ingress}
    )
    return run_history_projection(
        base=base,
        system_prompt="SYS",
        filtered_indices=list(range(len(base))),
        sess_anchor=sess_anchor,
        prefix_len=0,
        session_id=session_id,
        max_chars=1_100,
        runtime_history_budget_value=1_100,
        compact_ratio=0.85,
        archive_sink=archive_sink or (lambda _sid, _message: None),
        settings=SimpleNamespace(exact_duplicate_tool_fold=False),
        provider_id="glm",
        resolved_label="glm/glm-5.3",
        reasoning_tail=0,
        r6_ingress_truth=r6_ingress_truth,
        registry=SimpleNamespace(evidence_mode="off"),
        cache_monitor=_CacheMonitor(),
        effective_budget=1_100,
        current_turn_ref=current_turn_ref,
        **_extra,
    )


def _ingress_in_built(built, content: str) -> bool:
    return any(
        item.get("role") == "user" and item.get("content") == content
        for item in built
    )


def test_t4_1_ingress_survives_mid_run_compaction():
    """T4-1（锁定绿）: run 进行中触发压缩→提交视图仍含 ingress 逐字原文（真人/wake 委派参数化）."""
    for kind, metadata in (
        ("human", None),
        ("wake", {"ingress_delegated": True, "ingress_channel": "schedule_wake"}),
    ):
        ingress = Message(
            role="user",
            content=f"TASK-SOURCE-{kind}",
            source=MessageSource.USER,
            metadata=metadata,
        )
        base = [ingress]
        for index in range(5):
            base.extend(_tool_group(index))
        projection = _project(base, current_turn_ref=0, session_id=f"t4-1-{kind}")
        assert _ingress_in_built(projection.built, ingress.content), kind


def test_t4_2_new_run_turn_ref_rolls_over_old_ingress_not_pinned():
    """T4-2（锁定绿）: 新 run 新 turn_ref→旧起源不再固定、cap=1、新 ingress 为唯一豁免."""
    old_ingress = Message(role="user", content="OLD-TASK-SOURCE", source=MessageSource.USER)
    new_ingress = Message(role="user", content="NEW-TASK-SOURCE", source=MessageSource.USER)
    base = [
        *_tool_group(0),
        *_tool_group(1),
        old_ingress,
        *_tool_group(2),
        *_tool_group(3),
        new_ingress,
        *_tool_group(4),
        *_tool_group(5),
    ]
    projection = _project(base, current_turn_ref=10, session_id="t4-2-rollover")
    users = [item.get("content") for item in projection.built if item.get("role") == "user"]
    assert users.count(new_ingress.content) == 1
    assert old_ingress.content not in users


def test_t4_4_delegated_ingress_second_candidate_when_turn_ref_unresolved():
    """T4-4（先红后绿）: 退化路径（turn_ref None / index 失败）下委派 ingress 获第二候选豁免."""
    ingress = Message(
        role="user",
        content="[定时续跑·先前真人授权的程序委派·非新真人输入] DELEGATED-DEGENERATE",
        source=MessageSource.USER,
        metadata={"ingress_delegated": True, "ingress_channel": "schedule_wake"},
    )
    base = [ingress]
    for index in range(5):
        base.extend(_tool_group(index))

    # 变体1: current_turn_ref 为 None（host 未能解析 turn 身份）
    projection = _project(
        base, current_turn_ref=None, session_id="t4-4-none", frozen_run_ingress=ingress
    )
    assert _ingress_in_built(projection.built, ingress.content)

    # 变体2: ref 指向不在 filtered_indices 的下标（index() 失败 → _current_filtered_pos=-1）
    projection_b = _project(
        base, current_turn_ref=99, session_id="t4-4-miss", frozen_run_ingress=ingress
    )
    assert _ingress_in_built(projection_b.built, ingress.content)


def test_t4_5_exemption_resolution_failure_fail_open(monkeypatch):
    """T4-5（先红后绿）: 豁免解析异常→压缩照常（fail-open），archive 仍有稳定 ref."""
    def _raise(message):
        raise RuntimeError("ingress-probe-boom")

    monkeypatch.setattr(
        "llm_loop.core.prompt_build.stages.history_projection.is_active_run_ingress_message",
        _raise,
    )
    ingress = Message(
        role="user",
        content="FAIL-OPEN-SOURCE",
        source=MessageSource.USER,
    )
    base = [ingress]
    for index in range(5):
        base.extend(_tool_group(index))
    archived: list[Message] = []
    projection = _project(
        base,
        current_turn_ref=None,
        session_id="t4-5-fail-open",
        frozen_run_ingress=ingress,
        archive_sink=lambda _sid, message: archived.append(message),
    )
    assert isinstance(projection.built, list) and projection.built  # 压缩照常产出
    assert archived  # archive_sink 收到被归档消息（稳定 ref 通道仍在工作）
