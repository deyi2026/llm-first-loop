"""run_stream 跨 contextvars.Context 驱动回归：直驱 SSE 不能丢 run 上下文。"""

from __future__ import annotations

import contextvars
import itertools

from llm_loop.core.run_context import (
    current_model_label,
    current_reasoning_effort,
    current_session_id,
    current_workspace_root,
)
from llm_loop.llm.client import LLMResponse, StreamDelta


def _next_result(ctx: contextvars.Context, stream):
    try:
        ctx.run(next, stream)
    except StopIteration as exc:
        return exc.value
    raise AssertionError("stream 应已结束")


def test_run_stream_reseeds_context_on_cross_context_resume(build_test_engine, tmp_path):
    engine, fake = build_test_engine([])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine.workspace_root = str(workspace)
    seen: list[tuple[str, str, str, str]] = []

    def snapshot() -> None:
        seen.append((
            current_session_id.get(),
            current_workspace_root.get(),
            current_reasoning_effort.get(),
            current_model_label.get(),
        ))

    def chat_stream(**_kwargs):
        # Fake 默认 planned label 在该测试装配下可为空；显式写入哨兵，验证 wrapper
        # 会在第一个 yield 后捕获，并在另一个 Context 的下一次 resume 前恢复。
        current_model_label.set("sentinel/model")
        snapshot()
        yield StreamDelta(text="A")
        snapshot()
        yield StreamDelta(text="B")
        return LLMResponse(content="AB", tool_calls=[], provider="fake")

    fake.chat_stream = chat_stream
    sid = engine.session.create()
    stream = engine.run_stream(sid, "hello", reasoning_effort="medium")
    ctx1, ctx2, ctx3 = contextvars.Context(), contextvars.Context(), contextvars.Context()

    assert ctx1.run(next, stream).text == "A"
    assert ctx1.run(current_session_id.get) == ""
    assert ctx1.run(current_workspace_root.get) == ""
    assert ctx1.run(current_reasoning_effort.get) == ""
    assert ctx1.run(current_model_label.get) == ""

    assert ctx2.run(next, stream).text == "B"
    assert ctx2.run(current_session_id.get) == ""
    assert ctx2.run(current_workspace_root.get) == ""
    result = _next_result(ctx3, stream)
    assert result.final_answer == "AB"

    assert len(seen) == 2
    for got_sid, got_ws, got_effort, got_model in seen:
        assert got_sid == sid
        assert got_ws == str(workspace)
        assert got_effort == "medium"
        assert got_model == "sentinel/model"
    assert seen[0][3] == seen[1][3]


def test_cross_context_close_preserves_disconnect_save_and_releases_lease(
    build_test_engine,
):
    engine, fake = build_test_engine([])

    def chat_stream(**_kwargs):
        for i in itertools.count():
            yield StreamDelta(text=f"片段{i} ")
        return LLMResponse(content="never", tool_calls=[], provider="fake")

    fake.chat_stream = chat_stream
    sid = engine.session.create()
    stream = engine.run_stream(sid, "long answer", reasoning_effort="low")
    ctx1, ctx2 = contextvars.Context(), contextvars.Context()
    assert ctx1.run(next, stream).text.startswith("片段0")

    ctx2.run(stream.close)
    assert ctx2.run(current_session_id.get) == ""
    assert ctx2.run(current_reasoning_effort.get) == ""

    stored = engine.session.load(sid)
    assistants = [m for m in stored.messages if m.role == "assistant"]
    assert assistants
    assert "片段0" in assistants[-1].content
    assert "中断" in assistants[-1].content or "不完整" in assistants[-1].content
    with engine.session.run_lease(sid) as acquired:
        assert acquired is True, "跨 Context close 后 whole-run lease 必须释放"
