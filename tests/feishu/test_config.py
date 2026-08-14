"""飞书配置与敏感信息测试（M42，用例 21-22）.

密钥保护：密钥仅 env 读取（config 无硬编码）+ 错误提示/审计不含密钥值 + 日志脱敏。
审计落盘：处理一条 text 消息 → 审计文件存在可 grep + 不含密钥 + 写入失败不阻断（fail-open）。
零真实飞书 API（env 构造 + 源码 grep 断言）。
"""

from unittest.mock import Mock

from llm_loop.feishu.bridge import FeishuWsBridge
from llm_loop.feishu.config import FeishuConfig, load_feishu_config
from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler
from llm_loop.feishu.session_map import SessionMap

SECRET = "secret_value_do_not_leak_123"
APP_ID = "cli_test_app_0001"


def _text_msg(chat_id: str = "oc_audit", text: str = "你好") -> FeishuMessage:
    return FeishuMessage(
        message_id="om_audit_1",
        sender_id="ou_audit_1",
        chat_id=chat_id,
        msg_type="text",
        text=text,
        sender_type="user",
    )


def test_config_secret_protection(monkeypatch, tmp_path):
    """用例 21：密钥仅 env 读取 + 错误提示/审计不含密钥值 + 日志脱敏."""
    monkeypatch.setenv("FEISHU_APP_ID", APP_ID)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)
    monkeypatch.setenv("FEISHU_WS_ENABLED", "1")
    config = load_feishu_config()
    assert config.app_id == APP_ID
    assert config.app_secret == SECRET
    assert config.enabled is True

    # a) 密钥仅 env 读取：config.py 源码无硬编码 secret 值
    import llm_loop.feishu.config as cfg_module

    with open(cfg_module.__file__, encoding="utf-8") as f:
        src = f.read()
    assert SECRET not in src
    assert "os.environ.get" in src  # 密钥读取点 = env

    # b) 错误提示不含密钥值 + 日志脱敏（app_id 前缀）：格式异常提示仅含脱敏前缀
    bad = FeishuWsBridge(FeishuConfig(app_id="not_cli_format", app_secret=SECRET), None)  # type: ignore[arg-type]
    msg = bad._preflight()
    assert msg is not None
    assert SECRET not in msg
    assert APP_ID not in msg
    assert "格式异常" in msg

    # c) 审计记录不含密钥值
    audit_dir = tmp_path / "audit"
    handler = FeishuMessageHandler(
        engine=Mock(),
        session_map=Mock(),
        reply_fn=lambda c, t: None,
        audit_dir=str(audit_dir),
    )
    handler._audit(_text_msg(), "text", "正常审计内容")
    written = (audit_dir / "feishu_audit.jsonl").read_text(encoding="utf-8")
    assert "message_id" in written
    assert SECRET not in written  # 审计不含密钥值


def test_audit_written(build_test_engine, tmp_path, monkeypatch):
    """用例 22：处理一条 text 消息 → 审计落盘（可检索 + 不含密钥 + fail-open）."""
    engine, fake = build_test_engine([{"content": "最终回答"}, {"content": "最终回答"}])
    session_map = SessionMap(engine.session, path=str(tmp_path / "feishu_session_map.json"))
    replies: list[tuple[str, str]] = []
    audit_dir = tmp_path / "audit"
    handler = FeishuMessageHandler(
        engine,
        session_map,
        lambda rid, text, rtype: replies.append((rid, text, rtype)),
        audit_dir=str(audit_dir),
    )
    handler.handle(_text_msg())
    assert replies == [("oc_audit", "最终回答", "chat_id")]

    # a) 审计文件存在 + 内容可 grep（消息 ID/会话/sender/kind）
    audit_file = audit_dir / "feishu_audit.jsonl"
    assert audit_file.exists()
    content = audit_file.read_text(encoding="utf-8")
    assert "om_audit_1" in content
    assert "oc_audit" in content
    assert "ou_audit_1" in content
    assert '"kind": "text"' in content

    # b) 审计不含密钥
    assert "app_secret" not in content

    # c) 审计 fail-open：写入失败不阻断消息处理
    def _broken_write(path, record):
        raise OSError("disk full")

    monkeypatch.setattr("llm_loop.feishu.handlers._write_audit_line", _broken_write)
    replies.clear()
    handler.handle(_text_msg(text="第二条"))
    assert replies == [("oc_audit", "最终回答", "chat_id")]
    assert len(fake.calls) == 2  # 引擎仍被调用（审计失败不阻断）


def test_chunk_limit_default_30000(monkeypatch):
    """用例 19（M43）：chunk_limit 默认 30000（飞书字数不设人为限制）+ env 覆盖 + 下限保持."""
    # a) 默认（未设 env）→ 30000
    monkeypatch.delenv("FEISHU_CHUNK_LIMIT", raising=False)
    monkeypatch.setenv("FEISHU_APP_ID", APP_ID)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)
    assert load_feishu_config().chunk_limit == 30000

    # b) env 显式覆盖 → 尊重用户设置（500 > 下限 200，覆盖生效）
    monkeypatch.setenv("FEISHU_CHUNK_LIMIT", "500")
    assert load_feishu_config().chunk_limit == 500

    # c) 非法值 → 回退默认 30000
    monkeypatch.setenv("FEISHU_CHUNK_LIMIT", "abc")
    assert load_feishu_config().chunk_limit == 30000

    # d) 下限保持（min 200，防配置异常）
    monkeypatch.setenv("FEISHU_CHUNK_LIMIT", "50")
    assert load_feishu_config().chunk_limit == 200


def test_m46_switches_default_and_env(monkeypatch):
    """用例 M46-⑪：FEISHU_TYPING_ACK / FEISHU_STREAMING 默认 1，显式 0 关闭."""
    monkeypatch.setenv("FEISHU_APP_ID", APP_ID)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)
    # a) 默认（未设 env）→ 两者均 True
    monkeypatch.delenv("FEISHU_TYPING_ACK", raising=False)
    monkeypatch.delenv("FEISHU_STREAMING", raising=False)
    cfg = load_feishu_config()
    assert cfg.typing_ack is True
    assert cfg.streaming is True
    # b) 显式 0 → 关闭
    monkeypatch.setenv("FEISHU_TYPING_ACK", "0")
    monkeypatch.setenv("FEISHU_STREAMING", "false")
    cfg2 = load_feishu_config()
    assert cfg2.typing_ack is False
    assert cfg2.streaming is False
    # c) 显式 1 / off 语义（off 关闭，1 开启）
    monkeypatch.setenv("FEISHU_TYPING_ACK", "off")
    monkeypatch.setenv("FEISHU_STREAMING", "1")
    cfg3 = load_feishu_config()
    assert cfg3.typing_ack is False
    assert cfg3.streaming is True
