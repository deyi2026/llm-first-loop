"""SessionLifecycle——会话前段 reconcile / workspace 职责面 / 收尾持久化（R9 Phase 5 T6-A）.

B5-W2-01 迁入：_LifecycleMixin 职责面 11 法 + engine._run_stream_inner 前段
（exists/load/run_save_token 绑定/on_run_acquired/新建 repair/accepted persist）
装配为 reconcile(session_id) -> SessionPlan 门面。方法体逐字平移，
``self.`` → ``self._host.``（宿主 = LoopEngine；session/workspace_store/
memory/recovery/_cache_monitor/_run_acquired_callbacks* 等实例态与组件全留宿主）。
行为零变化：

- 编排入口（run_stream/run/run_single/close/_run_with_acquired 系）留宿主
  lifecycle.py（Mixin 更名 _RunEntrypointMixin，职责纯化）
- 公开面委托壳留宿主：workspace_snapshot/transition/prepare_workspace/
  set_workspace/_remember/_sync_cancel_discard（web/routes、feishu/bridge、
  tests 直调面签名不变）
- run admission 编排归装与 RunCoordinator 组装见 W5 组

宿主依赖（engine 持有）：session / settings / workspace_store / memory /
recovery / workspace_root / workspace_id / _workspace_epoch / _cache_monitor /
registry / correction_ctx / _run_sessions / _run_states_guard /
_run_acquired_callbacks / _run_acquired_callbacks_guard / _session_payload /
_fault_feedback / _record_program_fault / _record_action / _evidence_legacy_migrate_workspace_fn
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (host 属性来自 LoopEngine 混入体系，pyright 无法静态解析，文件级关闭这两条；
#   沿 recovery_controller.py 既有豁免口径)

from __future__ import annotations

import contextlib
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llm_loop.memory.extract import extract_memory_blocks, memory_blocks_to_entries

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


class SessionPlan:
    """reconcile 产物：会话载入态快照（engine 前段解构消费，字段面显式冻结）."""

    __slots__ = ("session_existed", "sess", "accepted_changed")

    def __init__(self, *, sess: Any, session_existed: bool, accepted_changed: bool) -> None:
        self.sess = sess
        self.session_existed = session_existed
        self.accepted_changed = accepted_changed


class SessionLifecycle:
    """会话生命周期职责：reconcile 前段 + workspace 职责面 + 收尾持久化."""

    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _sync_cancel_discard(self, session_id: str) -> None:
        """移除会话级同步取消标记（经 runner.discard_sync_cancel；fail-open 兼容旧装配）."""
        runner = getattr(self._host, "runner", None)
        fn = getattr(runner, "discard_sync_cancel", None) if runner is not None else None
        if callable(fn):
            try:
                fn(session_id)
            except Exception:  # noqa: BLE001 — fail-open 不阻断 run 生命周期
                logger.warning("同步取消标记清理失败（fail-open）: %s", session_id, exc_info=True)

    def _install_run_acquired_callback(
        self, session_id: str, callback: Any
    ) -> Any:
        if callback is None:
            return None
        with self._host._run_acquired_callbacks_guard:
            if session_id in self._host._run_acquired_callbacks:
                from llm_loop.core.loop.runner import SessionBusyError

                raise SessionBusyError(f"会话 {session_id} 已有待执行的 accepted callback")
            self._host._run_acquired_callbacks[session_id] = callback
        return callback

    def _clear_run_acquired_callback(
        self, session_id: str, marker: Any
    ) -> None:
        if marker is None:
            return
        with self._host._run_acquired_callbacks_guard:
            if self._host._run_acquired_callbacks.get(session_id) is marker:
                self._host._run_acquired_callbacks.pop(session_id, None)

    def _assert_workspace_epoch(self, expected_workspace_epoch: int | None) -> None:
        if expected_workspace_epoch is None:
            return
        if self._host._workspace_epoch != expected_workspace_epoch:
            from llm_loop.workspace.store import WorkspaceChangedError

            raise WorkspaceChangedError("请求解析会话后工作区已切换，请重新选择会话后重试")

    def _workspace_session_root(
        self, workspace_root: str, workspace_id: str | None = None
    ) -> tuple[str, Path]:
        """解析workspace对应session分区，不产生文件系统副作用。"""
        new_root = workspace_root or ""
        base = Path(self._host.settings.sessions_dir)
        if not new_root:
            return new_root, base
        from llm_loop.workspace.store import _validate_workspace_id, workspace_key

        partition_id = workspace_id or ""
        if not partition_id and self._host.workspace_store is not None:
            finder = getattr(self._host.workspace_store, "get_by_path", None)
            if callable(finder):
                ws = finder(new_root)
                partition_id = getattr(ws, "id", "") if ws is not None else ""
        partition_id = _validate_workspace_id(partition_id or workspace_key(new_root))
        return new_root, base / partition_id

    @contextmanager
    def workspace_snapshot(self):
        """短暂冻结workspace用于session查/建；正常并发请求排队，不误报workspace busy。"""
        # snapshot只保护“读取当前root/epoch + session查建”这一小段。多个请求可以
        # 顺序穿过临界区；若恰逢workspace transition，则等待其提交后读取新epoch。
        # 真正的busy语义只属于transition遇到active run，不属于snapshot彼此竞争。
        with self._host._workspace_transition_guard:
            yield self._host._workspace_epoch

    @contextmanager
    def workspace_transition(self):
        """独占workspace根切换窗口；任意active run存在时fail-fast。"""
        from llm_loop.workspace.store import WorkspaceBusyError

        acquired = self._host._workspace_transition_guard.acquire(blocking=False)
        if not acquired:
            raise WorkspaceBusyError("工作区切换/运行准入正在进行，请稍后重试")
        try:
            runner = getattr(self._host, "runner", None)
            has_background = bool(
                runner is not None
                and getattr(runner, "enabled", False)
                and getattr(runner, "has_running", lambda: False)()
            )
            with self._host._sync_guard:
                has_sync = bool(self._host._sync_active)
            if has_background or has_sync:
                raise WorkspaceBusyError("存在进行中的会话运行，暂不能切换工作区")
            yield
        finally:
            self._host._workspace_transition_guard.release()

    def prepare_workspace(
        self, workspace_root: str, workspace_id: str | None = None
    ) -> Path:
        """只准备可能失败的session分区；registry提交前可安全调用。"""
        _new_root, session_root = self._workspace_session_root(workspace_root, workspace_id)
        return self._host.session.prepare_root(session_root)

    def set_workspace(
        self,
        workspace_root: str,
        workspace_id: str | None = None,
        *,
        prepared_sessions_dir: Path | None = None,
    ) -> None:
        """激活工作区；若传prepared_sessions_dir则提交后不再做文件系统I/O。"""
        with self._host.workspace_transition():
            new_root, session_root = self._workspace_session_root(workspace_root, workspace_id)
            if prepared_sessions_dir is None:
                prepared_sessions_dir = self._host.session.prepare_root(session_root)
            elif Path(prepared_sessions_dir) != session_root:
                raise ValueError("prepared session root 与 workspace 分区不一致")
            changed = self._host.workspace_root != new_root or self._host.session.root != session_root
            self._host.session.activate_prepared_root(prepared_sessions_dir)
            self._host.workspace_root = new_root
            if changed:
                self._host._workspace_epoch += 1
            migrate_legacy = getattr(self._host, "_evidence_legacy_migrate_workspace_fn", None)
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
        self,
        *,
        target_type: str,
        source_id: str,
        write_fn: Any,
        payload: str,
        trigger_point: str,
    ) -> str:
        """调 RecoveryChannel.persist_with_recovery 并返回用户可见标注文本."""
        if self._host.recovery is None:
            return ""
        try:
            receipt = self._host.recovery.persist_with_recovery(
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

    def _remember(self, final_answer: str, session_id: str, sess) -> None:
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
                self._host.memory.save_entry(entry)
            if failures:
                logger.warning(
                    "记忆块解析失败 %d 条（如实记录，不丢弃回答）: %s",
                    len(failures),
                    failures[:2],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆沉淀失败（不阻塞主循环）: %s", exc)

    def reconcile(
        self,
        session_id: str,
        *,
        run_save_token: object | None = None,
        on_run_acquired: Any = None,
    ) -> SessionPlan:
        """run 前段装配：exists/load/run_save_token 绑定/on_run_acquired/新建 repair/accepted persist.

        逐字平移自 engine._run_stream_inner 前段（B5-W2-01）；fail-open 语义与
        fault 观测面（_fault_feedback/_record_program_fault/_record_action）保持。
        """
        # 会话恢复（重启继续对话，DFX-REL-03）
        session_existed = self._host.session.exists(session_id)
        sess = self._host.session.load(session_id)
        if run_save_token is not None:
            self._host.session._bind_run_save_token(sess, run_save_token)
        accepted_changed = False
        if on_run_acquired is not None:
            try:
                on_run_acquired(sess)
                accepted_changed = True
            except TypeError:
                # BackgroundRunner.before_start 历史兼容：旧内部调用方可能仍传零参 callback。
                try:
                    on_run_acquired()
                    accepted_changed = True
                except Exception:  # noqa: BLE001 — accepted 辅助动作 fail-open
                    logger.warning("run accepted callback 失败（fail-open）", exc_info=True)
            except Exception:  # noqa: BLE001 — accepted 辅助动作 fail-open
                logger.warning("run accepted callback 失败（fail-open）", exc_info=True)

        if not session_existed:
            # 2026-08-20 (EVO-20260820-0b96348d, 用户决策): 新会话首轮仅重置活动窗口与
            # 模型游标（note_new_session），**保留模型桶**——桶是模型生命周期统计，
            # 跨会话/跨切换持久，保证连续切换模型对话时各模型命中率统计稳定连续。
            try:
                if self._host._cache_monitor is not None:
                    self._host._cache_monitor.note_new_session(session_id=session_id)
            except Exception:  # noqa: BLE001 — fail-open
                logger.debug("新会话缓存健康重置异常（fail-open）", exc_info=True)
            try:
                self._host.session.save(sess)
            except Exception as exc:
                # R8.10/E33: persistence fault is runtime observability, not model authority.
                # Keep recovery + selfheal/status telemetry, but never append fault prose to
                # conversational history or the provider prompt.
                logger.warning("初始会话保存失败（fail-open）", exc_info=True)
                recovery_note = self._persist_with_recovery_note(
                    target_type="session",
                    source_id=sess.session_id,
                    write_fn=lambda: self._host.session.save(sess),
                    payload=self._host._session_payload(sess),
                    trigger_point="initial_save",
                )
                self._host._fault_feedback("session_persistence", exc)  # selfheal_log side effect only
                self._host._record_program_fault("session_persist")
                with contextlib.suppress(Exception):
                    self._host._record_action(
                        "session_persistence",
                        "fault_observed",
                        f"error={type(exc).__name__};recovery={'recorded' if recovery_note else 'none'}",
                    )
        elif accepted_changed:
            try:
                self._host.session.save(sess)
            except Exception:  # noqa: BLE001 — accepted 辅助持久化失败不阻断本次 run
                logger.warning("run accepted 状态持久化失败（fail-open）", exc_info=True)

        return SessionPlan(
            sess=sess, session_existed=session_existed, accepted_changed=accepted_changed
        )
