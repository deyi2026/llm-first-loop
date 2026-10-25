"""基础工具 2: 执行命令（design.md 模块 D / FR-TOOL-01）.

灾难性安全校验在 ToolRegistry.execute 包裹内完成（FR-SAFE-01），
工具自身只做真实执行与如实结果构造。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import (
    current_evidence_shadow_enabled,
    current_session_id,
    workspace_base,
)
from llm_loop.tools.builtin.job_registry import JobDurabilityError, JobLimitExceeded, JobRegistry

# P2-2/P2-3（安全建议书 2026-10-25）: argv 结构化执行 + 提权令牌覆盖守卫阻断。
# 置于顶层第一方 import 块安全：safety/escalation 均为独立叶子模块，此处仅类型与工具类。
from llm_loop.tools.escalation import EscalationStore
from llm_loop.tools.review_gate import (
    REVIEW_GATE_OBLIGATION,
    classify_review_gate_command,
    is_read_only_probe,
    review_gate_note,
)
from llm_loop.tools.safety import BlockDecision, CatastrophicGuard
from llm_loop.tools.source_recovery_contract import (
    SHARED_SOURCE_RECOVERY_CONTRACT,
    SourceRecoveryKind,
    source_recovery_guidance,
)
from llm_loop.workspace.worktree_isolation import (
    WorktreeIsolationError,
    WorktreeLease,
    format_release_note,
    prepare_worktree,
    release_worktree,
)

_argv_logger = logging.getLogger(__name__)

# EVO-20260814-61a52baf: 执行环境清洗（Harness defensive-patterns #6）
# 不给不可信输出 ambient environment：密钥类环境变量一律剔除，白名单基础键强制保留，
# 其余非敏感键保留（避免破坏 git/ssh/代理等正常功能，零回归）。
_ENV_WHITELIST = frozenset(
    {
        "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "SHELL",
        "USER", "LOGNAME", "TERM", "TMPDIR", "HOSTNAME", "PWD",
        "SSH_AUTH_SOCK",  # agent socket 路径（非密钥），保留以支持 ssh/git agent
    }
)
# 密钥类模式（大小写不敏感，子串匹配）
_ENV_BLOCK_PATTERNS = (
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
    "PRIVATE_KEY", "CREDENTIAL", "ACCESS_KEY", "SESSION_KEY", "BEARER",
)
# 控制面 capability metadata（review R3 P0-1）：非密钥但 agent 无业务理由
# 可知——COG_RUNTIME_ENFORCE_FILE 暴露路径即暴露 self-promote 攻击面
# （同 Unix 用户下 ~/.config 类路径可写），从子进程环境剔除。
_ENV_CONTROL_PLANE_EXACT = frozenset({"COG_RUNTIME_ENFORCE_FILE"})

def _scrubbed_env() -> dict[str, str]:
    """构造清洗后的子进程环境：白名单强制保留 + 密钥类/控制面剔除 + 其余保留."""
    scrubbed: dict[str, str] = {}
    for k, v in os.environ.items():
        up = k.upper()
        if k in _ENV_WHITELIST:
            scrubbed[k] = v
        elif any(p in up for p in _ENV_BLOCK_PATTERNS):
            continue  # 密钥类剔除，不外泄
        elif k in _ENV_CONTROL_PLANE_EXACT:
            continue  # 控制面 capability metadata 剔除（review R3 P0-1）
        else:
            scrubbed[k] = v
    return scrubbed


def _is_lfl_source_root(path: Path) -> bool:
    """Return whether *path* is mechanically recognizable as an LFL source checkout."""
    return (path / "pyproject.toml").is_file() and (path / "src" / "llm_loop").is_dir()


def _is_bare_python_tool_command(command: str) -> bool:
    """Return whether the shell starts with a bare project-Python tool executable."""
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return False
    while parts and "=" in parts[0] and parts[0].split("=", 1)[0].isidentifier():
        parts.pop(0)
    if not parts or "/" in parts[0]:
        return False
    return parts[0] in {"python", "python3", "pip", "pip3", "pytest", "ruff", "pyright"}


def _workspace_python_env(
    env: dict[str, str], workdir: str | None, command: str
) -> dict[str, str]:
    """Pin bare Python/tool resolution to the active LFL checkout when possible.

    Linked git worktrees intentionally do not carry their own ``.venv``. In that
    case the nearest ancestor LFL checkout with ``.venv/bin/python`` supplies the
    interpreter, while ``PYTHONPATH`` stays pinned to the *current* worktree's
    ``src`` so an editable install cannot silently execute code from the main tree.

    Binding is deliberately narrow: only a bare Python/project-tool executable at
    the start of the shell command is pinned. Commands that explicitly name an
    interpreter path or first ``cd``/delegate to another shell keep the host env,
    preventing the LFL venv from leaking into a different project.
    """
    if not workdir or not _is_bare_python_tool_command(command):
        return env
    try:
        start = Path(workdir).expanduser().resolve()
    except OSError:
        return env

    project_root: Path | None = None
    for candidate in (start, *start.parents):
        if _is_lfl_source_root(candidate):
            project_root = candidate
            break
    if project_root is None:
        return env

    venv_bin: Path | None = None
    for candidate in (project_root, *project_root.parents):
        if not _is_lfl_source_root(candidate):
            continue
        python_bin = candidate / ".venv" / "bin" / "python"
        if python_bin.is_file() and os.access(python_bin, os.X_OK):
            venv_bin = python_bin.parent
            break
    if venv_bin is None:
        return env

    pinned = dict(env)
    venv_bin_s = str(venv_bin)
    path_parts = [p for p in pinned.get("PATH", "").split(os.pathsep) if p]
    pinned["PATH"] = os.pathsep.join([venv_bin_s, *(p for p in path_parts if p != venv_bin_s)])

    src_s = str(project_root / "src")
    pythonpath_parts = [p for p in pinned.get("PYTHONPATH", "").split(os.pathsep) if p]
    pinned["PYTHONPATH"] = os.pathsep.join(
        [src_s, *(p for p in pythonpath_parts if p != src_s)]
    )
    return pinned


# B 最小闭环（工具故障可追溯）：词级匹配 python/python3（覆盖 `cd X && python3 …`
# 等非裸形态——_workspace_python_env 只 pin 以 python 开头的裸命令）。
_PY_WORD_RE = re.compile(r"(?:^|[\s;&|`(])python3?(?=[\s;&|)`]|$)")


def _python_interpreter_fact(command: str, env: dict[str, str]) -> str:
    """命令词级含 python/python3 时附解释器指纹（环境漂移当轮可见）.

    探测用与真实执行一致的 PATH（清洗后 env）；which 失败如实标 absent。
    仅观测事实，不改写/不重试命令。
    """
    if not _PY_WORD_RE.search(command):
        return ""
    facts: list[str] = []
    for name in ("python3", "python"):
        try:
            resolved = shutil.which(name, path=env.get("PATH"))
        except Exception:  # noqa: BLE001 — 观测 fail-open
            resolved = None
        facts.append(f"{name}={resolved or 'absent'}")
    return "[py] " + " | ".join(facts)


def _python_runtime_fact(
    command: str, returncode: int | None, stderr: str, env: dict[str, str]
) -> str | None:
    """Return a narrow current-runtime fact for an exact missing `python` executable.

    This is observability only: never rewrite/retry the command and never infer that
    python3 is semantically the right replacement.
    """
    if returncode != 127 or "not found" not in (stderr or "").lower():
        return None
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return None
    if not parts or parts[0] != "python":
        return None
    path_env = env.get("PATH")
    if shutil.which("python", path=path_env) is not None:
        return None
    python3 = shutil.which("python3", path=path_env)
    if not python3:
        return None
    return (
        "[runtime_fact] python available=false; "
        f"python3 available=true path={python3}"
    )


# S2-6（安全建议书 2026-10-25）：worktree 是施工面隔离而非系统沙箱——
# 工具描述与回执附注统一携带此从句，防止 isolation=true 被误读为安全隔离。
_WORKTREE_NON_SYSTEM_CLAUSE = "（worktree 隔离，非系统沙箱）"


def _release_cmd_worktree_note(lease: WorktreeLease) -> str:
    """释放命令级隔离树并返回回执附注（EVO-20261016-96abc163）.

    一次性语义由调用方（execute 内 _wt_note_in + finally 兜底）保证；
    本函数只做机械 release+格式化。释放异常如实返回文字（树保守保留，
    绝不让释放失败吞掉/遮蔽命令真实结果）。
    """
    try:
        report = release_worktree(lease.parent_root, lease.path)
    except Exception as exc:  # noqa: BLE001 — 释放失败不构成命令结果改写
        return (
            f"[worktree] 释放异常（树保守保留）: {type(exc).__name__}: {exc} "
            f"path={lease.path}{_WORKTREE_NON_SYSTEM_CLAUSE}"
        )
    return format_release_note(report, lease.path) + _WORKTREE_NON_SYSTEM_CLAUSE


@dataclass(frozen=True)
class _CommandSpec:
    """execute() 参数裁决后的执行规格（纯提取重构：阶段间状态显式化，不经全局/闭包共享）."""

    command: str
    exec_argv: list[str] | None
    exec_mode: str
    run_bg: bool
    fail_fast: bool
    isolation: bool
    launch_command: str


@dataclass(frozen=True)
class _ForegroundOutcome:
    """前台 communicate 完成后的结果载体（proc 句柄与输出，供终态回执组装）."""

    proc: subprocess.Popen
    stdout: str
    stderr: str


class ExecuteCommandTool:
    name = "execute_command"
    description = (
        "在本地 shell 执行命令并返回标准输出/错误。何时用: 运行脚本、查询系统状态、安装依赖、文件操作等。"
        "何时不用: 纯读取文件应优先 read_file；仅获取网页用 web_fetch。"
        "失败对策: 非零退出码会如实返回并标注；破坏性命令（rm -rf 根目录等）会被安全边界硬阻断，请改用安全方案。"
        "状态契约: 每次调用是独立 shell 进程——cd/环境变量/命令历史不跨调用持久（用 workdir 参数或命令内 cd && 串联）；"
        "run_in_background 任务跨调用持久，启动后用 job_output 查询；需要终止时须以真实用户取消意图为依据；"
        "等后台进程终态可用 wait(seconds=120, job_id=启动回执ID)，完成即返回；"
        "验证命令可显式 fail_fast=true（bash -e -o pipefail），未处理的失败停止后续命令；"
        "默认 shell 退出码仅是最后执行命令的状态，不代表管道内全部步骤成功。"
        "命令输出默认完整返回；仅统一 ToolRegistry/Evidence 的真实输出硬上限可截断，并由统一 durable recovery 负责恢复；"
        "长任务拆多次中型调用防超时丢进度，大量中间产物落盘文件而非全靠回显。"
        + "RULE-AI-28：" + REVIEW_GATE_OBLIGATION
        + "RULE-AI-35：护栏/门槛类变更（拦截判据/阻断清单/正则/阈值）宣称'已生效'前，"
          "须构造应拦输入实测拦截；未实测的完成声明只可停在'代码已提交'。"
        + SHARED_SOURCE_RECOVERY_CONTRACT
        + source_recovery_guidance(SourceRecoveryKind.COMMAND_SNAPSHOT)
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "要执行的 shell 命令（与 argv 二选一：两者都给或都不给均为参数错误）。"
                    "command 模式经 shell（/bin/sh）解释，exec_mode=shell。"
                ),
            },
            "argv": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "结构化执行参数数组（P2-2，与 command 二选一）。不经 shell（shell=False），"
                    "分号/引号/变量/$() 等元字符原样传给目标程序；守卫仍按 shlex.join(argv) "
                    "做灾难性判定。限制：元素不可含 NUL 字节；不可为空数组；shell 内建命令"
                    "（cd/管道/重定向等）不可用；fail_fast 需 shell，仅支持 command 模式。"
                ),
            },
            "workdir": {
                "type": "string",
                "description": "工作目录（可选）。默认继承进程当前目录；建议显式指定而非用 cd（fresh shell 语义，避免状态污染）。",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "后台运行（可选，默认 false）。true 时立即返回 job_id，不阻塞等待；用 job_output 查询输出。终止能力仅在真实用户明确要求取消时提供。适合长任务（测试/安装/编译）。",
            },
            "fail_fast": {
                "type": "boolean",
                "description": "可选，默认 false。true 使用 bash -e -o pipefail，管道或未处理命令失败即返回非零；显式处理的失败仍遵循 shell 语义。",
            },
            "isolation": {
                "type": "boolean",
                "description": (
                    "可选，默认 false（EVO-20261016-96abc163）。true 时本条命令在 "
                    "<workspace>/.worktrees/ 下的独立 git worktree 中执行（cwd=隔离树根，"
                    "基于父工作区当前 HEAD，与主工作区未提交改动互不干扰）。工作区须为 "
                    "git 仓库且磁盘充足，否则带 reason_code 整条拒绝，绝不降级共享工作区"
                    "执行。命令结束后：干净树自动删除；有未提交改动/新提交的树保守保留"
                    "并在回执报告路径与 HEAD，合并回主工作区是你的显式动作。不可与 "
                    "workdir/run_in_background 同用。best-effort 施工面隔离：命令经绝对"
                    "路径/跨目录操作仍可越界，非安全沙箱，不可用于约束不可信代码"
                    "（worktree 隔离，非系统沙箱）"
                ),
            },
            "escalation_id": {
                "type": "string",
                "description": (
                    "提权请求 ID（P2-3，可选；形如 ESC-xxx）。与 escalation_token 成对使用："
                    "当命令被灾难守卫阻断时，凭 (escalation_id, escalation_token) 三重绑定"
                    "（请求 id + 令牌 + 精确命令哈希）一次性放行。command 模式下单传 "
                    "escalation_token 的既有闭环不变（registry 层裁决）。"
                ),
            },
            "escalation_token": {
                "type": "string",
                "description": (
                    "提权令牌（可选）。仅当命令被灾难性安全硬阻断、且已通过 "
                    "escalation_request 提交申请并经 web 面板人工批准（escalation_wait "
                    "返回）时使用。令牌绑定批准时的精确命令文本（改动一字即废）、"
                    "单次有效、默认 10 分钟过期。argv 模式下须与 escalation_id 成对提供，"
                    "命令哈希基准为 shlex.join(argv)。"
                ),
            },
        },
        # P2-2: command 与 argv 二选一（互斥在 execute() 内确定性裁决，
        # 两者都给/都不给均为参数错误），故不再单列 required。
        "required": [],
    }

    def __init__(
        self,
        timeout_s: float | None = None,
        *,
        sandbox_mode: str = "none",
        sandbox_image: str = "python:3.13-slim",
        review_gate_recorder: Callable[[dict], str] | None = None,
        escalation_store: EscalationStore | None = None,
        safety_audit_dir: str | Path | None = None,
    ) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）.

        P2-2/P2-3（2026-10-25）: escalation_store / safety_audit_dir 缺省 None 时
        惰性解析（与 factory/web 面板共用 data/audit 同一文件，flock 跨实例安全）；
        解析失败 → None → 提权覆盖不可用（fail-closed 保持阻断），不影响执行主路径。
        """
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)
        self._sandbox_mode = sandbox_mode
        self._sandbox_image = sandbox_image
        # EVO-20261014-7ba73d88: push/全量测试前的 review gate 闸提示记录器
        # （factory 注入，返回观测线索；None 时审查资格仍未核验）。
        self._review_gate_recorder = review_gate_recorder
        self._escalation_store = escalation_store
        self._safety_audit_dir = safety_audit_dir
        self._tool_guard: CatastrophicGuard | None = None
        # P1-5 + Stop: 工具实例跨 session 共享，单 `_active_proc` 会被并发覆盖并
        # 导致超时/Stop 杀错进程。按 current_session_id 保存前台进程，锁保护跨线程访问。
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._active_proc_guard = threading.Lock()
        self._sandbox_note: str = ""  # P3-3/S2-6: 本次执行沙箱说明（启用时如实标注，与后端一一对应）

    def _escalation(self) -> EscalationStore | None:
        """提权存储惰性解析（与 registry/web 面板共用同一 data/audit 文件）."""
        if self._escalation_store is None:
            try:
                from llm_loop.config import load_settings

                self._escalation_store = EscalationStore(
                    load_settings().audit_dir / "escalation_requests.json"
                )
            except Exception:  # noqa: BLE001 — 解析失败=覆盖通道不可用（fail-closed）
                _argv_logger.warning("提权存储解析失败，令牌覆盖将保持阻断", exc_info=True)
                return None
        return self._escalation_store

    def _guard(self) -> CatastrophicGuard:
        """工具内灾难守卫（P2-2: argv 模式注册表层不可见，须在工具层兜底判定）.

        带 audit_dir 时阻断落 safety_blocks.jsonl（与 registry 层同一审计面）；
        解析失败时降级为无审计实例——阻断判定本身不依赖审计落盘。
        """
        if self._tool_guard is None:
            audit_dir = self._safety_audit_dir
            if audit_dir is None:
                try:
                    from llm_loop.config import load_settings

                    audit_dir = load_settings().audit_dir
                except Exception:  # noqa: BLE001 — 配置不可达=无审计实例，判定照常
                    audit_dir = None
            self._tool_guard = CatastrophicGuard(audit_dir=audit_dir)
        return self._tool_guard

    @staticmethod
    def _terminate_proc(proc: subprocess.Popen) -> None:
        try:
            if proc.poll() is not None:
                return
        except Exception:  # noqa: BLE001 — 句柄异常按已结束处理（防御）
            return
        with suppress(OSError):
            # start_new_session=True → proc.pid 即进程组 id；整树 SIGKILL。
            os.killpg(proc.pid, signal.SIGKILL)
        with suppress(Exception):  # noqa: BLE001 — 组击杀失败时兜底单进程
            proc.kill()

    @staticmethod
    def _sandbox_exec_argv(
        sandbox_cmd: list[str] | None, command: str, exec_argv: list[str] | None
    ) -> tuple[list[str] | None, bool]:
        """argv 模式下把沙箱包装尾部的 ``[sh, -c, command]`` 替换为 argv 本体（P2-2）.

        现有后端（bwrap/docker/sandbox-exec）包装尾部均为
        ``["/bin/sh"|"sh"|"/bin/bash", "-c"|"-lc", command]``——机械识别后以
        argv 直替，沙箱内保持不经 shell。结构不认识 → (None, False)：调用方
        确定性拒绝，绝不静默降级回 shell 包装（那会消灭 argv 的结构化语义）。
        """
        if sandbox_cmd is None or exec_argv is None:
            return sandbox_cmd, True
        if (
            len(sandbox_cmd) >= 3
            and sandbox_cmd[-1] == command
            and sandbox_cmd[-2] in ("-c", "-lc")
        ):
            return sandbox_cmd[:-3] + list(exec_argv), True
        return None, False

    def terminate_session(self, session_id: str) -> None:
        """只终止指定会话当前 execute_command 子进程，绝不波及其他会话。"""
        key = session_id or "__default__"
        with self._active_proc_guard:
            proc = self._active_procs.get(key)
        if proc is not None:
            self._terminate_proc(proc)

    def terminate(self) -> None:
        """超时兼容钩子；有会话上下文时定向终止，无上下文仅单活跃时终止。"""
        session_id = current_session_id.get()
        if session_id:
            self.terminate_session(session_id)
            return
        with self._active_proc_guard:
            procs = list(self._active_procs.values())
        # 无 session 上下文且存在多个并发执行时宁可不杀，也不能猜测目标误杀。
        if len(procs) == 1:
            self._terminate_proc(procs[0])

    def _review_gate_line(self, command: str) -> str:
        """RULE-AI-28 前置义务与观测线索；本行不是准入资格核验。

        触发面：git push（含 force 变体）与全量 pytest。机器事实由 factory 注入的
        recorder 探测本会话工具文本并写 review_gate_probe 观测事件；
        父 agent 必须在调用前核验真正独立回执，本行不凭文本授予资格。
        """
        kind = classify_review_gate_command(command)
        if not kind:
            return ""
        label = "git push" if kind == "git_push" else "全量 pytest"
        fact = ""
        recorder = getattr(self, "_review_gate_recorder", None)
        if recorder is not None:
            try:
                fact = str(recorder(
                    {
                        "action_kind": kind,
                        "tool": "execute_command",
                        "command_preview": command[:120],
                    }
                ) or "")
            except Exception:  # noqa: BLE001 - 观测失败不构成免审
                fact = ""
        if not fact:
            fact = "unknown（未注入探测器）"
        return review_gate_note(kind, fact, action_label=label)

    def _parse_command_mode(
        self, kwargs: dict
    ) -> tuple[str, list[str] | None, str] | ToolResult:
        """command / argv 二选一裁决（P2-2）: 参数错误原样返回 FAILURE 回执."""
        command = str(kwargs.get("command", "") or "").strip()
        argv_arg = kwargs.get("argv")
        exec_argv: list[str] | None = None
        exec_mode = "shell"
        if argv_arg is not None:
            if not isinstance(argv_arg, list) or not all(
                isinstance(a, str) for a in argv_arg
            ):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] argv 需为字符串数组（list[str]，结构化执行不经 shell）",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if command:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=(
                        "[参数错误] command 与 argv 二选一：同时提供会被拒绝"
                        "（结构化执行请只给 argv，shell 执行请只给 command）"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            if not argv_arg:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] argv 不能为空数组（至少须含可执行程序名）",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if any("\x00" in a for a in argv_arg):
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content="[参数错误] argv 元素含 NUL 字节（\\x00），无法作为 exec 参数传递，已拒绝",
                    tool_call_id="",
                    tool_name=self.name,
                )
            exec_argv = list(argv_arg)
            exec_mode = "argv"
            # 守卫判定/哈希绑定/回执展示的统一文本基准（join→split 往返无损）
            command = shlex.join(exec_argv)
        elif not command:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'command'（要执行的命令；或改用 argv 结构化执行）",
                tool_call_id="",
                tool_name=self.name,
            )
        return command, exec_argv, exec_mode

    def _resolve_flags_and_workdir(
        self, kwargs: dict, command: str, exec_argv: list[str] | None
    ) -> tuple[str | None, bool, bool, bool, str] | ToolResult:
        """workdir / run_bg / fail_fast / isolation 参数裁决并构造 launch_command."""
        workdir = str(kwargs.get("workdir", "") or "").strip() or None
        if workdir is not None:
            wd = Path(workdir).expanduser()
            if not wd.is_dir():
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=f"[参数错误] workdir 不是有效目录: {workdir}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            workdir = str(wd)
        run_bg = bool(kwargs.get("run_in_background", False))
        fail_fast = kwargs.get("fail_fast", False)
        if not isinstance(fail_fast, bool):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] fail_fast 需为 boolean",
                tool_call_id="", tool_name=self.name,
            )
        # P2-2: fail_fast = bash -e -o pipefail 包装，本质是 shell 语义；
        # argv 模式不经 shell，两者组合确定性拒绝（不静默降级、不悄悄走 shell）。
        if fail_fast and exec_argv is not None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] fail_fast 需要 shell（bash -e -o pipefail），"
                    "与 argv 结构化执行互斥；请改用 command 模式或去掉 fail_fast"
                ),
                tool_call_id="", tool_name=self.name,
            )
        # EVO-20261016-96abc163: 命令级 worktree 硬隔离（opt-in，默认关闭=零行为变化）。
        # 不可与 run_in_background（生命周期超出单次回执，无法确定性释放隔离树）或
        # 显式 workdir（绝对路径逃逸隔离树语义）组合——确定性拒绝，不静默忽略。
        isolation = kwargs.get("isolation", False)
        if not isinstance(isolation, bool):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] isolation 需为 boolean",
                tool_call_id="",
                tool_name=self.name,
            )
        if isolation and run_bg:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] isolation=true 不支持 run_in_background=true："
                    "后台任务生命周期超出单次回执，无法确定性释放隔离树。"
                    "长隔离施工请改用 spawn_subagent(requires.fs_isolation=true)"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        if isolation and workdir is not None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] isolation=true 不支持显式 workdir：隔离树根即本次 cwd"
                    "（基于父工作区当前 HEAD）；需要子目录请在命令内用相对路径 cd"
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        launch_command = "bash -e -o pipefail -c " + shlex.quote(command) if fail_fast else command
        return workdir, run_bg, fail_fast, isolation, launch_command

    def _apply_execution_guards(
        self, spec: _CommandSpec, workdir: str | None, esc_id: str, esc_token: str
    ) -> tuple[str, ToolResult | None]:
        """工具层灾难守卫链（P2-2/P2-3）: 守卫判定，阻断时走提权覆盖；返回 (附注, 错误回执)."""
        # ── P2-2/P2-3（2026-10-25）: 工具层灾难守卫 + 提权令牌定向覆盖 ──
        # 判定基准文本: argv 模式 = shlex.join(argv)（结构化执行不绕过守卫）；
        # command 模式 = command 原文（注册表层已判，工具层兜底重复判定，
        #   结果与注册表同一 CatastrophicGuard 规则一致，不构成行为变化）。
        # 覆盖通道: 仅当守卫 blocked 且 (escalation_id, escalation_token) 成对提供，
        #   经 EscalationStore.consume_for_execution 三重绑定（id+令牌+命令哈希）
        #   一次性消费放行；未提供/不通过 → 保持阻断（无令牌时行为不变）。
        # command 模式单传 escalation_token（无 id）→ 跳过工具层判定：
        #   该形态是 registry 层既有闭环（注册表已消耗令牌并裁决），工具层
        #   重复裁决会二次消费/误阻断已批准执行，故工具层让位（单一裁决权）。
        guard_override_note = ""
        run_tool_guard = spec.exec_argv is not None or bool(esc_id) or not esc_token
        if run_tool_guard:
            decision = self._guard().guard(
                self.name,
                {"command": spec.command, "run_in_background": spec.run_bg},
                workdir=workdir,
            )
            if decision is not None and decision.blocked:
                note, err = self._resolve_escalation_override(
                    decision, spec, esc_id, esc_token
                )
                if err is not None:
                    return "", err
                guard_override_note = note
        return guard_override_note, None

    def _resolve_escalation_override(
        self, decision: BlockDecision, spec: _CommandSpec, esc_id: str, esc_token: str
    ) -> tuple[str, ToolResult | None]:
        """守卫已阻断时的 (escalation_id, escalation_token) 三重绑定一次性覆盖（P2-3）."""
        if not (esc_id and esc_token):
            return "", ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    f"[安全硬阻断][E6_CATASTROPHIC_HARD] 已阻止可能造成不可逆破坏的行动"
                    f"（exec_mode={spec.exec_mode}）。{decision.reason}"
                    " 如确属必要: escalation_request 提交提权申请（web 弹窗人工审批），"
                    "批准后凭一次性令牌重发。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="E6_CATASTROPHIC_HARD",
                error_detail=f"判定依据: {decision.evidence}",
            )
        store = self._escalation()
        if store is None:
            return "", ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    "[安全硬阻断][E6_CATASTROPHIC_HARD] 已阻止可能造成不可逆破坏的行动。"
                    f"{decision.reason} [提权覆盖不可用] 提权存储未装配/不可达，保持阻断。"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="E6_CATASTROPHIC_HARD",
                error_detail=f"判定依据: {decision.evidence}; escalation store unavailable",
            )
        command_sha256 = hashlib.sha256(spec.command.encode("utf-8")).hexdigest()
        rec, reject_reason = store.consume_for_execution(
            esc_id, esc_token, command_sha256
        )
        if rec is None:
            return "", ToolResult(
                status=ToolResultStatus.BLOCKED,
                content=(
                    f"[提权令牌无效] {reject_reason}。请勿重试旧令牌；"
                    "如仍必要请重新 escalation_request 提交申请。"
                    "（原阻断保持）"
                ),
                tool_call_id="",
                tool_name=self.name,
                error_type="E6_ESCALATION_TOKEN",
                error_detail=f"escalation token rejected: {reject_reason}",
            )
        guard_override_note = (
            f'guard_override="escalation:{esc_id}"'
            "（人工批准令牌已消费：单次有效、绑定精确命令哈希）"
        )
        _argv_logger.info(
            "[提权覆盖放行] exec_mode=%s argv_len=%s escalation_id=%s "
            "command_sha256=%s（令牌已消费，单次）",
            spec.exec_mode,
            len(spec.exec_argv) if spec.exec_argv is not None else "",
            esc_id,
            command_sha256,
        )
        return guard_override_note, None

    def _prepare_isolation_lease(self) -> WorktreeLease | ToolResult:
        """准备命令级 worktree 隔离租约（EVO-20261016-96abc163）；失败整条拒绝，不降级共享工作区."""
        try:
            return prepare_worktree(
                f"lfl-cmd-{uuid4().hex[:16]}",
                parent_root=workspace_base(),
            )
        except WorktreeIsolationError as exc:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[worktree 隔离准备失败] reason_code={exc.reason_code}，"
                    f"命令未执行（未降级共享工作区执行）: {exc.detail or exc}"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

    def _apply_sandbox_policy(
        self, spec: _CommandSpec, workdir: str | None, wt_note_in: Callable[[str], str]
    ) -> tuple[list[str] | None, str] | ToolResult:
        """EXEC_SANDBOX 沙箱包装 + argv 模式包装尾部替换（P3-3/P2-2，前台/后台共用）."""
        # P3-3(2026-08-15)/P2-1(2026-10-25): EXEC_SANDBOX=auto/bwrap/docker/sandbox-exec →
        # 沙箱 argv（shell=False）；显式开启而后端缺失 → fail-closed 如实失败；
        # note 文案与实际后端一一对应（S2-6，不夸大隔离范围）
        from llm_loop.tools.sandbox import sandbox_argv

        try:
            sandbox_cmd, sandbox_note = sandbox_argv(
                spec.launch_command,
                str(workdir or "."),
                mode=self._sandbox_mode,
                image=self._sandbox_image,
            )
        except RuntimeError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=wt_note_in(f"[沙箱不可用] {exc}"),
                tool_call_id="",
                tool_name=self.name,
            )
        # P2-2: 沙箱启用时 argv 模式替换包装尾部为 argv 本体（沙箱内仍不经
        # shell）；包装结构不认识 → 确定性拒绝，绝不静默降级回 shell。
        if spec.exec_argv is not None and sandbox_cmd is not None:
            sandbox_cmd, _argv_sandbox_ok = self._sandbox_exec_argv(
                sandbox_cmd, spec.command, spec.exec_argv
            )
            if not _argv_sandbox_ok:
                return ToolResult(
                    status=ToolResultStatus.FAILURE,
                    content=wt_note_in(
                        "[参数错误] argv 模式与当前沙箱后端包装结构不兼容"
                        "（拒绝降级为 shell 执行）；请改用 command 模式或调整沙箱配置"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
        return sandbox_cmd, sandbox_note

    def _register_background_job(
        self, proc: subprocess.Popen, spec: _CommandSpec, workdir: str | None
    ) -> str | ToolResult:
        """后台 job 登记: JobRegistry create + 读线程 + 副作用面登记；超限释放进程并拒绝."""
        # DSH 借鉴 021-B: owner 并发上限——超限释放已启动进程并如实拒绝
        # （current_session_id 用模块级 import：函数内重复 import 会遮蔽 198/320 行引用）
        _sid = current_session_id.get() or ""
        try:
            job_id = JobRegistry.instance().create(
                proc,
                # P2-2: argv 模式持久化标签用 join 文本（可读且与守卫/哈希基准一致）
                spec.command if spec.exec_argv is not None else spec.launch_command,
                session_id=_sid,
                workspace_root=str(workdir or ""),
                executor="execute_command",
            )
        except (JobLimitExceeded, JobDurabilityError) as exc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()  # 兜底：单进程 SIGTERM
            kind = "任务超限拒绝" if isinstance(exc, JobLimitExceeded) else "后台任务持久化失败"
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[{kind}] {exc}\n后台进程已释放，不返回 false-success: {spec.command}",
                tool_call_id="",
                tool_name=self.name,
            )
        JobRegistry.instance().start_readers(job_id)
        # Phase3 M3（G3）：后台 job 是可回收副作用，登记进副作用面
        # （停止语义=JobRegistry cancel hook 已回收；revocable=True）。
        # D6：target 只含 job_id+命令头，不含输出/正文。
        try:
            from llm_loop.core.loop.side_effects import SideEffectRegistry

            SideEffectRegistry.instance().register(
                _sid,
                "execute_command",
                f"job:{job_id} cmd:{spec.command[:80]}",
                "process_bg",
                revocable=True,
                detail="停止路径: JobRegistry.cancel_session hook (factory)",
            )
        except Exception:  # noqa: BLE001 — 登记失败不阻断工具（观测面 fail-open）
            pass
        return job_id

    def _run_background(
        self,
        spec: _CommandSpec,
        workdir: str | None,
        env: dict[str, str],
        gate_line: str,
        guard_override_note: str,
        wt_note_in: Callable[[str], str],
    ) -> ToolResult:
        """后台分支: effect fence 下 Popen 不阻塞 + JobRegistry 登记 + 启动回执组装."""
        # A: 后台任务（对齐 Harness ctx.jobs）——Popen 不阻塞，登记 JobRegistry 供 job_output/job_kill
        wrapped = self._apply_sandbox_policy(spec, workdir, wt_note_in)
        if isinstance(wrapped, ToolResult):
            return wrapped
        bg_cmd, bg_sandbox_note = wrapped
        from llm_loop.core.tool_execution_journal import (
            current_effect_mutation_authority,
            format_effect_denial,
        )

        # EVO-20261014-459a8a1e: 确定只读探测（--help/--dry-run/status/diff/
        # log/ls 类）无 durable 副作用提交点，shell 围栏层确定性放行；
        # 其余命令仍 fail-closed，拒绝回执带分层码指认真实层。
        read_only_probe = is_read_only_probe(spec.command)
        with current_effect_mutation_authority() as verdict:
            # R1 effect fence: 进程 spawn 即副作用提交点。lease 权威
            # 丢失（过期/被接管）时拒绝 spawn，fail-closed。
            if not verdict and not read_only_probe:
                return ToolResult(
                    status=ToolResultStatus.UNAUTHORIZED,
                    content=format_effect_denial(
                        verdict, action=f"后台命令拒绝启动: {spec.command}"
                    ),
                    error_type=verdict.code or "E0_EFFECT_AUTHORITY",
                    tool_call_id="",
                    tool_name=self.name,
                )
            # P2-2: argv 模式 shell=False 直执行；沙箱启用时执行替换后的包装 argv
            if bg_cmd is not None:
                _bg_target, _bg_shell = bg_cmd, False
            elif spec.exec_argv is not None:
                _bg_target, _bg_shell = spec.exec_argv, False
            else:
                _bg_target, _bg_shell = spec.launch_command, True
            proc = subprocess.Popen(
                _bg_target,
                shell=_bg_shell,  # noqa: S602 — 安全校验由 CatastrophicGuard 前置
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=workdir,
                env=env,
                start_new_session=True,  # 独立进程组：job_kill 可整树终止（防孤儿进程）
            )
        job_id = self._register_background_job(proc, spec, workdir)
        if isinstance(job_id, ToolResult):
            return job_id
        bg_content = f"[后台任务已启动] job_id={job_id} status=running\n命令: {spec.command}\n"
        if bg_sandbox_note:
            # S2-6: 后台回执同样如实标注沙箱（文案与实际后端一一对应）
            bg_content += f"{bg_sandbox_note}\n"
        if gate_line:
            bg_content = f"{gate_line}\n{bg_content}"
        if guard_override_note:
            bg_content += f"{guard_override_note}\n"
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=bg_content
                    + f"shell_mode={'fail_fast' if spec.fail_fast else 'default'}\n"
                    + (
                        f"exec_mode={spec.exec_mode} argv_len={len(spec.exec_argv)}\n"
                        if spec.exec_argv is not None
                        else f"exec_mode={spec.exec_mode}\n"
                    )
                    + f"等进程终态用 wait(seconds=120, job_id={job_id})；"
                    f"用 job_output(job_id={job_id}) 查询退出码与输出。",
            tool_call_id="",
            tool_name=self.name,
            # R2 P1-7: 回执文案与结构化字段同一构造点产出（活跃句柄 → 下轮投影选入）
            capability_requirements=("job_output", "wait"),
        )

    def _run_foreground(
        self,
        spec: _CommandSpec,
        workdir: str | None,
        env: dict[str, str],
        gate_line: str,
        wt_note_in: Callable[[str], str],
    ) -> ToolResult | _ForegroundOutcome:
        """前台分支: 沙箱包装 + effect fence + Popen + communicate 兜底超时与句柄清理."""
        wrapped = self._apply_sandbox_policy(spec, workdir, wt_note_in)
        if isinstance(wrapped, ToolResult):
            return wrapped
        sandbox_cmd, sandbox_note = wrapped
        from llm_loop.core.tool_execution_journal import (
            current_effect_mutation_authority,
            format_effect_denial,
        )

        # EVO-20261014-459a8a1e: 同后台路径——只读探测围栏层放行，其余 fail-closed
        # 且拒绝回执带分层码（E3/E4）指认真实层。
        read_only_probe = is_read_only_probe(spec.command)
        with current_effect_mutation_authority() as verdict:
            # R1 effect fence: 进程 spawn 即副作用提交点（同后台路径）。
            if not verdict and not read_only_probe:
                return ToolResult(
                    status=ToolResultStatus.UNAUTHORIZED,
                    content=wt_note_in(format_effect_denial(
                        verdict, action=f"命令拒绝执行: {spec.command}"
                    )),
                    error_type=verdict.code or "E0_EFFECT_AUTHORITY",
                    tool_call_id="",
                    tool_name=self.name,
                )
            # P2-2: argv 模式 shell=False 直执行；沙箱启用时执行替换后的包装 argv
            if sandbox_cmd is not None:
                _fg_target, _fg_shell = sandbox_cmd, False
            elif spec.exec_argv is not None:
                _fg_target, _fg_shell = spec.exec_argv, False
            else:
                _fg_target, _fg_shell = spec.launch_command, True
            proc = subprocess.Popen(
                _fg_target,
                shell=_fg_shell,  # noqa: S602 — 工具本质是执行命令，安全校验由 CatastrophicGuard 前置
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workdir,  # B: workdir 支持（fresh shell，对齐 Harness）
                env=env,  # EVO-20260814-61a52baf: 环境清洗，密钥不外泄 + LLM_EXEC_CWD 事实
                # P1-5(审计发现 #11): 独立进程组——注册表超时 terminate 可整树终止（防孤儿）。
                # 原 subprocess.run 封装无句柄可抓，且其超时只杀直接 shell、孙进程成孤儿。
                start_new_session=True,
            )
        self._sandbox_note = sandbox_note
        _proc_key = current_session_id.get() or "__default__"
        with self._active_proc_guard:
            self._active_procs[_proc_key] = proc
        try:
            stdout, stderr = proc.communicate(timeout=self._timeout_s)
        except subprocess.TimeoutExpired:
            # 工具内兜底超时（communicate 只抛异常不杀进程）→ 整树终止防孤儿
            self.terminate()
            with suppress(Exception):
                proc.wait(timeout=5)  # 收尸（SIGKILL 后立即退出；失败不阻断回执）
            return ToolResult(
                status=ToolResultStatus.TIMEOUT,
                content=wt_note_in(
                    f"[执行超时] 命令超过 {self._timeout_s:.0f}s 未完成"
                    + (f"\n{gate_line}" if gate_line else "")
                ),
                tool_call_id="",
                tool_name=self.name,
            )
        finally:
            with self._active_proc_guard:
                if self._active_procs.get(_proc_key) is proc:
                    self._active_procs.pop(_proc_key, None)
        return _ForegroundOutcome(proc=proc, stdout=stdout, stderr=stderr)

    def _compose_foreground_result(
        self,
        outcome: _ForegroundOutcome,
        spec: _CommandSpec,
        env: dict[str, str],
        gate_line: str,
        guard_override_note: str,
        wt_note_in: Callable[[str], str],
    ) -> ToolResult:
        """前台终态回执组装: 摘要前置 + stdout/stderr + python 事实 + 隔离附注."""
        parts: list[str] = []
        if self._sandbox_note:
            parts.append(self._sandbox_note)  # 沙箱启用如实标注
        if outcome.stdout:
            parts.append(outcome.stdout.rstrip())
        if outcome.stderr:
            parts.append(f"[stderr] {outcome.stderr.rstrip()}")
        runtime_fact = _python_runtime_fact(
            spec.command, outcome.proc.returncode, outcome.stderr, env
        )
        if runtime_fact:
            parts.append(runtime_fact)
        interpreter_fact = _python_interpreter_fact(spec.command, env)
        # 仅故障/异常形态附指纹（非零退出码或 runtime_fact）——保住"成功回执首内容
        # 即纯 stdout"既有契约（test_execute_command_scrubs_env 断言纯 stdout）。
        if interpreter_fact and (outcome.proc.returncode != 0 or runtime_fact):
            parts.append(interpreter_fact)
        content = "\n".join(parts) if parts else "（命令执行成功，无输出）"

        status = (
            ToolResultStatus.SUCCESS
            if outcome.proc.returncode == 0
            else ToolResultStatus.FAILURE
        )
        # 2026-08-21 摘要前置（用户洞察: 截断区保留必要信息）: 统一前置
        # [命令] + 退出码 + 输出行数——成功/失败都可见元信息，截断时首行即摘要。
        # （原实现仅失败时前置退出码，成功时直接是输出内容）
        _cmd_preview = " ".join(spec.command.split()[:8]) if spec.command else "?"
        _out_lines = len(content.splitlines())
        # P2-2: 回执如实记录执行模式（argv=结构化不经 shell / shell=经 /bin/sh）与 argv 长度。
        _exec_mode_tag = (
            f"exec_mode={spec.exec_mode} argv_len={len(spec.exec_argv)}"
            if spec.exec_argv is not None
            else f"exec_mode={spec.exec_mode}"
        )
        # EVO-20261014-7ba73d88: 闸提示行紧随 [命令] 摘要行（成功回执首内容契约保持纯 stdout 紧随其后）。
        _summary_line = (
            f"[命令] {_cmd_preview} [退出码 {outcome.proc.returncode}]"
            f" [输出 {_out_lines} 行] [{_exec_mode_tag}]"
        )
        content = "\n".join(
            line
            for line in (_summary_line, gate_line or None, guard_override_note or None, content)
            if line is not None
        )
        # EVO-20261016-96abc163: 隔离树终态附注（干净=已删除；脏=保留路径+HEAD）
        content = wt_note_in(content)

        raw_observation = content if current_evidence_shadow_enabled.get() else None

        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )

    def execute(self, **kwargs) -> ToolResult:
        # ── P2-2（2026-10-25）: command / argv 二选一的结构化执行入口 ──
        # argv 模式: shell=False 直执行（不经 /bin/sh），守卫按 shlex.join(argv)
        # 判定；command 模式: 保持既有 shell 语义（exec_mode=shell，零回归）。
        mode = self._parse_command_mode(kwargs)
        if isinstance(mode, ToolResult):
            return mode
        command, exec_argv, exec_mode = mode
        flags = self._resolve_flags_and_workdir(kwargs, command, exec_argv)
        if isinstance(flags, ToolResult):
            return flags
        workdir, run_bg, fail_fast, isolation, launch_command = flags
        spec = _CommandSpec(
            command=command,
            exec_argv=exec_argv,
            exec_mode=exec_mode,
            run_bg=run_bg,
            fail_fast=fail_fast,
            isolation=isolation,
            launch_command=launch_command,
        )
        # ── P2-2/P2-3（2026-10-25）: 工具层灾难守卫 + 提权令牌定向覆盖 ──
        # （判定基准/覆盖通道/让位语义详见 _apply_execution_guards 文档）
        esc_id = str(kwargs.get("escalation_id", "") or "").strip()
        esc_token = str(kwargs.get("escalation_token", "") or "").strip()
        guard_override_note, guard_err = self._apply_execution_guards(
            spec, workdir, esc_id, esc_token
        )
        if guard_err is not None:
            return guard_err
        # RULE-AI-28: caller-visible obligation is in the schema before invocation;
        # the returned annotation reports observations, not automatic admission.
        gate_line = self._review_gate_line(command)
        # 工作区跟随: 未显式指定 workdir 时默认当前工作区根（无工作区 → 进程 cwd，零回归）
        if workdir is None:

            workdir = workspace_base()
        # EVO-20261016-96abc163: 命令级 worktree 隔离租约（opt-in）。prepare fail-fast
        # 即整条拒绝——绝不降级共享工作区执行（无声丢隔离比失败更糟）。
        # 释放协调：try 内联终态回执（超时/拒绝/OSError）经 _wt_note_in 现场释放并入
        # 附注；正常完成路径的释放由 try/finally 确定性先行执行（内容拼装在 finally
        # 之后），附注暂存 wt_note，由 _wt_note_in 从暂存并入——两路共享同一组
        # 标志，保证 release_worktree 恰好一次、附注恰好一条。
        wt_lease: WorktreeLease | None = None
        wt_released = False
        wt_note = ""

        def _wt_note_in(content: str) -> str:
            """终态一次性释放隔离树并把 ReleaseReport 附注并入回执内容."""
            nonlocal wt_lease, wt_released, wt_note
            if wt_lease is None and not wt_note:
                return content
            if wt_lease is not None and not wt_released:
                wt_released = True
                wt_note = _release_cmd_worktree_note(wt_lease)
                wt_lease = None
            if not wt_note:
                return content
            note, wt_note = wt_note, ""
            return f"{content}\n{note}" if note else content

        if isolation:
            lease = self._prepare_isolation_lease()
            if isinstance(lease, ToolResult):
                return lease
            wt_lease = lease
            workdir = wt_lease.path
        try:
            # C: 环境事实注入——子进程可见 LLM_EXEC_CWD（当前实际工作目录），模型可感知执行环境
            env = _scrubbed_env()
            env = _workspace_python_env(env, workdir, command)
            env["LLM_EXEC_CWD"] = workdir or os.getcwd()
            # A: 后台任务（对齐 Harness ctx.jobs）——Popen 不阻塞，登记 JobRegistry 供 job_output/job_kill
            if run_bg:
                return self._run_background(
                    spec, workdir, env, gate_line, guard_override_note, _wt_note_in
                )
            fg = self._run_foreground(spec, workdir, env, gate_line, _wt_note_in)
            if isinstance(fg, ToolResult):
                return fg
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=_wt_note_in(f"[执行失败] {type(exc).__name__}: {exc}"),
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        finally:
            if wt_lease is not None and not wt_released:
                # EVO-20261016-96abc163: 正常完成/非预期异常路径的确定性释放
                # （内容拼装在 finally 之后，附注暂存 wt_note 由 _wt_note_in 并入
                # 回执；异常向上传播时至少保证树不泄漏，释放异常不遮蔽原异常）。
                wt_released = True
                try:
                    wt_note = _release_cmd_worktree_note(wt_lease)
                finally:
                    wt_lease = None

        return self._compose_foreground_result(
            fg, spec, env, gate_line, guard_override_note, _wt_note_in
        )
