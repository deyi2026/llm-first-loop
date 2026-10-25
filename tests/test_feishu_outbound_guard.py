"""飞书出站默认拒绝 + 附件/文档/文件夹约束（安全建议书 P0-4 / S1-3）.

行为矩阵（接收方判定）：
| ALLOWED_USERS | OWNER_OPEN_ID | ALLOW_ALL | 结果                                    |
|---------------|---------------|-----------|-----------------------------------------|
| 设置          | 任意          | 任意      | 仅集合内 receive_id 放行                |
| 未设置        | 设置          | 任意      | 仅 owner 放行（回退）                   |
| 未设置        | 未设置        | 未设置    | 全拒 `outbound_denied_no_allowlist`     |
| 未设置        | 未设置        | 1         | 放行 + 每次记审计与 warning             |

飞书客户端全部 monkeypatch（patch.dict sys.modules），不触网。
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection import tools_feishu_outbound as tfo
from tests import env_channel

# 高置信密钥样例（格式真实、值伪造，仅用于触发 security_guard.anthropic_key 模式）
_FAKE_ANTHROPIC_KEY = "sk-ant-api03-FAKE000000000000000000000000000000"
# 经 \uXXXX 转义隐藏在卡片 JSON 里的同款密钥（验证解码-重编码扫描层）
_CARD_WITH_HIDDEN_KEY = json.dumps(
    {"elements": [{"tag": "div", "text": "\u6e05\u5355 sk-ant-api03-FAKE111111111111111111111111111111111"}]},
    ensure_ascii=True,
)
_HIDDEN_KEY_PLAIN = "sk-ant-api03-FAKE111111111111111111111111111111111"


@pytest.fixture(autouse=True)
def _outbound_env_isolation(tmp_path, monkeypatch):
    """每个 case 前重置速率状态、审计目录与全部出站相关环境变量."""
    tfo._rate_state.clear()
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(tfo, "_outbound_audit_path", audit_dir / "feishu_outbound.jsonl")
    for var in (
        "FEISHU_OUTBOUND_ALLOWED_USERS",
        "FEISHU_OWNER_OPEN_ID",
        "FEISHU_OUTBOUND_ALLOW_ALL",
        "LFL_FEISHU_ALLOW_SECRETS",
        "FEISHU_DOC_FOLDER_ALLOWLIST",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("FEISHU_OUTBOUND_ENABLED", "true")
    monkeypatch.setenv("FEISHU_OUTBOUND_RATE_PER_MIN", "5")
    yield


@pytest.fixture
def ws_root(tmp_path, monkeypatch):
    """可控工作区根：tmp_path/ws（与 /tmp、pytest tmp 目录天然分离）."""
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    monkeypatch.setattr("llm_loop.core.run_context.workspace_base", lambda: str(ws))
    return ws


@pytest.fixture
def mock_feishu():
    """monkeypatch 飞书 SDK 客户端链路（lark_oapi + config + rest），不触网."""
    fake_lark = MagicMock()
    builder = fake_lark.Client.builder.return_value
    builder.app_id.return_value.app_secret.return_value.log_level.return_value.build.return_value = MagicMock()
    send_text = MagicMock(return_value="om_mock")
    create_doc = MagicMock(return_value=("docx_mock", "https://example.feishu.cn/docx/docx_mock"))
    send_file = MagicMock(return_value="om_file_mock")
    fake_rest_mod = MagicMock()
    fake_rest_mod.FeishuRestClient = MagicMock(
        return_value=MagicMock(send_text=send_text, create_doc=create_doc, send_file=send_file)
    )
    fake_cfg_mod = MagicMock()
    fake_cfg_mod.load_feishu_config = MagicMock(
        return_value=MagicMock(has_credentials=True, app_id="cli_x", app_secret="sec")
    )
    with patch.dict(
        "sys.modules",
        {
            "lark_oapi": fake_lark,
            "llm_loop.feishu.rest": fake_rest_mod,
            "llm_loop.feishu.config": fake_cfg_mod,
        },
    ):
        yield {"send_text": send_text, "create_doc": create_doc, "send_file": send_file}


# ── 1. 接收方默认拒绝 ──

def test_get_allowed_users_fallback_to_owner(monkeypatch):
    """ALLOWED 未设置时回退为 {OWNER}；设置时以 ALLOWED 为准；两者皆空返回空集合."""
    monkeypatch.delenv("FEISHU_OUTBOUND_ALLOWED_USERS", raising=False)
    monkeypatch.setenv("FEISHU_OWNER_OPEN_ID", "ou_owner")
    assert tfo._get_allowed_users() == {"ou_owner"}
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_a, ou_b")
    assert tfo._get_allowed_users() == {"ou_a", "ou_b"}
    monkeypatch.delenv("FEISHU_OUTBOUND_ALLOWED_USERS", raising=False)
    monkeypatch.delenv("FEISHU_OWNER_OPEN_ID", raising=False)
    assert tfo._get_allowed_users() == set()


def test_empty_allowlist_with_owner_only_allows_owner(monkeypatch, mock_feishu):
    """空 allowlist + 有 owner：仅 owner 可发，其他 receive_id 拒绝（白名单分支）."""
    monkeypatch.setenv("FEISHU_OWNER_OPEN_ID", "ou_owner")
    ok_case = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_owner", "content": "hello", "confirm": True},
    )
    assert ok_case.status == ToolResultStatus.SUCCESS
    assert mock_feishu["send_text"].called

    denied = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_attacker123456", "content": "hello", "confirm": True},
    )
    assert denied.status == ToolResultStatus.FAILURE
    assert "白名单" in denied.content
    assert mock_feishu["send_text"].call_count == 1  # 第二次未触达 SDK


def test_empty_allowlist_no_owner_denies_all(monkeypatch, mock_feishu):
    """空 allowlist + 无 owner：全部拒绝，错误码 outbound_denied_no_allowlist + 配置指引."""
    denied = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_anyone1234567", "content": "hello", "confirm": True},
    )
    assert denied.status == ToolResultStatus.FAILURE
    assert "outbound_denied_no_allowlist" in denied.content
    assert "FEISHU_OUTBOUND_ALLOWED_USERS" in denied.content
    assert "FEISHU_OWNER_OPEN_ID" in denied.content
    assert not mock_feishu["send_text"].called

    denied_att = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_anyone1234567", "doc_id": "docx1", "confirm": True},
    )
    assert denied_att.status == ToolResultStatus.FAILURE
    assert "outbound_denied_no_allowlist" in denied_att.content


def test_allow_all_override_passes_with_warning(monkeypatch, mock_feishu, caplog):
    """ALLOW_ALL=1 逃生阀：放行且每次产生 warning + 审计."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOW_ALL", "1")
    with caplog.at_level(logging.WARNING, logger=tfo.logger.name):
        result = tfo.run_send_feishu_message(
            MagicMock(), MagicMock(),
            {"receive_id": "ou_stranger123456", "content": "hello", "confirm": True},
        )
    assert result.status == ToolResultStatus.SUCCESS
    assert mock_feishu["send_text"].called
    assert any(
        "FEISHU_OUTBOUND_ALLOW_ALL" in r.message for r in caplog.records if r.levelno >= logging.WARNING
    )
    # 审计留痕：override 记录
    audit_lines = tfo._outbound_audit_path.read_text(encoding="utf-8").strip().splitlines()
    actions = [json.loads(line) for line in audit_lines]
    assert any(a.get("action") == "preflight_allow_all_override" for a in actions)


def test_no_allow_all_without_flag_stays_denied(monkeypatch, mock_feishu):
    """非 1 值（如 0）不构成逃生阀."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOW_ALL", "0")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_stranger123456", "content": "hello", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "outbound_denied_no_allowlist" in result.content


# ── 2. 附件路径约束 ──

def test_attachment_inside_workspace_data_passes(ws_root, mock_feishu, monkeypatch):
    """data/ 内普通文件通过."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    fp = ws_root / "data" / "report.txt"
    fp.write_text("hello", encoding="utf-8")
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_user12345678", "file_path": str(fp), "confirm": True},
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert mock_feishu["send_file"].called


@pytest.mark.skipif(
    env_channel.tmpdir_redirected(),
    reason="环境受限：沙箱写域令 tempfile 回落 /tmp，tmp_path 落入允许根，"
           "outside_workspace 前置假设（tmp_path 在 /private/var）失效【RED-06】",
)
def test_attachment_outside_workspace_denied(ws_root, mock_feishu, tmp_path, monkeypatch):
    """工作区/data//tmp 之外的文件拒绝：attachment_path_outside_workspace."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    outside = tmp_path / "outside_ws" / "leak.txt"  # tmp_path 在 /private/var/...，不属于 /tmp
    outside.parent.mkdir(parents=True)
    outside.write_text("x", encoding="utf-8")
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_user12345678", "file_path": str(outside), "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "attachment_path_outside_workspace" in result.content
    assert not mock_feishu["send_file"].called
    # 审计留痕
    audit_lines = tfo._outbound_audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line).get("reason") == "attachment_path_outside_workspace" for line in audit_lines)


def test_attachment_real_tmp_dir_passes(mock_feishu, monkeypatch):
    """/tmp 真实根内普通文件放行（realpath 对齐 /private/tmp）."""
    import os

    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")

    probe = "/tmp/lfl_guard_probe_2026.txt"
    with open(probe, "w", encoding="utf-8") as f:
        f.write("ok")
    try:
        result = tfo.run_send_feishu_attachment(
            MagicMock(), MagicMock(),
            {"receive_id": "ou_user12345678", "file_path": probe, "confirm": True},
        )
        assert result.status == ToolResultStatus.SUCCESS
        assert mock_feishu["send_file"].called
    finally:
        os.remove(probe)


def test_attachment_env_file_denied(ws_root, mock_feishu, monkeypatch):
    """`.env` 附件（即便位于允许根内）拒绝：attachment_sensitive_file，且不读内容."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    fp = ws_root / "data" / ".env"
    fp.write_text("FAKE_SECRET=1", encoding="utf-8")
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_user12345678", "file_path": str(fp), "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "attachment_sensitive_file" in result.content
    assert ".env" in result.content  # 附判定原因（文件名），不附明文内容
    assert "FAKE_SECRET" not in result.content
    assert not mock_feishu["send_file"].called


@pytest.mark.skipif(
    env_channel.tmpdir_redirected(),
    reason="环境受限：同 RED-06——tmp_path 落入 /tmp 允许根，symlink 越界目标不再越界【RED-07】",
)
def test_attachment_symlink_escape_denied(ws_root, mock_feishu, tmp_path, monkeypatch):
    """工作区内 symlink 指向工作区外文件 → realpath 越界拒绝."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    target = tmp_path / "outside_ws" / "real_leak.txt"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")
    link = ws_root / "data" / "link.txt"
    link.symlink_to(target)
    result = tfo.run_send_feishu_attachment(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_user12345678", "file_path": str(link), "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "attachment_path_outside_workspace" in result.content


# ── 3. 内容泄密拦截 ──

def test_message_with_anthropic_key_denied_no_echo(monkeypatch, mock_feishu):
    """消息含 sk-ant-... → 拒绝、错误信息不含密钥本体、只给 kind."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_user12345678", "content": f"key={_FAKE_ANTHROPIC_KEY}", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "outbound_content_secret_detected" in result.content
    assert "anthropic_key" in result.content
    assert _FAKE_ANTHROPIC_KEY not in result.content  # 绝不回显命中片段
    assert not mock_feishu["send_text"].called


def test_card_with_unicode_escaped_key_denied(monkeypatch, mock_feishu):
    """interactive 卡片 JSON 内 \\uXXXX 转义密钥同样被拦（解码-重编码扫描层）."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {
            "receive_id": "ou_user12345678",
            "content": _CARD_WITH_HIDDEN_KEY,
            "msg_type": "interactive",
            "confirm": True,
        },
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "outbound_content_secret_detected" in result.content
    assert _HIDDEN_KEY_PLAIN not in result.content


def test_doc_with_secret_denied_no_echo(monkeypatch, mock_feishu):
    """create_feishu_doc 内容含密钥 → 拒绝且不回显."""
    monkeypatch.setenv("FEISHU_DOC_FOLDER_ALLOWLIST", "fldr_ok")
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {
            "title": "笔记",
            "content": f"api key: {_FAKE_ANTHROPIC_KEY}",
            "folder_token": "fldr_ok",
            "confirm": True,
        },
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "outbound_content_secret_detected" in result.content
    assert "anthropic_key" in result.content
    assert _FAKE_ANTHROPIC_KEY not in result.content
    assert not mock_feishu["create_doc"].called


def test_allow_secrets_override_passes_with_warning(monkeypatch, mock_feishu, caplog):
    """LFL_FEISHU_ALLOW_SECRETS=1 → 放行 + warning + 审计留痕."""
    monkeypatch.setenv("FEISHU_OUTBOUND_ALLOWED_USERS", "ou_user12345678")
    monkeypatch.setenv("LFL_FEISHU_ALLOW_SECRETS", "1")
    with caplog.at_level(logging.WARNING, logger=tfo.logger.name):
        result = tfo.run_send_feishu_message(
            MagicMock(), MagicMock(),
            {"receive_id": "ou_user12345678", "content": f"k={_FAKE_ANTHROPIC_KEY}", "confirm": True},
        )
    assert result.status == ToolResultStatus.SUCCESS
    assert mock_feishu["send_text"].called
    assert any("LFL_FEISHU_ALLOW_SECRETS" in r.message for r in caplog.records)
    audit_lines = tfo._outbound_audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert any(json.loads(line).get("result") == "allowed_secret_override" for line in audit_lines)


def test_plain_message_still_passes(monkeypatch, mock_feishu):
    """正常内容不受影响（回归：owner 通知链路不被打断）."""
    monkeypatch.setenv("FEISHU_OWNER_OPEN_ID", "ou_owner")
    result = tfo.run_send_feishu_message(
        MagicMock(), MagicMock(),
        {"receive_id": "ou_owner", "content": "任务完成，报告已生成", "confirm": True},
    )
    assert result.status == ToolResultStatus.SUCCESS


# ── 4. folder_token 约束 ──

def test_folder_not_in_allowlist_denied(monkeypatch, mock_feishu):
    """allowlist 已设置，非白名单 folder_token → 拒绝 folder_not_allowed."""
    monkeypatch.setenv("FEISHU_DOC_FOLDER_ALLOWLIST", "fldr_a,fldr_b")
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "t", "content": "c", "folder_token": "fldr_evil", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "folder_not_allowed" in result.content
    assert not mock_feishu["create_doc"].called


def test_folder_empty_passes_with_allowlist(monkeypatch, mock_feishu):
    """allowlist 已设置，空 folder_token（默认根目录）→ 通过."""
    monkeypatch.setenv("FEISHU_DOC_FOLDER_ALLOWLIST", "fldr_a,fldr_b")
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "t", "content": "c", "confirm": True},
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert mock_feishu["create_doc"].called


def test_folder_in_allowlist_passes(monkeypatch, mock_feishu):
    monkeypatch.setenv("FEISHU_DOC_FOLDER_ALLOWLIST", "fldr_a,fldr_b")
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "t", "content": "c", "folder_token": "fldr_b", "confirm": True},
    )
    assert result.status == ToolResultStatus.SUCCESS


def test_folder_no_allowlist_nonempty_denied(monkeypatch, mock_feishu):
    """allowlist 未设置，非空 folder_token → 拒绝（默认只允许根目录）."""
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "t", "content": "c", "folder_token": "fldr_anywhere", "confirm": True},
    )
    assert result.status == ToolResultStatus.FAILURE
    assert "folder_not_allowed" in result.content


def test_folder_no_allowlist_empty_passes(mock_feishu):
    """allowlist 未设置，空 folder_token → 通过."""
    result = tfo.run_create_feishu_doc(
        MagicMock(), MagicMock(),
        {"title": "t", "content": "c", "confirm": True},
    )
    assert result.status == ToolResultStatus.SUCCESS
    assert mock_feishu["create_doc"].called
