"""企微桥配置测试（M0-2）：正常加载 + 缺 bot_id + 缺 secret 三条路径.

零真实凭据（env 注入假值）；缺必填项必须明确报错（含字段名），不给静默默认值。
"""

import pytest

from llm_loop.wecom.config import (
    BOT_ID_ENV,
    DEFAULT_SESSION_MAP_FILENAME,
    OWNER_USERID_ENV,
    SECRET_ENV,
    SESSION_MAP_PATH_ENV,
    load_wecom_config,
)

FAKE_BOT_ID = "fake_bot_0001"
FAKE_SECRET = "fake_secret_do_not_leak_123"


def _clear_env(monkeypatch):
    for key in (BOT_ID_ENV, SECRET_ENV, SESSION_MAP_PATH_ENV, OWNER_USERID_ENV):
        monkeypatch.delenv(key, raising=False)


def test_config_load_ok(monkeypatch, tmp_path):
    """正常加载：全部字段从 env 读到；映射文件路径缺省与 DATA_DIR 挂钩."""
    _clear_env(monkeypatch)
    monkeypatch.setenv(BOT_ID_ENV, FAKE_BOT_ID)
    monkeypatch.setenv(SECRET_ENV, FAKE_SECRET)
    monkeypatch.setenv(OWNER_USERID_ENV, "fake_owner")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg = load_wecom_config()
    assert cfg.bot_id == FAKE_BOT_ID
    assert cfg.secret == FAKE_SECRET
    assert cfg.owner_userid == "fake_owner"
    assert cfg.has_credentials is True
    # 缺省映射路径：{DATA_DIR}/wecom_session_map.json（与飞书 feishu_session_map.json 分离）
    assert cfg.session_map_path == str(tmp_path / DEFAULT_SESSION_MAP_FILENAME)
    assert DEFAULT_SESSION_MAP_FILENAME == "wecom_session_map.json"


def test_config_missing_bot_id(monkeypatch):
    """缺 WECHAT_BOT_ID：ValueError 含字段名（明确报错，不给静默默认值）."""
    _clear_env(monkeypatch)
    monkeypatch.setenv(SECRET_ENV, FAKE_SECRET)
    with pytest.raises(ValueError) as ei:
        load_wecom_config()
    assert BOT_ID_ENV in str(ei.value)
    assert SECRET_ENV not in str(ei.value)  # 错误信息只点名缺失项


def test_config_missing_secret(monkeypatch):
    """缺 WECHAT_BOT_SECRET：ValueError 含字段名（明确报错，不给静默默认值）."""
    _clear_env(monkeypatch)
    monkeypatch.setenv(BOT_ID_ENV, FAKE_BOT_ID)
    with pytest.raises(ValueError) as ei:
        load_wecom_config()
    assert SECRET_ENV in str(ei.value)
    assert BOT_ID_ENV not in str(ei.value)


def test_config_missing_both_names_each(monkeypatch):
    """两项都缺：错误信息同时含两个字段名（逐项点名，不笼统）."""
    _clear_env(monkeypatch)
    with pytest.raises(ValueError) as ei:
        load_wecom_config()
    msg = str(ei.value)
    assert BOT_ID_ENV in msg and SECRET_ENV in msg


def test_config_env_override_map_path(monkeypatch, tmp_path):
    """WECHAT_SESSION_MAP_PATH 显式覆盖优先于 DATA_DIR 缺省."""
    _clear_env(monkeypatch)
    monkeypatch.setenv(BOT_ID_ENV, FAKE_BOT_ID)
    monkeypatch.setenv(SECRET_ENV, FAKE_SECRET)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    override = str(tmp_path / "custom_map.json")
    monkeypatch.setenv(SESSION_MAP_PATH_ENV, override)
    assert load_wecom_config().session_map_path == override
