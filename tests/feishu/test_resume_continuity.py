"""续聊上下文连续性测试（tasks 6.3/6.4；FTR-CONT-1~5、FTR-DFX-06/07/09/10）.

覆盖：
- detect_task_continuation 命中 /continue（与飞书指令同口径；变体/防误命中）。
- 授权轮 [Next Step] 锚点注入（checkpoint 来源）+ wire 保留原始 /continue、零程序 prose。
- 非授权轮零新增读取（E-G5）：无 [Next Step]、goal_read=0 审计在场。
- ResumeAnchorReader 三层降级优先级（execution-cursor > checkpoint > none）。
- ResumeCoordinator.prepare_resume 只读预检：repaired / no_event_log 如实标注。
- /continue 入口审计 continue_resume（anchor_source + repair_status 可还原）。
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from llm_loop.core.loop.input_authorization import detect_task_continuation
from llm_loop.event_log.store import EventStore
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.resume import (
    SOURCE_CHECKPOINT,
    SOURCE_EXECUTION_CURSOR,
    SOURCE_NONE,
    ResumeAnchorReader,
    ResumeCoordinator,
)
from llm_loop.feishu.session_map import SessionMap
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.task_store import TaskStore


class _ActionSpy:
    def __init__(self, inner):
        self._inner = inner
        self.calls: list[tuple[str, str, str]] = []

    def record_action(self, phase, action_type, detail):
        self.calls.append((phase, action_type, detail))

    def record_phase(self, phase):
        self._inner.record_phase(phase)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _wire(fake) -> str:
    return json.dumps(fake.calls[-1]["messages"], ensure_ascii=False)


def _seed(engine, sid: str, *, with_checkpoint: bool = True):
    audit = Path(engine.settings.data_dir) / "audit"
    goal = GoalStore(audit).create("续聊连续性目标", session_id=sid)
    tasks = TaskStore(audit)
    t = tasks.create(goal.id, "IN-PROGRESS-0", acceptance=["a0"])
    tasks.update(goal.id, t.task_id, status="in_progress")
    if with_checkpoint:
        GoalStore(audit).checkpoint(
            goal.id,
            what="已完成数据清洗",
            evidence="clean.py",
            next_step="跑数据分析第 3 步",
        )
    return goal


# ── /continue 授权命中（tasks 5.3，ADR-4）──


def test_detect_task_continuation_continue_variants():
    assert detect_task_continuation("/continue") is True
    assert detect_task_continuation("/Continue") is True
    assert detect_task_continuation("  /CONTINUE  ") is True
    # 防误命中：前缀词/普通文本不得授权
    assert detect_task_continuation("/continuation") is False
    assert detect_task_continuation("什么是 /continue 命令") is False
    assert detect_task_continuation("新问题：你好") is False
    # 既有触发词表不回归（词表为完整短语，非单词"继续"）
    assert detect_task_continuation("继续上次任务") is True


# ── 授权轮 [Next Step] 注入（tasks 5.4/6.3-2，FTR-CONT-2、FTR-DFX-06）──


def test_authorized_continue_injects_next_step(build_test_engine):
    engine, fake = build_test_engine([{"content": "恢复续做。"}])
    sid = engine.session.create()
    _seed(engine, sid)

    engine.run(sid, "/continue")
    wire = _wire(fake)

    assert "[Next Step] 跑数据分析第 3 步" in wire, "授权轮应注入 checkpoint 的 next_step"
    assert "已完成数据清洗" not in wire.split("[Next Step]")[0], "锚点仅注入 next 行"
    # 原始 /continue 原样在场（[指令·用户·原文] 段）、零程序 prose
    # （独立 user turn provenance 断言由 e2e T10 ④ 覆盖——飞书链路带 ingress 元数据）
    assert "/continue" in wire
    assert "[程序恢复]" not in wire


def test_authorized_without_checkpoint_skips_next_step(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    sid = engine.session.create()
    _seed(engine, sid, with_checkpoint=False)

    engine.run(sid, "/continue")
    wire = _wire(fake)

    assert "[Next Step]" not in wire, "无锚点（next 为空）应跳过注入（不伪造）"
    assert "slot:task_active" in wire, "既有授权投影不回归"


def test_unauthorized_zero_read_no_next_step(build_test_engine):
    engine, fake = build_test_engine([{"content": "ok"}])
    sid = engine.session.create()
    _seed(engine, sid)  # 活跃 goal 在场，但本轮非续聊授权
    spy = _ActionSpy(engine.status)
    engine.status = spy

    engine.run(sid, "一个全新的独立问题")
    wire = _wire(fake)

    assert "[Next Step]" not in wire, "非授权轮不得注入锚点"
    assert "slot:task_active" not in wire
    zero = [c for c in spy.calls if c[:2] == ("task.active", "unauthorized_zero_projection")]
    assert zero, "E-G5：非授权轮零 Goal/Task 读取审计必须在场"


# ── 锚点读取三层降级（tasks 5.1/6.3-4，ADR-5、FTR-DFX-10）──


def test_anchor_reader_prefers_execution_cursor(build_test_engine, monkeypatch):
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    _seed(engine, sid)
    audit = str(Path(engine.settings.data_dir) / "audit")

    def _fake_get_cursor(store, goal_id, session_id):
        assert goal_id and session_id == sid
        return SimpleNamespace(current_sub_item="正在写测试", next_step="执行 pytest 验证")

    monkeypatch.setattr(TaskStore, "get_cursor", staticmethod(_fake_get_cursor), raising=False)
    anchor = ResumeAnchorReader().read_anchor(sid, audit)

    assert anchor is not None and anchor.source == SOURCE_EXECUTION_CURSOR
    assert anchor.current_sub_item == "正在写测试"
    assert anchor.next_step == "执行 pytest 验证"


def test_anchor_reader_falls_back_to_checkpoint(build_test_engine):
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    _seed(engine, sid)
    audit = str(Path(engine.settings.data_dir) / "audit")

    anchor = ResumeAnchorReader().read_anchor(sid, audit)

    assert anchor is not None and anchor.source == SOURCE_CHECKPOINT
    assert anchor.current_sub_item == "已完成数据清洗"
    assert anchor.next_step == "跑数据分析第 3 步"


def test_anchor_reader_none_without_goal(build_test_engine):
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    audit = str(Path(engine.settings.data_dir) / "audit")

    assert ResumeAnchorReader().read_anchor(sid, audit) is None


# ── 现场预检 repair_status（tasks 5.2/6.3-1，ADR-6、FTR-CONT-1）──


def test_prepare_resume_no_event_log_degrades_truthfully(build_test_engine):
    engine, fake = build_test_engine([])
    sid = engine.session.create()
    _seed(engine, sid)

    prep = ResumeCoordinator().prepare_resume(sid, engine)

    assert prep.anchor_source == SOURCE_CHECKPOINT
    assert prep.repair_status == "no_event_log", "未装配事件日志 → 如实降级标注"


def test_prepare_resume_repaired_when_consistent(build_test_engine, tmp_path):
    engine, fake = build_test_engine([{"content": "第一轮产出。"}])
    engine._event_store = EventStore(tmp_path / "events")
    sid = engine.session.create()
    _seed(engine, sid)
    engine.run(sid, "开始任务")  # 产生事件 + 会话落盘（save 兜底对齐）

    prep = ResumeCoordinator().prepare_resume(sid, engine)

    assert prep.anchor_source == SOURCE_CHECKPOINT
    assert prep.repair_status == "repaired", "事件日志与现场一致 → repaired"


def test_prepare_resume_none_source_when_no_goal(build_test_engine):
    engine, fake = build_test_engine([])
    sid = engine.session.create()

    prep = ResumeCoordinator().prepare_resume(sid, engine)

    assert prep.anchor_source == SOURCE_NONE
    assert prep.anchor is None


# ── /continue 入口审计外显（tasks 5.5/6.3-5，FTR-CONT-5、FTR-DFX-07）──


def test_continue_resume_audit_records_source_and_repair(build_test_engine, tmp_path):
    engine, fake = build_test_engine([])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    audit_dir = tmp_path / "audit"
    handler = FeishuMessageHandler(
        engine, session_map, lambda rid, text, rtype: None, audit_dir=str(audit_dir)
    )
    sid = engine.session.create()
    _seed(engine, sid)
    msg = FeishuMessage(
        message_id="om_c", sender_id="ou_u", chat_id="oc_cont", msg_type="text", text="/continue"
    )

    handler._audit_resume_prep(sid, msg)

    lines = (audit_dir / "feishu_audit.jsonl").read_text(encoding="utf-8").splitlines()
    recs = [json.loads(x) for x in lines if x.strip()]
    resume = [r for r in recs if r.get("kind") == "continue_resume"]
    assert resume, "续聊预检审计必须在场"
    assert "anchor_source=checkpoint" in resume[0]["detail"]
    assert "repair_status=" in resume[0]["detail"], "repair_status 必须外显可审计"


def test_current_processing_sid_registered_during_run(build_test_engine, tmp_path):
    """ADR-3：处理中 session_id 登记（context_ref 数据源）+ finally 清空."""
    engine, fake = build_test_engine([{"content": "ok"}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    handler = FeishuMessageHandler(
        engine, session_map, lambda rid, text, rtype: None, audit_dir=str(tmp_path / "audit")
    )
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_u"))  # 默认私聊键（is_group=False）
    msg = FeishuMessage(
        message_id="om_p", sender_id="ou_u", chat_id="oc_proc", msg_type="text", text="任务"
    )
    observed: list[str] = []

    def _spy_run(m, run_text):
        observed.append(handler.current_processing_sid())

    handler._run_with_processing_actions(msg, _spy_run, "任务")

    assert observed == [sid], "处理中应登记当前 session_id（context_ref 数据源）"
    assert handler.current_processing_sid() == "", "finally 必须清空"
