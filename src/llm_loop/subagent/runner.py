"""SubAgentRunner：递归子代理执行器（设计见本地开发文档）.

核心: 独立 session（隔离上下文）+ 迷你 LLM 循环（受限工具 schema）+ 真实执行（复用 registry）+
深度/轮数预算 + 工具子集边界。全部如实回执（拒绝/截断/失败显式标注）。
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field

from llm_loop.core.message import Message, MessageSource, ToolCall
from llm_loop.core.session import Session, SessionStore
from llm_loop.llm.client import LLMClient
from llm_loop.tools.registry import ToolRegistry

# 子代理受限工具子集（信息获取 + 真实执行；禁修改/架构修正类——程序最小化下的最小安全边界）
SUBAGENT_ALLOWED_TOOLS = {
    "read_file",
    "execute_command",
    "web_fetch",
    "web_search",
    "get_tool_schema",
    # EVO-20260817 审查 P0-2: fix_loop 路径 I 子代理修复需要 edit_file（P0-D1 设计
    # 本要求"修复由子代理经 edit_file 完成"，白名单漏配致端到端断路）。
    # 安全链完整: edit_file 含 symlink 写防护 + FileBaseline 并发校验 + CatastrophicGuard。
    "edit_file",
}

MAX_DEPTH = 3
MAX_ITERATIONS = 8


@dataclass
class SubAgentResult:
    """子代理执行结果（如实回传父代理）."""

    final_answer: str
    rounds: int = 0
    tool_calls: list[dict] = field(default_factory=list)  # 工具轨迹摘要（name→status）
    truncated: bool = False  # 轮数超限截断
    refused: bool = False  # 深度超限拒绝
    depth: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


class SubAgentRunner:
    """子代理执行器：独立会话 + 迷你循环 + 受限工具 + 预算/深度边界."""

    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        session_store: SessionStore,
        *,
        max_depth: int = MAX_DEPTH,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.session_store = session_store
        self.max_depth = max_depth
        self.max_iterations = max_iterations

    # ── 公开入口 ──
    def run(
        self,
        task: str,
        context: str = "",
        depth: int = 0,
        max_rounds: int | None = None,
    ) -> SubAgentResult:
        """执行子代理任务（父代理调用 depth=0，子代理内部递归自增）.

        max_rounds: 节点级轮次预算（P3-4 DAG 节点预算）；None = 构造器 max_iterations。
        """
        """执行子代理任务（父代理调用 depth=0，子代理内部递归自增）."""
        if depth >= self.max_depth:
            return SubAgentResult(
                final_answer=(
                    f"[状态: failure] 递归深度超限（已达上限 {self.max_depth}），"
                    f"请在父级整合结果，勿继续拆分。"
                ),
                refused=True,
                depth=depth,
            )

        # 独立会话（隔离父上下文）
        sid = f"subagent_{uuid.uuid4().hex[:12]}"
        sess = self.session_store.load(sid)
        with suppress(Exception):
            self.session_store.save(sess)  # 落盘（可审计）

        # P1-5(审计发现 #10): 子代理执行期间切换到子会话，执行结束必须恢复父会话——
        # 否则父级后续的超长工具结果归档/变更日志会归错到子会话（串台）。
        # registry._session_id 为 contextvar 优先（P0-5），因此显式回退字段与
        # current_session_id 两者都要保存/恢复；用值快照 + set 还原（engine 层
        # 已验证该模式跨 Context 兼容——token reset 跨 Context 会抛 ValueError）。
        from llm_loop.core.run_context import current_session_id

        old_explicit = getattr(self.registry, "_session_id_explicit", "")
        old_ctx_sid = current_session_id.get()
        try:
            with suppress(Exception):
                self.registry.set_session_id(sid)
            with suppress(Exception):
                current_session_id.set(sid)
            return self._execute_subagent(sess, task, context, depth, max_rounds=max_rounds)
        finally:
            # 恢复父会话（成功/异常/截断任何返回路径都必须执行）
            with suppress(Exception):
                self.registry.set_session_id(old_explicit)
            with suppress(Exception):
                current_session_id.set(old_ctx_sid)

    def _execute_subagent(
        self,
        sess: Session,
        task: str,
        context: str,
        depth: int,
        max_rounds: int | None = None,
    ) -> SubAgentResult:
        """子代理循环本体（会话注入/恢复由 run 包裹；拆出保证 finally 覆盖全部返回路径）."""
        effective_rounds = (
            max(1, int(max_rounds)) if max_rounds is not None else self.max_iterations
        )
        # 构造子代理消息
        sys_prompt = (
            f"你是递归子代理（深度 {depth}/{self.max_depth}）。你的任务:\n{task}\n"
            f"父代理提供的上下文要点:\n{context or '（无）'}\n\n"
            "规则:\n"
            f"- 可用工具: {sorted(SUBAGENT_ALLOWED_TOOLS)}\n"
            f"- 最多 {effective_rounds} 轮工具循环，结束后给出最终回答\n"
            "- 如任务仍可拆分且未达深度上限，可用 spawn_subagent 递归委派（depth 自动+1）\n"
            "- 全部基于真实工具结果作答，不得编造"
        )
        sess.messages.append(Message(role="user", content=sys_prompt, source=MessageSource.USER))

        rounds = 0
        tool_trace: list[dict] = []
        tokens_in = 0
        tokens_out = 0
        truncated = False

        while rounds < effective_rounds:
            rounds += 1
            # ── LLM 决策 ──
            msgs = [m.to_llm_dict() for m in sess.messages]  # type: ignore[attr-defined]
            schemas = self.registry.schemas(lazy=False)
            sub_schemas = [s for s in schemas if s.get("name") in SUBAGENT_ALLOWED_TOOLS or s.get("name") == "spawn_subagent"]
            try:
                resp = self.llm.chat(msgs, tools=sub_schemas)
            except Exception as exc:  # noqa: BLE001 — 子代理 LLM 失败如实回传
                sess.messages.append(
                    Message(
                        role="tool",
                        content=f"[状态: error] 子代理 LLM 调用失败: {type(exc).__name__}: {exc}",
                        source=MessageSource.TOOL,
                    )
                )
                continue
            tokens_in += resp.prompt_tokens
            tokens_out += resp.completion_tokens

            # 无工具调用 → 最终回答
            if not resp.tool_calls:
                answer = resp.content or "（子代理未给出回答）"
                with suppress(Exception):
                    self.session_store.save(sess)
                return SubAgentResult(
                    final_answer=answer,
                    rounds=rounds,
                    tool_calls=tool_trace,
                    truncated=truncated,
                    depth=depth,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                )

            # ── 执行工具（真实执行，复用 registry）──
            for tc in resp.tool_calls:
                call = ToolCall(id=tc.id, name=tc.name, arguments=tc.arguments)
                # 受限工具集强制校验（含 spawn_subagent 递归）
                if call.name not in SUBAGENT_ALLOWED_TOOLS and call.name != "spawn_subagent":
                    result_content = f"[状态: blocked] 工具 {call.name} 不在子代理受限工具集内（仅 {sorted(SUBAGENT_ALLOWED_TOOLS | {'spawn_subagent'})}）"
                    tool_trace.append({"name": call.name, "status": "blocked"})
                    sess.messages.append(
                        Message(
                            role="tool",
                            content=result_content,
                            source=MessageSource.TOOL,
                            tool_call_id=call.id,
                        )
                    )
                    continue
                try:
                    result = self.registry.execute(call)
                    tool_trace.append({"name": call.name, "status": result.status.value})
                except Exception as exc:  # noqa: BLE001 — 如实回传
                    tool_trace.append({"name": call.name, "status": "error"})
                    result_content = f"[状态: error] 子代理工具执行异常: {type(exc).__name__}: {exc}"
                    sess.messages.append(
                        Message(
                            role="tool",
                            content=result_content,
                            source=MessageSource.TOOL,
                            tool_call_id=call.id,
                        )
                    )
                    continue
                # 工具结果回注入子会话（T21 前置状态标注）
                from llm_loop.tools.registry import tool_result_to_message

                sess.messages.append(
                    tool_result_to_message(
                        result,
                        failure_guidance_enabled=False,
                        experience_guidance_enabled=True,  # 阶段4-A: 子代理仅注入经验（无默认模板噪音）
                    )
                )

        # 轮数超限截断（如实标注）
        truncated = True
        answer = "（子代理已达轮数上限，结果未完整收敛——请父级基于已有工具反馈整合）"
        with suppress(Exception):
            self.session_store.save(sess)
        return SubAgentResult(
            final_answer=answer,
            rounds=rounds,
            tool_calls=tool_trace,
            truncated=truncated,
            depth=depth,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
