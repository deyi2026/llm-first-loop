"""feishu 推送通道解析测试（复合通道支持）."""

from __future__ import annotations

from llm_loop.web.feishu_push import parse_feishu_channel


def test_parse_plain_p2p():
    assert parse_feishu_channel("feishu:p2p:ou_abc123") == ("ou_abc123", "open_id")


def test_parse_compound_shared_web():
    """复合通道（共享会话 +web 后缀）→ 还原目标 id."""
    assert parse_feishu_channel("feishu:p2p:ou_abc123+web") == ("ou_abc123", "open_id")


def test_parse_group():
    assert parse_feishu_channel("feishu:group:oc_xyz") == ("oc_xyz", "chat_id")


def test_parse_invalid():
    assert parse_feishu_channel("web") is None
    assert parse_feishu_channel("") is None
