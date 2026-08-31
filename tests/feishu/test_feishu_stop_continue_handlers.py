"""飞书 /stop·/continue 拦截器矩阵单元测试（T1/T5/T6，tasks 3.8）.

T1 匹配矩阵（含只读定位断言） / T5 幂等 / T6 忙拒绝·空防呆·降级·处理异常。
"""

from __future__ import annotations

import json

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap


def _msg(text: str, chat_id: str = "oc_a", sender_id: str = "ou_a") -> FeishuMessage:
    return FeishuMessage(
        message_id=f"om_{text}",
        sender_id=sender_id,
        chat_id=chat_id,
        msg_type="text",
        text=text,
    )


def _make(build_test_engine, tmp_path, responses=None):
    engine, fake = build_test_engine(responses or [{"content": "默认回答"}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_map.json"))
    replies: list[tuple[str, str, str]] = []
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(tmp_path / "audit"),
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    return handler, engine, fake, session_map, replies, runner


def _audit_kinds(tmp_path) -> list[str]:
    p = tmp_path / "audit" / "feishu_audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(line)["kind"] for line in p.read_text().splitlines() if line.strip()]


# ── T1 匹配矩阵 ──


def test_stop_command_variants_intercepted(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    engine._sync_active.add(sid)  # 模拟推理进行中（同步 run 活跃）

    for text in ("/stop", "/STOP", " /stop ", "/Stop"):
        replies.clear()
        handler.handle(_msg(text=text))
        assert any("停止已受理" in r[1] for r in replies), f"{text!r} 应被拦截并受理"
        assert len(fake.calls) == 0  # 不进引擎
    assert "stop_accepted" in _audit_kinds(tmp_path)


def test_continue_command_variants_intercepted(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    session_map.get_or_create(SessionMap.p2p_key("ou_a"))

    for text in ("/continue", "/Continue", " /CONTINUE "):
        handler.handle(_msg(text=text))
        assert any("无可恢复内容" in r[1] for r in replies), f"{text!r} 应被拦截（空会话防呆）"
        assert len(fake.calls) == 0  # 无 LLM 调用


def test_non_command_text_goes_normal_path(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(
        build_test_engine, tmp_path, [{"content": "普通回答"}, {"content": "普通回答"}]
    )
    session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    handler.handle(_msg(text="stop"))
    handler.handle(_msg(text="/stopping"))
    handler.handle(_msg(text="继续分析"))
    assert len(fake.calls) == 3  # 全部走普通引擎路径
    assert "stop_accepted" not in _audit_kinds(tmp_path)


def test_unmapped_session_stop_creates_no_mapping(build_test_engine, tmp_path):
    """只读定位（3.2）：未映射会话 /stop → 空操作回执且 /stop 拦截器不新建映射.

    注：挂载链上游 M50 /model 拦截器对每条文本既有 get_or_create 行为（存量，
    非本任务范围）——"不新建映射"断言在拦截器单元级直调验证。
    """
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    assert session_map.to_dict() == {}

    msg = _msg(text="/stop", chat_id="oc_new", sender_id="ou_new")
    handled = handler._try_handle_stop_command(msg, "/stop")

    assert handled is True
    assert session_map.to_dict() == {}  # /stop 拦截器只读定位（get 非 get_or_create）
    assert any("当前没有进行中的推理" in r[1] for r in replies)
    assert len(fake.calls) == 0
    assert "stop_noop" in _audit_kinds(tmp_path)


def test_stop_session_isolation(build_test_engine, tmp_path):
    """会话隔离（spec 4.3.1）：会话 A 推理中，会话 B /stop 不影响 A."""
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    sid_a = session_map.get_or_create(SessionMap.group_key("oc_a"))
    engine._sync_active.add(sid_a)

    handler.handle(_msg(text="/stop", chat_id="oc_b"))  # B 无映射 → 空操作

    assert runner.is_cancelled(sid_a) is False  # A 不受影响
    assert any("当前没有进行中的推理" in r[1] for r in replies)


def test_continue_accepted_triggers_recovery_round(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(
        build_test_engine, tmp_path, [{"content": "预置回答"}, {"content": "继续完成任务"}]
    )
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    engine.run(sid, "任务 X 第一步")  # 预置会话现场（1 次 LLM 调用）

    handler.handle(_msg(text="/continue"))

    assert len(fake.calls) == 2  # 预置 1 次 + 恢复轮 1 次
    msgs = fake.calls[-1]["messages"]
    wire = json.dumps(msgs, ensure_ascii=False)
    assert any(m.get("role") == "user" and m.get("content") == "/continue" for m in msgs)
    assert "[程序恢复]" not in wire  # 用户控制语义不得被改写成程序自然语言注入
    assert "任务 X 第一步" in wire  # 会话现场完整保留
    sess = engine.session.load(sid)
    continue_msg = next(m for m in reversed(sess.messages) if m.role == "user")
    assert continue_msg.content == "/continue"
    assert continue_msg.metadata.get("origin_layer") == "user_instruction"
    assert continue_msg.metadata.get("program_origin") is False
    assert any("继续完成任务" in r[1] for r in replies)
    assert "continue_accepted" in _audit_kinds(tmp_path)


# ── T5 幂等 ──


def test_stop_idempotent_after_run_ends(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    engine._sync_active.add(sid)

    handler.handle(_msg(text="/stop"))
    assert any("停止已受理" in r[1] for r in replies)

    engine._sync_active.discard(sid)  # 模拟原 run 已收口结束
    engine._sync_cancel_discard(sid)
    replies.clear()
    handler.handle(_msg(text="/stop"))
    assert any("当前没有进行中的推理" in r[1] for r in replies)  # stop_noop 如实回执
    assert "stop_noop" in _audit_kinds(tmp_path)
    assert len(fake.calls) == 0


def test_stop_repeated_while_closing_window_no_side_effect(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    engine._sync_active.add(sid)

    handler.handle(_msg(text="/stop"))
    handler.handle(_msg(text="/stop"))  # 收口进行中（sync 仍登记）→ 再次置标记无副作用

    assert sum(1 for r in replies if "停止已受理" in r[1]) == 2
    assert runner.cancel_reason(sid) == "user_stop"
    assert len(fake.calls) == 0


# ── T6 忙拒绝 / 空防呆 / 降级 / 处理异常 ──


def test_continue_busy_rejected(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    sid = session_map.get_or_create(SessionMap.p2p_key("ou_a"))
    engine._sync_active.add(sid)  # 推理进行中

    handler.handle(_msg(text="/continue"))

    assert any("请先发送 /stop" in r[1] for r in replies)
    assert len(fake.calls) == 0
    assert "continue_busy" in _audit_kinds(tmp_path)


def test_continue_empty_session_noop(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    session_map.get_or_create(SessionMap.p2p_key("ou_a"))  # 空会话

    handler.handle(_msg(text="/continue"))

    assert any("无可恢复内容" in r[1] for r in replies)
    assert len(fake.calls) == 0
    assert "continue_empty" in _audit_kinds(tmp_path)


def test_stop_continue_degraded_when_runner_missing(build_test_engine, tmp_path):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    engine.runner = None  # runner 未装配

    handler.handle(_msg(text="/stop"))
    handler.handle(_msg(text="/continue"))

    assert any("停止能力未启用" in r[1] for r in replies)
    assert any("恢复能力未启用" in r[1] for r in replies)
    kinds = _audit_kinds(tmp_path)
    assert "stop_degraded" in kinds
    assert "continue_degraded" in kinds
    assert len(fake.calls) == 0


def test_stop_error_fail_open(build_test_engine, tmp_path, monkeypatch):
    handler, engine, fake, session_map, replies, runner = _make(build_test_engine, tmp_path)
    session_map.get_or_create(SessionMap.p2p_key("ou_a"))

    def _boom(session_id, reason="user_stop"):
        raise RuntimeError("cancel 通道故障")

    monkeypatch.setattr(runner, "cancel", _boom)
    handler.handle(_msg(text="/stop"))

    assert any("指令处理异常" in r[1] for r in replies)
    assert len(fake.calls) == 0  # 指令文本不漏入引擎
    assert "stop_error" in _audit_kinds(tmp_path)
