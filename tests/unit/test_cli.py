"""单元测试: CLI 会话管理命令（T26 / 覆盖收尾）."""

from __future__ import annotations

import builtins
from unittest import mock

from llm_loop.cli import _cmd_delete, _cmd_list, _cmd_search
from llm_loop.config import Settings
from llm_loop.core.message import Message, MessageSource
from llm_loop.factory import build_engine


def _make_engine(tmp_path):
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        self_inspection_enabled=False,
        extract_enabled=False,
    )
    return build_engine(settings)  # type: ignore[no-any-return]


def test_cmd_list_empty(tmp_path):
    engine = _make_engine(tmp_path)
    assert _cmd_list(engine, include_archived=False) == 0


def test_cmd_delete_without_confirm(tmp_path):
    """删除无确认 → 不删（拒绝输入 / 非 y）."""
    engine = _make_engine(tmp_path)
    sid = engine.session.create()
    # 输入 n → 不删
    with mock.patch.object(builtins, "input", return_value="n"):
        assert _cmd_delete(engine, sid, yes=False) == 1
    assert engine.session.exists(sid)
    # --yes → 删除
    assert _cmd_delete(engine, sid, yes=True) == 0
    assert not engine.session.exists(sid)


def test_cmd_delete_confirm_yes(tmp_path):
    """确认 y → 删除."""
    engine = _make_engine(tmp_path)
    sid = engine.session.create()
    with mock.patch.object(builtins, "input", return_value="y"):
        assert _cmd_delete(engine, sid, yes=False) == 0
    assert not engine.session.exists(sid)


def test_cmd_delete_missing(tmp_path):
    engine = _make_engine(tmp_path)
    assert _cmd_delete(engine, "no-such", yes=True) == 1


def test_cmd_search(tmp_path):
    engine = _make_engine(tmp_path)
    sid = engine.session.create()
    engine.session.append(
        sid, Message(role="user", content="搜索关键词 SEO_KEY", source=MessageSource.USER)
    )
    assert _cmd_search(engine, "SEO_KEY") == 0
    assert _cmd_search(engine, "完全不存在xyz") == 0


def test_cmd_list_with_session(tmp_path):
    engine = _make_engine(tmp_path)
    sid = engine.session.create()
    engine.session.append(sid, Message(role="user", content="会话内容", source=MessageSource.USER))
    assert _cmd_list(engine, include_archived=True) == 0


def test_evolve_review_level0_wait_human(tmp_path, capsys):
    """T60: evolve-review accepted 且级别 0 → 等待人工执行（保持 accepted）."""
    from llm_loop.cli import _cmd_evolve_review

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    engine.correction_ctx.evolve_local_exec = 0
    assert _cmd_evolve_review(engine, sug.id, "accepted") == 0
    out = capsys.readouterr().out
    assert "仅建议模式" in out
    assert store.list(status="accepted")[0]["id"] == sug.id


def test_evolve_review_accepted_auto_execute(tmp_path, capsys):
    """T60/M16: accepted + 级别 2 → 自动执行置 executing（verify=unverified，执行/验证交 AI）."""
    from llm_loop.cli import _cmd_evolve_review

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(
        content="清理缓存演进",
        impact_scope="recover_state",
        actions=[{"tool_name": "recover_state", "arguments": {"scope": "clear_cache"}}],
    )
    engine.correction_ctx.evolve_local_exec = 2
    assert _cmd_evolve_review(engine, sug.id, "accepted") == 0
    out = capsys.readouterr().out
    assert "自动执行" in out
    # M16 审计（FR-AUDIT-AI-01）: 移交后允许 → executing（不伪装终态）
    assert store.list(status="executed") == []
    assert len(store.list(status="executing")) == 1
    assert store.list(status="accepted") == []


def test_evolve_review_rejected_no_exec(tmp_path, capsys):
    """T60: rejected → 不触发自动执行."""
    from llm_loop.cli import _cmd_evolve_review

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="优化超时参数", impact_scope="timeout_s")
    engine.correction_ctx.evolve_local_exec = 2
    assert _cmd_evolve_review(engine, sug.id, "rejected") == 0
    out = capsys.readouterr().out
    assert "自动执行" not in out
    assert store.list(status="rejected")[0]["id"] == sug.id


def test_evolve_complete_human_channel(tmp_path, capsys):
    """M17 FR-REVIEW-AI-01: evolve-complete 人工通道 → executed + executor=human + 审计落盘."""
    from llm_loop.cli import _cmd_evolve_complete

    engine = _make_engine(tmp_path)
    store = engine.correction_ctx.evolution_store
    sug = store.submit(content="调整安全策略", impact_scope="safety")
    store.review(sug.id, "accepted")
    assert _cmd_evolve_complete(engine, sug.id, "人工已完成安全边界调整") == 0
    out = capsys.readouterr().out
    assert "executor=human" in out
    assert store.list(status="executed")[0]["id"] == sug.id
    exec_log = (engine.settings.audit_dir / "evolution_exec_log.jsonl").read_text(encoding="utf-8")
    assert '"executor": "human"' in exec_log


def test_evolve_complete_missing_result(tmp_path, capsys):
    """evolve-complete 缺结果说明 → 参数错误返回 2."""
    from llm_loop.cli import _cmd_evolve_complete

    engine = _make_engine(tmp_path)
    assert _cmd_evolve_complete(engine, "EVO-x", "   ") == 2
    out = capsys.readouterr().out
    assert "执行结果说明" in out


def test_evolve_complete_store_unavailable(tmp_path, capsys):
    """EVOLVE_ENABLED=0（store 未装配）→ 如实报错返回 1."""
    from llm_loop.cli import _cmd_evolve_complete

    engine = _make_engine(tmp_path)
    engine.correction_ctx.evolution_store = None
    assert _cmd_evolve_complete(engine, "EVO-x", "人工完成") == 1
    out = capsys.readouterr().out
    assert "演进建议不可用" in out
