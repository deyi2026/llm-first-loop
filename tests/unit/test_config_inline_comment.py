"""config 行内注释剥离测试（config.py _raw_env，EVO-ba4a107c 解析端对齐）.

覆盖: 脏值环境变量（KEY=1  # 注释）不再触发非整数回退 / 干净值正常解析 /
注释含 # 但非空白分隔（如 URL 中 #fragment）不误伤 / 未设置回退默认.
"""

from __future__ import annotations

import os

from llm_loop import config as cfg


def _restore(key: str):
    old = os.environ.get(key)
    if old is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old


def test_env_int_ignores_inline_comment():
    """RETRIEVE_TIMEOUT_S='1  # 秒（整数）' → 解析为 1（不再回退默认）."""
    os.environ["TEST_RETRIEVE_TIMEOUT_S"] = "1  # 秒（整数；config _env_int 解析）"
    try:
        assert cfg._env_int("TEST_RETRIEVE_TIMEOUT_S", 5) == 1
    finally:
        _restore("TEST_RETRIEVE_TIMEOUT_S")


def test_env_bool_ignores_inline_comment():
    """VALIDATE_SEMANTIC='0  # 默认关' → False（不再回退 True）."""
    os.environ["TEST_VALIDATE_SEMANTIC"] = "0  # 默认关"
    try:
        assert cfg._env_bool("TEST_VALIDATE_SEMANTIC", True) is False
    finally:
        _restore("TEST_VALIDATE_SEMANTIC")


def test_env_int_clean_value():
    """干净值不受影响."""
    os.environ["TEST_CLEAN_INT"] = "42"
    try:
        assert cfg._env_int("TEST_CLEAN_INT", 5) == 42
    finally:
        _restore("TEST_CLEAN_INT")


def test_env_int_hash_in_url_not_stripped():
    """URL 中 '#' 前无空白分隔（如 EMBEDDING_BASE_URL）不被误伤——_raw_env 仅剥离 ' #'."""
    os.environ["TEST_URL"] = "https://api.example.com/v1#fragment"
    try:
        # URL 场景用 _env_str 不存在，直接用 _raw_env 验证不截断
        assert cfg._raw_env("TEST_URL") == "https://api.example.com/v1#fragment"
    finally:
        _restore("TEST_URL")


def test_env_int_missing_returns_default():
    """未设置 → 默认值."""
    os.environ.pop("TEST_NOT_SET", None)
    assert cfg._env_int("TEST_NOT_SET", 7) == 7


def test_invalid_fallback_not_noted_for_comment_value():
    """带注释的整数值不产生 invalid_fallback 记录（真实修复验证）."""
    os.environ["TEST_NO_FALLBACK"] = "3  # 秒"
    try:
        before = len(cfg._fallback_notes)
        assert cfg._env_int("TEST_NO_FALLBACK", 9) == 3
        # 该键解析不应新增回退记录
        names = [n.name for n in cfg._fallback_notes[before:]]
        assert "TEST_NO_FALLBACK" not in names
    finally:
        _restore("TEST_NO_FALLBACK")
