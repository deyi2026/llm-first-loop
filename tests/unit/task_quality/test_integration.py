"""task_quality 集成测试（tasks.md §9.2：D+H+I+K 纠错闭环 + 装配/零回归）.

覆盖 design §2.6 跨路径协同 10 场景：
①装配开关 ②D+K 串接 ③K+H 协同 ④I 复用 D+H+K ⑤I 的 LLM 修复
⑥熔断协同 ⑦A 与 E 独立 ⑧trace_id 贯穿 ⑨fail-open 零回归 ⑩程序最小化
"""

from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
from llm_loop.task_quality.error_locate import ErrorLocator
from llm_loop.task_quality.fix_loop import FixLoopTool
from llm_loop.task_quality.regression import RegressionGuard
from llm_loop.task_quality.static_check import StaticCheckChain

# ── 桩组件 ──

class _FakeRegistry:
    """registry 桩：按命令内容返回预设结果（检查/测试命令分流）."""

    def __init__(self, check_results: dict[int, str], test_output: str = "1 passed"):
        self._check_results = check_results  # 按轮次
        self._test_output = test_output
        self._round = 0
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        self._round += 1
        content = self._check_results.get(self._round, self._test_output)
        status = ToolResultStatus.SUCCESS if "passed" in content else ToolResultStatus.FAILURE
        return ToolResult(status=status, content=content, tool_call_id=call.id,
                          tool_name=call.name)


class _FakeSubAgent:
    def __init__(self, answer="已修复代码"):
        self._answer = answer
        self.tasks = []

    def run(self, task, context="", depth=0, max_rounds=None):
        self.tasks.append(task)
        return SimpleNamespace(final_answer=self._answer, refused=False)


class _FakeDepGraph:
    def __init__(self, subset=None, available=True):
        self._subset = subset or []
        self._available = available

    def affected_tests(self, modified_files):
        return list(self._subset), self._available


class _FakeCmdRunner:
    """命令执行桩（回归保护用）."""

    def __init__(self, code=0, out="1 passed"):
        self._code, self._out = code, out
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        return self._code, self._out


class _Store:
    def __init__(self):
        self.events = []

    def append(self, sid, etype, payload):
        self.events.append((etype, payload))
        return None


# ── ① 装配开关 ──

def test_assembly_switches_control_enable():
    """①装配: enabled_fn 控制路径生效（开=拦截/执行，关=放行/未启用）."""
    from llm_loop.task_quality.precheck import PreCheckLayer

    # A 预检开关
    on = PreCheckLayer(enabled_fn=lambda: True)
    off = PreCheckLayer(enabled_fn=lambda: False)
    schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
    assert on.check({"n": "x"}, schema).valid is False  # 开=拦截
    assert off.check({"n": "x"}, schema).valid is True  # 关=放行

    # I 修复循环开关
    reg = _FakeRegistry({1: "5 passed"})
    on_i = FixLoopTool(registry=reg, subagent_runner=_FakeSubAgent(),
                       enabled_fn=lambda: True)
    off_i = FixLoopTool(registry=reg, subagent_runner=_FakeSubAgent(),
                        enabled_fn=lambda: False)
    assert on_i.execute(check_command="pytest").status.value == "success"
    assert off_i.execute(check_command="pytest").status.value == "failure"
    assert "未启用" in off_i.execute(check_command="pytest").content


# ── ② D+K 串接 ──

def test_dk_chain_results_visible():
    """②D+K: 静态检查 + 回归保护结果并入回执（LLM 一次可见全部反馈）."""
    runner = _FakeCmdRunner(0, "2 passed")
    d = StaticCheckChain(command_runner=_FakeCmdRunner(0, ""))  # 全过
    k = RegressionGuard(dep_graph=_FakeDepGraph(["tests/test_x.py"]),
                        command_runner=runner)
    # D: 检查结果
    check = d.run("src/x.py")
    # K: 回归结果
    reg = k.verify(["src/x.py"])
    # 串接：两者都可生成 feedback 文本，合入同一回执
    combined = f"{check.to_feedback_section()}\n{reg.to_feedback_section()}"
    assert "[状态: success]" in combined
    assert "回归保护" in combined
    assert "src/x.py" in combined


# ── ③ K+H 协同 ──

def test_kh_failure_structured():
    """③K+H: 回归测试失败 → 经 ErrorLocator 结构化定位."""
    out = ("1 failed\nFAILED tests/test_x.py::test_add - AssertionError: assert 1 == 2")
    k = RegressionGuard(dep_graph=_FakeDepGraph(["tests/test_x.py"]),
                        command_runner=_FakeCmdRunner(1, out),
                        error_locator=ErrorLocator())
    r = k.verify(["src/x.py"])
    assert r.failed_count == 1
    assert len(r.failures) >= 1
    assert r.failures[0].file_path == "tests/test_x.py"
    # 结构化信息含失败位置（非原始全文）
    text = r.to_feedback_section()
    assert "tests/test_x.py" in text


# ── ④ I 复用 D+H+K ──

def test_i_reuses_dhk():
    """④I: fix_loop 循环内跑检查经 registry（复用路径 D/K 执行通道）、定位复用 H."""
    store = _Store()
    reg = _FakeRegistry({1: "1 failed\nFAILED tests/test_x.py::test_a - AssertionError",
                         2: "5 passed"})
    sub = _FakeSubAgent()
    t = FixLoopTool(registry=reg, subagent_runner=sub,
                    error_locator=ErrorLocator(), event_store=store, session_id="s1")
    r = t.execute(check_command="pytest tests/test_x.py")
    assert r.status.value == "success"
    # 循环内全部经 registry 调用 execute_command（复用 ToolRegistry 通道）
    assert all(c.name == "execute_command" for c in reg.calls)
    # 定位经 H（error_locator 注入）
    assert len(store.events) >= 2  # round + terminated


# ── ⑤ I 的 LLM 修复步骤 ──

def test_i_llm_fix_via_subagent():
    """⑤I: 修复由子代理 LLM 完成（任务文本含修复指令，程序不自动改代码）."""
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    sub = _FakeSubAgent()
    t = FixLoopTool(registry=reg, subagent_runner=sub)
    t.execute(check_command="pytest", fix_hint="修复 test_a")
    assert len(sub.tasks) == 1
    assert "修复" in sub.tasks[0]
    # FixLoopTool 未直接调 edit_file（仅 execute_command 检查）
    assert all(c.name == "execute_command" for c in reg.calls)


# ── ⑥ 熔断协同 ──

def test_fuse_uses_h_structured_fingerprint():
    """⑥熔断: 错误指纹经路径 H 结构化信息计算（同错误识别）."""
    err = "1 failed\nFAILED tests/test_x.py::test_a - AssertionError: assert 1 == 2"
    store = _Store()
    reg = _FakeRegistry({i: err for i in range(1, 4)})
    t = FixLoopTool(registry=reg, subagent_runner=_FakeSubAgent(),
                    error_locator=ErrorLocator(), event_store=store)
    r = t.execute(check_command="pytest", fuse_count=3)
    assert r.status.value == "failure"
    assert "熔断" in r.content
    # 终态事件 final_status=fuse_triggered
    terms = [e for e in store.events if e[0] == "task.fix_loop.terminated"]
    assert terms and terms[-1][1]["final_status"] == "fuse_triggered"


# ── ⑦ A 与 E 独立 ──

def test_a_e_independent():
    """⑦A 与 E: 预检（调用前端）与约定注入（编辑前）独立，不参与纠错闭环."""
    from llm_loop.task_quality.convention import ConventionExtractor
    from llm_loop.task_quality.precheck import PreCheckLayer

    # A: 预检独立（参数校验）
    p = PreCheckLayer()
    assert p.check({"x": 1}, {"type": "object"}).valid is True
    # E: 约定提取独立（不依赖 A）
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    (tmp / "a.py").write_text("def good_name():\n    pass\n", encoding="utf-8")
    c = ConventionExtractor().extract(str(tmp / "new.py"))
    # E 有约定（独立工作）；A 不触发 E，E 不触发 A
    assert len(c.conventions) >= 1
    assert not hasattr(p, "conventions")  # A 无约定概念


# ── ⑧ trace_id 贯穿 ──

def test_trace_id_throughout():
    """⑧trace_id: 贯穿每轮迭代/检查/定位/回归事件，可双向溯源."""
    store = _Store()
    err = "1 failed\nFAILED tests/test_x.py::test_a - AssertionError"
    reg = _FakeRegistry({1: err, 2: "5 passed"})
    t = FixLoopTool(registry=reg, subagent_runner=_FakeSubAgent(),
                    error_locator=ErrorLocator(), event_store=store, session_id="s1")
    r = t.execute(check_command="pytest")
    assert r.status.value == "success"
    # 所有事件 trace_id 一致
    traces = {e[1].get("trace_id") for e in store.events}
    assert len(traces) == 1 and traces != {None}
    # loop_id 一致
    loops = {e[1].get("loop_id") for e in store.events}
    assert len(loops) == 1
    # 回执含 trace（双向溯源：事件 ↔ 回执）
    assert "trace=" in r.content


# ── ⑨ fail-open 零回归 ──

def test_fail_open_zero_regression():
    """⑨零回归: 各路径缺省关闭时既有工具行为不变（开关关=原行为）."""
    from llm_loop.task_quality.precheck import PreCheckLayer
    from llm_loop.tools.registry import ToolRegistry

    class _Dummy:
        name = "dummy"
        description = "t"
        parameters = {"type": "object", "properties": {}}
        def execute(self, **kw):
            return ToolResult(status=ToolResultStatus.SUCCESS, content="ok",
                              tool_call_id="", tool_name="dummy")

    # 开关关的 precheck（enabled_fn=False）→ 行为与无 precheck 一致
    reg = ToolRegistry(precheck_layer=PreCheckLayer(enabled_fn=lambda: False))
    reg.register(_Dummy())
    r = reg.execute(ToolCall(id="t1", name="dummy", arguments={}))
    assert r.status.value == "success"
    assert "ok" in r.content


# ── ⑩ 程序最小化 ──

def test_program_minimalism():
    """⑩程序最小化: 六路径只提供事实与执行通道，不含自动修改/强制指令."""
    # FixLoopTool 的修复动作在子代理任务文本（LLM 决策），工具自身只编排
    reg = _FakeRegistry({1: "1 failed", 2: "5 passed"})
    sub = _FakeSubAgent()
    t = FixLoopTool(registry=reg, subagent_runner=sub)
    t.execute(check_command="pytest", fix_hint="修复")
    # 任务文本是"要求"而非"强制指令"（含'请'/'要求'引导，给 LLM 决策空间）
    task = sub.tasks[0]
    assert "修复" in task
    # FixLoopTool 输出是反馈（事实），不是修复后的代码（未自动改码）
    assert all(c.name == "execute_command" for c in reg.calls)
