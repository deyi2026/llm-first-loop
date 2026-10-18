"""Offline first-use CLI configuration; one exclusive new file, never an update.

The installed application's authoritative paths and read-only doctor remain the
only configuration/control plane. No provider, engine or service is created here.
"""

from __future__ import annotations

import getpass
import json
import os
import secrets
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from llm_loop.config import read_env_file_values


def _lexical_path(raw: str | Path) -> Path:
    value = Path(raw).expanduser()
    if ".." in value.parts:
        raise ValueError("unsafe target path")
    return Path(os.path.abspath(value))


def _target_path(raw: str | Path) -> Path:
    lexical = _lexical_path(raw)
    # Never resolve the final component: it may be a symlink we must refuse.
    # Resolving an existing ancestor makes legitimate /tmp or HOME symlinks
    # usable. The final canonical parent is still walked with O_NOFOLLOW.
    if lexical.is_symlink():
        return lexical
    return Path(os.path.realpath(lexical.parent)) / lexical.name


def _unsafe_path(target: Path, bundle: Path | None, *, allow_default_parent: Path | None = None) -> str | None:
    if any(path.is_symlink() for path in (target, *target.parents)):
        return "symlink_target_or_parent"
    if bundle is not None and target.is_relative_to(Path(os.path.realpath(bundle))):
        return "read_only_installation_bundle"
    if target.exists() and not target.is_file():
        return "target_not_a_regular_file"
    if not target.exists():
        if not target.parent.is_dir() and target.parent != allow_default_parent:
            return "nonexistent_explicit_parent"
        parent = next((p for p in (target.parent, *target.parents) if p.exists()), None)
        if parent is None or not parent.is_dir() or not os.access(parent, os.W_OK | os.X_OK):
            return "unwritable_target_parent"
    return None


def plan_first_use(*, args: Any, root: Path, bundle: Path | None, environment: Mapping[str, str]) -> tuple[dict[str, Any], Path | None]:
    """Compute a redacted snapshot; never create paths or mutate the process env."""
    shell = dict(environment)
    source = "command_line" if args.config else "environment" if shell.get("LFL_ENV_FILE") else "default"
    raw = args.config or shell.get("LFL_ENV_FILE") or root / ".env"
    blocked: str | None = None
    target: Path | None = None
    file_values: dict[str, str] = {}
    try:
        target = _target_path(raw)
        blocked = _unsafe_path(target, bundle, allow_default_parent=Path(os.path.realpath(root)) if source == "default" else None)
        if not blocked and target.is_file():
            file_values = read_env_file_values(target)
    except (OSError, UnicodeError, ValueError):
        blocked = "unreadable_or_invalid_target"

    merged = dict(shell)
    for key, val in file_values.items():
        merged.setdefault(key, val)

    def origin(key: str) -> str:
        if key in shell:
            return "environment"
        if key in file_values:
            return "config_file"
        return "default"

    required = [key for key in ("LLM_API_KEY", "LLM_BASE_URL") if not str(merged.get(key, "")).strip()]
    env_ready = not required
    exists = target is not None and target.exists()
    if not blocked and not exists and any(key in shell and not str(shell[key]).strip() for key in ("LLM_API_KEY", "LLM_BASE_URL")):
        blocked = "empty_process_variable_overrides_file"
    status = "blocked" if blocked else "already_configured" if env_ready else "existing_config" if exists else "needs_setup"
    can_create = not blocked and not exists and not env_ready
    report = {
        "schema": "lfl.init.plan/v1",
        "status": status,
        "read_only": True,
        "write_performed": False,
        "requires_confirmation": True,
        "target": {"source": source, "exists": bool(exists), "can_create": bool(can_create)},
        "sources": {key: origin(key) for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")},
        "required_keys": required,
        "reason": blocked or ("existing_config" if exists else ""),
        "next_steps": ["lfl doctor", "lfl init"] if can_create else ["lfl doctor"],
    }
    return report, target


def _validate_value(value: str, *, key: str, optional: bool = False) -> str:
    if not value and not optional:
        raise ValueError(key + " must be non-empty")
    if len(value) > 8192 or value != value.strip() or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("invalid configuration value")
    if "\"" in value and "'" in value:
        raise ValueError("configuration value cannot be represented without loss")
    if key == "LLM_BASE_URL":
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("model URL must be an HTTP(S) endpoint without embedded credentials")
    if key == "LLM_MODEL" and len(value) > 250:
        raise ValueError("model name too long")
    return value


def _config_line(key: str, value: str) -> str:
    # Our CLI dotenv reader does not unescape quoted values. Choose an enclosing
    # quote that never occurs in the value; fail earlier if both occur.
    quote = "'" if '"' in value else '"'
    return key + "=" + quote + value + quote + "\n"


def _open_directory_chain(path: Path, *, create: bool) -> tuple[int, list[Path]]:
    """Walk each segment via dirfd/O_NOFOLLOW to avoid ancestor-symlink races."""
    # Never realpath here: doing so hides a newly swapped ancestor symlink
    # from O_NOFOLLOW, defeating the confirmation-to-publish race guard.
    absolute = _lexical_path(path)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    dir_fd = os.open(absolute.anchor, flags)
    current = Path(absolute.anchor)
    made: list[Path] = []
    try:
        for name in absolute.parts[1:]:
            try:
                child_fd = os.open(name, flags, dir_fd=dir_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(name, mode=0o700, dir_fd=dir_fd)
                made.append(current / name)
                child_fd = os.open(name, flags, dir_fd=dir_fd)
            os.close(dir_fd)
            dir_fd = child_fd
            current /= name
        return dir_fd, made
    except OSError:
        os.close(dir_fd)
        for made_dir in reversed(made):
            with suppress(OSError):
                made_dir.rmdir()
        raise


def _make_parent(target: Path, *, root: Path, source: str) -> list[Path]:
    """Create only the application's own default directory, never arbitrary parents."""
    parent = target.parent
    if parent.is_dir():
        return []
    if source != "default" or parent != Path(os.path.realpath(root)):
        raise OSError("parent directory does not exist")
    dir_fd, made = _open_directory_chain(parent, create=True)
    os.close(dir_fd)
    return made


def _exclusive_create(target: Path, content: bytes) -> None:
    """Durable same-directory create-only publication; no rename-overwrite race."""
    parent_fd, _ = _open_directory_chain(target.parent, create=False)
    # Bounded NAME_MAX, even when the requested basename is nearly 255 bytes.
    temp = ".lfl-init-" + secrets.token_hex(12) + ".tmp"
    created = False
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
        created = True
        with os.fdopen(fd, "wb", closefd=True) as dest:
            os.fchmod(dest.fileno(), 0o600)
            dest.write(content)
            dest.flush()
            os.fsync(dest.fileno())
        os.link(temp, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
        os.fsync(parent_fd)
    finally:
        if created:
            os.unlink(temp, dir_fd=parent_fd)
        os.close(parent_fd)


def _interactive_setup(*, target: Path, report: dict[str, Any], root: Path, bundle: Path | None,
                       args: Any, environment: Mapping[str, str], check_install: Callable[[], dict[str, Any]]) -> int:
    if not sys.stdin.isatty():
        print("交互向导需要终端；可运行 lfl init --plan", file=sys.stderr)
        return 2
    if report["status"] == "blocked":
        print("配置目标不安全或不能写入，请检查 lfl init --plan", file=sys.stderr)
        return 1
    if not report["target"]["can_create"]:
        print("现有配置或进程环境已存在；不会覆盖。请运行 lfl doctor。")
        return 0
    try:
        print("LFL 首次配置（离线）。只新建配置，绝不覆盖已有文件。")
        print("目标：" + str(target))
        print("填写结束后会显示摘要；只有最后确认 yes 才会写入。API Key 不会显示。")
        base_url = _validate_value(input("LLM_BASE_URL（HTTP(S)）：").strip(), key="LLM_BASE_URL")
        model = _validate_value(input("LLM_MODEL（可留空）：").strip(), key="LLM_MODEL", optional=True)
        key = _validate_value(getpass.getpass("LLM_API_KEY（隐藏输入）："), key="LLM_API_KEY")
        print("即将新建0600权限配置：LLM_BASE_URL=已输入，LLM_API_KEY=已隐藏，LLM_MODEL=" + ("已输入" if model else "默认"))
        if input("确认新建配置？输入 yes 写入：").strip() != "yes":
            return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已取消，未写入配置。", file=sys.stderr)
        return 1
    except ValueError:
        print("输入值不符合安全格式，未写入配置。", file=sys.stderr)
        return 1

    # Close the confirmation-to-write gap with a mechanical target recheck.
    if _unsafe_path(target, bundle, allow_default_parent=Path(os.path.realpath(root)) if report["target"]["source"] == "default" else None) or target.exists():
        print("配置目标在确认后已变化，拒绝覆盖。", file=sys.stderr)
        return 1
    created: list[Path] = []
    try:
        created = _make_parent(target, root=root, source=report["target"]["source"])
        if _unsafe_path(target, bundle) or target.exists():
            raise FileExistsError("config target changed")
        payload = _config_line("LLM_API_KEY", key) + _config_line("LLM_BASE_URL", base_url)
        if model:
            payload += _config_line("LLM_MODEL", model)
        _exclusive_create(target, payload.encode("utf-8"))
    except OSError:
        # Never delete an already-published target. Only remove our empty dirs.
        for path in reversed(created):
            with suppress(OSError):
                path.rmdir()
        print("配置写入未完成；未覆盖已有文件。", file=sys.stderr)
        return 1

    from llm_loop.runtime.doctor import human_report, inspect_first_use

    print("已创建新配置（没有联网或启动服务）。")
    result = inspect_first_use(args=args, root=root, bundle=bundle, environment=environment, check_install=check_install)
    print(human_report(result))
    print("后续可自行选择运行 lfl chat 或 lfl web，必要时先运行 lfl doctor。")
    return 0 if result["ready"] else 1


def run_first_use(*, args: Any, root: Path, bundle: Path | None, environment: Mapping[str, str],
                  check_install: Callable[[], dict[str, Any]], preview: bool, as_json: bool) -> int:
    if as_json and not preview:
        print("--json 只能和 --plan 一起使用，不能通过 JSON 绕过交互确认。", file=sys.stderr)
        return 2
    report, target = plan_first_use(args=args, root=root, bundle=bundle, environment=environment)
    if preview:
        if as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print("LFL 首次配置预览（离线只读）\n状态：" + report["status"])
            print("配置来源：" + report["target"]["source"] + "；会创建新文件：" + ("是，需确认" if report["target"]["can_create"] else "否"))
            print("下一步：" + ", ".join(report["next_steps"]))
        return 1 if report["status"] == "blocked" else 0
    assert target is not None or report["status"] == "blocked"
    if target is None:
        print("配置目标无效；请运行 lfl init --plan", file=sys.stderr)
        return 1
    return _interactive_setup(target=target, report=report, root=root, bundle=bundle,
                              args=args, environment=environment, check_install=check_install)
