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
    parser.add_argument(
        "--profile", choices=("one-attempt", "direct-subagent"),
        default="one-attempt",
        help="explicit separate two-level canary capability, default unchanged",
    )
    parser.add_argument(
        "--provider-proxy", default=None,
        help=(
            "optional explicit loopback http:// egress proxy for the one "
            "physical attempt, e.g. http://127.0.0.1:6152 (macOS system proxy)"
        ),
    )
    args = parser.parse_args()
    if not 60 <= args.ttl_seconds <= 3600:
        parser.error("--ttl-seconds must be 60..3600")
    if args.profile == "direct-subagent" and args.provider_proxy is not None:
        parser.error("direct-subagent canary cannot use provider-proxy")
    if args.provider_proxy is not None:
        from llm_loop.resources.task_budget_transport_context import (
            qualify_loopback_provider_proxy,
        )

        if qualify_loopback_provider_proxy(args.provider_proxy) is None:
            parser.error(
                "--provider-proxy must be a plain http:// loopback URL with "
                "an explicit port, e.g. http://127.0.0.1:6152"
            )
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
    if args.profile == "direct-subagent":
        from llm_loop.resources import task_budget_subagent_profile as subagent_profile

        schema = subagent_profile.CONFIG_SCHEMA
    else:
        schema = "web-task-budget-admin-once/v1"
    payload = {
        "schema": schema,
        "authorization_id": secrets.token_hex(16),
        "session_id": session_id,
        "workspace_root": engine.workspace_root or "",
        "model_ref": "glm/glm-5.3",
        "valid_from_epoch_s": now - 1,
        "valid_until_epoch_s": now + args.ttl_seconds,
    }
    if args.profile == "direct-subagent":
        payload["profile"] = subagent_profile.PROFILE
    if args.provider_proxy is not None:
        payload["provider_proxy"] = args.provider_proxy
    # EVO-20261009-9d116efa G3：发放前置校验——字段未在本代码注册即拒发。
    # 事故：task_budget_canary_config 先落 runtime.toml、目标代码未注册
    # （2026-10-09，7fe0170d4 目标重启失败、41 分钟人工回滚）。发放一份
    # 本代码消费不了的配置就是在制造同类事故，fail-closed 拒绝。
    from llm_loop.runtime.resolver import TOML_SCHEMA

    if ("web", "task_budget_canary_config") not in TOML_SCHEMA:
        print("REFUSED: 本代码 TOML_SCHEMA 未注册 (web, task_budget_canary_config)")
        print("先在 resolver.py 注册字段并补齐单测，再发放 admin-once 配置。")
        print("未注册状态下 runtime.toml 引用该配置，重启会 fail-closed 中止（G1）或停机（旧脚本）。")
        return 3
    _store_exclusive(args.output, payload)
    print("ADMIN_ONCE_CONFIG_CREATED: true")
    print("WEB_SESSION_ID:", session_id)
    print("CONFIG_PATH:", args.output)
    print("TIME_WINDOW_SECONDS:", args.ttl_seconds)
    if args.profile == "direct-subagent":
        print("CANARY_PROFILE:", subagent_profile.PROFILE)
        print("PHYSICAL_ATTEMPTS_MAX:", subagent_profile.MAX_PHYSICAL_ATTEMPTS)
        print("TOOL_INVOCATIONS_MAX:", subagent_profile.MAX_TOOL_INVOCATIONS)
        print("TOOLS: spawn_subagent x1; subagent_result x2")
        print("SUBAGENTS: ONE DIRECT, ZERO CHILD TOOLS, NO RECURSION")
        print("WAKE / SHELL / FS / NET / BROWSER TOOLS: DENIED")
    else:
        print("PHYSICAL_ATTEMPTS_MAX: 1")
        print("TOOLS_WAKE_SUBAGENTS: DENIED")
    print(
        "NEXT: runtime.toml [web] task_budget_canary_config 指向该文件后，"
        "重启前先自检: python -m llm_loop.runtime.resolver --check-toml <runtime.toml> web"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
