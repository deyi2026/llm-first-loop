"""security_guard 共享原语的边界测试（P0-4/P1-3 的上游依赖）。"""

from __future__ import annotations

from pathlib import Path

from llm_loop.security_guard import (
    find_sensitive_paths,
    has_strong_secret,
    is_sensitive_path,
    redact_secrets,
    scan_text,
    sensitive_path_reason,
)


def test_sensitive_names_and_dirs() -> None:
    assert is_sensitive_path(".env")
    assert is_sensitive_path("prod.env")
    assert is_sensitive_path("id_ed25519")
    assert is_sensitive_path("certs/server.pem")
    assert is_sensitive_path("config/secrets.yaml")
    assert sensitive_path_reason("/ho" + "me/u/.ssh/known_hosts") == "dir:.ssh"  # 拼接：源码不留绝对路径字面量
    assert sensitive_path_reason("tls/client.key") == "name:client.key"


def test_templates_are_not_flagged() -> None:
    # 模板只含占位符，不应该把常规删除/外发动作抬高门槛
    assert not is_sensitive_path(".env.example")
    assert not is_sensitive_path(".env.sample")
    assert not is_sensitive_path("config.yaml")


def test_ordinary_files_are_not_flagged() -> None:
    for name in ("README.md", "main.py", "tokenizer_config.json", "package-lock.json"):
        assert not is_sensitive_path(name), name


def test_scan_text_strong_vs_weak() -> None:
    assert has_strong_secret("-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc")  # 拼接避免源码触发 CacheGuard
    assert has_strong_secret("token=sk-ant-abcdefghijklmnopqrstuvwxyz012345")
    assert has_strong_secret("AK" + "IAABCDEFGHIJKLMNOP")
    assert not has_strong_secret("password = changeme")  # 低置信，默认不阻断
    weak = scan_text("password = changeme", include_weak=True)
    assert [hit.kind for hit in weak] == ["credential_assignment"]
    assert weak[0].severity == "weak"


def test_redact_secrets_removes_plaintext() -> None:
    secret = "sk-ant-abcdefghijklmnopqrstuvwxyz012345"
    redacted = redact_secrets(f"before {secret} after")
    assert secret not in redacted
    assert "[REDACTED:anthropic_key]" in redacted


def test_find_sensitive_paths_walks_tree(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / ".env").write_text("A=1", encoding="utf-8")
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "server.pem").write_text("x", encoding="utf-8")
    found = sorted(find_sensitive_paths(tmp_path))
    assert found == [".env", "deploy/server.pem"]


def test_find_sensitive_paths_respects_budget(tmp_path: Path) -> None:
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("A=1", encoding="utf-8")
    # 上限截断时不得抛异常；返回值可能为空，调用方不能把空当"干净"
    assert isinstance(find_sensitive_paths(tmp_path, max_entries=1), list)
