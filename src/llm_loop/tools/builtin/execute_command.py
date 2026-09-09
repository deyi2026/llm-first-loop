"""基础工具 2: 执行命令（design.md 模块 D / FR-TOOL-01）.

灾难性安全校验在 ToolRegistry.execute 包裹内完成（FR-SAFE-01），
工具自身只做真实执行与如实结果构造。
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from contextlib import suppress
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.tools.builtin.job_registry import JobDurabilityError, JobLimitExceeded, JobRegistry
from llm_loop.tools.source_recovery_contract import (
    SHARED_SOURCE_RECOVERY_CONTRACT,
    SourceRecoveryKind,
    source_recovery_guidance,
)

# EVO-20260814-61a52baf: 执行环境清洗（Harness defensive-patterns #6）
# 不给不可信输出 ambient environment：密钥类环境变量一律剔除，白名单基础键强制保留，
# 其余非敏感键保留（避免破坏 git/ssh/代理等正常功能，零回归）。
_ENV_WHITELIST = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "SHELL",
        "USER",
        "LOGNAME",
        "TERM",
        "TMPDIR",
        "HOSTNAME",
        "PWD",
        "SSH_AUTH_SOCK",  # agent socket 路径（非密钥），保留以支持 ssh/git agent
    }
)
# 密钥类模式（大小写不敏感，子串匹配）
_ENV_BLOCK_PATTERNS = (
    "API_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "ACCESS_KEY",
    "SESSION_KEY",
    "BEARER",
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


class ExecuteCommandTool:
    name = "execute_command"
    description = (
        "在本地 shell 执行命令并返回标准输出/错误。何时用: 运行脚本、查询系统状态、安装依赖、文件操作等。"
        "何时不用: 纯读取文件应优先 read_file；仅获取网页用 web_fetch。"
        "失败对策: 非零退出码会如实返回并标注；破坏性命令（rm -rf 根目录等）会被安全边界硬阻断，请改用安全方案。"
        "状态契约: 每次调用是独立 shell 进程——cd/环境变量/命令历史不跨调用持久（用 workdir 参数或命令内 cd && 串联）；"
        "run_in_background 任务跨调用持久，启动后用 job_output 查询；需要终止时须以真实用户取消意图为依据；"
        "命令输出默认完整返回；仅统一 ToolRegistry/Evidence 的真实输出硬上限可截断，并由统一 durable recovery 负责恢复；"
        "长任务拆多次中型调用防超时丢进度，大量中间产物落盘文件而非全靠回显。"
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
        },
        "required": ["command"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)
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
        # 工作区跟随: 未显式指定 workdir 时默认当前工作区根（无工作区 → 进程 cwd，零回归）
        if workdir is None:
            from llm_loop.core.run_context import workspace_base

            workdir = workspace_base()
        try:
            # C: 环境事实注入——子进程可见 LLM_EXEC_CWD（当前实际工作目录），模型可感知执行环境
            env = _scrubbed_env()
            env["LLM_EXEC_CWD"] = workdir or os.getcwd()
            if run_bg:
                # A: 后台任务（对齐 Harness ctx.jobs）——Popen 不阻塞，登记 JobRegistry 供 job_output/job_kill
                from llm_loop.tools.sandbox import sandbox_argv

                try:
                    bg_cmd, _ = sandbox_argv(command, str(workdir or "."))
                except RuntimeError as exc:
                    return ToolResult(
                        status=ToolResultStatus.ERROR,
                        content=f"[沙箱不可用] {exc}",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                proc = subprocess.Popen(
                    bg_cmd if bg_cmd is not None else command,
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
                        command,
                        session_id=_sid,
                        workspace_root=str(workdir or ""),
                        executor="execute_command",
                    )
                except (JobLimitExceeded, JobDurabilityError) as exc:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        proc.terminate()  # 兜底：单进程 SIGTERM
                    kind = (
                        "任务超限拒绝"
                        if isinstance(exc, JobLimitExceeded)
                        else "后台任务持久化失败"
                    )
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=f"[{kind}] {exc}\n后台进程已释放，不返回 false-success: {command}",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                JobRegistry.instance().start_readers(job_id)
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=f"[后台任务已启动] job_id={job_id} status=running\n命令: {command}\n"
                    f"用 job_output(job_id={job_id}) 查询输出；如用户明确要求终止，再按取消意图处理。",
                    tool_call_id="",
                    tool_name=self.name,
                    # R2 P1-7: 回执文案与结构化字段同一构造点产出（活跃句柄 → 下轮投影选入）
                    capability_requirements=("job_output",),
                )
            # P3-3(2026-08-15): EXEC_SANDBOX=bwrap → bwrap argv（shell=False，独立命名空间 +
            # 只读系统目录 + 工作区可写）；显式开启而 bwrap 缺失 → fail-closed 如实失败
            from llm_loop.tools.sandbox import sandbox_argv

            sandbox_note = ""
            try:
                sandbox_cmd, sandbox_note = sandbox_argv(command, str(workdir or "."))
            except RuntimeError as exc:
                return ToolResult(
                    status=ToolResultStatus.ERROR,
                    content=f"[沙箱不可用] {exc}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            proc = subprocess.Popen(
                sandbox_cmd if sandbox_cmd is not None else command,
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
                    content=f"[执行超时] 命令超过 {self._timeout_s:.0f}s 未完成",
                    tool_call_id="",
                    tool_name=self.name,
                )
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[执行失败] {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
        finally:
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
        content = "\n".join(parts) if parts else "（命令执行成功，无输出）"

        status = ToolResultStatus.SUCCESS if proc.returncode == 0 else ToolResultStatus.FAILURE
        # 2026-08-21 摘要前置（用户洞察: 截断区保留必要信息）: 统一前置
        # [命令] + 退出码 + 输出行数——成功/失败都可见元信息，截断时首行即摘要。
        # （原实现仅失败时前置退出码，成功时直接是输出内容）
        _cmd_preview = " ".join(command.split()[:8]) if command else "?"
        _out_lines = len(content.splitlines())
        content = (
            f"[命令] {_cmd_preview} [退出码 {proc.returncode}] [输出 {_out_lines} 行]\n{content}"
        )
        from llm_loop.core.run_context import current_evidence_shadow_enabled

        raw_observation = content if current_evidence_shadow_enabled.get() else None

        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
            raw_observation=raw_observation,
        )
