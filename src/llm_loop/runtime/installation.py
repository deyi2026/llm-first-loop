"""Facts about the wheel installation, independent of the task workspace."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path


def bundle_root() -> Path | None:
    root = Path(__file__).resolve().parents[1] / "_bundled"
    return root if (root / "manifest.json").is_file() else None


def installed_identity(module: Path) -> dict[str, str] | None:
    """Recognize a distribution-owned package, never a relocated source checkout."""
    root = bundle_root()
    if root is None:
        return None
    try:
        dist = distribution("llm-first-loop")
        owned_module = Path(str(dist.locate_file("llm_loop/__init__.py"))).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        listed = {str(f) for f in dist.files or ()}
        if (
            module.resolve() != owned_module
            or "llm_loop/_bundled/manifest.json" not in listed
            or manifest.get("schema") != "lfl.application-bundle/v1"
            or manifest.get("version") != dist.version
        ):
            return None
        return {"name": "llm-first-loop", "version": dist.version,
                "package_root": str(owned_module.parent)}
    except (PackageNotFoundError, OSError, ValueError, AttributeError):
        return None


def rules_doc_candidates(name: str) -> tuple[Path, ...]:
    """单一真值根下的规则文档候选路径（模式确定后不跨根试探）。

    wheel 安装（bundle_root 命中）只看 ``llm_loop/_bundled/docs/``；源码检出
    只看仓库根 ``docs/``。sys.prefix、site-packages、CWD、DATA_DIR、用户 home
    永不作为回退候选——回退根上的同名文件只会掩盖 bundle 损坏（Linux 0.6.37
    wheel 旁路事故的收敛项）。
    """
    bundled = bundle_root()
    if bundled is not None:
        return (bundled / "docs" / name,)
    module = Path(__file__).resolve()
    return (module.parents[3] / "docs" / name,)   # 源码检出：<repo>/src/llm_loop/runtime/installation.py


def rules_version() -> str:
    """读 docs/ai_rules.lite.md 头部 version=N 并归一；失败/缺失返回空串.

    与规则索引同源解析（bundle_root 优先，源码检出回退仓库根），
    使 wheel 安装与源码检出在同一版本文件上得到一致结论。
    前导零归一为十进制规范形式（"020"→"20"，评审 §3.4 任务 4）：
    版本以整数值相等，消费方的严格相等比较不再受等值写法差异影响。
    """
    for path in rules_doc_candidates("ai_rules.lite.md"):
        try:
            head = path.read_text(encoding="utf-8")[:512]
        except OSError:
            continue
        match = re.search(r"version\s*=\s*(\d+)", head)
        if match:
            return str(int(match.group(1)))
    return ""


def rule_asset_facts() -> dict[str, object]:
    """规则资产诊断事实（doctor 与自检共用的单一事实函数；评审 §4.2/§3.4 任务 3）。

    ``rule_body_retrievable`` 按程序真实检索路径判断：与 RuleIndex 同根
    （wheel 命中 bundle 根，源码取仓库根），不凭 Agent 能否直接读文件推断。
    DOCS_DIR 覆盖只影响 briefing 文档列表、不影响规则索引，故 source_kind
    只有 wheel/source。error_code：asset_missing / asset_unreadable /
    version_parse_error / asset_hash_mismatch；rule_lookup_failed 由 doctor
    层真实 RuleIndex 探测补充（本函数保持纯事实、不 import introspection）。
    wheel 模式 rule_body_sha256 恒为 bundle 实体计算哈希；manifest 声明值
    独立披露为 rule_body_sha256_manifest（P2-2 安全审查 2026-10-29：声明值
    覆盖计算值会掩盖内容篡改，不一致 → asset_hash_mismatch）。
    """
    facts: dict[str, object] = {
        "source_kind": "",
        "rule_body_ref": "",
        "rule_body_retrievable": False,
        "rules_version": "",
        "rule_body_sha256": "",
        "error_code": None,
    }
    bundled = bundle_root()
    if bundled is not None:
        docs_dir = bundled / "docs"
        facts["source_kind"], facts["rule_body_ref"] = "wheel", "wheel:docs/ai_rules.md"
    else:
        module = Path(__file__).resolve()
        docs_dir = module.parents[3] / "docs"
        facts["source_kind"], facts["rule_body_ref"] = "source", "source:docs/ai_rules.md"
    body, lite = docs_dir / "ai_rules.md", docs_dir / "ai_rules.lite.md"
    if not body.is_file():
        facts["error_code"] = "asset_missing"
        return facts
    try:
        data = body.read_bytes()
    except OSError:
        facts["error_code"] = "asset_unreadable"
        return facts
    facts["rule_body_retrievable"] = True
    facts["rule_body_sha256"] = hashlib.sha256(data).hexdigest()
    if bundled is not None:
        trusted = _manifest_rule_body_sha256(bundled / "manifest.json")
        if trusted:
            # P2-2（安全审查 2026-10-29）：计算值恒为唯一 rule_body_sha256——
            # 声明值不再覆盖计算值（覆盖会掩盖 bundle 内容篡改）；声明值独立
            # 披露，不一致 → asset_hash_mismatch（doctor 判 fail、深探测跳过）。
            facts["rule_body_sha256_manifest"] = trusted
            if trusted != facts["rule_body_sha256"]:
                facts["error_code"] = "asset_hash_mismatch"
    version = rules_version()
    facts["rules_version"] = version
    if not version and facts["error_code"] is None:
        facts["error_code"] = "asset_missing" if not lite.is_file() else "version_parse_error"
    return facts


def _manifest_rule_body_sha256(manifest_path: Path) -> str:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    files = payload.get("files") if isinstance(payload, dict) else None
    return str(files.get("docs/ai_rules.md") or "") if isinstance(files, dict) else ""


# lite 自 0.6.38 起才保证随包并列入 bundle manifest；0.6.37 存在 pre-fix 与
# 修复版两种同号 wheel，同号区分只能靠 manifest 是否显式列出 lite 条目，
# 版本阈值只对更高发布号生效（Linux 0.6.37 wheel 事故评审 §3.4 任务 2）。
LITE_RULES_MIN_VERSION = "0.6.38"


def version_at_least(raw: str, floor: str) -> bool:
    """点分数字版本比较；任一段非数字按 False 处理（宁降级告警，不砖化升级路径）。"""
    def parse(value: str) -> tuple[int, ...] | None:
        parts = value.strip().split(".")
        if not value.strip() or not all(part.isdigit() for part in parts):
            return None
        return tuple(int(part) for part in parts)

    left, right = parse(raw), parse(floor)
    return left is not None and right is not None and left >= right


# ── Linux systemd user units 与 lfl-service 启动器 ─────────────────────────
# DESIGN-20261107 §4.1/§4.2（v0.2）：三服务统一 systemd --user 管理；ExecStart
# 指向稳定启动器而非版本目录；版本唯一真值是 .LFL-active-version。本段只提供
# 生成/校验/安装的机械事实，不读取运行期服务状态。

MANAGED_UNIT_SERVICES: tuple[str, ...] = ("web", "feishu", "learning")
_MANAGED_UNIT_NAMES: dict[str, str] = {
    "web": "lfl.service",
    "feishu": "lfl-feishu.service",
    "learning": "lfl-learning.service",
}
_UNIT_DESCRIPTIONS: dict[str, str] = {
    "web": "LFL Web service",
    "feishu": "LFL Feishu service",
    "learning": "LFL Learning service",
    "recovery": "LFL boot recovery gate",
}
_RECOVERY_UNIT_NAME = "lfl-recovery.service"
_MANAGED_UNIT_FILES: tuple[str, ...] = (
    "lfl.service",
    "lfl-feishu.service",
    "lfl-learning.service",
    _RECOVERY_UNIT_NAME,
)
_UNIT_INSTALL_SCHEMA = "lfl.service-units-install/v1"
# §4.1：自定义安装根不得落在系统目录的裸路径上。
_SYSTEM_BARE_ROOTS = frozenset({"/", "/usr", "/etc", "/var", "/home"})
_DEFAULT_ROOT_SUFFIX = ".local/share/lfl"


class UnitInstallError(RuntimeError):
    """systemd unit 安装失败（verify 失败或写入失败）；fail-closed，绝不 enable。"""


def validate_install_root_for_units(lfl_home: str | Path) -> None:
    """§4.1 安装根形态校验：绝对路径、无 ``..``、无空白/控制字符、非系统裸路径。

    symlink 检查覆盖**任一父组件**（不只最后一段）：路径中任何一个组件是
    symlink 都拒绝，防止安装根经中间链接逃逸。不满足即拒绝，不"自动修正"。
    """
    path = Path(str(lfl_home))
    text = str(path)
    if not path.is_absolute():
        raise ValueError(f"install root must be an absolute path: {text!r}")
    if ".." in path.parts:
        raise ValueError(f"install root must not contain '..': {text!r}")
    for ch in text:
        if ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValueError(
                f"install root must not contain whitespace or control characters: {text!r}"
            )
    if text in _SYSTEM_BARE_ROOTS:
        raise ValueError(f"install root must not be a bare system directory: {text!r}")
    # 任一已存在的父组件为 symlink 即拒绝（父会话自检 ③）。
    import os as _os

    probe = Path(_os.sep)
    for part in path.parts[1:]:
        probe = probe / part
        if _os.path.lexists(str(probe)) and probe.is_symlink():
            raise ValueError(
                f"install root path crosses a symlink component: {probe}"
            )


def _unit_path_base(lfl_home: Path, home: Path) -> str:
    """默认根展开为 ``%h`` 宏；自定义根写绝对路径（三处共用同一 base）。"""
    root_text = str(Path(str(lfl_home)))
    default_text = str(Path(str(home)).expanduser() / _DEFAULT_ROOT_SUFFIX)
    if root_text == default_text:
        return "%h/" + _DEFAULT_ROOT_SUFFIX
    return root_text


def render_unit_text(service: str, lfl_home: str | Path, *, home: str | Path) -> str:
    """渲染一个受管服务的 systemd --user unit 文本（§4.1 模板）。

    业务单元以 ``Wants=`` + ``After=`` 引用 lfl-recovery.service，形成
    §4.4 的单一串行恢复门；launcher 侧再以 recovery-ok 标记做 fail-closed
    前置判定（双通道，任一不满足即不启动）。
    """
    if service not in _MANAGED_UNIT_NAMES:
        raise ValueError(f"unsupported managed service: {service!r}")
    root = Path(str(lfl_home))
    validate_install_root_for_units(root)
    base = _unit_path_base(root, Path(str(home)))
    lines = [
        "[Unit]",
        f"Description={_UNIT_DESCRIPTIONS[service]}",
        f"Wants={_RECOVERY_UNIT_NAME}",
        f"After={_RECOVERY_UNIT_NAME}",
        "StartLimitIntervalSec=60",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=simple",
        f"WorkingDirectory={base}",
        f"Environment=LFL_HOME={base}",
        f"Environment=DATA_DIR={base}/data",
        f"Environment=LFL_DATA_DIR={base}/data",
        f"Environment=LFL_ENV_FILE={base}/.env",
        "Environment=PYTHONUNBUFFERED=1",
        f"ExecStart={base}/bin/lfl-service {service}",
        "Restart=always",
        "RestartSec=5s",
        "KillMode=control-group",
        "KillSignal=SIGTERM",
        "TimeoutStopSec=45s",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    return "\n".join(lines) + "\n"


def render_recovery_unit_text(service: str, lfl_home: str | Path, *, home: str | Path) -> str:
    """渲染 §4.4 的单一恢复门 lfl-recovery.service（oneshot、fail-closed）。

    ``Before=`` 三个业务单元 + 业务单元的 ``Wants=/After=`` 形成单点串行；
    ``Restart=no`` + oneshot 保证 recovery 失败后不自动重试；超时由
    ``TimeoutStartSec`` 处理且按 fail-closed 对待。
    """
    if service != "recovery":
        raise ValueError(f"recovery unit renderer only accepts 'recovery', got {service!r}")
    root = Path(str(lfl_home))
    validate_install_root_for_units(root)
    base = _unit_path_base(root, Path(str(home)))
    lines = [
        "[Unit]",
        f"Description={_UNIT_DESCRIPTIONS['recovery']}",
        f"Before={' '.join(n for n in _MANAGED_UNIT_NAMES.values())}",
        "",
        "[Service]",
        "Type=oneshot",
        "RemainAfterExit=yes",
        "Restart=no",
        "TimeoutStartSec=120",
        f"ExecStart={base}/bin/lfl-recovery",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    return "\n".join(lines) + "\n"


def render_lfl_service_launcher(lfl_home: str | Path) -> str:
    """渲染稳定启动器 ``LFL_HOME/bin/lfl-service``（§4.2/§4.4）。

    门（全部通过才 exec）：
    1. 安装根与活动指针真实且无 symlink 逃逸（``pwd -P`` 归一后仍等于自身）；
       版本格式严格校验；``releases/``、``releases/LFL-*`` 不接受 symlink。
    2. ``state/recovery-ok`` 标记存在（§4.4 fail-closed：recovery 未放行即以
       ``recovery_incomplete`` 拒绝启动，不猜测）。
    3. 目标 release 无 ``.installer-incomplete``；wheel 清单唯一（恰好一行）
       且文件名即当前 release 的 wheel 名；``sha256sum --check`` 通过。
    4. 显式 ``DATA_DIR`` 与 ``LFL_DATA_DIR`` 同设且不等即拒绝（§2.4，不被
       unit 环境悄悄覆盖）。
    exec 保留 systemd MainPID/cgroup 语义。
    """
    root = Path(str(lfl_home))
    validate_install_root_for_units(root)
    quoted = shlex.quote(str(root))
    return f"""#!/bin/sh
# LFL_LINUX_SERVICE_LAUNCHER_V1
# LFL_LINUX_INSTALL_ROOT: {root}
# Generated by llm_loop.runtime.installation (DESIGN-20261107 §4.2/§4.4).
# 版本唯一真值：.LFL-active-version。禁止引入第二个 current symlink。
set -eu
INSTALL_ROOT={quoted}
ACTIVE_FILE="$INSTALL_ROOT/.LFL-active-version"
RECOVERY_OK="$INSTALL_ROOT/state/recovery-ok"
SERVICE="${{1:-}}"
case "$SERVICE" in
  web|feishu|learning) ;;
  *) echo "usage: lfl-service web|feishu|learning" >&2; exit 64 ;;
esac
if [ -n "${{DATA_DIR:-}}" ] && [ -n "${{LFL_DATA_DIR:-}}" ] && [ "$DATA_DIR" != "$LFL_DATA_DIR" ]; then
  echo "DATA_DIR and LFL_DATA_DIR are both set but differ; refusing to start." >&2
  exit 1
fi
if [ ! -d "$INSTALL_ROOT" ]; then
  echo "LFL_HOME is missing: $INSTALL_ROOT" >&2; exit 1
fi
case "$(cd "$INSTALL_ROOT" && pwd -P)" in
  "$INSTALL_ROOT") : ;;
  *) echo "LFL_HOME resolves outside itself (symlink escape)." >&2; exit 1 ;;
esac
if [ ! -f "$ACTIVE_FILE" ] || [ -L "$ACTIVE_FILE" ]; then
  echo "LFL active-version pointer is missing or a symlink; refusing to guess." >&2
  exit 1
fi
IFS= read -r VERSION < "$ACTIVE_FILE" || true
# 审查 P2-6：版本必须是恰好三段数字（与安装器/指针写入器同构的严格校验）。
_vIFS=$IFS
IFS=.
set -- $VERSION
IFS=$_vIFS
if [ $# -ne 3 ]; then
  echo "LFL active-version pointer is invalid: '$VERSION'" >&2; exit 1
fi
for _seg in "$1" "$2" "$3"; do
  case "$_seg" in
    ''|*[!0-9]*) echo "LFL active-version pointer is invalid: '$VERSION'" >&2; exit 1 ;;
  esac
done
VERSION="$1.$2.$3"
if [ ! -f "$RECOVERY_OK" ] || [ -L "$RECOVERY_OK" ]; then
  echo "recovery_incomplete: $RECOVERY_OK missing; run lfl-recovery.service first." >&2
  exit 1
fi
APP="$INSTALL_ROOT/releases/LFL-$VERSION"
if [ ! -d "$APP" ] || [ -L "$APP" ] || [ -L "$INSTALL_ROOT/releases" ]; then
  echo "LFL release $VERSION directory is missing or unsafe." >&2; exit 1
fi
case "$(cd "$APP" && pwd -P)" in
  "$APP") : ;;
  *) echo "LFL release path resolves outside itself (symlink escape)." >&2; exit 1 ;;
esac
if [ -e "$APP/.installer-incomplete" ]; then
  echo "LFL release $VERSION is marked incomplete; refusing to start it." >&2
  exit 1
fi
CHECKSUM="$APP/.installer-wheel.sha256"
WHEEL_NAME="llm_first_loop-$VERSION-py3-none-any.whl"
if [ ! -f "$CHECKSUM" ] || [ -L "$CHECKSUM" ]; then
  echo "LFL release $VERSION lacks its wheel integrity record." >&2
  exit 1
fi
if [ "$(wc -l < "$CHECKSUM")" != "1" ] || [ "$(wc -c < "$CHECKSUM")" -eq 0 ]; then
  echo "LFL release $VERSION wheel manifest must list exactly one file." >&2
  exit 1
fi
case "$(cat "$CHECKSUM")" in
  *"  $WHEEL_NAME") : ;;
  *) echo "LFL release $VERSION wheel manifest names an unexpected file." >&2
     exit 1 ;;
esac
case "$WHEEL_NAME" in
  *../*|*/..*|*/*../*) echo "unsafe wheel name in manifest." >&2; exit 1 ;;
esac
(cd "$APP" && sha256sum --check --status .installer-wheel.sha256) || {{
  echo "LFL release $VERSION wheel checksum failed." >&2; exit 1
}}
echo "lfl-service: release=$VERSION service=$SERVICE root=$INSTALL_ROOT" >&2
case "$SERVICE" in
  web)      exec "$APP/venv/bin/lfl" start ;;
  feishu)   exec "$APP/venv/bin/python" -m llm_loop.runtime.launch feishu ;;
  learning) exec "$APP/venv/bin/python" -m llm_loop.runtime.launch learning ;;
esac
"""


def render_lfl_recovery_launcher(lfl_home: str | Path) -> str:
    """渲染 ``LFL_HOME/bin/lfl-recovery``（§4.4 单一恢复协调器，最小实现）。

    判定（fail-closed）：
    - ``state/recovery-ok`` 已存在且非 symlink → 幂等放行。
    - 无 ``upgrade-transactions/`` 或其中无未完成 journal → 写 recovery-ok
      （``journal_id=none decision=no_pending_transaction``）放行。
    - 存在未 settled 的 upgrade journal → 维护状态退出非零（真实恢复推进
      由升级事务模块负责，本启动器不猜测、不自动重试）。
    """
    root = Path(str(lfl_home))
    validate_install_root_for_units(root)
    quoted = shlex.quote(str(root))
    return f"""#!/bin/sh
# LFL_LINUX_RECOVERY_LAUNCHER_V1
# LFL_LINUX_INSTALL_ROOT: {root}
# Generated by llm_loop.runtime.installation (DESIGN-20261107 §4.4).
set -eu
INSTALL_ROOT={quoted}
STATE_DIR="$INSTALL_ROOT/state"
RECOVERY_OK="$STATE_DIR/recovery-ok"
TX_DIR="$INSTALL_ROOT/upgrade-transactions"
mkdir -p -- "$STATE_DIR"
if [ -f "$RECOVERY_OK" ] && [ ! -L "$RECOVERY_OK" ]; then
  echo "lfl-recovery: recovery-ok present; allowing services." >&2
  exit 0
fi
if [ ! -d "$TX_DIR" ] || [ -L "$TX_DIR" ]; then
  printf 'journal_id=none\\ndecision=no_pending_transaction\\nts=%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RECOVERY_OK"
  echo "lfl-recovery: no pending upgrade journal; services allowed." >&2
  exit 0
fi
for journal in "$TX_DIR"/*/journal.json; do
  [ -f "$journal" ] || continue
  # P1-3（审查 b7691f4e）：精确提取 JSON 顶层 state 值，只接受
  # upgrade_stage.TX_TERMINAL_STATES 的三个真实终态；禁止对整行做子串匹配
  # （"settled" 是 handover.phase 值而非终态；state=observed+handover.phase=settled
  # 的可达状态必须 fail-closed）。解析失败同样拒绝。
  state_value="$(python3 -c 'import json,sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    print("unreadable_journal")
    raise SystemExit(0)
value = data.get("state") if isinstance(data, dict) else None
print(value if isinstance(value, str) and value else "unreadable_journal")' "$journal" 2>/dev/null || printf 'unreadable_journal')"
  case "$state_value" in
    committed|aborted_before_cutover|rolled_back) : ;;
    *)
      echo "recovery_incomplete: journal $journal state=$state_value; manual recovery required." >&2
      exit 1
      ;;
  esac
done
printf 'journal_id=none\\ndecision=no_pending_transaction\\nts=%s\\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$RECOVERY_OK"
echo "lfl-recovery: all journals settled; services allowed." >&2
exit 0
"""


def install_service_units(
    lfl_home: str | Path,
    *,
    unit_dir: str | Path | None = None,
    home: str | Path | None = None,
    runner=None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """安装三服务 unit 与 lfl-service 启动器，返回安装回执。

    顺序（§4.1）：写入 unit 文本 → ``systemd-analyze --user verify`` 全部通过
    → ``daemon-reload`` → 内容变化的单元 ``try-restart`` → 逐单元
    ``enable --now``。verify 失败即恢复原 unit 内容并抛
    :class:`UnitInstallError`（fail-closed：不 reload、不 enable）。
    """
    import subprocess as _sp

    if runner is None:
        runner = _sp.run
    root = Path(str(lfl_home))
    validate_install_root_for_units(root)
    # §2.4：显式 DATA_DIR 与 LFL_DATA_DIR 冲突 → fail-closed。env 只接受调用方
    # 显式注入的映射（one-way ratchet：本模块不直取进程环境）；缺省 None 表示
    # 不检查——真实服务进程层的冲突由 lfl-service launcher 的运行时门守护
    # （launcher 读的是 systemd 注入的服务环境，才是 §2.4 的判定层）。
    if env is not None:
        explicit_data = str(env.get("DATA_DIR", "") or "").strip()
        explicit_lfl_data = str(env.get("LFL_DATA_DIR", "") or "").strip()
        if explicit_data and explicit_lfl_data and explicit_data != explicit_lfl_data:
            raise UnitInstallError(
                "DATA_DIR and LFL_DATA_DIR are both set but differ; "
                "refusing to install units that would silently override them"
            )
    if home is None:
        import os as _os_home

        home = _os_home.path.expanduser("~")
    home_path = Path(str(home))
    if unit_dir is None:
        unit_dir = home_path / ".config" / "systemd" / "user"
    unit_path = Path(str(unit_dir))
    unit_path.mkdir(parents=True, exist_ok=True)

    failures: list[dict[str, str]] = []

    def _run_checked(argv: list[str]) -> tuple[bool, str]:
        """父会话自检 ②：每个调用都检查返回码并设超时；异常等同失败。"""
        try:
            result = runner(argv, capture_output=True, text=True, timeout=30)
        except _sp.TimeoutExpired:
            return False, f"timeout after 30s: {' '.join(argv)}"
        except OSError as exc:
            return False, f"failed to execute {argv[0]}: {exc}"
        if getattr(result, "returncode", 1) != 0:
            detail = (
                getattr(result, "stderr", "") or getattr(result, "stdout", "") or ""
            ).strip()
            return False, detail
        return True, ""

    # ① launcher 先原子安装并回读校验，units 之后才 verify/enable：
    # enable --now 触发时 ExecStart 必须已可执行。
    launcher_dir = root / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    launchers: dict[str, Path] = {}
    for launcher_name, renderer in (
        ("lfl-service", render_lfl_service_launcher),
        ("lfl-recovery", render_lfl_recovery_launcher),
    ):
        target = launcher_dir / launcher_name
        from .service_control import atomic_write_text_file

        atomic_write_text_file(target, renderer(root), mode=0o755)
        if not target.is_file() or not (target.stat().st_mode & 0o111):
            raise UnitInstallError(
                f"launcher {target} was not installed executable; aborting before units"
            )
        launchers[launcher_name] = target

    original: dict[str, tuple[bytes | None, int | None]] = {}
    changed: dict[str, bool] = {}
    digests: dict[str, str] = {}
    import hashlib as _hl

    unit_texts: dict[str, str] = {}
    for svc, name in _MANAGED_UNIT_NAMES.items():
        unit_texts[name] = render_unit_text(svc, root, home=home_path)
    unit_texts[_RECOVERY_UNIT_NAME] = render_recovery_unit_text(
        "recovery", root, home=home_path
    )

    def _restore_units() -> None:
        """恢复写入前的 unit 磁盘状态（内容+mode），不留半状态。"""
        from .service_control import atomic_write_bytes_file

        for restore_name, (payload, mode) in original.items():
            target = unit_path / restore_name
            if payload is None:
                target.unlink(missing_ok=True)
            else:
                atomic_write_bytes_file(target, payload, mode=mode)

    for name, text in unit_texts.items():
        target = unit_path / name
        digests[name] = _hl.sha256(text.encode("utf-8")).hexdigest()
        try:
            prev = target.read_bytes()
            prev_mode = target.stat().st_mode & 0o777
        except OSError:
            prev, prev_mode = None, None
        original[name] = (prev, prev_mode)
        changed[name] = prev != text.encode("utf-8")
        # 写盘委托 service_control 的已登记原子写助手（durability surface：
        # service_control_state），本模块不散落未登记写原语；③ 保留原 mode。
        from .service_control import atomic_write_bytes_file

        atomic_write_bytes_file(
            target, text.encode("utf-8"), mode=prev_mode
        )

    for name in unit_texts:
        ok, detail = _run_checked(
            ["systemd-analyze", "--user", "verify", str(unit_path / name)]
        )
        if not ok:
            _restore_units()
            raise UnitInstallError(
                f"systemd-analyze verify failed for {name}: {detail}"
            )

    ok, detail = _run_checked(["systemctl", "--user", "daemon-reload"])
    if not ok:
        _restore_units()
        raise UnitInstallError(f"systemctl --user daemon-reload failed: {detail}")

    for name in unit_texts:
        if changed[name] and original[name][0] is not None:
            ok, detail = _run_checked(["systemctl", "--user", "try-restart", name])
            if not ok:
                failures.append(
                    {"step": "try-restart", "unit": name, "detail": detail}
                )

    # recovery 门先启用（业务单元 Wants= 它；启动顺序由 Before/After 保证）。
    enable_order = [_RECOVERY_UNIT_NAME, *_MANAGED_UNIT_NAMES.values()]
    enabled: list[str] = []
    for name in enable_order:
        ok, detail = _run_checked(["systemctl", "--user", "enable", "--now", name])
        if ok:
            enabled.append(name)
        else:
            failures.append({"step": "enable", "unit": name, "detail": detail})

    return {
        "schema": _UNIT_INSTALL_SCHEMA,
        "status": "installed" if not failures else "partial_failed",
        "lfl_home": str(root),
        "launcher": str(launchers["lfl-service"]),
        "recovery_launcher": str(launchers["lfl-recovery"]),
        "enabled": enabled,
        "failures": failures,
        "units": {
            name: {
                "path": str(unit_path / name),
                "sha256": digests[name],
                "changed": changed[name],
            }
            for name in unit_texts
        },
    }


def _install_units_main(argv: list[str] | None = None) -> int:
    import argparse
    import json as _json
    import os as _os
    import sys as _sys

    parser = argparse.ArgumentParser(
        prog="python -m llm_loop.runtime.installation"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_install = sub.add_parser("install-units", help="install managed systemd user units")
    p_install.add_argument("--lfl-home", default=None)
    p_install.add_argument("--home", default=None)
    args = parser.parse_args(argv)

    lfl_home = Path(args.lfl_home or "")
    if not str(lfl_home).strip():
        # one-way ratchet：不直取进程环境；安装器 shell 已显式传 --lfl-home。
        parser.error("install-units requires --lfl-home")
    home = Path(args.home) if args.home else Path(_os.path.expanduser("~"))
    receipt = install_service_units(lfl_home, home=home)
    print(_json.dumps(receipt, ensure_ascii=False, indent=2))
    # 审查 P2-1：enable/try-restart 部分失败（partial_failed）必须以非零退出，
    # 安装器（install_linux.sh）的 `|| die` 才能感知并停在可诊断状态。
    if receipt.get("status") != "installed":
        print(
            "install-units: some units failed to enable; see failures[] in the "
            "receipt above and recover manually (unit files are kept).",
            file=_sys.stderr,
        )
        return 1
    return 0


# ── scripts/systemd 参考样本再生成入口（worktree 内开发用）──
# 用法: .venv/bin/python -m llm_loop.runtime.installation regen-samples --out scripts/systemd
# （见 tests/unit/test_install_upgrade_recovery.py 一致性测试；样本非安装真值）


def _regen_samples_main(argv: list[str] | None = None) -> int:
    out_dir = Path("scripts/systemd" if argv is None else argv[argv.index("--out") + 1] if "--out" in argv else "scripts/systemd")
    out_dir.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    root = home / ".local/share/lfl"
    # launcher 绑定具体安装根，无可移植静态形态——样本只含 %h 形式的 unit 文本；
    # lfl-service / lfl-recovery 由安装器经 render_*_launcher 动态生成。
    from .service_control import atomic_write_text_file

    for svc, name in _MANAGED_UNIT_NAMES.items():
        atomic_write_text_file(out_dir / name, render_unit_text(svc, root, home=home))
    atomic_write_text_file(
        out_dir / _RECOVERY_UNIT_NAME,
        render_recovery_unit_text("recovery", root, home=home),
    )
    print(f"reference samples regenerated under {out_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin shell entry
    import sys as _sys

    if len(_sys.argv) > 1 and _sys.argv[1] == "regen-samples":
        raise SystemExit(_regen_samples_main(_sys.argv[1:]))
    raise SystemExit(_install_units_main())
