"""P1 first-use diagnostics: read-only, credential-value-free.

By default this is an offline human preflight: it describes local prerequisites and
does not assert that a live model works.  ``online=True`` (``lfl doctor --online``)
adds exactly one bounded live request through :mod:`llm_loop.runtime.model_check`
so installation guidance can distinguish "configured" from "usable".
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
    online: bool = False,
) -> dict[str, Any]:
    """Return only whitelisted structural facts, never config or secret values.

    ``root`` is the source root or the installed application home, matching the
    production CLI's existing default selection. No global state is changed.
    """
    shell = dict(environment)
    checks: list[dict[str, object]] = []

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

    # Installation briefing: the same three asset classes the context prefix will
    # load.  Missing resources degrade the briefing, not the runtime; report it so
    # a fresh install can be fixed before the first conversation.
    try:
        from llm_loop.runtime.briefing import inspect_installation_assets

        def asset_path(key: str) -> str:
            raw = str(merged.get(key, "")).strip()
            if not raw:
                return ""
            try:
                return str(_select_path(raw, source=source(key), config=config))
            except (OSError, ValueError):
                return ""

        assets = inspect_installation_assets({
            "docs": asset_path("DOCS_DIR"),
            "methods": asset_path("METHOD_SEED_DIR"),
            "experiences": asset_path("EXPERIENCES_DIR"),
            "skills": asset_path("SKILLS_DIR"),
        })
        summary = ("规则索引 {rules} 条、方法 {methods} 条、经验 {experiences} 条、技能 {skills} 个"
                   .format(**assets))
        if assets["rules"] and (assets["methods"] or assets["experiences"] or assets["skills"]):
            add("context_assets", "pass", "安装上下文资产可加载：" + summary + "。")
        elif assets["rules"] or assets["methods"] or assets["experiences"] or assets["skills"]:
            add("context_assets", "warn", "安装上下文资产不完整：" + summary + "。",
                "运行 lfl check-install 核对安装包；源码运行时检查 docs/、methods/、skills/ 是否存在。")
        else:
            add("context_assets", "warn", "未找到规则/经验/技能资产，会话只加载通用提示。",
                "确认安装包包含 docs/ai_rules.md、methods/、skills/；源码运行时确认仓库资源目录。")
    except Exception:  # noqa: BLE001 - a broken index must not break diagnostics
        add("context_assets", "warn", "安装上下文资产索引不可用。",
            "检查 docs/ai_rules.md 与资源目录权限；运行 lfl doctor 复检。")

    # 规则资产事实（评审 §4.2 / §3.4 任务 3）：与 rules_version()/RuleIndex 同源，
    # 离线只读；错误带 error_code，lite 版本缺失不再静默当作健康。探测走程序
    # 真实检索路径（RuleIndex），成功即视为可取回真实规则卡（评审 §5）。
    try:
        from llm_loop.introspection.rule_index import RuleIndex
        from llm_loop.runtime.installation import rule_asset_facts, rules_doc_candidates

        facts = rule_asset_facts()
        if facts["rule_body_retrievable"] and facts["error_code"] is None:
            body_path = rules_doc_candidates("ai_rules.md")[0]
            if not RuleIndex(body_path).search("RULE-AI-24", 1):
                facts["error_code"] = "rule_lookup_failed"
        detail = (
            "source_kind={source_kind} ref={rule_body_ref} rules_version={version} "
            "rule_body_sha256={digest}".format(
                source_kind=facts["source_kind"],
                rule_body_ref=facts["rule_body_ref"],
                version=str(facts["rules_version"]) or "?",
                digest=str(facts["rule_body_sha256"])[:16],
            )
        )
        error_code = facts["error_code"]
        if error_code is None:
            add("rule_assets", "pass", "规则资产可检索：" + detail)
        elif error_code == "version_parse_error" or (
            error_code == "asset_missing" and facts["rule_body_retrievable"]
        ):
            # 正文仍可检索，仅版本信号缺失（lite 缺失/不可解析）：warn 而非 fail，
            # pre-fix 存留安装不应被诊断判死（评审 §3.4 任务 2 的互操作语义）。
            add("rule_assets", "warn", "规则正文可检索但规则版本信号缺失：" + detail,
                "修复或重装 docs/ai_rules.lite.md（lfl check-install 验证完整性）。")
        else:
            action = {
                "asset_missing": "确认安装完整：重装包或恢复缺失资源，再运行 lfl check-install。",
                "asset_unreadable": "检查文件权限或重装包，再运行 lfl check-install。",
                "rule_lookup_failed": "docs/ai_rules.md 存在但解析不出规则卡：重装或修复包内容。",
            }.get(str(error_code), "重装包并运行 lfl check-install。")
            add("rule_assets", "fail", "规则资产不可用（error_code=" + str(error_code) + "）：" + detail, action)
        checks[-1]["facts"] = facts
    except Exception:  # noqa: BLE001 - report a bounded fact, never leak exception payload
        add("rule_assets", "fail", "规则资产检查本身失败。", "请反馈给维护者。")

    # Optional live check: exactly one bounded request, only when explicitly asked.
    # It answers a different question from the local "model" check above and never
    # writes configuration or starts the Engine.
    online_report: dict[str, Any] | None = None
    if online:
        from llm_loop.runtime.model_check import check_model_config

        if missing:
            online_report = {
                "status": "not_configured",
                "ok": False,
                "message": "缺少模型配置，未发起在线检测。",
                "action": "先完成 LLM_API_KEY / LLM_BASE_URL 配置，再运行 lfl doctor --online。",
            }
            add("model_live", "fail", online_report["message"], online_report["action"])
        else:
            online_report = check_model_config(
                {
                    "llm_api_key": str(merged.get("LLM_API_KEY", "")),
                    "llm_base_url": str(merged.get("LLM_BASE_URL", "")),
                    "llm_model": str(merged.get("LLM_MODEL", "") or "deepseek-flash"),
                    "llm_wire_protocol": str(merged.get("LLM_WIRE_PROTOCOL", "") or "openai"),
                }
            )
            add(
                "model_live",
                "pass" if online_report.get("ok") else "fail",
                str(online_report.get("message", "")),
                str(online_report.get("action", "")),
            )

    status = "error" if any(c["status"] == "fail" for c in checks) else (
        "needs_setup" if any(c["status"] == "warn" for c in checks) else "ready"
    )
    return {
        "schema": "lfl.doctor/v1",
        "status": status,
        "ready": status == "ready",
        "read_only": True,
        "online": online_report,
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
             "model_live": "模型在线检测", "data_dir": "数据目录", "workspace": "工作目录",
             "resources": "扩展资源", "context_assets": "上下文资产", "rule_assets": "规则资产"}
    online = report.get("online") is not None
    lines = ["LFL doctor（只读 / " + ("含在线检测" if online else "离线") + "）",
             "状态：" + str(report["status"])]
    for check in report["checks"]:
        lines.append(f"[{labels[check['status']]}] {names[check['id']]}：{check['message']}")
        if check["action"]:
            lines.append("  建议：" + check["action"])
    if online:
        lines.append("在线检测只证明本次一次最小请求可用，不代表额度、并发或长期可用性。")
    else:
        lines.append("仅检查本地先决条件；如需验证凭据与模型，运行 lfl doctor --online。")
    return "\n".join(lines)
