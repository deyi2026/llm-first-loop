"""EVO-20261112-fd945e83（D8）：发布完成事件钩子——通知与扫描单测.

- 开场卡/轮卡：STATUS 层非指令、幂等去重（共用 metadata.service_action_ids）、
  ≤3 条上限、扫描失败/无 data_dir 不注入（fail-open）；
- 扫描判据（全机械）：origin=update ∧ status=succeeded ∧ verify_verdict=
  confirmed_ok ∧ target∈{web,all} ∧ 当前 desired 代 ∧ 24h TTL ∧ 未 dismissed；
- 闭合即停：dismissal 标记写入后扫描不再返回；
- 注入位置/元数据/语调与 service_action_notice 先例逐字段同构
  （provider prompt 面 L2-2/L2-6 准入的行为面等价依据）。
"""

from __future__ import annotations

import json

import llm_loop.runtime.service_control as sc_mod
from llm_loop.core.loop.engine_services.publish_closeout_notice import (
    build_publish_closeout_notice_message,
    build_publish_closeout_turn_notice,
    injected_publish_action_ids,
)
from llm_loop.llm.client import LLMResponse


def _item(action_id: str) -> dict:
    return {
        "action_id": action_id,
        "target": "web",
        "generation": 406,
        "updated_at": "2026-11-12T18:00:00+08:00",
        "detail": "restart_mirror rc=0; verify=confirmed_ok",
        "verify_evidence": "verify=confirmed_ok web[ok pid=1 head=abc]",
        "deployment_id": "deploy-x",
    }


def test_turn_builder_filters_and_caps(monkeypatch) -> None:
    """轮卡：过滤已注入 ids；新项超 3 只取 3；无新项/无 data_dir 返回 None."""
    _pool = [_item(f"svc-{c}") for c in "abcde"]
    monkeypatch.setattr(
        sc_mod, "scan_publish_closeout_pending", lambda data_dir: _pool
    )
    cards = [
        build_publish_closeout_turn_notice("data", {"svc-a"}),
        build_publish_closeout_turn_notice("data", {f"svc-{c}" for c in "abcde"}),
        build_publish_closeout_turn_notice(None, set()),
    ]
    assert cards[0].metadata["service_action_ids"] == ["svc-b", "svc-c", "svc-d"]
    assert "svc-a" not in cards[0].content and "svc-b" in cards[0].content
    assert (cards[0].metadata or {}).get("injection_kind") == "publish_closeout_turn_notice"
    assert cards[1] is None, "全部已注入 → 不注入（幂等）"
    assert cards[2] is None, "无 data_dir → 不注入"


def test_notice_content_status_layer_non_imperative(monkeypatch) -> None:
    """STATUS 层渲染：程序附录仲裁句 + [通知·状态] + 收口出口（非指令语义）."""
    monkeypatch.setattr(
        sc_mod, "scan_publish_closeout_pending", lambda data_dir: [_item("svc-z")]
    )
    for msg in (
        build_publish_closeout_notice_message("data"),
        build_publish_closeout_turn_notice("data", set()),
    ):
        assert msg.content.startswith("[程序附录·非用户输入]")
        assert "[通知·状态]" in msg.content and "非指令" in msg.content
        assert "promo_closeout.py" in msg.content  # 收口出口
        assert (msg.metadata or {}).get("origin_layer") == "status"


def test_injected_ids_dedup_across_cards(monkeypatch) -> None:
    """开场卡与轮卡共用 service_action_ids 登记——同动作不双重注入."""
    monkeypatch.setattr(
        sc_mod, "scan_publish_closeout_pending", lambda data_dir: [_item("svc-1")]
    )
    opening = build_publish_closeout_notice_message("data")
    ids = injected_publish_action_ids([opening])
    assert ids == {"svc-1"}
    assert build_publish_closeout_turn_notice("data", ids) is None


def test_scan_filters_and_dismissal(tmp_path, monkeypatch) -> None:
    """扫描判据：origin/verify/target/状态过滤 + dismissed 闭合即停.

    审查修复（R1 P2-4）：冻结扫描时钟（2026-11-12），测试不随墙钟腐烂。
    """
    from datetime import datetime

    frozen = datetime.fromisoformat("2026-11-12T19:00:00+08:00")
    monkeypatch.setattr(sc_mod, "system_local_now", lambda: frozen)
    store = sc_mod.ManagedServiceDeploymentStore(tmp_path)
    store.actions_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "schema": "service-control-action/v1",
        "action": "restart",
        "target": "web",
        "deployment_id": "deploy-t",
        "deployment_generation": 7,
        "requester_session_id": "s",
        "created_at": "2026-11-12T17:00:00+08:00",
        "updated_at": "2026-11-12T17:01:00+08:00",
    }
    def _write(aid: str, **over):
        rec = {**base, "action_id": aid, **over}
        (store.actions_dir / f"{aid}.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8"
        )

    _write("svc-ok", origin="update", status="succeeded", verify_verdict="confirmed_ok")
    _write("svc-restart-only", origin="restart", status="succeeded", verify_verdict="confirmed_ok")
    _write("svc-unverified", origin="update", status="succeeded", verify_verdict="")
    _write("svc-failed", origin="update", status="failed", verify_verdict="confirmed_ok")
    _write("svc-notweb", origin="update", status="succeeded", verify_verdict="confirmed_ok", target="feishu")
    _write("svc-stale", origin="update", status="succeeded", verify_verdict="confirmed_ok",
           updated_at="2026-11-01T00:00:00+08:00")

    out = sc_mod.scan_publish_closeout_pending(tmp_path)
    assert [it["action_id"] for it in out] == ["svc-ok"]

    # dismissal 标记 → 闭合即停
    assert sc_mod.write_publish_closeout_dismissal(tmp_path, "svc-ok", by="test")
    assert sc_mod.write_publish_closeout_dismissal(tmp_path, "svc-ok", by="test")  # 幂等
    assert sc_mod.write_publish_closeout_dismissal(tmp_path, "../evil", by="test") is False
    assert sc_mod.scan_publish_closeout_pending(tmp_path) == []


def test_engine_injects_turn_notice_before_user_text(
    monkeypatch, fake_settings, build_test_engine
) -> None:
    """轮级接线：第二轮新完成的发布 → 一张轮卡置于该轮用户原文之前."""
    scan_results: list[list[dict]] = [[], [_item("svc-new")]]
    monkeypatch.setattr(
        sc_mod, "scan_publish_closeout_pending", lambda data_dir: scan_results[0]
    )
    engine, _fake = build_test_engine(
        [LLMResponse(content="好的", tool_calls=[], provider="fake")] * 2
    )
    sid = engine.session.create()
    engine.run(sid, "第一轮")  # 无待收口 → 不注入
    monkeypatch.setattr(
        sc_mod, "scan_publish_closeout_pending", lambda data_dir: scan_results[1]
    )
    engine.run(sid, "第二轮")  # 发布完成 → 轮卡

    sess = engine.session.load(sid)
    turn_cards = [
        m
        for m in sess.messages
        if (m.metadata or {}).get("injection_kind") == "publish_closeout_turn_notice"
    ]
    assert len(turn_cards) == 1
    assert "svc-new" in turn_cards[0].content
    users = [i for i, m in enumerate(sess.messages) if m.role == "user"]
    card_idx = sess.messages.index(turn_cards[0])
    later_user = [i for i in users if i > card_idx]
    assert later_user, "轮卡位于本轮用户原文之前"
    assert (turn_cards[0].metadata or {}).get("origin_layer") == "status"
