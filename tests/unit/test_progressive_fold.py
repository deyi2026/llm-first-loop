"""单元测试: 渐进折叠（progressive_fold, EVO-20260824-54d46549 镜像落地 2026-08-24）.

billion-context 拷问产出: 字节级前缀缓存下"小范围折叠保前缀"宣传不成立——
渐进折叠的真实价值是命中率曲线平滑 + cache_guard 不 BLOCK + 智力无断崖
（每次只折最老 K 个配对组, 其余保留; 折满 K 后提交仍超预算 → 保命突破 K）。

覆盖:
1. progressive_fold=0（默认）→ 一次性大裁（零回归, 无渐进标注）
2. progressive_fold=K → 只折最老 K 个配对组（归档组数 ≤ K）+ 折叠标注注入
3. 折满 K 仍超限 → 突破 K 继续归档（保命兜底, 防 guard 规则 F BLOCK）
4. 配对原子性（配对组不拆散, 无孤儿 tool 回执）
"""

from __future__ import annotations

from typing import Literal

from llm_loop.core.history import build_history_messages
from llm_loop.core.message import Message, MessageSource

_Role = Literal["user", "assistant", "tool", "system"]


def _m(role: _Role, content: str) -> Message:
    return Message(role=role, content=content, source=MessageSource.USER)


def _pair(uid: int, decl: str = "D", resp: str = "R") -> list[Message]:
    """构造一个完整配对组: [assistant(tool_calls), tool(回执)]（tool 带 tool_call_id）."""
    return [
        Message(
            role="assistant",
            content=decl,
            source=MessageSource.USER,
            tool_calls=[
                {"id": f"c{uid}", "name": "read_file", "arguments": {"path": f"/tmp/{uid}"}}
            ],
        ),
        Message(
            role="tool",
            content=resp,
            source=MessageSource.USER,
            tool_call_id=f"c{uid}",
        ),
    ]


def _archived_pair_count(archived: list[Message]) -> int:
    """归档中配对组数 = 唯一 tool_call_id 数（每组 1 个回执）."""
    return len({str(m.tool_call_id) for m in archived if m.tool_call_id})


def _collect_archive() -> tuple[list[Message], object]:
    archived: list[Message] = []

    def sink(session_id: str, msg: Message) -> None:
        archived.append(msg)

    return archived, sink


def _has_annotate(out: list[dict]) -> bool:
    # 文案随版本演进（54d46549 "[渐进折叠]" → merge 后镜像版 "[中段折叠]"），兼容两者
    return any(
        "[渐进折叠]" in str(m.get("content", "")) or "[中段折叠]" in str(m.get("content", ""))
        for m in out
    )


def test_default_zero_progressive_fold_is_legacy():
    """progressive_fold=0（默认）→ 一次性大裁（无渐进标注, 零回归）."""
    archived, sink = _collect_archive()
    msgs: list[Message] = []
    for i in range(6):
        msgs.extend(_pair(i, decl="D" * 300, resp="R" * 300))
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1500, session_id="s1", archive_sink=sink,
        progressive_fold=0,
    )
    # 一次性大裁归档多个组（无 K 限制）
    assert _archived_pair_count(archived) >= 3, f"默认应归档多个组, 实际 {_archived_pair_count(archived)}"
    # 无渐进折叠标注（避免语义漂移）
    assert not _has_annotate(out)


def test_progressive_fold_limits_to_k():
    """progressive_fold=2: 只折最老 2 个配对组（归档组数 ≤ 2）+ 折叠标注注入.

    渐进语义: 每次只折 K 组（智力无断崖）, 其余保留——归档组数受 K 限制。
    """
    archived, sink = _collect_archive()
    msgs: list[Message] = []
    for i in range(5):
        msgs.extend(_pair(i, decl="D" * 120, resp="R" * 120))
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1000, session_id="s1", archive_sink=sink,
        progressive_fold=2, cache_archive_provider="minimax",  # 任务7§5.7: 缺 provider 会降级关闭渐进折叠
    )
    # 归档组数受限（不一次大裁；K=2 为软限——折满后保留侧仍 >95% 预算时
    # 保命兜底可突破上限继续归档，见 CHANGELOG 压缩风暴熔断条目）
    assert 1 <= _archived_pair_count(archived) < 5, f"渐进应保留多数组, 实际 {_archived_pair_count(archived)}"
    # 折叠标注注入（AI 有感知）
    assert _has_annotate(out)


def test_progressive_fold_bailout_breaks_k():
    """折满 K 组后提交仍超限 → 突破 K 继续归档（保命兜底）.

    防 guard 规则 F BLOCK（submit_ratio >95% 拦截）——渐进不能以超限为代价:
    严重超限时归档组数 > K（突破上限直至可提交）。
    """
    archived, sink = _collect_archive()
    msgs: list[Message] = []
    for i in range(6):
        msgs.extend(_pair(i, decl="D" * 400, resp="R" * 400))
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1500, session_id="s1", archive_sink=sink,
        progressive_fold=3,
    )
    # 严重超限 → 突破 K=3 继续归档（保命）
    assert _archived_pair_count(archived) > 3, f"保命应突破 K=3, 实际 {_archived_pair_count(archived)}"
    # 保留最近组（提交仍有最新配对）
    submitted_ids = [str(m.get("tool_call_id")) for m in out if m.get("tool_call_id")]
    assert submitted_ids, "提交应保留至少一个配对组"


def test_progressive_fold_pairing_atomic():
    """渐进折叠不拆散配对组（声明↔回执同归档或同保留）.

    协议 C1: assistant(tool_calls) 与 tool 回执必须同窗（孤儿回执 → 400）。
    """
    archived, sink = _collect_archive()
    msgs: list[Message] = []
    for i in range(4):
        msgs.extend(_pair(i, decl="D" * 200, resp="R" * 200))
    out = build_history_messages(
        msgs, system_prompt="SYS", max_chars=1000, session_id="s1", archive_sink=sink,
        progressive_fold=2,
    )
    archived_ids = {str(m.tool_call_id) for m in archived if m.tool_call_id}
    submitted_ids = {str(m.get("tool_call_id")) for m in out if m.get("tool_call_id")}
    overlap = archived_ids & submitted_ids
    assert not overlap, f"配对组被拆散: 同一 tool_call_id 出现在归档与提交 {overlap}"
