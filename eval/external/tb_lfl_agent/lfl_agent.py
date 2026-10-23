"""Terminal-Bench 适配器：把 LFL 作为 TB agent 接入（2026-10-23，P4）.

设计（方案 C，**受限工具集**）
--------------------------------
TB 的 agent 契约是"通过 tmux session 向容器内 shell 发送命令"（见
`terminal_bench/agents/base_agent.py`）。本适配器让 **LFL 在宿主运行**，但把
LFL 的工具集**限制为两项**：

- `tb_shell`  —— 把一条命令送进容器（`session.send_keys`），并回读容器输出
- `tb_read`   —— 回读容器当前输出（`session.capture_pane`）

因此 LFL 看到的世界**只有容器**，无法读写宿主文件、无法调用宿主工具。
这在语义上等价于"一个只有终端的 agent"，可真实测量 LFL 的
多轮推理 / 错误恢复 / 自我纠错能力。

**适配改动量（必须如实登记，见计划 §5-P4 出口判据）**
- 工具集：从 LFL 默认全量工具 → **2 项受限工具**
- 入口：`--agent-import-path` + `--agent lfl`
- ⚠️ 本适配**不是**"原封不动的 LFL 跑 TB"；结论只对"受限终端工具集下的 LFL"成立。

**失败模式映射（对照 P0 归因）**
TB 的 `FailureMode` 枚举（实测自 terminal_bench/agents/failure_mode.py）：
`UNSET / NONE / UNKNOWN / TEST_TIMEOUT / AGENT_TIMEOUT / UNKNOWN_AGENT_ERROR /
PARSE_ERROR / FATAL_LLM_PARSE_ERROR / CONTEXT_LENGTH_EXCEEDED /
OUTPUT_LENGTH_EXCEEDED / AGENT_INSTALLATION_FAILED`。

本适配器的映射：
- agent 自身异常 → `UNKNOWN_AGENT_ERROR`（**显式归因**，不与"环境失败"混淆）
- 正常跑完（由 TB 另行跑测试判定通过与否）→ `NONE`
- ⚠️ 容器/构建/环境失败由 **TB harness** 产生，落在 `AGENT_INSTALLATION_FAILED`
  或 harness 自己的 `unknown_agent_error`；本适配器**无法**也**不应**冒充该归因。
  这正是 P0 要求"先归因再解读"的原因：P0 的 52 例 `unknown_agent_error`
  实为环境失败，若不归因就会被误读为 agent 能力差。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

# 避免 release 快照覆盖工作树（known-red §13）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
_SRC = os.path.join(_ROOT, "src")
if os.path.isdir(_SRC) and _SRC not in os.sys.path:
    os.sys.path.insert(0, _SRC)

from terminal_bench.agents.base_agent import BaseAgent  # noqa: E402
from terminal_bench.agents.failure_mode import FailureMode  # noqa: E402

# 容器内命令的默认超时（秒）与轮次上限
DEFAULT_CMD_TIMEOUT_S = float(os.environ.get("TB_LFL_CMD_TIMEOUT_S", "60"))
DEFAULT_MAX_ROUNDS = int(os.environ.get("TB_LFL_MAX_ROUNDS", "40"))
DEFAULT_MAX_OUTPUT_CHARS = int(os.environ.get("TB_LFL_MAX_OUTPUT_CHARS", "6000"))


@dataclass
class _RunState:
    """一次 TB 任务运行期状态（命令发送 + 输出采集）。"""

    session: Any = None
    sent: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    last_output: str = ""
    error: str = ""


class _TbShellTool:
    """把一条命令送进容器并回读输出。"""

    name = "tb_shell"
    description = (
        "在**任务容器**内执行一条 shell 命令并返回其输出。"
        "这是你与题目环境交互的唯一通道；宿主文件系统不可见。"
        "一次只发一条命令；不要在命令里拼接破坏性操作。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要在容器内执行的 shell 命令（单条）。",
            },
            "timeout_s": {
                "type": "number",
                "description": f"等待输出的秒数（默认 {DEFAULT_CMD_TIMEOUT_S:.0f}）。",
            },
        },
        "required": ["command"],
    }

    def __init__(self, state: _RunState) -> None:
        self._state = state

    def execute(self, **kwargs: Any) -> str:
        cmd = str(kwargs.get("command", "")).strip()
        if not cmd:
            return "ERROR: empty command"
        timeout = float(kwargs.get("timeout_s") or DEFAULT_CMD_TIMEOUT_S)
        st = self._state
        if st.session is None:
            return "ERROR: no session"
        try:
            st.session.send_keys([cmd, "Enter"])
            st.sent.append(cmd)
            deadline = time.time() + timeout
            out = ""
            last = ""
            # 轮询直到输出稳定（tmux capture_pane）
            stable = 0
            while time.time() < deadline:
                time.sleep(1.0)
                try:
                    out = st.session.capture_pane()
                except Exception as e:  # noqa: BLE001
                    return f"ERROR: capture_pane failed: {e}"
                if out == last:
                    stable += 1
                    if stable >= 2:
                        break
                else:
                    stable = 0
                last = out
            st.outputs.append(out)
            st.last_output = out
            trimmed = out[-DEFAULT_MAX_OUTPUT_CHARS:]
            return trimmed if trimmed else "(no output)"
        except Exception as e:  # noqa: BLE001
            st.error = str(e)
            return f"ERROR: {e}"


class _TbReadTool:
    """回读容器当前屏幕输出（不发送任何命令）。"""

    name = "tb_read"
    description = "回读任务容器当前屏幕上的最后若干行输出（不执行任何命令）。"
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, state: _RunState) -> None:
        self._state = state

    def execute(self, **kwargs: Any) -> str:
        st = self._state
        if st.session is None:
            return "ERROR: no session"
        try:
            out = st.session.capture_pane()
        except Exception as e:  # noqa: BLE001
            return f"ERROR: capture_pane failed: {e}"
        st.last_output = out
        return out[-DEFAULT_MAX_OUTPUT_CHARS:] if out else "(no output)"


class LflAgent(BaseAgent):
    """LFL 作为 Terminal-Bench agent。"""

    def __init__(self, model_name: str | None = None, **kwargs: Any) -> None:
        super().__init__(model_name=model_name or "minimax/MiniMax-M3.1-Flash", **kwargs)
        self._model_name = model_name or os.environ.get(
            "LLM_MODEL", "minimax/MiniMax-M3.1-Flash"
        )
        self._last_state: _RunState | None = None

    # ── TB 契约 ────────────────────────────────────────────────────────────
    @staticmethod
    def name() -> str:
        """TB 通过 --agent lfl 选择本 agent（配合 --agent-import-path）。"""
        return "lfl"

    @property
    def _init_agent_script(self) -> str:
        # LFL 跑在宿主，不需要在容器里装 agent 进程；这里只回显一个标记，
        # 避免 TB 反复等待一个永远不会出现的 shell 提示符。
        return "true"

    def perform_task(
        self,
        instruction: str,
        session,
        logging_dir=None,
        timeout_s: float = 600.0,
    ):
        """在容器里完成一个 TB 任务。

        签名对照 TB 真实契约（实测自 terminal-bench 0.2.18）：
          terminal_bench/agents/base_agent.py::BaseAgent.perform_task(
              instruction: str, session: TmuxSession, logging_dir: Path | None = None)
          harness/harness.py:625 调用 agent.perform_task(
              instruction=..., session=..., logging_dir=...)
        → 参数名必须是 instruction / session / logging_dir（**关键字调用**），
          写成 task / tmux_session 会抛 TypeError（首轮实跑实测）。
        """
        task = instruction
        state = _RunState(session=session)
        self._last_state = state

        # ── 1) 构造 LFL 引擎（工厂装配全套工具）──
        # 真实 API（实测自 src/llm_loop/factory.py::build_engine 与
        # src/llm_loop/core/loop/engine.py::LoopEngine.__init__）：
        # build_engine(settings) 无自定义工具入口；LoopEngine 需 llm_client/
        # registry/memory/session/settings 五个必需参数。
        # → 处置：用工厂装配，再把 registry 里的默认工具**逐个注销**，
        #    只保留两个 TB 工具（ToolRegistry.unregister 存在，实测）。
        api_key = (
            os.environ.get("MINIMAX_API_KEY", "")
            or os.environ.get("LLM_API_KEY", "")
            or os.environ.get("DEEPSEEK_API_KEY", "")
        )
        from llm_loop.config import Settings
        from llm_loop.factory import build_engine

        # Settings 必填三件套（实测 src/llm_loop/config.py::Settings.__init__：
        # llm_api_key / llm_base_url / llm_model）。全限定模型名
        # （minimax/MiniMax-M3.1-Flash）下，build_engine 会走
        # registry.client_params() 从**模型注册表**取真实 base_url/api_key/model
        # （src/llm_loop/factory.py:565），settings.llm_base_url 只是 fallback。
        # → 这里给注册表解析出的 base_url；解析不到时用 LLM_BASE_URL env 兜底。
        base_url = os.environ.get("LLM_BASE_URL", "").strip()
        try:
            from llm_loop.llm.providers import load_registry

            _reg = load_registry(
                Settings(
                    llm_api_key=api_key,
                    llm_base_url=base_url or "http://localhost:1/",
                    llm_model=self._model_name,
                    data_dir=os.path.join(_ROOT, "data"),
                )
            )
            _pid, _mid = _reg.resolve(self._model_name)
            _params = _reg.client_params(_pid, _mid)
            base_url = _params.get("base_url", base_url)
            api_key = _params.get("api_key", api_key)
        except Exception:  # noqa: BLE001 — 注册表不可用时退回 env 兜底
            pass
        if not base_url:
            base_url = "https://api.minimax.chat/v1"

        settings = Settings(
            llm_api_key=api_key,
            llm_base_url=base_url,
            llm_model=self._model_name,
            data_dir=os.path.join(_ROOT, "data"),
        )
        engine = build_engine(settings)

        # ── 2) 把默认工具集换成受限的两项 ──
        registry = getattr(engine, "registry", None)
        if registry is None:
            return self._error_result("engine.registry unavailable", 0, 0)
        for name in list(registry.names()):
            registry.unregister(name)
        registry.register(_TbShellTool(state))
        registry.register(_TbReadTool(state))

        # ── 3) 任务提示 ──
        # TB 真实契约：perform_task(instruction=<str>, ...) —— task 就是**字符串**
        # （实测 terminal_bench 0.2.18 harness/harness.py:625）。
        # 早前按 `getattr(task, "instruction", "")` 取值会恒为空（字符串无该属性）
        # → 任务提示为空，agent 无从下手。兼容两种形态：
        instruction = (
            task
            if isinstance(task, str)
            else (getattr(task, "instruction", None) or "")
        )
        prompt = (
            f"你正在 Terminal-Bench 容器内完成一个任务。\n"
            f"你**只有**两个工具：tb_shell（执行命令）、tb_read（回读输出）。\n"
            f"所有命令都通过 tb_shell 发送到容器内执行。\n\n"
            f"任务说明：\n{instruction}\n\n"
            f"完成后用一段话说明你做了什么、以及最终状态（成功/失败/未完成）。"
        )

        # 人类输入通道凭据（agent_trace_leak 3.5）：engine.run 的 ingress 缺省 None
        # → 用户输入被通道白名单拒绝（leak.channel_denied），agent 收到的是隔离
        # 提示而非任务响应（首轮实跑实测：answer = "[写入被拒] …"）。
        # TB 场景是**程序化 CLI 通道**的人类输入 → 签发 cli 通道凭据
        # （issue_ingress 是正式签发入口，不是 issue_test_ingress 测试后门）。
        from llm_loop.core.trace_leak.ingress_token import issue_ingress

        ingress = issue_ingress("cli")

        try:
            result = engine.run(
                f"tb-{getattr(task, 'task_id', 'task')}", prompt, ingress=ingress
            )
        except Exception as e:  # noqa: BLE001 — agent 侧异常要显式归类，不吞成 unknown
            # 2026-10-23：把完整 traceback 落盘到 logging_dir（TB 提供的审计目录）。
            # 早前异常只进 AgentResult.markers，TB 不回显 → 容器/agent 侧真实错误
            # 不可见，只能看到 unknown_agent_error，无法归因。落盘后可审计。
            self._dump_error(logging_dir, "agent_exception", e)
            return self._error_result(f"agent exception: {e}", 0, 0)

        tok_in = int(getattr(result, "tokens_in", 0) or 0)
        tok_out = int(getattr(result, "tokens_out", 0) or 0)
        answer = getattr(result, "final_answer", "") or ""

        # agent 自身异常 → 计入 agent 能力；容器/环境问题 → setup
        if getattr(result, "run_incomplete", False) and not answer:
            self._dump_error(
                logging_dir, "agent_run_incomplete", RuntimeError(answer or "no answer")
            )
            return self._error_result(
                "agent run incomplete", tok_in, tok_out
            )

        return self._ok_result(answer, tok_in, tok_out)

    @staticmethod
    def _dump_error(logging_dir, kind: str, exc: BaseException) -> None:
        """把错误类型 + traceback 写到 logging_dir（不抛，失败也不影响主流程）."""
        try:
            if logging_dir is None:
                return
            import traceback

            d = Path(str(logging_dir))
            d.mkdir(parents=True, exist_ok=True)
            (d / "lfl_agent_error.txt").write_text(
                f"kind={kind}\nerror_type={type(exc).__name__}\nerror={exc}\n\n"
                + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001 — 诊断落盘失败不得影响主流程
            pass

    # ── 内部：构造 AgentResult ────────────────────────────────────────────
    def _ok_result(self, answer: str, tok_in: int, tok_out: int):
        """正常跑完：failure_mode=NONE，由 TB 另行跑测试判定通过与否.

        ⚠️ `AgentResult` **没有** agent_output 字段（实测自
        terminal_bench/agents/base_agent.py）—— agent 的最终说明通过
        `timestamped_markers` 传递（TB 契约内唯一可携带文本的字段）。
        """
        from terminal_bench.agents.base_agent import AgentResult

        return AgentResult(
            total_input_tokens=tok_in,
            total_output_tokens=tok_out,
            failure_mode=FailureMode.NONE,
            timestamped_markers=[(0.0, answer[:2000])],
        )

    def _error_result(self, msg: str, tok_in: int, tok_out: int):
        """agent 侧异常：显式归因到 UNKNOWN_AGENT_ERROR（不与环境失败混淆）。"""
        from terminal_bench.agents.base_agent import AgentResult

        return AgentResult(
            total_input_tokens=tok_in,
            total_output_tokens=tok_out,
            failure_mode=FailureMode.UNKNOWN_AGENT_ERROR,
            timestamped_markers=[(0.0, msg[:2000])],
        )
