"""_ThinkTagStreamParser 流首限制回归（2026-09-05 中段字面 <think> 误分流修复）.

背景: 正文中间出现字面 `<think>`（引用/示例代码）曾被当作开标签翻转，
导致其后整段正文误入 reasoning、content 丢失。修复后开标签仅在
「尚未产出任何段落且其前仅有空白」时生效，中段字面按原文透传并打审计日志。

分段粒度由 SSE delta 边界决定（feed 每次只吐安全前缀），故关键断言按
kind 拼接校验；流首基线另保留精确分段断言锁定原行为。
"""

from __future__ import annotations

from llm_loop.llm.client import _ThinkTagStreamParser


def _feed_all(chunks: list[str]) -> list[tuple[str, str]]:
    parser = _ThinkTagStreamParser()
    out: list[tuple[str, str]] = []
    for chunk in chunks:
        out.extend(parser.feed(chunk))
    out.extend(parser.flush())
    return out


def _joined(chunks: list[str]) -> dict[str, str]:
    out = _feed_all(chunks)
    return {
        kind: "".join(text for k, text in out if k == kind)
        for kind in ("reasoning", "content")
    }


def test_leading_think_still_splits() -> None:
    """流首思考段保持原分流语义与分段（回归基线）."""
    assert _feed_all(["<think>abc</think>", "answer"]) == [
        ("reasoning", "abc"),
        ("content", "answer"),
    ]


def test_leading_think_with_blank_prefix() -> None:
    """前导空白不破坏流首识别."""
    assert _feed_all(["\n\n<think>abc</think>ok"]) == [
        ("content", "\n\n"),
        ("reasoning", "abc"),
        ("content", "ok"),
    ]


def test_split_across_deltas() -> None:
    """标签跨任意 SSE 分片仍正确识别（回归基线）."""
    joined = _joined(["<thi", "nk>par", "tial</thi", "nk>done"])
    assert joined == {"reasoning": "partial", "content": "done"}


def test_midstream_literal_open_tag_kept_as_content() -> None:
    """修复主场景: 正文中的字面 <think> 不再吞掉后续正文."""
    joined = _joined(["answer part1 <think> fake", " answer part2"])
    assert joined == {"reasoning": "", "content": "answer part1 <think> fake answer part2"}


def test_midstream_literal_split_across_deltas() -> None:
    """跨分片拼出的中段字面 <think> 同样被拒（emitted 窗口的关键用例）."""
    joined = _joined(["use <think> to toggle: <th", "ink> stays literal"])
    assert joined == {"reasoning": "", "content": "use <think> to toggle: <think> stays literal"}


def test_second_open_tag_with_close_follows_tag_semantics() -> None:
    """完整标签对仍按标签语义分流（与旧行为一致；无法与真二次思考区分）."""
    joined = _joined(["<think>real</think>see <think>code</think>?"])
    assert joined == {"reasoning": "realcode", "content": "see ?"}


def test_prefixed_think_with_close_still_splits() -> None:
    """M3「正文前缀+<think>...[</think>」形态: 有配对闭合则照常分流."""
    joined = _joined(["前缀<think>秘密推理</think>答案"])
    assert joined == {"reasoning": "秘密推理", "content": "前缀答案"}


def test_prefixed_think_without_close_is_literal() -> None:
    """同形态但无闭合: 整段（含标签）回吐正文，reasoning 不吞正文."""
    joined = _joined(["前缀<think>没有闭合的正文继续走"])
    assert joined == {"reasoning": "", "content": "前缀<think>没有闭合的正文继续走"}


def test_pending_overflow_falls_back_to_literal(monkeypatch) -> None:
    """无闭合且超限: 放弃等待按字面吐出，不再无限积压."""
    import llm_loop.llm.client as client_mod

    monkeypatch.setattr(client_mod, "_THINK_PENDING_LIMIT", 10)
    joined = _joined(["hi <think>", "0123456789", "abc"])
    assert joined == {"reasoning": "", "content": "hi <think>0123456789abc"}


def test_empty_think_then_literal() -> None:
    """空思考后紧跟的字面 <think> 不误翻（翻转亦关闭流首窗口）."""
    joined = _joined(["<think></think>", "<th", "ink>x"])
    assert joined == {"reasoning": "", "content": "<think>x"}


def test_literal_no_content_loss_regression() -> None:
    """端到端口径: 修复前该场景 content 全丢、正文整段进 reasoning."""
    joined = _joined(["Here is the plan. <think>For example...", "step 2 continues"])
    assert joined == {
        "reasoning": "",
        "content": "Here is the plan. <think>For example...step 2 continues",
    }


def test_unclosed_leading_tag_is_chunk_invariant_and_literal() -> None:
    """前导空白是否独立成 delta，不得改变同一字节流的归属。"""
    whole = _joined(["\n\n<think>未闭合正文"])
    split = _joined(["\n\n", "<th", "ink>未闭合正文"])
    assert whole == split == {"reasoning": "", "content": "\n\n<think>未闭合正文"}
