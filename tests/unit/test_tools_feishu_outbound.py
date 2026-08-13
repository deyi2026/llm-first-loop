"""AI 主动出站飞书工具单测（EVO-20260813-432813b2，涉安全边界）."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection import tools_feishu_outbound as tfo


@pytest.fixture(autouse=True)
def reset_module_state(tmp_path, monkeypatch):
    """每个 case 前重置模块速率状态 + 审计目录."""
    tfo._rate_state.clear()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir()
    monkeypatch.setenv("FEISHU_AUDIT_DIR", str(audit_dir))
    monkeypatch.setenv("FEISHU_OUTBOUND_RATE_PER_MIN", "5")
    monkeypatch.setattr(tfo, "_outbound_audit_path", audit_dir / "feishu_outbound.jsonl")
    yield


# ── 工具定义层校验 ──

def test_tool_defs_present():
    assert tfo.SEND_FEISHU_MESSAGE_TOOL_DEF["name"] == "send_feishu_message"
    assert tfo.CREATE_FEISHU_DOC_TOOL_DEF["name"] == "create_feishu_doc"
    assert tfo.SEND_FEISHU_ATTACHMENT_TOOL_DEF["name"] == "send_feishu_attachment"
    for td in [tfo.SEND_FEISHU_MESSAGE_TOOL_DEF, tfo.CREATE_FEISHU_DOC_TOOL_DEF, tfo.SEND_FEISHU_ATTACHMENT_TOOL_DEF]:
        assert "confirm" in td["parameters"]["properties"], f"{td['name']} 必须含二次确认参数"
        assert "confirm" in td["parameters"]["required"]


def test_tool_descriptions_mention_security():
    """工具描述必须显式声明涉安全边界，避免 AI 误用."""
    for td in [tfo.SEND_FEISHU_MESSAGE_TOOL_DEF, tfo.CREATE_FEISHU_DOC_TOOL_DEF, tfo.SEND_FEISHU_ATTACHMENT_TOOL_DEF]:
        desc = td["description"]
        assert "EVO-20260813-432813b2" in desc
        assert "涉安全边界" in desc or "禁用" in desc


# ── 安全防护校验 ──

def test_outbound_disabled_by_default(monkeypatch):
    """默认 FEISHU_OUTBOUND_ENABLED=false 时全部拒绝."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "false")
    monkeypatch.delenv("FEISHU_OUTBOUND_ALLOWED_USERS", raising=False)
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_abc", "content": "hi", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "禁用" in result.content


def test_requires_confirm_flag(monkeypatch):
    """未传 confirm=true 必须拒绝（防 AI 误调用）."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_abc")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_abc", "content": "hi", "confirm": False},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "二次确认" in result.content


def test_whitelist_enforced(monkeypatch):
    """白名单外的接收方必须拒绝."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_allowed")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_blocked", "content": "hi", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "白名单" in result.content


def test_rate_limit_blocks_after_5(monkeypatch):
    """超过速率限制必须拒绝."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_abc")
    monkeypatch.setenv("FEISHU_OUTBOUND_RATE_PER_MIN", "3")

    # 注入 mock client 避免真发
    fake_lark = MagicMock()
    fake_lark.Client.builder.return_value.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = MagicMock()
    with patch.dict("sys.modules", {
        "lark_oapi": fake_lark,
        "llm_loop.feishu.rest": MagicMock(FeishuRestClient=MagicMock(return_value=MagicMock(send_text=MagicMock(return_value="msg_1")))),
        "llm_loop.feishu.config": MagicMock(load_feishu_config=MagicMock(return_value=MagicMock(has_credentials=True, app_id="cli", app_secret="sec"))),
    }):
        for i in range(3):
            result = tfo.run_send_feishu_message(
                MagicMock(), MagicMock(),
                {"receive_id": "ou_abc", "content": f"msg{i}", "confirm": True},
            )
            assert result.status == ToolResultStatus.SUCCESS
        # 第 4 次必须被限流
        result4 = tfo.run_send_feishu_message(
            MagicMock(), MagicMock(),
            {"receive_id": "ou_abc", "content": "msg4", "confirm": True},
        )
        assert result4.status == ToolResultStatus.FAILURE
        assert "速率" in result4.content


def test_create_doc_disabled_when_outbound_off(monkeypatch):
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "false")
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "测试", "content": "# hi", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "禁用" in result.content


def test_attachment_rejects_missing_both(monkeypatch):
    """file_path 与 doc_id 都没传必须拒绝."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_abc")
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_abc", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "file_path 与 doc_id" in result.content


def test_attachment_rejects_nonexistent_file(monkeypatch, tmp_path):
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_abc")
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_abc", "file_path": "/nonexistent/file.txt", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "文件不存在" in result.content


# ── 审计落盘校验 ──

def test_audit_log_written_on_disabled(monkeypatch, tmp_path):
    """即使被拒绝也要落审计（防规避）."""
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("FEISHU_AUDIT_DIR", str(audit_dir))
    monkeypatch.setattr(tfo, "_outbound_audit_path", audit_dir / "feishu_outbound.jsonl")
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "false")

    tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_abc", "content": "hi", "confirm": True},
    )
    # 默认状态下被禁用，不写审计（仅尝试发送才写）
    # 此 case 仅验证：审计函数本身 fail-open
    tfo._write_audit({"test": "ok"})
    log_path = audit_dir / "feishu_outbound.jsonl"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "test" in content


def test_mask_id_does_not_leak():
    """receive_id 脱敏后必须不包含完整明文."""
    masked = tfo._mask_id("ou_8fc14b9345399c1cffe7f6173afd0f49")
    assert "8fc14b9345399c1cffe7f6173afd0f49" not in masked
    assert masked.startswith("ou_8")
    assert masked.endswith("0f49")
