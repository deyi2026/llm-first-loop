#!/usr/bin/env python3
"""Configure browser login without ever placing plaintext secrets in argv/env/history."""

from __future__ import annotations

import getpass
import hmac
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llm_loop.web.auth import hash_login_password  # noqa: E402

ENV_PATH = ROOT / ".env"
DEFAULT_ORIGINS = "https://app.llmfirstloop.com,https://llmfirstloop.com"


def _upsert(lines: list[str], key: str, value: str) -> list[str]:
    prefix = f"{key}="
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            if not found:
                out.append(f"{key}={value}")
                found = True
            continue
        out.append(line)
    if not found:
        out.append(f"{key}={value}")
    return out


def main() -> int:
    password = getpass.getpass("Web login password (min 12 chars; paste is supported): ")
    confirm = getpass.getpass("Confirm web login password: ")
    if not hmac.compare_digest(password, confirm):
        print("ERROR: passwords do not match; existing configuration was not changed.", file=sys.stderr)
        return 2
    try:
        encoded = hash_login_password(password)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    for key, value in (
        ("WEB_AUTH_REQUIRE", "1"),
        ("WEB_LOGIN_PASSWORD_HASH", encoded),
        ("WEB_SESSION_TTL_SECONDS", "43200"),
        ("WEB_ORIGIN_ALLOWLIST", DEFAULT_ORIGINS),
    ):
        lines = _upsert(lines, key, value)
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV_PATH.chmod(0o600)
    print("Browser login configured. Plaintext password was not persisted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
