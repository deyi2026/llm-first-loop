"""Safe browser-login configuration script: no plaintext persistence, no partial mismatch writes."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "configure_web_login.py"
    spec = importlib.util.spec_from_file_location("configure_web_login", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_persists_only_hash_and_private_mode(tmp_path, monkeypatch) -> None:
    mod = _load_script()
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=value\n", encoding="utf-8")
    prompts = iter(["super-secret-password", "super-secret-password"])
    monkeypatch.setattr(mod, "ENV_PATH", env_path)
    monkeypatch.setattr(mod.getpass, "getpass", lambda _prompt: next(prompts))
    monkeypatch.setattr(mod, "hash_login_password", lambda password: "pbkdf2$HASHED")

    assert mod.main() == 0
    text = env_path.read_text(encoding="utf-8")
    assert "super-secret-password" not in text
    assert "WEB_LOGIN_PASSWORD_HASH=pbkdf2$HASHED" in text
    assert "WEB_AUTH_REQUIRE=1" in text
    assert "WEB_ORIGIN_ALLOWLIST=https://app.llmfirstloop.com,https://llmfirstloop.com" in text
    assert env_path.stat().st_mode & 0o777 == 0o600


def test_password_mismatch_keeps_existing_configuration_unchanged(tmp_path, monkeypatch) -> None:
    mod = _load_script()
    env_path = tmp_path / ".env"
    original = "KEEP=unchanged\n"
    env_path.write_text(original, encoding="utf-8")
    prompts = iter(["first-password", "different-password"])
    monkeypatch.setattr(mod, "ENV_PATH", env_path)
    monkeypatch.setattr(mod.getpass, "getpass", lambda _prompt: next(prompts))

    assert mod.main() == 2
    assert env_path.read_text(encoding="utf-8") == original
