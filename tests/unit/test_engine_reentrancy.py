"""P0-5(2026-08-15): LoopEngine 可重入（审计发现 #7）.

背景：Web 端单引擎实例并发服务多会话（"同会话串行，不同会话并行"），
引擎/注册表/修正上下文的 per-run 可变状态原为实例属性 → 跨会话并发 run 串台
（停滞指纹互染、预警互吞、超长归档/变更日志归错会话、switch_model 写错 sess）。

修复机制：contextvars（run_context.current_session_id）+ per-session 状态桶
（engine._run_states）+ execute_many 只读池 copy_context 逐任务传播。

本测试覆盖四个层面：
1. 属性 shim 机制隔离（contextvar 分桶单元验证）
2. registry._session_id contextvar 优先 + 只读池传播
3. 两会话并发 run 端到端：停滞状态互不污染、超长归档归属正确
4. switch_model override 绑定按会话解析（不互踩回调）
"""

from __future__ import annotations

import threading

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.llm.client import LLMResponse
from llm_loop.tools.registry import ToolRegistry


# ── 1. 机制单元：属性 shim 按 contextvar 分桶 ──
def test_run_state_buckets_isolated_by_contextvar(build_test_engine):
    engine, _fake = build_test_engine([LLMResponse(content="ok", tool_calls=[], provider="fake")])

    token = current_session_id.set("sess-a")
    try:
        engine._stagnation_state["count"] = 7
        engine._overflow_reinject_count = 1

        other: list = []
        barrier = threading.Barrier(2)

        def _in_b() -> None:
            current_session_id.set("sess-b")
            # B 桶不受 A 污染
            other.append(engine._stagnation_state["count"])
            other.append(engine._overflow_reinject_count)
            engine._stagnation_state["count"] = 2
            barrier.wait()

        t = threading.Thread(target=_in_b)
        t.start()
        barrier.wait()
        # A 桶保持 A 的写入（B 的写入不影响）
        assert engine._stagnation_state["count"] == 7
        t.join()
        assert other == [0, 0], f"B 桶读到 A 的停滞/overflow 状态: {other}"
        assert engine._run_states["sess-b"].stagnation_state["count"] == 2
    finally:
        current_session_id.reset(token)


# ── 2. registry._session_id：contextvar 优先 + 只读池传播 ──
def test_registry_session_id_contextvar_precedence():
    reg = ToolRegistry()
    reg.set_session_id("explicit-sid")
    assert reg._session_id == "explicit-sid"
    token = current_session_id.set("ctx-sid")
    try:
        assert reg._session_id == "ctx-sid"
    finally:
        current_session_id.reset(token)
    assert reg._session_id == "explicit-sid"


class _SessionProbeTool:
    """只读探针工具（命名 read_file 命中 _READONLY_TOOLS 走池线程）：记录执行时的 contextvar."""

    name = "read_file"
    description = "探针"
    parameters = {"type": "object", "properties": {}, "required": []}

    seen: list[str] = []

    def execute(self, **kwargs):
        type(self).seen.append(current_session_id.get())
        return ToolResult(
            status=ToolResultStatus.SUCCESS, content="ok", tool_call_id="", tool_name=self.name
        )


def test_execute_many_propagates_session_context_to_pool():
    _SessionProbeTool.seen = []
    reg = ToolRegistry()
    reg.register(_SessionProbeTool())
    token = current_session_id.set("probe-sid")
    try:
        results = reg.execute_many([ToolCall(id="c1", name="read_file", arguments={})])
    finally:
        current_session_id.reset(token)
    assert results[0].status == ToolResultStatus.SUCCESS
    assert _SessionProbeTool.seen == ["probe-sid"], (
        f"只读池线程未继承会话上下文: {_SessionProbeTool.seen}"
    )


# ── 3. 两会话并发 run 端到端（共享单引擎，模拟 Web 并发）──
def _make_files(tmp_path):
    small = tmp_path / "data" / "x.txt"
    small.write_text("小文件", encoding="utf-8")
    big = tmp_path / "data" / "y.txt"
    big.write_text("y" * 13000, encoding="utf-8")  # 超 summary_threshold(12000，2026-08-15 新默认) 触发归档


def test_concurrent_runs_isolated_state_and_archive(build_test_engine, tmp_path):
    """A 会话反复同参数工具调用（触停滞）；B 会话一次工具调用（超长输出触发归档）后即答.

    断言:
    - B 正常完成（不被 A 的停滞熔断串台）
    - A/B 的停滞桶各自独立
    - B 的超长输出归档到 B 会话（不经串台的 registry._session_id 落到 A）
    """
    _make_files(tmp_path)
    x_path = str(tmp_path / "data" / "x.txt")  # 绝对路径（工具以 CWD 解析相对路径）
    y_path = str(tmp_path / "data" / "y.txt")

    def brancher(calls):
        msgs = calls[-1]["messages"]
        first_user = next((m for m in msgs if m.get("role") == "user"), {})
        marker = first_user.get("content", "")
        n = len(calls)
        if marker.startswith("A"):
            # A：每次重复同一工具同一参数（停滞模式），并稍作停顿保证并发窗口
            import time

            time.sleep(0.05)
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id=f"call_a_{n}", name="read_file",
                                     arguments={"path": x_path})],
                provider="fake",
            )
        # B：首轮调工具（大文件），第二轮给最终回答
        has_tool = any(m.get("role") == "tool" for m in msgs)
        if not has_tool:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="call_b_1", name="read_file",
                                     arguments={"path": y_path})],
                provider="fake",
            )
        return LLMResponse(content="B 完成", tool_calls=[], provider="fake")

    engine, _fake = build_test_engine([brancher] * 40)  # FakeLLM 逐次弹出响应，brancher 需足量
    sid_a = engine.session.create()
    sid_b = engine.session.create()
    results: dict[str, object] = {}
    errors: list[Exception] = []

    def _run(sid: str, text: str, key: str) -> None:
        try:
            results[key] = engine.run(sid, text)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t_a = threading.Thread(target=_run, args=(sid_a, "A 任务", "a"))
    t_b = threading.Thread(target=_run, args=(sid_b, "B 任务", "b"))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    assert not errors, f"并发 run 抛异常: {errors[:2]}"

    res_b = results["b"]
    assert res_b.final_answer == "B 完成", f"B 被串台（停滞熔断/预警互吞）: {res_b.final_answer[:120]}"
    assert res_b.rounds == 2, f"B 轮数异常: {res_b.rounds}"

    # 停滞桶按会话独立：A 触发提醒/熔断（count>=3），B 干净
    assert engine._run_states[sid_a].stagnation_state["count"] >= 3
    assert engine._run_states[sid_b].stagnation_state["count"] <= 1

    # B 的超长输出归档到 B 会话（contextvar 传播进只读池线程）
    stats_b = engine.archive.stats(sid_b)
    stats_a = engine.archive.stats(sid_a)
    assert stats_b["archived_count"] >= 1, f"B 的超长输出未归档: {stats_b}"
    assert stats_a["archived_count"] == 0, f"B 的归档串台落入 A: {stats_a}"


# ── 4. switch_model override 绑定按会话解析 ──
def test_override_binding_resolves_per_session(build_test_engine):
    """两会话各有绑定：resolver(sid) 返回对应 sess 的 getter/setter，互不串台."""
    engine, _fake = build_test_engine([LLMResponse(content="ok", tool_calls=[], provider="fake")])
    sid_a = engine.session.create()
    sid_b = engine.session.create()

    # 模拟两次 run 的装配（run_stream 内部行为）
    sess_a = engine.session.load(sid_a)
    engine._run_sessions[sid_a] = sess_a
    sess_b = engine.session.load(sid_b)
    engine._run_sessions[sid_b] = sess_b

    binding_a = engine._resolve_session_binding(sid_a)
    binding_b = engine._resolve_session_binding(sid_b)
    assert binding_a is not None and binding_b is not None

    binding_a[1]("minimax/MiniMax-M3")  # setter
    assert sess_a.model_override == "minimax/MiniMax-M3"
    assert sess_b.model_override is None, "A 的 switch_model 串台写入 B 的 sess"
    assert binding_a[0]() == "minimax/MiniMax-M3"
    assert binding_b[0]() is None
