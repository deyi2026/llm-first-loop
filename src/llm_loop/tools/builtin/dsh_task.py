"""基础工具: dsh_task —— 调度 DeepSeek Harness headless 执行任务（进程级子代理）.

对齐 DSH-ORCHESTRATION-PLAN-20260816（docs/local/）：llm-first-loop 作为编排者，
spawn `dsh --profile headless "<task>"`（新 Agent + 新 session，cwd=目标工作区），
回收 stdout 最终回答 + 退出码，映射工具五态。

契约（已验证 headless-runner 源码）:
- stdout = 最终 assistant 文本（聚合最后一条 assistant 消息的 text）
- 退出码: completed → 0；error/aborted → 1（stderr 带 dsh: <code>: <message>）
- 每次任务新 session（无跨任务记忆 → 任务文本自带上下文）

P1（协议 v2，2026-08-16）:
- ctx_path: 上下文文件引用（llm-first-loop 写 dsh_ctx.md → 工具读取并入任务文本）
- report_format: 汇报格式模板注入（决策摘要/关键中间结论/产物清单/未决项）
- retry: 失败（非 0 退出码）新 session 重试；timeout 不重试（防无限超时）
- 任务文本脱敏: 替换已知敏感 env 值（防 DSH session 日志留存密钥）
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus

logger = logging.getLogger(__name__)

_DSH_PROFILE = "headless"
_MAX_OUTPUT_CHARS = 30_000  # 对齐 TOOL_MAX_OUTPUT_CHARS：回答截断，超限标注
_DEFAULT_TIMEOUT_S = 300.0  # 对齐 FEISHU_MSG_PROCESS_TIMEOUT_S
_MAX_TIMEOUT_S = 3600.0  # 上限保护（防编排失控）
_CTX_MAX_CHARS = 8_000  # ctx 文件并入任务文本的上限
_MAX_RETRY = 3  # retry 上限保护

# 汇报格式模板（协议 v2 §7.1：结构化汇报，压缩 DSH 自由发挥空间）
_REPORT_FORMAT_SUFFIX = (
    "\n\n--- 汇报格式（必须遵守）---\n"
    "完成时按以下结构输出：\n"
    "## 决策摘要\n（目标理解 + 关键决策）\n"
    "## 关键中间结论\n（影响结果的中间判断/发现）\n"
    "## 产物清单\n（创建/修改的文件路径 + 状态）\n"
    "## 未决项\n（未完成/不确定项；无则写 (none)）\n"
)

# 敏感 env 名判定（值替换防泄漏进 DSH session 日志）
_SENSITIVE_ENV_RE = re.compile(r"^(.*(?:KEY|SECRET|TOKEN|PASSWORD).*)$", re.IGNORECASE)


def _dsh_env(cwd: str) -> dict[str, str]:
    """构造 DSH 子进程环境：DSH_HOME 可写性回退（2026-08-16 EPERM 复盘）.

    背景: profile-boot 启动时覆写 $DSH_HOME/profiles/headless/cordis.yml。
    长驻 agent 进程可能携带过期 DSH_HOME（如 ~/.dsh 在 macOS 沙箱/TCC 下不可写）
    → EPERM 启动失败。策略: 当前值可写则沿用；否则回退 <cwd>/data/dsh-home
    （restart_system.sh 注入的服务级 DSH_HOME，profile/session 落盘项目内）。
    """
    env = dict(os.environ)
    home = env.get("DSH_HOME", "").strip()
    if home:
        probe = Path(home) / "profiles" / _DSH_PROFILE
        try:
            probe.mkdir(parents=True, exist_ok=True)
            t = probe / ".write_probe"
            t.write_text("ok")
            t.unlink()
            return env  # 可写，沿用
        except OSError:
            pass  # 不可写 → 走回退
    fallback = Path(cwd) / "data" / "dsh-home"
    if fallback.is_dir():
        env["DSH_HOME"] = str(fallback)
        logger.info("DSH_HOME 回退到项目内: %s（原值不可写: %s）", fallback, home or "(未设)")
    return env


class DshTaskTool:
    name = "dsh_task"
    description = (
        "调度 DeepSeek Harness（DSH）headless 执行任务（进程级子代理）。何时用: 需要 DSH 完整"
        "工具链/多模型路由/大上下文长任务，或需要在其他工作区执行的任务，委派给 DSH 在隔离"
        "进程 + 新会话中真实执行。何时不用: 简单任务直接用 llm-first-loop 自身工具；任务依赖"
        "本会话大量上下文时（DSH 看不到本会话历史——用 ctx_path 传上下文文件或把要点写进任务）。"
        "注意: DSH 每次任务新会话（无跨任务记忆）；结果只回最终回答文本（截断 3 万字符，超限"
        "另存可检索）；进程冷启动有开销（长任务占比可忽略）；任务文本自动附加汇报格式要求与验收清单"
        "（可用 report_format=false 关闭汇报格式），失败可 retry（新 session 重试，无状态污染）；"
        "background=true 后台执行（返回 job_id，用 job_output/job_kill 管理，支持多任务并行 fan-out）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "任务文本（DSH agent 直接执行；可含目标/约束/期望产出；自动附加汇报格式要求）",
            },
            "ctx_path": {
                "type": "string",
                "description": "上下文文件路径（可选，协议 v2：llm-first-loop 把前情摘要/相关路径/约束写入"
                "该文件，工具读取并入任务文本——上下文通过引用传递而非复制）",
            },
            "cwd": {
                "type": "string",
                "description": "目标工作区目录（可选，默认当前工作区；DSH 以 cwd 为工作根执行）",
            },
            "timeout_s": {
                "type": "integer",
                "description": "超时秒数（可选，默认 300，上限 3600；超时整树终止并如实标注，不重试）",
            },
            "retry": {
                "type": "integer",
                "description": "失败重试次数（可选，默认 0，上限 3；仅对非 0 退出码生效，每次新 session 重跑）",
            },
            "report_format": {
                "type": "boolean",
                "description": "是否附加汇报格式模板（可选，默认 true；false 时不注入格式约束）",
            },
            "acceptance": {
                "type": "array",
                "items": {"type": "string"},
                "description": "验收清单（可选，协议 v2：DSH 完成时逐项自检输出 完成/未完成/原因，"
                "让分歧显性化，llm-first-loop 保留最终裁决权）",
            },
            "background": {
                "type": "boolean",
                "description": "后台执行（可选，默认 false）。true 时立即返回 job_id 不阻塞等待，"
                "用 job_output 查询输出、job_kill 终止——支持多 dsh_task 并行 fan-out（每任务独立进程/session）。"
                "注意: 后台模式不执行 retry/审计，退出码经 job_output 可见。",
            },
        },
        "required": ["task"],
    }

    def execute(self, **kwargs) -> ToolResult:
        task = str(kwargs.get("task", "")).strip()
        if not task:
            return self._fail(kwargs, "缺少必填参数 task（任务文本）")
        cwd = str(kwargs.get("cwd", "") or "").strip()
        if not cwd:
            from llm_loop.core.run_context import workspace_base

            cwd = workspace_base()
        timeout_s = float(kwargs.get("timeout_s") or _DEFAULT_TIMEOUT_S)
        timeout_s = max(1.0, min(timeout_s, _MAX_TIMEOUT_S))
        retry = int(kwargs.get("retry") or 0)
        retry = max(0, min(retry, _MAX_RETRY))
        report_format = bool(kwargs.get("report_format", True))
        ctx_path = str(kwargs.get("ctx_path", "") or "").strip()
        acceptance = [str(a).strip() for a in (kwargs.get("acceptance") or []) if str(a).strip()]
        background = bool(kwargs.get("background", False))

        dsh_bin = shutil.which("dsh")
        if dsh_bin is None:
            return self._fail(
                kwargs,
                "找不到 dsh 命令（DeepSeek Harness 未安装或不在 PATH）。"
                "安装/确认后可重试；示例: npm i -g @deepseek-ai/dsh 或确保 ~/.npm/_npx/*/node_modules/.bin 在 PATH。",
            )

        # 任务组装：ctx 引用并入 → 汇报格式注入 → 脱敏
        full_task = self._build_task(task, ctx_path, report_format, acceptance)

        if background:
            return self._start_background(full_task, cwd, dsh_bin)

        # 执行 + 重试（仅非 0 退出码；timeout 不重试防无限超时）
        attempts = 0
        while True:
            attempts += 1
            code, out, err, elapsed = self._run_once(full_task, cwd, timeout_s, dsh_bin)
            self._audit(full_task, cwd, code, elapsed, attempts)
            if code == 0:
                return ToolResult(
                    status=ToolResultStatus.SUCCESS,
                    content=f"[状态: success] DSH 回答（{elapsed:.1f}s）:\n{self._clip(out)}",
                    tool_call_id="",
                    tool_name=self.name,
                )
            if code == "timeout":
                return ToolResult(
                    status=ToolResultStatus.TIMEOUT,
                    content=(
                        f"[状态: timeout] DSH 任务超时（>{timeout_s:.0f}s），已整树终止（不重试）。\n"
                        f"部分输出: {self._clip(out)}"
                    ),
                    tool_call_id="",
                    tool_name=self.name,
                )
            # 非 0 退出码
            if attempts <= retry:
                logger.warning("dsh_task 失败（退出码 %s），重试 %d/%d", code, attempts, retry)
                continue
            err_info = (err or "").strip().splitlines()
            err_summary = err_info[-1] if err_info else ""
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=(
                    f"[状态: failure] DSH 任务失败（退出码 {code}，{elapsed:.1f}s"
                    f"{f'，重试 {attempts - 1} 次' if attempts > 1 else ''}）。\n"
                    f"stderr: {err_summary}\n"
                    f"回答（可能有部分）: {self._clip(out)}"
                ),
                tool_call_id="",
                tool_name=self.name,
            )

    # ── 内部 ──
    def _start_background(self, task: str, cwd: str, dsh_bin: str) -> ToolResult:
        """后台执行：spawn + JobRegistry 登记（对齐 execute_command run_in_background）."""
        from llm_loop.tools.builtin.job_registry import JobLimitExceeded, JobRegistry

        proc = subprocess.Popen(
            [dsh_bin, "--profile", _DSH_PROFILE, task],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            start_new_session=True,
        )
        # DSH 借鉴 021-B: owner 并发上限——超限释放已启动进程并如实拒绝
        try:
            job_id = JobRegistry.instance().create(proc, f"dsh --profile {_DSH_PROFILE} <task>")
        except JobLimitExceeded as exc:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()  # 兜底：单进程 SIGTERM
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[任务超限拒绝] {exc}\ndsh_task 未执行（进程已释放）",
                tool_call_id="",
                tool_name=self.name,
            )
        JobRegistry.instance().start_readers(job_id)
        return ToolResult(
            status=ToolResultStatus.SUCCESS,
            content=(
                f"[后台 dsh_task 已启动] job_id={job_id} status=running\n"
                f"任务: {task[:120]}\n"
                f"用 job_output(job_id={job_id}) 查询输出（退出码经其可见），"
                f"job_kill(job_id={job_id}) 终止。"
            ),
            tool_call_id="",
            tool_name=self.name,
        )

    def _build_task(self, task: str, ctx_path: str, report_format: bool, acceptance: list[str]) -> str:
        """任务组装（协议 v2）：ctx 引用并入 + 汇报格式注入 + 验收清单 + 敏感值脱敏."""
        if ctx_path:
            try:
                ctx_text = Path(ctx_path).read_text(encoding="utf-8")[:_CTX_MAX_CHARS]
                task = f"参考上下文（{ctx_path}）：\n{ctx_text}\n\n--- 任务 ---\n{task}"
            except OSError:
                task = f"[警告: ctx_path 读取失败（{ctx_path}），已忽略]\n{task}"
        if report_format:
            task = task + _REPORT_FORMAT_SUFFIX
        if acceptance:
            items = "\n".join(f"{i}. {a}" for i, a in enumerate(acceptance, 1))
            task = task + (
                "\n\n--- 验收清单（必须逐项自检输出：完成 / 未完成 / 原因）---\n"
                f"{items}\n"
            )
        return self._redact(task)

    @staticmethod
    def _redact(text: str) -> str:
        """任务文本脱敏：替换已知敏感 env 值（防泄漏进 DSH session 日志）."""
        out = text
        for name, val in os.environ.items():
            if val and len(val) >= 8 and _SENSITIVE_ENV_RE.match(name):
                out = out.replace(val, "***")
        return out

    def _run_once(self, task: str, cwd: str, timeout_s: float, dsh_bin: str):
        """单次执行：spawn DSH headless → 回收 stdout/stderr/退出码/耗时."""
        start = time.perf_counter()
        proc = subprocess.Popen(
            [dsh_bin, "--profile", _DSH_PROFILE, task],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=cwd,
            env=_dsh_env(cwd),
            start_new_session=True,  # 独立进程组：超时整树终止（防孤儿）
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # 进程已退出（超时竞态）时 killpg 抛 ProcessLookupError——suppress 等价容忍
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            return "timeout", out, err, time.perf_counter() - start
        return proc.returncode, out, err, time.perf_counter() - start

    def _fail(self, kwargs, detail: str) -> ToolResult:
        return ToolResult(
            status=ToolResultStatus.FAILURE,
            content=f"[参数错误/环境] {detail}",
            tool_call_id="",
            tool_name=self.name,
        )

    @staticmethod
    def _clip(text: str) -> str:
        text = text or ""
        if len(text) <= _MAX_OUTPUT_CHARS:
            return text
        return (
            text[:_MAX_OUTPUT_CHARS]
            + f"\n…[回答超 {_MAX_OUTPUT_CHARS} 字符已截断，完整内容见 DSH session 事件日志]…"
        )

    @staticmethod
    def _audit(task: str, cwd: str, outcome, elapsed: float | None, attempt: int) -> None:
        """审计落盘 data/audit/dsh_tasks.jsonl（fail-open，不阻塞主链路）."""
        try:
            p = Path("data/audit/dsh_tasks.jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "task": task[:200],
                            "cwd": cwd,
                            "outcome": str(outcome),
                            "elapsed_s": round(elapsed, 2) if elapsed is not None else None,
                            "attempt": attempt,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            logger.warning("dsh_task 审计写失败（fail-open）")
