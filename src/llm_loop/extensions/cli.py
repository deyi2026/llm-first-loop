"""Small local CLI around the existing ExtensionStore; no new control plane."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from llm_loop.config import read_env_file_values
from llm_loop.extensions.formats import parse_plugin_package
from llm_loop.extensions.store import (
    CommitUncertainError,
    ExtensionStore,
    InstallRejectedError,
    RevisionConflictError,
)
from llm_loop.extensions.vendor_formats import (
    FORMAT_STANDARD,
    detect_vendor_format,
    parse_vendor_package,
)


def _data_root(args: Any, home: Path, environment: Mapping[str, str]) -> Path:
    """Match the normal application's data-directory precedence without booting it."""
    config = Path(args.config or environment.get("LFL_ENV_FILE") or home / ".env").expanduser()
    if args.config and not config.is_file():
        raise ValueError("explicit_config_unavailable")
    file_values = read_env_file_values(config) if config.is_file() else {}
    inherited = environment.get("DATA_DIR") or environment.get("LFL_DATA_DIR")
    from_file = file_values.get("DATA_DIR") or file_values.get("LFL_DATA_DIR")
    raw = args.data_dir or inherited or from_file or home / "data"
    path = Path(raw).expanduser()
    if from_file and raw == from_file and not path.is_absolute():
        path = config.parent / path
    return path.resolve()


def _record(item: Any) -> dict[str, Any]:
    return {
        "install_id": item.install_id,
        "name": item.plugin_name,
        "version": item.version,
        "components": [
            {"kind": part.kind, "name": part.name, "status": part.status,
             "enabled": part.enabled} for part in item.components
        ],
    }


def _report(data: dict[str, Any], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif data.get("status") == "rejected":
        print("扩展操作已拒绝：" + data.get("reason", "unknown"), file=sys.stderr)
    elif "installs" in data:
        items = data["installs"]
        print("已安装扩展：" + str(len(items)))
        for item in items:
            enabled = sum(bool(c["enabled"]) for c in item["components"])
            print("- " + item["install_id"] + " v" + item["version"] +
                  "：启用组件 " + str(enabled) + "/" + str(len(item["components"])))
    elif "plugin_name" in data:
        print("扩展候选：" + data["plugin_name"] + " v" + data["version"] +
              "；状态 " + data["overall"])
    else:
        print("扩展操作：" + data["status"] + "（" + data.get("install_id", "") + "）")


def _approve(action: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input("将" + action + "本地扩展记录；确认输入 yes：").strip() == "yes"
    except (EOFError, KeyboardInterrupt):
        return False


def _inspect(path: str) -> dict[str, Any]:
    root = Path(path).expanduser()
    fmt = detect_vendor_format(root) or FORMAT_STANDARD
    parsed = (parse_plugin_package(root) if fmt == FORMAT_STANDARD else
              parse_vendor_package(root, source_format=fmt).report)
    if parsed.overall == "unavailable":
        raise InstallRejectedError("unavailable_package")
    return {
        "plugin_name": parsed.plugin_name,
        "version": parsed.version,
        "overall": parsed.overall,
        "source_format": fmt,
        "components": [
            {"kind": "skill", "name": p.name, "status": p.status}
            for p in parsed.skills
        ] + [
            {"kind": "mcp_server", "name": p.name, "status": p.status}
            for p in parsed.servers
        ],
    }


def run_extensions(argv: list[str], *, args: Any, home: Path,
                   environment: Mapping[str, str]) -> int:
    parser = argparse.ArgumentParser(prog="lfl extensions", description="本地扩展管理")
    parser.add_argument("operation", choices=("list", "inspect", "install", "update",
                                               "enable", "disable", "remove"))
    parser.add_argument("target", nargs="?")
    parser.add_argument("--component")
    parser.add_argument("--yes", action="store_true", help="确认写入扩展安装记录")
    parser.add_argument("--json", action="store_true")
    try:
        options = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    op = options.operation
    if (op in ("list",) and options.target or
            op != "list" and not options.target or
            options.component and op not in ("enable", "disable")):
        return 2
    if op == "inspect":
        try:
            _report(_inspect(options.target), options.json)
            return 0
        except (OSError, ValueError, InstallRejectedError):
            _report({"schema": "lfl.extensions/v1", "status": "rejected",
                     "reason": "invalid_or_unavailable_package"}, options.json)
            return 1
    try:
        data = _data_root(args, home, environment)
    except (OSError, UnicodeError, ValueError):
        _report({"schema": "lfl.extensions/v1", "status": "rejected",
                 "reason": "invalid_data_or_config_path"}, options.json)
        return 1
    store_root = data / "extensions"
    if op == "list" and not (store_root / "installed.json").exists():
        _report({"schema": "lfl.extensions/v1", "revision": 0, "installs": []}, options.json)
        return 0
    if op != "list" and not _approve(op, options.yes):
        if not options.yes and not sys.stdin.isatty():
            print("非交互操作请显式添加 --yes；不会修改扩展。", file=sys.stderr)
            return 2
        return 1
    try:
        store = ExtensionStore(store_root)
        state = store.read_state()
        if op == "list":
            report = {"schema": "lfl.extensions/v1", "revision": state.revision,
                      "installs": [_record(item) for item in state.installs]}
        elif op in ("install", "update"):
            package = Path(options.target).expanduser().resolve()
            if not package.is_dir():
                raise InstallRejectedError("invalid_package")
            existing = tuple(item.install_id for item in state.installs)
            item = store.install(package, source=str(package), expected_revision=state.revision)
            report = {"schema": "lfl.extensions/v1",
                      "status": "updated" if item.install_id in existing else "installed",
                      "install_id": item.install_id, "revision": state.revision + 1}
        elif op in ("enable", "disable"):
            existing = state.find(options.target)
            if existing is None or (options.component is not None and not any(
                item.name == options.component for item in existing.components
            )):
                raise InstallRejectedError("unknown_install_or_component")
            record = store.set_enabled(
                options.target, enabled=op == "enable", component=options.component,
                expected_revision=state.revision,
            )
            report = {"schema": "lfl.extensions/v1", "status": "enabled" if op == "enable" else "disabled",
                      "install_id": record.install_id, "revision": state.revision + 1}
        else:
            name = store.uninstall(options.target, expected_revision=state.revision)
            report = {"schema": "lfl.extensions/v1", "status": "removed",
                      "install_id": name, "instance_data_preserved": True,
                      "revision": state.revision + 1}
        _report(report, options.json)
        return 0
    except (CommitUncertainError, RevisionConflictError):
        reason = "state_conflict_or_uncertain_commit"
    except (InstallRejectedError, OSError, ValueError):
        reason = "invalid_or_unavailable_package" if op in ("install", "update") else "mutation_rejected"
    _report({"schema": "lfl.extensions/v1", "status": "rejected", "reason": reason}, options.json)
    return 1
