"""LoopEngine 工具执行职责 mixin（M53 拆分: engine.py 946 行→按职责分文件，纯重构行为零变化）.

move 自 engine.py 内联工具段（492-553）与辅助方法（888-913）及模块级函数（49-67）：
- assistant 声明配对（约束 C1）、缺 id 如实反馈
- 只读并行/修改串行/按声明顺序回写（EVO-20260810-750e985a）
- tool_round 进展外泄（P2-1，fail-open）与 tool_trace 记录
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)


from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from llm_loop.core.message import Message, MessageSource, ToolResult
from llm_loop.introspection.status import ToolHistoryItem
from llm_loop.llm.client import LLMResponse, StreamDelta, ToolRoundInfo
from llm_loop.tools.registry import tool_result_to_message

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)

# EVO-20260814-aab7eb0b P2: 循环实时停滞检测阈值
# 连续 N 次相同指纹（tool_name + 规范化参数 JSON）：
#   >= _STAGNATION_REMIND_AT 注入 [停滞提醒]（一次）；>= _STAGNATION_BREAK_AT 熔断如实结束。
_STAGNATION_REMIND_AT = 3
_STAGNATION_BREAK_AT = 5


def _json_dumps_args(arguments: dict) -> str:
    """工具参数序列化为 JSON 字符串（FC 协议 function.arguments 要求）."""
    import json as _json

    try:
        return _json.dumps(arguments, ensure_ascii=False)
    except TypeError:
        return "{}"


def _tool_args_summary(arguments: Any) -> str:
    """工具参数摘要（P2-1，design §2.5.1 B4）：JSON 序列化 + 超 200 字符截断附 "…"。"""
    import json as _json

    try:
        s = _json.dumps(arguments, ensure_ascii=False) if isinstance(arguments, dict) else str(arguments)
    except (TypeError, ValueError):
        s = str(arguments)
    return s[:200] + "…" if len(s) > 200 else s


class _ToolExecMixin:
    def _execute_tools(
        self: LoopEngine,
        resp: LLMResponse,
        sess,
        rounds: int,
        tool_trace: list[dict],
    ) -> Iterator[StreamDelta]:
        """行动：执行工具（tool_calls），move 自 engine.py:492-553（生成器保持外泄次序）."""
        self._phase("action.tool_loop")
        # 约束 C1 配对: 先把 LLM 声明追加为 assistant 消息（带 tool_calls），
        # 后续 tool 回执才有前置声明（严格 API 要求，否则 400）
        if resp.tool_calls:
            assistant_decl = Message(
                role="assistant",
                content=resp.content or "",
                source=MessageSource.USER,
                tool_calls=[
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": _json_dumps_args(tc.arguments),
                        },
                    }
                    for tc in resp.tool_calls
                ],
                reasoning_content=resp.reasoning_content,  # M20 THK-04: 工具轮回传思考链
            )
            sess.messages.append(assistant_decl)
            # D1: assistant 声明消息事件（fail-open）
            self._append_message_event(sess, assistant_decl)
        for tc in resp.tool_calls:
            if not tc.id:
                # 约束 C1: 缺 id 声明不可执行，如实注入反馈（AI-first 三件套）
                msg = Message(
                    role="system",
                    content=(
                        f"[工具调用异常] 事实: 声明缺少 tool_call_id，无法绑定执行（工具 '{tc.name}'）。\n"
                        f"原因: 程序不伪造执行无绑定标识的声明（协议约束）。\n"
                        f"建议: 请重新声明工具调用（确保原生 tool_calls 含 id 字段）。"
                    ),
                    source=MessageSource.SYSTEM,
                )
                sess.messages.append(msg)
                # D1: 系统注入消息事件（fail-open）
                self._append_message_event(sess, msg)
                self._record_action("action.tool_loop", "missing_tool_call_id", tc.name)
        # EVO-20260810-750e985a: 工具并发控制（只读并行/修改串行/按声明顺序回写）
        valid_calls = [tc for tc in resp.tool_calls if tc.id]
        if valid_calls:
            # P2-1: 工具轮次进展外泄（fail-open，yield 异常不阻断主循环）
            for tc in valid_calls:
                # H-UI: 工具调用开始（实时状态条）
                self._notify_action(
                    "tool_call",
                    tool_name=tc.name,
                    args_summary=_tool_args_summary(tc.arguments),
                )
                try:
                    yield StreamDelta(
                        text="",
                        tool_round=ToolRoundInfo(
                            tool_name=tc.name,
                            round_index=rounds,
                            args_summary=_tool_args_summary(tc.arguments),
                            tool_call_id=tc.id,
                        ),
                    )
                except Exception:  # noqa: BLE001 — fail-open
                    logger.warning("tool_round yield 失败（fail-open）", exc_info=True)
            results = self.registry.execute_many(valid_calls)
            for tc, result in zip(valid_calls, results, strict=False):
                tool_trace.append({"id": tc.id, "name": tc.name, "arguments": tc.arguments})
                self._record_tool_history(result)
                # H-UI: 工具结果（实时状态条）
                self._notify_action(
                    "tool_result", tool_name=tc.name, status=result.status.value
                )
                tool_msg = tool_result_to_message(
                    result, failure_guidance_enabled=self.registry.failure_guidance_enabled
                )
                sess.messages.append(tool_msg)
                # D1: tool 回执消息事件（fail-open）
                self._append_message_event(sess, tool_msg)
                # EVO-20260814-aab7eb0b P2: 运行中停滞指纹追踪（evaluator.py:271 同构指纹）
                self._track_stagnation(tc, sess, tool_trace)

    # ── EVO-20260814-aab7eb0b P2: 循环实时停滞检测 ──

    def _stagnation_fingerprint(self: LoopEngine, tc) -> str:
        """单次工具调用指纹（evaluator.py:271 同构: 名称 + 规范化参数 JSON）."""
        return f"{tc.name}|{_json_dumps_args(tc.arguments)}"

    def _track_stagnation(self: LoopEngine, tc, sess, tool_trace: list[dict]) -> None:
        """每次工具执行后更新连续同指纹计数；达提醒阈值注入 [停滞提醒]（一次，AI 自主决策）。

        熔断决策在 engine 主循环（能 break 的位置）读取 _stagnation_should_break() 完成。
        """
        fp = self._stagnation_fingerprint(tc)
        state = getattr(self, "_stagnation_state", None)
        if state is None:
            state = self._stagnation_state = {"fp": None, "count": 0, "reminded": False}
        if state["fp"] == fp:
            state["count"] += 1
        else:
            state["fp"] = fp
            state["count"] = 1
            state["reminded"] = False
        if state["count"] >= _STAGNATION_REMIND_AT and not state["reminded"]:
            state["reminded"] = True
            try:
                from llm_loop.feedback.honesty import stagnation_reminder_message

                reminder = stagnation_reminder_message(tc.name, state["count"])
                sess.messages.append(reminder)
                self._append_message_event(sess, reminder)
                self._record_action("stagnation.reminder", "injected", f"{tc.name} x{state['count']}")
            except Exception:
                logger.warning("停滞提醒注入失败（fail-open）", exc_info=True)

    def _stagnation_should_break(self: LoopEngine) -> tuple[bool, str, int]:
        """是否达熔断阈值（engine 主循环每轮工具执行后调用）。."""
        state = getattr(self, "_stagnation_state", None)
        if not state or state["count"] < _STAGNATION_BREAK_AT:
            return (False, "", 0)
        name = (state["fp"] or "").split("|", 1)[0]
        return (True, name, state["count"])

    def _schema_to_param(self: LoopEngine, t: dict) -> dict:
        return {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }

    def _resp_summary(self: LoopEngine, resp: LLMResponse) -> str:
        if resp.tool_calls:
            return "tool_calls=" + ",".join(t.name for t in resp.tool_calls)
        return f"content={resp.content[:80] if resp.content else '(空)'}"

    def _record_tool_history(self: LoopEngine, result: ToolResult) -> None:
        if self.status:
            self.status.record_tool_history(
                ToolHistoryItem(
                    name=result.tool_name,
                    arguments={},
                    status=result.status,
                    summary=result.content[:120],
                    duration_ms=result.duration_ms,
                )
            )
