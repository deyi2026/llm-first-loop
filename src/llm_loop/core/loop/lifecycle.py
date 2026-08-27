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
    current_session_id as _current_session_id,
)
from llm_loop.core.run_context import (
    current_workspace_root as _current_workspace_root,
)
from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine, LoopResult
    from llm_loop.llm.client import StreamDelta

logger = logging.getLogger(__name__)


class _LifecycleMixin:
    # ── 主入口 ──
    def run_stream(
        self, session_id: str, user_text: str, model: str | None = None,
        reasoning_effort: str | None = None,
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
                self._sync_active.add(session_id)
            run_workspace = self.workspace_root or ""

        run_effort = reasoning_effort or ""
        run_model_label = ""
        _run_stack = ExitStack()
        _run_save_token: object | None = None
        inner = None

        @contextmanager
        def _bound_run_context():
            sid_token = _current_session_id.set(session_id)
            ws_token = _current_workspace_root.set(run_workspace)
            effort_token = _current_reasoning_effort.set(run_effort)
            model_token = _current_model_label.set(run_model_label)
            try:
                yield
            finally:
                _current_model_label.reset(model_token)
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
            with self._run_states_guard:
                self._run_sessions.pop(session_id, None)
            if _run_save_token is not None:
                self.session._deactivate_run_save_token(session_id, _run_save_token)
            _run_stack.close()
            with self._sync_guard:
                self._sync_active.discard(session_id)


    def run(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> LoopResult:
        """单条用户消息的完整循环（run_stream 的同步聚合包装，签名/返回不变）.

        model: 可选，本次对话覆盖使用的 LLM 模型（None 用装配模型，Web 模型切换用）。
        """
        it = self.run_stream(
            session_id, user_text, model, reasoning_effort=reasoning_effort,
        )
        while True:
            try:
                next(it)
            except StopIteration as exc:
                return exc.value

    def _install_run_acquired_callback(
        self: LoopEngine, session_id: str, callback: Any
    ) -> Any:
        if callback is None:
            return None
        with self._run_acquired_callbacks_guard:
            if session_id in self._run_acquired_callbacks:
                from llm_loop.core.loop.runner import SessionBusyError

                raise SessionBusyError(f"会话 {session_id} 已有待执行的 accepted callback")
            self._run_acquired_callbacks[session_id] = callback
        return callback

    def _clear_run_acquired_callback(
        self: LoopEngine, session_id: str, marker: Any
    ) -> None:
        if marker is None:
            return
        with self._run_acquired_callbacks_guard:
            if self._run_acquired_callbacks.get(session_id) is marker:
                self._run_acquired_callbacks.pop(session_id, None)

    def _assert_workspace_epoch(self: LoopEngine, expected_workspace_epoch: int | None) -> None:
        if expected_workspace_epoch is None:
            return
        if self._workspace_epoch != expected_workspace_epoch:
            from llm_loop.workspace.store import WorkspaceChangedError

            raise WorkspaceChangedError("请求解析会话后工作区已切换，请重新选择会话后重试")

    def _run_with_acquired(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        *,
        on_run_acquired: Any = None,
        expected_workspace_epoch: int | None = None,
    ) -> LoopResult:
        """内部同步入口：首个generator推进前校验session解析时的workspace epoch。"""
        marker = self._install_run_acquired_callback(session_id, on_run_acquired)
        it = self.run_stream(
            session_id, user_text, model=model, reasoning_effort=reasoning_effort
        )
        try:
            # 首次next执行run_stream admission；与epoch校验同处workspace guard内，
            # 一旦_sync_active登记完成即可释放guard，后续transition会因active而拒绝。
            with self._workspace_transition_guard:
                self._assert_workspace_epoch(expected_workspace_epoch)
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
                self._clear_run_acquired_callback(session_id, marker)

    def _run_stream_with_acquired(
        self: LoopEngine,
        session_id: str,
        user_text: str,
        model: str | None = None,
        reasoning_effort: str | None = None,
        *,
        on_run_acquired: Any = None,
        expected_workspace_epoch: int | None = None,
    ):
        """内部流式入口：首次推进时原子校验workspace epoch并完成run admission。"""
        marker = self._install_run_acquired_callback(session_id, on_run_acquired)
        it = self.run_stream(
            session_id, user_text, model=model, reasoning_effort=reasoning_effort
        )
        try:
            with self._workspace_transition_guard:
                self._assert_workspace_epoch(expected_workspace_epoch)
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
                self._clear_run_acquired_callback(session_id, marker)

    def run_single(self: LoopEngine, user_text: str, model: str | None = None) -> LoopResult:
        """一次性便捷入口：自动创建新会话并执行完整循环."""
        session_id = self.session.create()
        return self.run(session_id, user_text, model=model)

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

    def _workspace_session_root(
        self: LoopEngine, workspace_root: str, workspace_id: str | None = None
    ) -> tuple[str, Path]:
        """解析workspace对应session分区，不产生文件系统副作用。"""
        new_root = workspace_root or ""
        base = Path(self.settings.sessions_dir)
        if not new_root:
            return new_root, base
        from llm_loop.workspace.store import _validate_workspace_id, workspace_key

        partition_id = workspace_id or ""
        if not partition_id and self.workspace_store is not None:
            finder = getattr(self.workspace_store, "get_by_path", None)
            if callable(finder):
                ws = finder(new_root)
                partition_id = getattr(ws, "id", "") if ws is not None else ""
        partition_id = _validate_workspace_id(partition_id or workspace_key(new_root))
        return new_root, base / partition_id

    @contextmanager
    def workspace_snapshot(self: LoopEngine):
        """短暂冻结workspace用于session查/建；正常并发请求排队，不误报workspace busy。"""
        # snapshot只保护“读取当前root/epoch + session查建”这一小段。多个请求可以
        # 顺序穿过临界区；若恰逢workspace transition，则等待其提交后读取新epoch。
        # 真正的busy语义只属于transition遇到active run，不属于snapshot彼此竞争。
        with self._workspace_transition_guard:
            yield self._workspace_epoch

    @contextmanager
    def workspace_transition(self: LoopEngine):
        """独占workspace根切换窗口；任意active run存在时fail-fast。"""
        from llm_loop.workspace.store import WorkspaceBusyError

        acquired = self._workspace_transition_guard.acquire(blocking=False)
        if not acquired:
            raise WorkspaceBusyError("工作区切换/运行准入正在进行，请稍后重试")
        try:
            runner = getattr(self, "runner", None)
            has_background = bool(
                runner is not None
                and getattr(runner, "enabled", False)
                and getattr(runner, "has_running", lambda: False)()
            )
            with self._sync_guard:
                has_sync = bool(self._sync_active)
            if has_background or has_sync:
                raise WorkspaceBusyError("存在进行中的会话运行，暂不能切换工作区")
            yield
        finally:
            self._workspace_transition_guard.release()

    def prepare_workspace(
        self: LoopEngine, workspace_root: str, workspace_id: str | None = None
    ) -> Path:
        """只准备可能失败的session分区；registry提交前可安全调用。"""
        _new_root, session_root = self._workspace_session_root(workspace_root, workspace_id)
        return self.session.prepare_root(session_root)

    def set_workspace(
        self: LoopEngine,
        workspace_root: str,
        workspace_id: str | None = None,
        *,
        prepared_sessions_dir: Path | None = None,
    ) -> None:
        """激活工作区；若传prepared_sessions_dir则提交后不再做文件系统I/O。"""
        with self.workspace_transition():
            new_root, session_root = self._workspace_session_root(workspace_root, workspace_id)
            if prepared_sessions_dir is None:
                prepared_sessions_dir = self.session.prepare_root(session_root)
            elif Path(prepared_sessions_dir) != session_root:
                raise ValueError("prepared session root 与 workspace 分区不一致")
            changed = self.workspace_root != new_root or self.session.root != session_root
            self.session.activate_prepared_root(prepared_sessions_dir)
            self.workspace_root = new_root
            if changed:
                self._workspace_epoch += 1
            migrate_legacy = getattr(self, "_evidence_legacy_migrate_workspace_fn", None)
            if callable(migrate_legacy):
                try:
                    report = migrate_legacy(str(new_root))
                    logger.info("Evidence legacy sidecar migration after workspace activation: %s", report)
                except Exception:  # noqa: BLE001 - unproven legacy files remain model-invisible
                    logger.exception(
                        "Evidence legacy sidecar migration failed after workspace activation; "
                        "legacy files remain quarantined/unowned"
                    )

    def _persist_with_recovery_note(
        self: LoopEngine,
        *,
        target_type: str,
        source_id: str,
        write_fn: Any,
        payload: str,
        trigger_point: str,
    ) -> str:
        """调 RecoveryChannel.persist_with_recovery 并返回用户可见标注文本."""
        if self.recovery is None:
            return ""
        try:
            receipt = self.recovery.persist_with_recovery(
                target_type=target_type,
                source_id=source_id,
                write_fn=write_fn,
                payload=payload,
                trigger_point=trigger_point,
            )
        except Exception:  # noqa: BLE001 — 恢复通道自身失败不中断主循环
            logger.warning("恢复通道异常（fail-open）", exc_info=True)
            return "[恢复通道异常] 重试/备份均未完成"
        if receipt.status == "retried_ok":
            return f"[恢复通道] 已重试 {receipt.retries} 次后成功落盘"
        if receipt.status == "backed_up":
            return f"[恢复通道] 重试 {receipt.retries} 次仍失败，已备份 {receipt.backup_id}"
        return f"[恢复通道] 重试 {receipt.retries} 次仍失败，备份也失败: {receipt.error}"

    def _remember(self: LoopEngine, final_answer: str, session_id: str, sess) -> None:
        """解析最终回答的记忆块并落盘（FR-MEM-01/03，失败不阻塞）."""
        if not final_answer.strip():
            return
        try:
            blocks = extract_memory_blocks(final_answer)
            if not blocks:
                return
            entries, failures = memory_blocks_to_entries(
                blocks,
                session_id=session_id,
                message_id=str(len(sess.messages)),
            )
            for entry in entries:
                entry.deposit_path = "inline"
                self.memory.save_entry(entry)
            if failures:
                logger.warning(
                    "记忆块解析失败 %d 条（如实记录，不丢弃回答）: %s",
                    len(failures),
                    failures[:2],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆沉淀失败（不阻塞主循环）: %s", exc)
