"""P1 first-use diagnostics: read-only, offline and credential-value-free.

This is a human preflight, not an Engine, service, provider or deployment probe.
It describes local prerequisites; it does not assert that a live model works.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from llm_loop.config import read_env_file_values


def _select_path(raw: str | Path, *, source: str, config: Path) -> Path:
    path = Path(raw).expanduser()
    if source == "config_file" and not path.is_absolute():
        path = config.parent / path
    return path.resolve()


def _check_data_dir(path: Path, bundle: Path | None) -> tuple[str, str, str]:
    if bundle is not None and path.is_relative_to(bundle.resolve()):
        return ("fail", "数据目录位于只读安装包内。", "使用 --data-dir 指向包外的持久目录。")
    if (path.exists() and not path.is_dir()) or (path.is_symlink() and not path.exists()):
        return ("fail", "数据目录不是可用目录。", "使用 --data-dir 指向目录而非文件或无效链接。")
    ancestor = next((p for p in (path, *path.parents) if p.exists()), None)
    if ancestor is None or not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
        return ("fail", "数据目录的现有父目录不可写入。", "检查目录权限或使用 --data-dir 选择其他位置。")
    return ("pass", "数据目录路径可用（未创建或写入任何文件）。", "")


def inspect_first_use(
    *,
    args: Any,
    root: Path,
    bundle: Path | None,
    environment: Mapping[str, str],
    check_install: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Return only whitelisted structural facts, never config or secret values.

    ``root`` is the source root or the installed application home, matching the
    production CLI's existing default selection. No global state is changed.
    """
    shell = dict(environment)
    checks: list[dict[str, str]] = []

    def add(id_: str, status: str, message: str, action: str = "") -> None:
        checks.append({"id": id_, "status": status, "message": message, "action": action})

    if bundle is None:
        add("installation", "pass", "当前从源码目录运行，安装包完整性检查不适用。")
    else:
        try:
            integrity = check_install()
            good = integrity.get("ok") is True
        except Exception:  # noqa: BLE001 - report a bounded fact, never leak exception payload
            good = False
        if good:
            add("installation", "pass", "安装包资源清单完整。")
        else:
            add("installation", "fail", "安装包资源校验未通过。", "核对原始 wheel 摘要并重新安装，运行 lfl check-install 复核。")

    config_source = "command_line" if args.config else "environment" if shell.get("LFL_ENV_FILE") else "default"
    config: Path | None = None
    file_values: dict[str, str] = {}
    try:
        config = Path(args.config or shell.get("LFL_ENV_FILE") or root / ".env").expanduser().resolve()
        if not config.is_file():
            if config_source == "default" and not config.exists():
                if all(str(shell.get(k, "")).strip() for k in ("LLM_API_KEY", "LLM_BASE_URL")):
                    add("config", "pass", "未使用默认配置文件；必要配置由进程环境提供。")
                else:
                    add("config", "warn", "尚未找到默认配置文件。", "配置 LLM_API_KEY / LLM_BASE_URL，或使用 --config 指定配置文件。")
            else:
                add("config", "fail", "指定的配置文件不存在或不是普通文件。", "检查 --config 或 LFL_ENV_FILE 指定的配置文件。")
        else:
            file_values = read_env_file_values(config)
            add("config", "pass", "配置文件存在且可按 CLI 语法读取。")
    except (OSError, UnicodeError, ValueError):
        add("config", "fail", "配置路径或文件无法读取。", "检查文件格式、UTF-8 编码及读取权限。")

    # A shell key set to an empty value still wins over the .env file, just as
    # load_env_file's setdefault does. Never project this snapshot to os.environ.
    merged = dict(shell)
    for key, value in file_values.items():
        merged.setdefault(key, value)

    def source(key: str) -> str:
        if key in shell:
            return "environment"
        if key in file_values:
            return "config_file"
        return "default"

    model_keys = ("LLM_API_KEY", "LLM_BASE_URL")
    missing = [key for key in model_keys if not str(merged.get(key, "")).strip()]
    if missing:
        add("model", "warn", "缺少模型启动所需配置项：" + ", ".join(missing) + "。", "使用环境变量或配置文件设置这些键；不要把密钥写入安装包。")
    else:
        add("model", "pass", "必要模型配置项已设置（未触网验证凭据或模型）。")

    cli_data = str(args.data_dir or "")
    shell_data = str(shell.get("DATA_DIR") or shell.get("LFL_DATA_DIR") or "")
    file_data = str(merged.get("DATA_DIR") or merged.get("LFL_DATA_DIR") or "")
    data_source = "command_line" if cli_data else "environment" if shell_data else (
        "config_file" if file_data else "default"
    )
    data_raw = cli_data or shell_data or file_data or str(root / "data")
    workspace_raw = str(args.workspace or merged.get("LFL_WORKSPACE_ROOT") or Path.cwd())
    workspace_source = (
        "command_line" if args.workspace else "environment" if source("LFL_WORKSPACE_ROOT") == "environment" and merged.get("LFL_WORKSPACE_ROOT")
        else "config_file" if source("LFL_WORKSPACE_ROOT") == "config_file" and merged.get("LFL_WORKSPACE_ROOT")
        else "default"
    )
    if config is None:
        # Do not use an untrusted config path as a source of relative bindings.
        config = root / ".env"
    try:
        data = _select_path(data_raw, source=data_source, config=config)
        add("data_dir", *_check_data_dir(data, bundle))
    except (OSError, ValueError):
        add("data_dir", "fail", "数据目录路径无法解析。", "检查 --data-dir 或 DATA_DIR 配置。")
    try:
        workspace = _select_path(workspace_raw, source=workspace_source, config=config)
        if not workspace.is_dir():
            add("workspace", "fail", "所选工作目录不存在或不是目录。", "创建工作目录或通过 --workspace 选择存在的目录。")
        else:
            add("workspace", "pass", "工作目录存在（未访问用户文件内容）。")
    except (OSError, ValueError):
        add("workspace", "fail", "工作目录路径无法解析。", "检查 --workspace 或 LFL_WORKSPACE_ROOT 配置。")

    # Only explicitly overridden resource directories can be diagnosed here;
    # the bundled defaults are already covered by check_install's manifest.
    overrides = ("SKILLS_DIR", "DOCS_DIR", "UI_V2_DIR", "METHOD_SEED_DIR")
    invalid = []
    for name in overrides:
        if not str(merged.get(name, "")).strip():
            continue
        try:
            if not _select_path(str(merged[name]), source=source(name), config=config).is_dir():
                invalid.append(name)
        except (OSError, ValueError):
            invalid.append(name)
    if invalid:
        add("resources", "fail", "资源目录不可用：" + ", ".join(invalid) + "。", "修正对应路径或移除无效覆盖以使用包内资源。")
    else:
        add("resources", "pass", "未发现无效的自定义资源目录。")

    status = "error" if any(c["status"] == "fail" for c in checks) else (
        "needs_setup" if any(c["status"] == "warn" for c in checks) else "ready"
    )
    return {
        "schema": "lfl.doctor/v1",
        "status": status,
        "ready": status == "ready",
        "read_only": True,
        "sources": {
            "LFL_ENV_FILE": config_source,
            "LLM_API_KEY": source("LLM_API_KEY"),
            "LLM_BASE_URL": source("LLM_BASE_URL"),
            "LLM_MODEL": source("LLM_MODEL") if str(merged.get("LLM_MODEL", "")).strip() else "default",
            "DATA_DIR": data_source,
            "LFL_WORKSPACE_ROOT": workspace_source,
        },
        "checks": checks,
    }


def human_report(report: Mapping[str, Any]) -> str:
    labels = {"pass": "通过", "warn": "待配置", "fail": "失败"}
    names = {"installation": "安装包", "config": "配置文件", "model": "模型配置",
             "data_dir": "数据目录", "workspace": "工作目录", "resources": "扩展资源"}
    lines = ["LFL doctor（只读 / 离线）", "状态：" + str(report["status"])]
    for check in report["checks"]:
        lines.append(f"[{labels[check['status']]}] {names[check['id']]}：{check['message']}")
        if check["action"]:
            lines.append("  建议：" + check["action"])
    lines.append("仅检查本地先决条件，不代表模型、远端服务或生产环境已验收。")
    return "\n".join(lines)
