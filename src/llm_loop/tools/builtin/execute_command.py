"""基础工具 2: 执行命令（design.md 模块 D / FR-TOOL-01）.

灾难性安全校验在 ToolRegistry.execute 包裹内完成（FR-SAFE-01），
工具自身只做真实执行与如实结果构造。
"""

from __future__ import annotations

import os
import signal
import subprocess
from contextlib import suppress
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.tools.builtin.job_registry import JobLimitExceeded, JobRegistry

# 方案 4: 工具输出截断（context 优化——长输出只发头尾，完整内容可经 search_archive 检索）
# EVO-20260814: 裁剪阈值可配置化（对齐 Harness toolResultPruner 思路）——
# TOOL_TRIM_MAX/HEAD/TAIL 环境变量可调，未设置用默认；非法值回退默认（零回归）。
_NOISE_WORDS = {"and", "or", "not", "the", "for", "with", "echo"}


def _trim_config() -> tuple[int, int, int]:
    """返回 (max, head, tail) 裁剪参数；环境变量非法/未设置回退默认."""
    def _get(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, "") or default)
        except ValueError:
            return default

    return (
        _get("TOOL_TRIM_MAX", 3000),
        _get("TOOL_TRIM_HEAD", 1500),
        _get("TOOL_TRIM_TAIL", 1500),
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


def _scrubbed_env() -> dict[str, str]:
    """构造清洗后的子进程环境：白名单强制保留 + 密钥类剔除 + 其余保留."""
    scrubbed: dict[str, str] = {}
    for k, v in os.environ.items():
        up = k.upper()
        if k in _ENV_WHITELIST:
            scrubbed[k] = v
        elif any(p in up for p in _ENV_BLOCK_PATTERNS):
            continue  # 密钥类剔除，不外泄
        else:
            scrubbed[k] = v
    return scrubbed


def _truncate_output(content: str, command: str = "") -> str:
    """截断长输出：保留首 N + 末 M 字符（可配），中间附截断说明与搜索关键词.

    EVO-20260817-f485acac: 超阈值完整输出落盘到显式文件（data/audit/cmd_outputs/），
    回执标注路径——AI 可 read_file 按需读全文，避免反复全量回显撑大请求前缀
    （缓存命中时前缀体量仍计费；评测/批量任务大输出是成本大头）。
    落盘失败 fail-open 不影响截断。
    """
    max_chars, keep_head, keep_tail = _trim_config()
    if len(content) <= max_chars:
        return content
    head = content[:keep_head]
    tail = content[-keep_tail:]
    # 从命令提取关键词（取可打印词，最多 3 个；排除常见 shell 噪音词）
    kw = " ".join(
        [w for w in command.split() if w.isalnum() and len(w) >= 2 and w not in _NOISE_WORDS][:3]
    )
    # 完整输出落盘（f485acac）——仅超阈值时；data/ 已 gitignore 不入库
    saved_note = ""
    try:
        import os
        import time

        out_dir = (
            Path(os.environ.get("DATA_DIR", "data")) / "audit" / "cmd_outputs"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_cmd = "".join(c if c.isalnum() or c in "-_." else "_" for c in command[:40])
        dump_path = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe_cmd[:24] or 'cmd'}.log"
        dump_path.write_text(content, encoding="utf-8")
        saved_note = f"\n完整输出已落盘: {dump_path}（可 read_file 按需读取全文，无需重跑命令）"
    except Exception:  # noqa: BLE001 — 落盘失败不阻断截断
        saved_note = ""
    return (
        f"{head}\n"
        f"[输出已截断] 事实: 完整输出 {len(content)} 字符，仅展示首 {keep_head} + 末 {keep_tail} 字符"
        f"（触发阈值: {max_chars} 字符，TOOL_TRIM_MAX/HEAD/TAIL 环境变量可调）。"
        f"\n原因: 上下文优化（方案 4 工具输出截断）。"
        f"\n建议: 如需完整内容可用 search_archive 检索{'，搜索关键词: ' + kw if kw else '（按命令相关词检索）'}。"
        f"{saved_note}\n"
        f"{tail}"
    )


class ExecuteCommandTool:
    name = "execute_command"
    description = (
        "在本地 shell 执行命令并返回标准输出/错误。何时用: 运行脚本、查询系统状态、安装依赖、文件操作等。"
        "何时不用: 纯读取文件应优先 read_file；仅获取网页用 web_fetch。"
        "失败对策: 非零退出码会如实返回并标注；破坏性命令（rm -rf 根目录等）会被安全边界硬阻断，请改用安全方案。"
        "状态契约: 每次调用是独立 shell 进程——cd/环境变量/命令历史不跨调用持久（用 workdir 参数或命令内 cd && 串联）；"
        "run_in_background 任务跨调用持久，经 job_output/job_kill 管理；"
        "输出超 3000 字符将截断为首 1500 + 末 1500（完整原文另存压缩档案可 search_archive 检索；"
        "阈值由 TOOL_TRIM_MAX/HEAD/TAIL 环境变量控制）；"
        "长任务拆多次中型调用防超时丢进度，大量中间产物落盘文件而非全靠回显。"
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
                "description": "后台运行（可选，默认 false）。true 时立即返回 job_id，不阻塞等待；用 job_output 查询输出、job_kill 终止。适合长任务（测试/安装/编译）。",
            },
        },
        "required": ["command"],
    }

    def __init__(self, timeout_s: float | None = None) -> None:
        """工具内兜底超时（M18 AA8: 读配置值，默认 30s 兜底向后兼容；注册表另有线程级超时）."""
        self._timeout_s = 30.0 if timeout_s is None else float(timeout_s)
        # P1-5(审计发现 #11): 当前前台子进程句柄（注册表线程级超时的 terminate 钩子用）。
        # 由执行线程写、注册表线程读——GIL 下简单属性赋值原子，竞态窗口仅进程刚启动的
        # 瞬间，错过则退化为工具自身超时兜底（如实标注，不静默吞掉）。
        self._active_proc: subprocess.Popen | None = None
        self._sandbox_note: str = ""  # P3-3: 本次执行沙箱说明（bwrap 启用时如实标注）

    def terminate(self) -> None:
        """注册表超时兜底钩子：终止正在执行的前台子进程（整树 SIGKILL）.

        P1-5(审计发现 #11): 注册表线程级超时先于工具内超时触发时，工作线程仍阻塞在
        communicate() 等子进程——本钩子整树击杀后 communicate 立即返回，线程可回收，
        孤儿子进程不再残留。尽力而为：击杀失败只记残留，不抛穿。
        """
        proc = self._active_proc
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return  # 已结束（无需终止）
        except Exception:  # noqa: BLE001 — 句柄异常按已结束处理（防御）
            return
        with suppress(OSError):
            # start_new_session=True → proc.pid 即进程组 id；整树 SIGKILL（超时强制
            # 终止，比 job_kill 的 SIGTERM 更果断——本钩子只在已超时后触发）
            os.killpg(proc.pid, signal.SIGKILL)
        with suppress(Exception):  # noqa: BLE001 — 组击杀失败时兜底单进程
            proc.kill()

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
                try:
                    job_id = JobRegistry.instance().create(proc, command)
                except JobLimitExceeded as exc:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        proc.terminate()  # 兜底：单进程 SIGTERM
                    return ToolResult(
                        status=ToolResultStatus.FAILURE,
                        content=f"[任务超限拒绝] {exc}\n命令未执行（进程已释放）: {command}",
                        tool_call_id="",
                        tool_name=self.name,
                    )
                JobRegistry.instance().start_readers(job_id)
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=f"[后台任务已启动] job_id={job_id} status=running\n命令: {command}\n"
                            f"用 job_output(job_id={job_id}) 查询输出，job_kill(job_id={job_id}) 终止。",
                    tool_call_id="",
                    tool_name=self.name,
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
            self._active_proc = proc
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
            self._active_proc = None

        parts: list[str] = []
        if self._sandbox_note:
            parts.append(self._sandbox_note)  # 沙箱启用如实标注
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr] {stderr.rstrip()}")
        content = "\n".join(parts) if parts else "（命令执行成功，无输出）"

        status = ToolResultStatus.SUCCESS if proc.returncode == 0 else ToolResultStatus.FAILURE
        if proc.returncode != 0:
            content = f"[命令退出码 {proc.returncode}] {content}"

        content = _truncate_output(content, command)

        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )
