"""G5 重启授权守卫测试（C-G5 / T5.7，spec 5.2.1 全组 + 5.2.3 + 4.3-2 + 6.3）.

用例名以 spec 验收条目编号为前缀（tasks.md §5.7 清单逐项对应）：
- 1a completed 拒绝重跑 / 1b 全新任务不受限
- 2a 未完成先确认帧 / 2b 同意后执行（帧-应答对应）/ 2c 拒绝与超时留痕
- 3a 授权一次性（跨任务无效）
- 4a 终态未知 confirm 兜底 + 异常留痕
- 5a /continue 无应答零执行
- 6a-6d 普通自然语言绕过 restart semantic gate；只保留 pending /continue 帧应答
- 7a-7b 普通“重跑”交模型判断 / 新任务建模旧终态只读
- 票据重放 / 授权时刻复核 / 帧完整性
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

try:  # handlers 顶层链带 lark_oapi（pyproject 声明依赖，部分环境未装全）——缺依赖时用例统一 skip，不崩收集
    from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
except ImportError:  # pragma: no cover — 环境差异路径
    FeishuMessage = None  # type: ignore[assignment,misc]
    FeishuMessageHandler = None  # type: ignore[assignment,misc]
from llm_loop.feishu.restart_guard import (
    RestartConfirmationFrame,
    RestartGuardService,
    classify_reply,
    frame_complete,
)
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore

# ── 测试基建（stub engine / session_map / handler）──


class _StubRunner:
    def __init__(self) -> None:
        self.enabled = True
        self.running: set[str] = set()

    def is_running(self, sid: str) -> bool:
        return sid in self.running

    def is_sync_active(self, sid: str) -> bool:
        return False


class _StubSession:
    def load(self, sid: str):  # noqa: ANN201 — 非空 messages 即可通过 /continue 预检
        return SimpleNamespace(messages=["历史消息"])


class _StubEngine:
    def __init__(self, audit_dir: str) -> None:
        self.settings = SimpleNamespace(audit_dir=audit_dir)
        self.runner = _StubRunner()
        self.session = _StubSession()
        self.audits: list[tuple[str, str, str]] = []  # (phase, action_type, detail)
        self.ran: list[tuple[str, str]] = []

    def _record_action(self, phase: str, action_type: str, detail: str) -> None:
        self.audits.append((phase, action_type, detail))

    def run(self, sid: str, text: str, ingress=None):  # noqa: ANN001, ANN201
        self.audits.append(("run", "run_started", sid))  # run 启动痕迹（6c 审计序锚点）
        self.ran.append((sid, text))
        return SimpleNamespace(
            final_answer="ok",
            truncated=False,
            verification_note="",
            cancel_reason="",
            model_used="",
            tokens_in=0,
            tokens_out=0,
            tool_calls=[],
        )


class _StubSessionMap:
    def __init__(self, sid: str) -> None:
        self._sid = sid

    def get(self, key: str) -> str:
        return self._sid

    def get_or_create(self, key: str, **_kw) -> str:
        return self._sid


def _audit_types(engine: _StubEngine) -> list[str]:
    return [a[1] for a in engine.audits]


def _audit_details(engine: _StubEngine, action_type: str) -> list[str]:
    return [a[2] for a in engine.audits if a[1] == action_type]


def _make_handler(engine: _StubEngine, sid: str, *, guard: RestartGuardService | None = None):
    if FeishuMessageHandler is None:
        pytest.skip("lark_oapi 未安装（pyproject 声明依赖，此环境未装全）——守卫逻辑由完整环境覆盖")
    replies: list[str] = []
    handler = FeishuMessageHandler(
        engine,
        _StubSessionMap(sid),
        lambda rid, text, rtype: replies.append(text),
        audit_dir=str(Path(engine.settings.audit_dir)),
        typing_ack=False,
        streaming=False,
    )
    if guard is not None:
        handler._restart_guard_svc = guard  # noqa: SLF001 — 共享守卫实例（3a 跨会话）
    return handler, replies


def _msg(text: str) -> FeishuMessage:
    return FeishuMessage(
        message_id=f"m-{text}",
        sender_id="ou-1",
        chat_id="",
        msg_type="text",
        text=text,
        sender_type="user",
    )


def _completed_goal(audit_dir: str, sid: str = "s-done") -> str:
    goal = GoalStore(audit_dir).create("已经做完的任务", session_id=sid)
    GoalStore(audit_dir).update(goal.id, "complete")
    return goal.id


def _inprogress_goal(audit_dir: str, sid: str = "s-wip") -> tuple[str, str]:
    goal = GoalStore(audit_dir).create("进行中的任务", session_id=sid)
    task = TaskStore(audit_dir).create(goal.id, "子任务A", acceptance=["验收1"])
    TaskStore(audit_dir).update(goal.id, task.task_id, status="in_progress")
    return goal.id, task.task_id


# ── 1a completed 拒绝重跑 ──


def test_r521_1a_completed_deny():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    goal_id = _completed_goal(d)
    handler, replies = _make_handler(engine, "s-done")
    handled = handler._try_handle_continue_command(_msg("/continue"), "/continue")
    assert handled is True
    assert engine.ran == []  # 任务不执行
    text = replies[0]
    assert (
        goal_id in text and "不再自动重跑" in text and "发起新任务" in text
    )  # 拒绝回执含标识+引导
    assert (
        "restart_guard",
        "restart.denied",
        f"goal_id={goal_id}; reason=completed",
    ) in engine.audits
    feishu_audit = (Path(d) / "feishu_audit.jsonl").read_text(encoding="utf-8")
    assert "restart_denied" in feishu_audit  # 通道侧留痕


# ── 1b 全新任务不受限 ──


def test_r521_1b_new_task_bypass():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)  # 空 audit_dir：无活跃 goal
    handler, replies = _make_handler(engine, "s-new")
    handled = handler._try_handle_continue_command(_msg("/continue"), "/continue")
    assert handled is True
    assert len(engine.ran) == 1 and engine.ran[0][0] == "s-new"  # 既有直跑零变化
    assert not [a for a in _audit_types(engine) if a.startswith("restart.")]  # 不经守卫分支


# ── 2a 未完成先确认帧不执行 ──


def test_r521_2a_inprogress_confirm_first():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    goal_id, _ = _inprogress_goal(d, "s-wip")
    handler, replies = _make_handler(engine, "s-wip")
    handled = handler._try_handle_continue_command(_msg("/continue"), "/continue")
    assert handled is True
    assert engine.ran == []  # 未获同意前不执行
    assert "[重启确认]" in replies[0] and goal_id in replies[0]  # 帧含任务标识
    assert "进度锚点" in replies[0] and "待续" in replies[0]  # 帧含进度锚点与待续概要
    confirms = _audit_details(engine, "restart.confirm")
    assert len(confirms) == 1 and f"goal_id={goal_id}" in confirms[0]


# ── 2b 同意后执行 + 帧-应答对应审计 ──


def test_r521_2b_approve_then_run():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    decision = handler._restart_guard().check_restart("s-wip")
    assert decision.kind == "confirm"  # 前置：帧已挂起
    handled = handler._try_restart_gate(_msg("同意"), "同意")
    assert handled is True
    assert engine.ran == [("s-wip", "/continue")]  # 执行原始排队命令，不把“同意”伪装成任务文本
    approved = _audit_details(engine, "restart.authorization")
    assert any("decision=approved" in x and decision.frame.frame_id in x for x in approved)


# ── 2c 拒绝 / 超时留痕且不执行 ──


def test_r521_2c_deny_and_timeout():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    handled = handler._try_restart_gate(_msg("拒绝"), "拒绝")
    assert handled is True and engine.ran == []  # 拒绝不执行
    denied = _audit_details(engine, "restart.authorization")
    assert any("decision=denied" in x for x in denied)
    # 超时：极短 TTL → 帧 purge → timeout 留痕 + 后续授权词返回 timeout，不降级自动执行
    _inprogress_goal(d, "s-wip2")
    guard = RestartGuardService(engine, ttl_s=0.05)
    handler2, _r2 = _make_handler(engine, "s-wip2", guard=guard)
    assert guard.check_restart("s-wip2").kind == "confirm"
    time.sleep(0.12)
    grant = guard.match_reply("s-wip2", "同意")
    assert not grant.ok and grant.decision == "timeout"
    auth = _audit_details(engine, "restart.authorization")
    assert any("decision=timeout" in x for x in auth)  # 超时留痕
    assert all(sid != "s-wip2" for sid, _text in engine.ran)  # 超时不降级自动执行


# ── 3a 授权一次性（T1 授权不放行 T2）──


def test_r521_3a_cross_task_grant_invalid():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    goal_a, _ = _inprogress_goal(d, "s-a")
    goal_b, _ = _inprogress_goal(d, "s-b")
    guard = RestartGuardService(engine)
    handler_a, replies_a = _make_handler(engine, "s-a", guard=guard)
    handler_b, replies_b = _make_handler(engine, "s-b", guard=guard)
    assert handler_a._try_handle_continue_command(_msg("/continue"), "/continue") is True
    assert handler_a._try_restart_gate(_msg("同意"), "同意") is True  # T1 授权放行
    assert engine.ran[0] == ("s-a", "/continue")
    grant = guard.consume_grant(_find_frame(guard, goal_a))
    assert not grant.ok and grant.decision == "consumed"  # T1 票据已焚
    assert handler_b._try_handle_continue_command(_msg("/continue"), "/continue") is True
    assert engine.ran == [("s-a", "/continue")]  # T2 未因 T1 授权放行
    assert any("[重启确认]" in x and goal_b in x for x in replies_b)  # T2 须自己的确认帧流程


def _find_frame(guard: RestartGuardService, goal_id: str) -> str:
    with guard._lock:  # noqa: SLF001 — 测试读取 pending 登记
        for fid, entry in guard._pending.items():
            if entry.goal_id == goal_id:
                return fid
    raise AssertionError(f"no pending frame for {goal_id}")


# ── 4a 终态未知 confirm 兜底 + 异常留痕 ──


def test_r521_4a_unknown_state_confirm():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    Path(d, "goals.jsonl").write_text("not-json-line\n", encoding="utf-8")  # 全坏行 → 查询必抛
    handler, replies = _make_handler(engine, "s-x")
    handled = handler._try_handle_continue_command(_msg("/continue"), "/continue")
    assert handled is True
    assert engine.ran == []  # 不直接执行
    assert "[重启确认]" in replies[0] or "状态待确认" in replies[0]  # 确认帧路径（兜底文案）
    assert any(a[1] == "restart.guard_error" for a in engine.audits)  # 异常留痕
    confirms = _audit_details(engine, "restart.confirm")
    assert confirms and "state=state_unknown" in confirms[0]


# ── 5a /continue 无应答零执行 ──


def test_r521_5a_no_silent_run_on_continue():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    assert engine.ran == []  # 已开始任务零执行（无明确应答）
    assert handler._restart_guard().pending_frame_count() == 1  # 帧挂起等待授权


# ── 6a 普通“继续”不再读取历史 Goal 判定语义 ──


def test_r521_6a_bare_continue_reaches_model_unchanged():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, replies = _make_handler(engine, "s-wip")
    handled = handler._try_restart_gate(_msg("继续"), "继续")
    assert handled is False
    assert replies == [] and engine.ran == []
    assert not [a for a in _audit_types(engine) if a.startswith("restart.")]


# ── 6b 旧 notify_confirm env 不得恢复普通消息语义门 ──


def test_r521_6b_legacy_notify_mode_cannot_reenable_bare_gate(monkeypatch):
    monkeypatch.setenv("LFL_RESTART_NOTIFY_MODE", "notify_confirm")
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, replies = _make_handler(engine, "s-wip")
    assert handler._try_restart_gate(_msg("继续"), "继续") is False
    assert replies == [] and engine.ran == []


# ── 6c 只有既存 /continue pending frame 才消费“同意/拒绝” ──


def test_r521_6c_pending_frame_remains_scoped_control_protocol():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    assert engine.ran == []
    assert handler._try_restart_gate(_msg("同意"), "同意") is True
    assert engine.ran == [("s-wip", "/continue")]


# ── 6d 显式新任务指令零误伤 ──


def test_r521_6d_explicit_new_task_unaffected():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)  # 无活跃 goal：新任务/新会话场景
    handler, replies = _make_handler(engine, "s-new")
    text = "帮我新建一个任务：写周报"
    handled = handler._try_restart_gate(_msg(text), text)
    assert handled is False  # 守卫放行（return False → 调用方继续既有直跑路径）
    assert replies == []  # 无任何守卫帧
    handler._run_with_processing_actions(_msg(text), handler._run_text, text)
    assert len(engine.ran) == 1  # 直跑零变化（零误伤）
    assert not [a for a in _audit_types(engine) if a.startswith("restart.")]  # 零守卫痕迹


# ── 7a completed + 普通“重跑”也交当前模型判断 ──


def test_r521_7a_plain_rerun_text_is_not_program_denied():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _completed_goal(d, "s-done")
    handler, replies = _make_handler(engine, "s-done")

    handled = handler._try_restart_gate(_msg("重跑这个任务"), "重跑这个任务")
    assert handled is False
    assert engine.ran == [] and replies == []
    assert not _audit_details(engine, "restart.denied")


# ── 7b 显式坚持重跑 → 新任务建模：新 goal_id、旧终态只读 ──


def test_r521_7b_rerun_models_new_goal():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    old_goal, old_task = _inprogress_goal(d, "s-old")
    TaskStore(d).update(old_goal, old_task, status="done")
    GoalStore(d).update(old_goal, "complete")
    engine.settings.audit_dir = d
    guard = RestartGuardService(engine)
    # 新会话（坚持重跑按新任务发起）：普通自然语言不经 restart semantic gate。
    handler, replies = _make_handler(engine, "s-new2", guard=guard)
    assert handler._try_restart_gate(_msg("重做这个任务"), "重做这个任务") is False
    assert replies == []
    new_goal = GoalStore(d).create(
        "重做：进行中的任务（新任务）", session_id="s-new2"
    )  # 既有创建链
    new_task = TaskStore(d).create(new_goal.id, "子任务A（重做）", acceptance=["验收1"])
    TaskStore(d).update(new_goal.id, new_task.task_id, status="in_progress")
    # 旧任务终态记录只读不变（done/complete 账本未被触碰）
    assert GoalStore(d).get(goal_id=old_goal)["status"] == "complete"
    assert TaskStore(d).get(old_goal, old_task).status == "done"
    # 新旧 goal_id 并存可溯（审计可区分）
    ids = {g["id"] for g in GoalStore(d).list()}
    assert old_goal in ids and new_goal.id in ids and old_goal != new_goal.id
    # 守卫只读核验：restart_guard 源码无账本写入口（无 .update( / .create( 调用）
    import llm_loop.feishu.restart_guard as rg_mod

    src = Path(rg_mod.__file__).read_text(encoding="utf-8")
    assert ".update(" not in src and ".create(" not in src


# ── 票据重放：二次消费 consumed 不二次放行 ──


def test_grant_replay_consumed_rejected():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    decision = handler._restart_guard().check_restart("s-wip")
    frame_id = decision.frame.frame_id
    guard = handler._restart_guard()
    grant1 = guard.match_reply("s-wip", "同意")  # 首次经应答处置：approved
    assert grant1.ok and grant1.decision == "approved"
    grant2 = guard.consume_grant(frame_id)
    assert not grant2.ok and grant2.decision == "consumed"  # 二次消费不二次放行
    # 同帧同意不再 approved（票据已焚，结构性不可能复用）
    handler._try_restart_gate(_msg("同意"), "同意")
    approved = [
        x for x in _audit_details(engine, "restart.authorization") if "decision=approved" in x
    ]
    assert len(approved) == 1


# ── 授权时刻复核：等待期变 done → 转拒绝 ──


def test_grant_recheck_on_concurrent_done():
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    goal_id, task_id = _inprogress_goal(d, "s-wip")
    handler, replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True
    TaskStore(d).update(goal_id, task_id, status="done")  # 等待期并发完成
    handled = handler._try_restart_gate(_msg("同意"), "同意")
    assert handled is True
    assert engine.ran == []  # 转拒绝不执行
    assert "任务已完成，无需重启" in replies[-1]
    denied = [x for x in _audit_details(engine, "restart.authorization") if "decision=denied" in x]
    assert any("reason=completed" in x and f"goal_id={goal_id}" in x for x in denied)


# ── 帧完整性：缺任务标识/进度信息 → 无效 ──


def test_frame_without_required_fields_invalid():
    base = dict(
        frame_id="f1",
        goal_id="G1",
        task_summary="t",
        anchor_source="checkpoint",
        current_sub_item="做了一半",
        next_step="继续做",
        pending_summary="待续 1 项",
        created_at="t0",
    )
    assert frame_complete(RestartConfirmationFrame(**base))  # 完整帧有效
    assert not frame_complete(None)
    assert not frame_complete(RestartConfirmationFrame(**{**base, "goal_id": ""}))  # 缺任务标识
    no_progress = {**base, "current_sub_item": "", "next_step": "", "pending_summary": ""}
    assert not frame_complete(RestartConfirmationFrame(**no_progress))  # 缺进度信息


def test_pending_reply_classifier_never_authorizes_by_substring() -> None:
    """Negated/ordinary prose must not accidentally become an approval token."""
    assert classify_reply("不同意") == "deny"
    assert classify_reply("不要继续") == "deny"
    assert classify_reply("同意。") == "approve"
    assert classify_reply("我同意你继续分析这篇文章") == "none"
    assert classify_reply("我们继续讨论，但不要执行") == "none"


def test_pending_frame_negated_approval_never_runs() -> None:
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, _replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True

    handled = handler._try_restart_gate(_msg("不同意"), "不同意")
    assert handled is True
    assert engine.ran == []
    assert any("decision=denied" in x for x in _audit_details(engine, "restart.authorization"))


def test_continue_guard_internal_crash_does_not_start_run(monkeypatch) -> None:
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    handler, replies = _make_handler(engine, "s-wip")

    class _BrokenGuard:
        def check_restart(self, _sid: str):
            raise RuntimeError("guard unavailable")

    handler._restart_guard_svc = _BrokenGuard()  # noqa: SLF001
    handled = handler._try_handle_continue_command(_msg("/continue"), "/continue")
    assert handled is True
    assert engine.ran == []
    assert replies and "本次未恢复执行" in replies[-1]


def test_grant_recheck_failure_never_turns_unknown_into_authorization(monkeypatch) -> None:
    d = tempfile.mkdtemp()
    engine = _StubEngine(d)
    _inprogress_goal(d, "s-wip")
    handler, replies = _make_handler(engine, "s-wip")
    assert handler._try_handle_continue_command(_msg("/continue"), "/continue") is True

    from llm_loop.introspection.goal import GoalStore

    def _boom(*_args, **_kwargs):
        raise OSError("ledger temporarily unreadable")

    monkeypatch.setattr(GoalStore, "get", _boom)
    handled = handler._try_restart_gate(_msg("同意"), "同意")
    assert handled is True
    assert engine.ran == []
    assert replies and "状态无法可靠复核" in replies[-1]
    assert any(
        "decision=denied" in x and "reason=state_unknown" in x
        for x in _audit_details(engine, "restart.authorization")
    )
