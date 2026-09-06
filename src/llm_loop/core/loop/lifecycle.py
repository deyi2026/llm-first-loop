"""LoopEngine 生命周期/持久化包装 mixin.

把同步 run 包装、一次性会话入口、资源关闭、Workspace 会话分区、恢复通道与
最终回答记忆沉淀从 engine.py 核心五阶段循环中拆出；纯职责迁移，行为保持不变。
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llm_loop.core.run_context import (
    current_model_label as _current_model_label,
)
from llm_loop.core.run_context import (
    current_reasoning_effort as _current_reasoning_effort,
)
from llm_loop.core.run_context import (
    current_reasoning_mode as _current_reasoning_mode,
)
from llm_loop.core.run_context import (
    current_session_id as _current_session_id,
)
from llm_loop.core.run_context import (
    current_workspace_root as _current_workspace_root,
)
from llm_loop.core.trace_leak.ingress_token import (
    IngressToken,
)
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_session_id as _current_ingress_session_id,
)
from llm_loop.core.trace_leak.ingress_token import (
    current_ingress_token as _current_ingress_token,
)

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine, LoopResult
    from llm_loop.llm.client import StreamDelta

logger = logging.getLogger(__name__)


class _RunEntrypointMixin:
    # ── 主入口 ──
    def run_stream(
        self, session_id: str, user_text: str, model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        *, ingress: object | None = None,
    ) -> Iterator[StreamDelta]:
        """单条用户消息的完整循环（流式）：逐 content delta yield，结束返回 LoopResult.

        ASGI/同步生成器允许同一 generator 在不同 ``contextvars.Context`` 中被
        继续驱动。run 的 sid/workspace/reasoning/model 上下文因此不能只在生成器入口
        set 一次；每次推进 inner generator 前都重新播种，返回 delta 前立刻恢复调用方
        Context。这样 runner-disabled 直驱 SSE 与后台 worker 语义一致，且不污染调用方。
        """
        # run admission与workspace transition同锁：先登记active并捕获workspace，
        # 再释放门；后续workspace切换看到active集合后fail-fast。
        with self._workspace_transition_guard:
            runner = getattr(self, "runner", None)
            if (
                runner is not None
                and runner.enabled
                and not runner.is_worker()
                and runner.is_running(session_id)
            ):
                from llm_loop.core.loop.runner import SessionBusyError

                raise SessionBusyError(
                    f"会话 {session_id} 已有进行中的 run（跨入口互斥，请稍后重试）"
                )
            with self._sync_guard:
                if session_id in self._sync_active:
                    from llm_loop.core.loop.runner import SessionBusyError

                    raise SessionBusyError(
                        f"会话 {session_id} 已有进行中的同步 run（互斥，请稍后重试）"
                    )
            # 同步取消标记生命周期与 run 对齐（1.5）：必须在本轮 active 发布前
            # 清理上一轮残留。若先 add(active) 再 discard，会存在真实 lost-stop 窗口：
            # /stop 已观察到 active 并返回“已受理”，随后却被这里清掉。
            # workspace transition guard 保证标准 admission 不并发；第二次 sync 检查
            # 保留为防御性互斥，确保清理期间任何尚未发布的 stop 只会得到 noop，
            # 一旦 active 发布，之后 accepted 的 stop 绝不会再被初始化路径删除。
            self._sync_cancel_discard(session_id)
            with self._sync_guard:
                if session_id in self._sync_active:
                    from llm_loop.core.loop.runner import SessionBusyError

                    raise SessionBusyError(
                        f"会话 {session_id} 已有进行中的同步 run（互斥，请稍后重试）"
                    )
                self._sync_active.add(session_id)
            run_workspace = self.workspace_root or ""

        run_effort = reasoning_effort or ""
        run_reasoning_mode = (reasoning_mode or "auto").strip().lower()
        if run_reasoning_mode not in {"auto", "off", "on"}:
            run_reasoning_mode = "auto"
        run_model_label = ""
        _run_stack = ExitStack()
        _run_save_token: object | None = None
        inner = None

        @contextmanager
        def _bound_run_context():
            sid_token = _current_session_id.set(session_id)
            ws_token = _current_workspace_root.set(run_workspace)
            effort_token = _current_reasoning_effort.set(run_effort)
            reasoning_mode_token = _current_reasoning_mode.set(run_reasoning_mode)
            model_token = _current_model_label.set(run_model_label)
            bound_ingress = ingress if isinstance(ingress, IngressToken) else None
            ingress_token = _current_ingress_token.set(bound_ingress)
            ingress_sid_token = _current_ingress_session_id.set(
                session_id if bound_ingress is not None else ""
            )
            try:
                yield
            finally:
                _current_ingress_session_id.reset(ingress_sid_token)
                _current_ingress_token.reset(ingress_token)
                _current_model_label.reset(model_token)
                _current_reasoning_mode.reset(reasoning_mode_token)
                _current_reasoning_effort.reset(effort_token)
                _current_workspace_root.reset(ws_token)
                _current_session_id.reset(sid_token)

        try:
            if not _run_stack.enter_context(self.session.run_lease(session_id)):
                from llm_loop.core.loop.runner import SessionBusyError

                raise SessionBusyError(f"会话 {session_id} 正由另一进程执行，请稍后重试")
            _run_save_token = self.session._activate_run_save_token(session_id)
            with self._run_acquired_callbacks_guard:
                on_run_acquired = self._run_acquired_callbacks.get(session_id)
            inner = self._run_stream_inner(
                session_id, user_text, model,
                run_save_token=_run_save_token, on_run_acquired=on_run_acquired,
                ingress=ingress,
            )

            while True:
                with _bound_run_context():
                    try:
                        delta = next(inner)
                    except StopIteration as exc:
                        return exc.value
                    # inner 可在工具轮临时把 effort 调成 low，也会在每轮刷新 model label；
                    # 捕获后跨 yield 保存，下一次即使换 Context 也精确恢复本 run 状态。
                    run_effort = _current_reasoning_effort.get()
                    run_reasoning_mode = _current_reasoning_mode.get() or run_reasoning_mode
                    run_model_label = _current_model_label.get()
                try:
                    yield delta
                except GeneratorExit:
                    # 手动驱动替代 yield-from 后，必须显式把 close 注入 inner，
                    # 才能保留部分回答落盘/孤儿 tool_calls 合成取消回执语义。
                    with _bound_run_context():
                        inner.close()
                    raise
        finally:
            if inner is not None:
                # 非 GeneratorExit 异常/消费者 throw 的防御性收尾；已结束/已关闭时幂等。
                try:
                    with _bound_run_context():
                        inner.close()
                except Exception:  # noqa: BLE001 — 清理失败不覆盖原始异常
                    logger.warning("run_stream inner close 失败（fail-open）", exc_info=True)
            # inner 已完成/关闭：当前run的in-memory Session绑定不再需要，立即释放整段历史引用。
            with self._run_state_mgr.guard:
                self._run_sessions.pop(session_id, None)
            if _run_save_token is not None:
                self.session._deactivate_run_save_token(session_id, _run_save_token)
            _run_stack.close()
            with self._sync_guard:
                self._sync_active.discard(session_id)
            # 同步 run 注销 → 同步取消登记一并移除（1.5：标记生命周期与 run 对齐，
            # 支撑第二次 /stop 幂等与恢复轮可再停止）
            self._sync_cancel_discard(session_id)



    def run(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        *,
        ingress: object | None = None,
    ) -> LoopResult:
        """单条用户消息的完整循环（run_stream 的同步聚合包装，签名/返回不变）.

        model: 可选，本次对话覆盖使用的 LLM 模型（None 用装配模型，Web 模型切换用）。
        ingress: agent_trace_leak 3.5——人类输入通道凭据（缺省 None 向后兼容）。
        """
        it = self.run_stream(
            session_id, user_text, model, reasoning_effort=reasoning_effort,
            reasoning_mode=reasoning_mode,
            ingress=ingress,
        )
        while True:
            try:
                next(it)
            except StopIteration as exc:
                return exc.value




    def _run_with_acquired(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        *,
        on_run_acquired: Any = None,
        expected_workspace_epoch: int | None = None,
        ingress: object | None = None,
    ) -> LoopResult:
        """内部同步入口：首个generator推进前校验session解析时的workspace epoch。"""
        marker = self._session_lifecycle._install_run_acquired_callback(session_id, on_run_acquired)
        it = self.run_stream(
            session_id, user_text, model=model, reasoning_effort=reasoning_effort,
            reasoning_mode=reasoning_mode, ingress=ingress,
        )
        try:
            # 首次next执行run_stream admission；与epoch校验同处workspace guard内，
            # 一旦_sync_active登记完成即可释放guard，后续transition会因active而拒绝。
            with self._workspace_transition_guard:
                self._session_lifecycle._assert_workspace_epoch(expected_workspace_epoch)
                try:
                    next(it)
                except StopIteration as exc:
                    return exc.value
            while True:
                try:
                    next(it)
                except StopIteration as exc:
                    return exc.value
        finally:
            try:
                it.close()
            finally:
                self._session_lifecycle._clear_run_acquired_callback(session_id, marker)

    def _run_stream_with_acquired(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        reasoning_mode: str | None = None,
        *,
        on_run_acquired: Any = None,
        expected_workspace_epoch: int | None = None,
        ingress: object | None = None,
    ):
        """内部流式入口：首次推进时原子校验workspace epoch并完成run admission。"""
        marker = self._session_lifecycle._install_run_acquired_callback(session_id, on_run_acquired)
        it = self.run_stream(
            session_id, user_text, model=model, reasoning_effort=reasoning_effort,
            reasoning_mode=reasoning_mode, ingress=ingress,
        )
        try:
            with self._workspace_transition_guard:
                self._session_lifecycle._assert_workspace_epoch(expected_workspace_epoch)
                try:
                    first = next(it)
                except StopIteration as exc:
                    return exc.value
            yield first
            return (yield from it)
        finally:
            try:
                it.close()
            finally:
                self._session_lifecycle._clear_run_acquired_callback(session_id, marker)

    # ---- R9-B5-W2-01 委托壳：职责面已迁 SessionLifecycle（engine_services/session_lifecycle.py），
    # 公开直调面（web/routes、feishu/bridge、tests）签名不变 ----

    def _sync_cancel_discard(self: LoopEngine, session_id: str) -> None:
        """移除会话级同步取消标记（委托 SessionLifecycle；feishu/tests 直调面）."""
        self._session_lifecycle._sync_cancel_discard(session_id)

    def workspace_snapshot(self: LoopEngine):
        """（委托 SessionLifecycle）"""
        return self._session_lifecycle.workspace_snapshot()

    def workspace_transition(self: LoopEngine):
        """（委托 SessionLifecycle）"""
        return self._session_lifecycle.workspace_transition()

    def prepare_workspace(
        self: LoopEngine, workspace_root: str, workspace_id: str | None = None
    ) -> Path:
        """（委托 SessionLifecycle）"""
        return self._session_lifecycle.prepare_workspace(workspace_root, workspace_id)

    def set_workspace(
        self,
        workspace_root: str,
        workspace_id: str | None = None,
        *,
        prepared_sessions_dir: Path | None = None,
    ) -> None:
        """（委托 SessionLifecycle）"""
        self._session_lifecycle.set_workspace(
            workspace_root, workspace_id, prepared_sessions_dir=prepared_sessions_dir
        )

    def _remember(self: LoopEngine, final_answer: str, session_id: str, sess) -> None:
        """记忆块解析落盘（委托 SessionLifecycle；feishu/bridge 直调面）."""
        self._session_lifecycle._remember(final_answer, session_id, sess)

    def run_single(self: LoopEngine, user_text: str, model: str | None = None, *, ingress: object | None = None) -> LoopResult:
        """一次性便捷入口：自动创建新会话并执行完整循环."""
        session_id = self.session.create()
        return self.run(session_id, user_text, model=model, ingress=ingress)

    def close(self: LoopEngine) -> None:
        """释放底层 LLM 客户端连接，幂等且 fail-open."""
        target = self.llm_pool if self.llm_pool is not None else self.llm
        closer = getattr(target, "close", None)
        if closer is None:
            return
        try:
            closer()
        except Exception as exc:  # noqa: BLE001 — 关闭失败 fail-open
            logger.warning("LLM 客户端关闭失败（fail-open）: %s", exc)







