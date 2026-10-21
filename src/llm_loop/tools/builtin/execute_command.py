"""基础工具 2: 执行命令（design.md 模块 D / FR-TOOL-01）.

灾难性安全校验在 ToolRegistry.execute 包裹内完成（FR-SAFE-01），
工具自身只做真实执行与如实结果构造。
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import (
    current_evidence_shadow_enabled,
    current_session_id,
    workspace_base,
)
from llm_loop.tools.builtin.job_registry import JobDurabilityError, JobLimitExceeded, JobRegistry
from llm_loop.tools.review_gate import (
    REVIEW_GATE_OBLIGATION,
    classify_review_gate_command,
    is_read_only_probe,
    review_gate_note,
)
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
            f"path={lease.path}"
        )
    return format_release_note(report, lease.path)


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
            "command": {"type": "string", "description": "要执行的 shell 命令"},
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
                ),
            },
            "escalation_token": {
                "type": "string",
                "description": (
                    "提权令牌（可选）。仅当命令被灾难性安全硬阻断、且已通过 "
                    "escalation_request 提交申请并经 web 面板人工批准（escalation_wait "
                    "返回）时使用。令牌绑定批准时的精确命令文本（改动一字即废）、"
                    "单次有效、默认 10 分钟过期。"
                ),
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        timeout_s: float | None = None,
        *,
        sandbox_mode: str = "none",
        sandbox_image: str = "python:3.13-slim",
        review_gate_recorder: Callable[[dict], str] | None = None,
    ) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)
        self._sandbox_mode = sandbox_mode
        self._sandbox_image = sandbox_image
        # EVO-20261014-7ba73d88: push/全量测试前的 review gate 闸提示记录器
        # （factory 注入，返回观测线索；None 时审查资格仍未核验）。
        self._review_gate_recorder = review_gate_recorder
        # P1-5 + Stop: 工具实例跨 session 共享，单 `_active_proc` 会被并发覆盖并
        # 导致超时/Stop 杀错进程。按 current_session_id 保存前台进程，锁保护跨线程访问。
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._active_proc_guard = threading.Lock()
        self._sandbox_note: str = ""  # P3-3: 本次执行沙箱说明（bwrap 启用时如实标注）

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

    def execute(self, **kwargs) -> ToolResult:
        command = str(kwargs.get("command", "")).strip()
        if not command:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'command'（要执行的命令）",
                tool_call_id="",
                tool_name=self.name,
            )
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
        # EVO-20261016-96abc163: 命令级 worktree 硬隔离（opt-in，默认关闭=零行为变化）。
        # 不可与 run_in_background（生命周期超出单次回执，无法确定性释放隔离树）或
        # 显式 workdir（绝对路径逃逸隔离树语义）组合——确定性拒绝，不静默忽略。
        isolation = kwargs.get("isolation", False)
        if not isinstance(isolation, bool):
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] isolation 需为 boolean",
                tool_call_id="", tool_name=self.name,
            )
        if isolation and run_bg:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] isolation=true 不支持 run_in_background=true："
                    "后台任务生命周期超出单次回执，无法确定性释放隔离树。"
                    "长隔离施工请改用 spawn_subagent(requires.fs_isolation=true)"
                ),
                tool_call_id="", tool_name=self.name,
            )
        if isolation and workdir is not None:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    "[参数错误] isolation=true 不支持显式 workdir：隔离树根即本次 cwd"
                    "（基于父工作区当前 HEAD）；需要子目录请在命令内用相对路径 cd"
                ),
                tool_call_id="", tool_name=self.name,
            )
        launch_command = "bash -e -o pipefail -c " + shlex.quote(command) if fail_fast else command
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
            try:
                wt_lease = prepare_worktree(
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
            workdir = wt_lease.path
        try:
            # C: 环境事实注入——子进程可见 LLM_EXEC_CWD（当前实际工作目录），模型可感知执行环境
            env = _scrubbed_env()
            env = _workspace_python_env(env, workdir, command)
            env["LLM_EXEC_CWD"] = workdir or os.getcwd()
            if run_bg:
                # A: 后台任务（对齐 Harness ctx.jobs）——Popen 不阻塞，登记 JobRegistry 供 job_output/job_kill
                from llm_loop.tools.sandbox import sandbox_argv

                try:
                    bg_cmd, _ = sandbox_argv(
                        launch_command,
                        str(workdir or "."),
                        mode=self._sandbox_mode,
                        image=self._sandbox_image,
                    )
                except RuntimeError as exc:
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=f"[沙箱不可用] {exc}",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                from llm_loop.core.tool_execution_journal import (
                    current_effect_mutation_authority,
                    format_effect_denial,
                )

                # EVO-20261014-459a8a1e: 确定只读探测（--help/--dry-run/status/diff/
                # log/ls 类）无 durable 副作用提交点，shell 围栏层确定性放行；
                # 其余命令仍 fail-closed，拒绝回执带分层码指认真实层。
                read_only_probe = is_read_only_probe(command)
                with current_effect_mutation_authority() as verdict:
                    # R1 effect fence: 进程 spawn 即副作用提交点。lease 权威
                    # 丢失（过期/被接管）时拒绝 spawn，fail-closed。
                    if not verdict and not read_only_probe:
                        return ToolResult(
                            status=ToolResultStatus.UNAUTHORIZED,
                            content=format_effect_denial(
                                verdict, action=f"后台命令拒绝启动: {command}"
                            ),
                            error_type=verdict.code or "E0_EFFECT_AUTHORITY",
                            tool_call_id="",
                            tool_name=self.name,
                        )
                    proc = subprocess.Popen(
                        bg_cmd if bg_cmd is not None else launch_command,
                        shell=bg_cmd is None,  # noqa: S602 — 安全校验由 CatastrophicGuard 前置
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,
                        cwd=workdir,
                        env=env,
                        start_new_session=True,  # 独立进程组：job_kill 可整树终止（防孤儿进程）
                    )
                # DSH 借鉴 021-B: owner 并发上限——超限释放已启动进程并如实拒绝
                # （current_session_id 用模块级 import：函数内重复 import 会遮蔽 198/320 行引用）
                _sid = current_session_id.get() or ""
                try:
                    job_id = JobRegistry.instance().create(
                        proc,
                        launch_command,
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
                        content=f"[{kind}] {exc}\n后台进程已释放，不返回 false-success: {command}",
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
                        f"job:{job_id} cmd:{command[:80]}",
                        "process_bg",
                        revocable=True,
                        detail="停止路径: JobRegistry.cancel_session hook (factory)",
                    )
                except Exception:  # noqa: BLE001 — 登记失败不阻断工具（观测面 fail-open）
                    pass
                bg_content = f"[后台任务已启动] job_id={job_id} status=running\n命令: {command}\n"
                if gate_line:
                    bg_content = f"{gate_line}\n{bg_content}"
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=bg_content
                            + f"shell_mode={'fail_fast' if fail_fast else 'default'}\n"
                            f"等进程终态用 wait(seconds=120, job_id={job_id})；"
                            f"用 job_output(job_id={job_id}) 查询退出码与输出。",
                    tool_call_id="",
                    tool_name=self.name,
                    # R2 P1-7: 回执文案与结构化字段同一构造点产出（活跃句柄 → 下轮投影选入）
                    capability_requirements=("job_output", "wait"),
                )
            # P3-3(2026-08-15): EXEC_SANDBOX=bwrap → bwrap argv（shell=False，独立命名空间 +
            # 只读系统目录 + 工作区可写）；显式开启而 bwrap 缺失 → fail-closed 如实失败
            from llm_loop.tools.sandbox import sandbox_argv

            sandbox_note = ""
            try:
                sandbox_cmd, sandbox_note = sandbox_argv(
                    launch_command,
                    str(workdir or "."),
                    mode=self._sandbox_mode,
                    image=self._sandbox_image,
                )
            except RuntimeError as exc:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=_wt_note_in(f"[沙箱不可用] {exc}"),
                    tool_call_id="",
                    tool_name=self.name,
                )
            from llm_loop.core.tool_execution_journal import (
                current_effect_mutation_authority,
                format_effect_denial,
            )

            # EVO-20261014-459a8a1e: 同后台路径——只读探测围栏层放行，其余 fail-closed
            # 且拒绝回执带分层码（E3/E4）指认真实层。
            read_only_probe = is_read_only_probe(command)
            with current_effect_mutation_authority() as verdict:
                # R1 effect fence: 进程 spawn 即副作用提交点（同后台路径）。
                if not verdict and not read_only_probe:
                    return ToolResult(
                        status=ToolResultStatus.UNAUTHORIZED,
                        content=_wt_note_in(format_effect_denial(
                            verdict, action=f"命令拒绝执行: {command}"
                        )),
                        error_type=verdict.code or "E0_EFFECT_AUTHORITY",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                proc = subprocess.Popen(
                    sandbox_cmd if sandbox_cmd is not None else launch_command,
                    shell=sandbox_cmd is None,  # noqa: S602 — 工具本质是执行命令，安全校验由 CatastrophicGuard 前置
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
                    content=_wt_note_in(
                        f"[执行超时] 命令超过 {self._timeout_s:.0f}s 未完成"
                        + (f"\n{gate_line}" if gate_line else "")
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
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
            _proc_key = locals().get("_proc_key")
            _proc = locals().get("proc")
            if _proc_key is not None:
                with self._active_proc_guard:
                    if self._active_procs.get(_proc_key) is _proc:
                        self._active_procs.pop(_proc_key, None)

        parts: list[str] = []
        if self._sandbox_note:
            parts.append(self._sandbox_note)  # 沙箱启用如实标注
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr] {stderr.rstrip()}")
        runtime_fact = _python_runtime_fact(command, proc.returncode, stderr, env)
        if runtime_fact:
            parts.append(runtime_fact)
        interpreter_fact = _python_interpreter_fact(command, env)
        # 仅故障/异常形态附指纹（非零退出码或 runtime_fact）——保住"成功回执首内容
        # 即纯 stdout"既有契约（test_execute_command_scrubs_env 断言纯 stdout）。
        if interpreter_fact and (proc.returncode != 0 or runtime_fact):
            parts.append(interpreter_fact)
        content = "\n".join(parts) if parts else "（命令执行成功，无输出）"

        status = ToolResultStatus.SUCCESS if proc.returncode == 0 else ToolResultStatus.FAILURE
        # 2026-08-21 摘要前置（用户洞察: 截断区保留必要信息）: 统一前置
        # [命令] + 退出码 + 输出行数——成功/失败都可见元信息，截断时首行即摘要。
        # （原实现仅失败时前置退出码，成功时直接是输出内容）
        _cmd_preview = " ".join(command.split()[:8]) if command else "?"
        _out_lines = len(content.splitlines())
        # EVO-20261014-7ba73d88: 闸提示行紧随 [命令] 摘要行（成功回执首内容契约保持纯 stdout 紧随其后）。
        _summary_line = f"[命令] {_cmd_preview} [退出码 {proc.returncode}] [输出 {_out_lines} 行]"
        content = "\n".join(
            line
            for line in (_summary_line, gate_line or None, content)
            if line is not None
        )
        # EVO-20261016-96abc163: 隔离树终态附注（干净=已删除；脏=保留路径+HEAD）
        content = _wt_note_in(content)

        raw_observation = content if current_evidence_shadow_enabled.get() else None

        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )
