#!/usr/bin/env python3
"""Operator terminal: issue ONE server-side Web/GLM canary configuration.

This script NEVER publishes/restarts managed services, modifies runtime.toml,
or makes a Provider request. Only the operator owns the output path and may
enable it via the separately governed Web configuration setting.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import time
from pathlib import Path

from llm_loop.config import load_settings
from llm_loop.factory import build_engine


def _store_exclusive(path: Path, payload: dict) -> None:
    if not path.is_absolute() or not path.parent.is_dir() or path.exists() or path.is_symlink():
        raise ValueError("admin canary output must be new, absolute, and parent must exist")
    content = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if len(content) > 16384:
        raise ValueError("admin canary configuration too large")
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)
    parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-id", default="", help="existing, dedicated Web session")
    parser.add_argument("--ttl-seconds", type=int, default=900)
    args = parser.parse_args()
    if not 60 <= args.ttl_seconds <= 3600:
        parser.error("--ttl-seconds must be 60..3600")
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        parser.error("--output must be an unused absolute path")

    engine = build_engine(load_settings())
    if not getattr(engine._event_store, "enabled", False):
        parser.error("durable EventStore is required")
    if not getattr(getattr(engine, "runner", None), "enabled", False):
        parser.error("Web BackgroundRunner is required")
    if args.session_id and not engine.session.exists(args.session_id):
        parser.error("specified session does not exist in this workspace")
    session_id = args.session_id or engine.session.create()
    now = time.time()
    payload = {
        "schema": "web-task-budget-admin-once/v1",
        "authorization_id": secrets.token_hex(16),
        "session_id": session_id,
        "workspace_root": engine.workspace_root or "",
        "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": now - 1,
        "valid_until_epoch_s": now + args.ttl_seconds,
    }
    _store_exclusive(args.output, payload)
    print("ADMIN_ONCE_CONFIG_CREATED: true")
    print("WEB_SESSION_ID:", session_id)
    print("CONFIG_PATH:", args.output)
    print("TIME_WINDOW_SECONDS:", args.ttl_seconds)
    print("PHYSICAL_ATTEMPTS_MAX: 1")
    print("TOOLS_WAKE_SUBAGENTS: DENIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
