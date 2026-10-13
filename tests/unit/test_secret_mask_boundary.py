"""EVO-20261014-483ca6de #2 秘密脱敏三类边界契约（RULE-AI-30 fail-closed 纵深）.

执行时核验的分层结论：
- 入口层已 fail-closed：parse_env_file 的 _KEY_RE 拒绝含不可见字符的键名；
  runtime.toml 闭式 schema 对未知字段直接 ValueError（本文件锁定前者）。
- 本层（resolver._mask_secret → to_summary values 单一消费点）为纵深防御：
  (a) 密钥名含不可见字符 → 按敏感处理（含零宽插进词内的 compact 兜底）；
  (b) URL userinfo 密码含 @ : 标点 → 以最后一个 @ 为界整体掩码，不漏尾部；
  (c) IPv6 括号主机不受误伤，其 userinfo 凭据仍被掩码。
"""
from __future__ import annotations

from pathlib import Path

from llm_loop.runtime.resolver import (
    _mask_secret,
    _redact_url_credentials,
    parse_env_file,
)


def test_invisible_char_key_name_is_treated_as_secret() -> None:
    # 零宽空格插在 "API" 与 "KEY" 之间：子串匹配失效 → compact 兜底必须仍掩码
    assert _mask_secret("EVIL_API\u200bKEY", "sk-abc123") == "<secret:9chars>"
    # 零宽插在词间（_KEY_RE 层已拒，但若进入 values 也必须掩码）
    assert _mask_secret("EVIL_API\u200b_KEY", "sk-x") == "<secret:4chars>"
    # 双向覆盖控制符包住 TOKEN
    assert _mask_secret("auth\u202eTOKEN\u202c", "v1") == "<secret:2chars>"


def test_normal_keys_unchanged_by_name_hint() -> None:
    assert _mask_secret("SUMMARY_MODE", "off") == "off"
    assert (
        _mask_secret("EMBEDDING_MODEL", "text-embedding-3-small")
        == "text-embedding-3-small"
    )


def test_env_file_layer_rejects_invisible_char_keys(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("EVIL_API\u200bKEY=sk-1\nSUMMARY_MODE=on\n", encoding="utf-8")
    out = parse_env_file(p)
    assert out.get("SUMMARY_MODE") == "on"
    assert not any("\u200b" in k for k in out), "含不可见字符的键名必须在入口层被拒绝"


def test_url_userinfo_password_with_punctuation_fully_masked() -> None:
    # 密码含 @ 与 : ：以最后一个 @ 为界，密码尾部不泄漏
    assert (
        _redact_url_credentials("postgres://user:p@ss:word@host/db")
        == "postgres://user:***@host/db"
    )
    # 空 username + 含 @ 密码（redis/postgres 常见形态）
    assert (
        _redact_url_credentials("redis://:p@ss@10.0.0.1:6379")
        == "redis://:***@10.0.0.1:6379"
    )


def test_ipv6_bracket_host_preserved_and_userinfo_still_masked() -> None:
    # 括号主机无 userinfo：原样返回，不把主机/端口冒号当凭据
    assert _redact_url_credentials("http://[::1]:8080/x") == "http://[::1]:8080/x"
    # 括号主机 + userinfo 凭据：凭据掩码、主机保留
    assert (
        _redact_url_credentials("postgres://u:pw@[::1]:5432/db")
        == "postgres://u:***@[::1]:5432/db"
    )
    # username-only userinfo：无密码事实可泄，不掩码
    assert (
        _redact_url_credentials("http://user@[2001:db8::1]/x")
        == "http://user@[2001:db8::1]/x"
    )


def test_mask_secret_composes_url_redaction_for_non_secret_values() -> None:
    # 键名不含敏感词，但值携带凭据 URL → 值层面仍掩码
    assert (
        _mask_secret("MY_PROXY_URL", "redis://:pw@10.0.0.1:6379")
        == "redis://:***@10.0.0.1:6379"
    )
    # 无凭据 URL 不受影响
    assert (
        _mask_secret("EMBEDDING_BASE_URL", "https://api.example.com/v1")
        == "https://api.example.com/v1"
    )


def test_multi_url_value_all_credentials_masked() -> None:
    # 审查 P1：前一 URL 无路径、逗号直接接下一 scheme:// —— 第二个密码不得泄漏
    assert (
        _redact_url_credentials("redis://:pw@h:6379,redis://:pw2@h2:6379")
        == "redis://:***@h:6379,redis://:***@h2:6379"
    )
    # 空格分隔形态
    assert (
        _redact_url_credentials("postgres://u:p1@h1 redis://:p2@h2")
        == "postgres://u:***@h1 redis://:***@h2"
    )
    # 带路径的正常多 URL 形态（锁防回归）
    assert (
        _redact_url_credentials("postgres://u:p@h/db redis://:p2@h2")
        == "postgres://u:***@h/db redis://:***@h2"
    )
    # 组合面：非敏感键名 + 多 URL 值 → to_summary 单一消费点全掩码
    assert (
        _mask_secret("REDIS_URL", "redis://:pw@h:6379,redis://:pw2@h2:6379")
        == "redis://:***@h:6379,redis://:***@h2:6379"
    )


def test_scheme_with_hyphen_and_plus_supported() -> None:
    # 审查 P3：字符类含 + 与 - 的 scheme 形态防回归
    assert (
        _redact_url_credentials("my-db+ssl://u:pw@h:5432/x")
        == "my-db+ssl://u:***@h:5432/x"
    )
