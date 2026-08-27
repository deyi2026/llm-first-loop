"""EVO-20260826-81f8f674: 任务热卡（Task Hot-Card）单测.

覆盖:
- 单元层: write/pop 跨会话消费语义（未消费取出即标记；同会话跳过；已消费返回 None）
- payload: 五字段聚合（anchor/active_goals/pending_evolutions/consumed 标记）
- 集成层: build 注入——写入卡后新会话 build 的提交消息含热卡文本（wrap 前缀），
  同会话再 build 不重复注入（pop 已标记 consumed）
- fail-open: data_dir 不可写等异常不抛穿
"""

from __future__ import annotations

import json

from llm_loop.core.loop.hotcard import (
    build_hotcard_payload,
    hotcard_path,
    pop_hotcard,
    write_hotcard,
)


def _mk(tmp_path):
    return {"origin_session": "sess-origin", "anchor": "当前任务: 分组提交\n最近动作: git commit", "data_dir": str(tmp_path / "data")}


def test_write_and_pop_cross_session(tmp_path):
    ok = write_hotcard(**_mk(tmp_path))
    assert ok is True
    p = hotcard_path(tmp_path / "data")
    card = json.loads(p.read_text(encoding="utf-8"))
    assert card["origin_session"] == "sess-origin"
    assert "分组提交" in card["anchor"]

    # 跨会话: 取出文本并标记 consumed
    text = pop_hotcard(session_id="sess-new", data_dir=str(tmp_path / "data"))
    assert text is not None and "[任务热卡]" in text and "分组提交" in text
    card2 = json.loads(p.read_text(encoding="utf-8"))
    assert card2["consumed"] is True and card2["consumed_by"] == "sess-new"

    # 已消费 → None（防陈旧卡反复注入）
    assert pop_hotcard(session_id="sess-new2", data_dir=str(tmp_path / "data")) is None


def test_pop_skips_same_origin_session(tmp_path):
    write_hotcard(**_mk(tmp_path))
    # 同来源会话（压缩会话自身）: 不注入（已有 [压缩关键事实] 帧，不重复）
    assert pop_hotcard(session_id="sess-origin", data_dir=str(tmp_path / "data")) is None
    # 且未被标记消费——后续真正新会话仍可取
    assert pop_hotcard(session_id="sess-other", data_dir=str(tmp_path / "data")) is not None


def test_pop_no_card_returns_none(tmp_path):
    assert pop_hotcard(session_id="s", data_dir=str(tmp_path / "data")) is None


def test_payload_aggregates_goals_and_pending(tmp_path):
    data_dir = tmp_path / "data"
    audit = data_dir / "audit"
    audit.mkdir(parents=True)
    # 造一个 active goal 与一条 pending_review 演进
    (audit / "goals.jsonl").write_text(
        json.dumps(
            {
                "id": "GOAL-T1",
                "objective": "压测 106 文件",
                "status": "active",
                "checkpoints": [{"ts": "t", "what": "完成 12 轮", "evidence": "e", "path": "p", "next": "第 13 轮"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (audit / "evolution_suggestions.jsonl").write_text(
        json.dumps({"id": "EVO-T1", "status": "pending_review"}) + "\n"
        + json.dumps({"id": "EVO-T2", "status": "accepted"}) + "\n",
        encoding="utf-8",
    )
    payload = build_hotcard_payload(origin_session="s", anchor="a", data_dir=data_dir)
    assert payload["active_goals"] and payload["active_goals"][0]["id"] == "GOAL-T1"
    assert payload["active_goals"][0]["checkpoint_next"] == "第 13 轮"
    assert payload["pending_evolutions"] == ["EVO-T1"]  # 只取 pending_review
    assert payload["consumed"] is False


def test_write_fail_open_on_bad_dir(tmp_path):
    # data_dir 指向一个文件（mkdir 失败）→ write 返回 False 不抛穿
    bad = tmp_path / "blocker"
    bad.write_text("x", encoding="utf-8")
    assert write_hotcard(origin_session="s", anchor="a", data_dir=str(bad / "data")) is False
    # pop 对损坏 JSON fail-open 返回 None
    p = tmp_path / "data2" / "handoff"
    p.mkdir(parents=True)
    (p / "task_hotcard.json").write_text("{broken", encoding="utf-8")
    assert pop_hotcard(session_id="s", data_dir=str(tmp_path / "data2")) is None


def test_build_injects_hotcard_once(build_test_engine, isolated_data_dir, tmp_path):
    """集成: 跨会话热卡在新会话 build 尾部注入（wrap 前缀），再 build 不重复."""
    engine, fake = build_test_engine([{"content": "ok", "tool_calls": []}])
    # 直接写卡（模拟上一会话压缩时刻写入），origin 为外全会话
    from llm_loop.core.loop.hotcard import write_hotcard as _w

    assert _w(
        origin_session="sess-previous",
        anchor="当前任务: 热卡接力验证\n最近动作: write_hotcard",
        data_dir=str(tmp_path / "hc"),
    )
    # 把引擎 data_dir 指到同一位置（fake_settings 为 frozen dataclass，用
    # object.__setattr__ 绕过冻结——测试内合法手法，不触产品代码）
    object.__setattr__(engine.settings, "data_dir", str(tmp_path / "hc"))
    sid = engine.session.create()
    engine.run(sid, "接着干什么")
    msgs = fake.calls[0]["messages"]
    joined = json.dumps([m.get("content", "") for m in msgs], ensure_ascii=False)
    assert "任务热卡" in joined, "新会话首轮提交应含热卡注入"
    assert "热卡接力验证" in joined
    # 已消费 → 第二次 run 不再注入
    engine.run(sid, "下一步")
    msgs2 = fake.calls[-1]["messages"]
    joined2 = "".join(str(m.get("content", "")) for m in msgs2)
    # 第二轮历史可能仍带第一轮注入消息（历史保留），但不得出现两张卡
    assert joined2.count("[任务热卡]") <= 1
