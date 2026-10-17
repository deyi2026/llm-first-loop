"""知识打分自动闭环执行器。

职责边界（程序只做调度与事实记录，不替模型打分）：
- 周期扫描 use ledger 中尚未成功打分的 slot，后台调用既有 CLI 补齐；
- 与 CLI 共用 ``data/knowledge_scores/.run.lock``，定时触发与结算后触发不会重复打分；
- 用 ``runner_state.json`` 暴露最近运行、待补分数量、连续失败与退避时间；
- 打分服务不可用/单卡超时时快速失败并指数退避，不阻塞 web 主进程。

单卡语义仍由 CLI / knowledge_score 包负责；本模块只负责“什么时候跑、跑多少、
失败了什么时候再试”，避免把打分策略复制到调度层。
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from llm_loop.knowledge_score.client import resolve_endpoint
from llm_loop.knowledge_score.pending import scan_pending
from llm_loop.timekeeping import system_local_now

logger = logging.getLogger(__name__)
SCHEMA = "knowledge-score-runner/v1"
DEFAULT_INTERVAL_S = 120.0
DEFAULT_BATCH_LIMIT = 20
DEFAULT_CARD_TIMEOUT_S = 45.0
DEFAULT_MAX_CONSECUTIVE_FAILURES = 2
MAX_BACKOFF_S = 1800.0
SUMMARY_RE = re.compile(
    r"^\[run\]\s+scored=(\d+)\s+failed=(\d+)\s+stopped=(\S+)",
    re.MULTILINE,
)


def _as_text(value: str | bytes | None) -> str:
    """subprocess 输出归一为 str（text=True 时正常是 str，超时异常可能带 bytes）。"""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def repo_root() -> Path:
    """仓库根目录：``src/llm_loop/knowledge_score/runner.py`` 上溯四层。"""
    return Path(__file__).resolve().parents[3]


def scores_dir(root: Path | str) -> Path:
    return Path(root).resolve() / "data" / "knowledge_scores"


def state_path(root: Path | str) -> Path:
    return scores_dir(root) / "runner_state.json"


def read_runner_state(root: Path | str) -> dict[str, Any] | None:
    """读取持久化运行状态；缺失/损坏返回 None，管理视图不因此 5xx。"""
    try:
        payload = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_runner_state(root: Path | str, payload: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def count_pending(root: Path | str) -> tuple[int | None, str | None]:
    """返回 (待打分 slot 数, 错误)。读失败不抛给调用方，交由状态字段如实暴露。"""
    try:
        return len(scan_pending(Path(root), limit=None)), None
    except Exception as exc:  # noqa: BLE001 - 管理视图/调度器需降级而不是拖垮主流程
        return None, f"{type(exc).__name__}: {exc}"


def _health_url(endpoint: str | None = None) -> str:
    parts = urlsplit(resolve_endpoint() if endpoint is None else endpoint)
    return urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))


def scorer_healthy(endpoint: str | None = None, timeout_s: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(_health_url(endpoint), timeout=timeout_s) as response:  # noqa: S310 - 本机固定/环境配置端点
            return 200 <= int(response.status) < 300
    except Exception:  # noqa: BLE001 - 健康检查失败按不可用处理
        return False


def _retry_delay(consecutive_failures: int, base_s: float) -> float:
    exponent = min(max(consecutive_failures - 1, 0), 6)
    return min(base_s * (2**exponent), MAX_BACKOFF_S)


def retry_wait_seconds(value: str | None, now: datetime | None = None) -> float:
    """距离 next_retry_at 的未来秒数；已过期/不可解析返回 0。

    必须是 ``next_retry - now``。写成 ``now - next_retry`` 会让退避在
    未来时间点为负、被 max(interval, 负) 吞掉，指数退避永远不会生效。
    """
    if not value:
        return 0.0
    try:
        delta = (datetime.fromisoformat(value) - (now or system_local_now())).total_seconds()
    except (TypeError, ValueError):
        return 0.0
    return max(delta, 0.0)


def _summary(stdout: str) -> tuple[int, int, str]:
    match = SUMMARY_RE.search(stdout or "")
    if not match:
        return stdout.count("[scored]"), stdout.count("[failed]"), "unknown"
    return int(match.group(1)), int(match.group(2)), match.group(3)


def run_once(
    root: Path | str | None = None,
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
    card_timeout_s: float = DEFAULT_CARD_TIMEOUT_S,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    process_timeout_s: float = 300.0,
    retry_base_s: float = DEFAULT_INTERVAL_S,
    error_cooldown_s: float = 1800.0,
    health_check: bool = True,
) -> dict[str, Any]:
    """跑一轮待打分补齐，返回并持久化本轮事实。

    关键约束：
    - 先扫 pending，空队列直接跳过，不启动子进程；
    - 健康检查失败/子进程超时/CLI 非零退出都进入指数退避；
    - ``[skip] another ...``（另一进程持锁）不算失败，短延迟后再试。
    """
    base = Path(root).resolve() if root is not None else repo_root()
    now = system_local_now()
    previous = read_runner_state(base) or {}
    before, pending_error = count_pending(base)
    state: dict[str, Any] = {
        **previous,
        "schema": SCHEMA,
        "last_attempt_at": now.isoformat(),
        "last_pending_before": before,
        "last_error": pending_error or str(previous.get("last_error") or ""),
        "updated_at": now.isoformat(),
    }

    if before == 0:
        state.update(
            last_exit_code=0,
            last_scored=0,
            last_failed=0,
            last_pending_after=0,
            last_error="",
            skipped="no_pending",
            consecutive_failures=0,
            next_retry_at=None,
        )
        _write_runner_state(base, state)
        return state

    if before is None:
        failures = int(previous.get("consecutive_failures") or 0) + 1
        next_retry = now + timedelta(seconds=_retry_delay(failures, retry_base_s))
        state.update(
            last_exit_code=None,
            last_scored=0,
            last_failed=0,
            last_pending_after=None,
            skipped="scan_failed",
            consecutive_failures=failures,
            next_retry_at=next_retry.isoformat(),
        )
        _write_runner_state(base, state)
        return state

    # 上一轮已明确写入的退避时间未到：不启动子进程。否则 2 分钟巡检会
    # 在 30 分钟 error cooldown 内空跑并 exit 0，把失败状态错误清零。
    wait_s = retry_wait_seconds(previous.get("next_retry_at"), now)
    if wait_s > 0:
        state.update(
            last_exit_code=previous.get("last_exit_code"),
            last_scored=0,
            last_failed=0,
            last_pending_after=before,
            skipped="backoff",
        )
        _write_runner_state(base, state)
        return state

    if health_check and not scorer_healthy(timeout_s=3.0):
        failures = int(previous.get("consecutive_failures") or 0) + 1
        next_retry = now + timedelta(seconds=_retry_delay(failures, retry_base_s))
        state.update(
            last_exit_code=None,
            last_scored=0,
            last_failed=0,
            last_pending_after=before,
            last_error="scorer_unhealthy",
            skipped="scorer_unhealthy",
            consecutive_failures=failures,
            next_retry_at=next_retry.isoformat(),
        )
        _write_runner_state(base, state)
        return state

    script = base / "scripts" / "knowledge_score.py"
    if not script.is_file():
        failures = int(previous.get("consecutive_failures") or 0) + 1
        next_retry = now + timedelta(seconds=_retry_delay(failures, retry_base_s))
        state.update(
            last_exit_code=None,
            last_scored=0,
            last_failed=0,
            last_pending_after=before,
            last_error="script_missing",
            skipped="script_missing",
            consecutive_failures=failures,
            next_retry_at=next_retry.isoformat(),
        )
        _write_runner_state(base, state)
        return state

    command = [
        sys.executable,
        str(script),
        "--root",
        str(base),
        "--all-pending",
        "--limit",
        str(max(int(limit), 1)),
        "--timeout-seconds",
        str(float(card_timeout_s)),
        "--max-consecutive-failures",
        str(max(int(max_consecutive_failures), 0)),
        "--error-cooldown-seconds",
        str(float(error_cooldown_s)),
    ]
    stdout = ""
    stderr = ""
    exit_code: int | None = None
    timed_out = False
    try:
        completed = subprocess.run(  # noqa: S603 - 固定脚本路径，无 shell 拼接
            command,
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=process_timeout_s,
            check=False,
        )
        stdout = _as_text(completed.stdout)
        stderr = _as_text(completed.stderr)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
    except OSError as exc:
        stderr = f"{type(exc).__name__}: {exc}"

    scored, failed, stopped = _summary(stdout)
    after, after_error = count_pending(base)
    finished = system_local_now()
    lock_skipped = "[skip] another knowledge-score run is in progress" in (stdout + stderr)
    error_text = ""
    if timed_out:
        error_text = f"run_timeout_{int(process_timeout_s)}s"
    elif lock_skipped:
        # 锁竞争不是失败；保留上一轮真实错误，避免把不可用状态覆盖成健康。
        error_text = str(previous.get("last_error") or "")
    elif exit_code not in (0, None):
        detail = (stderr or stdout).strip().splitlines()
        error_text = detail[-1][:500] if detail else f"exit_code={exit_code}"
    elif after_error:
        error_text = after_error

    state.update(
        last_exit_code=exit_code,
        last_scored=scored,
        last_failed=failed,
        last_pending_after=after,
        last_error=error_text,
    )

    if lock_skipped and exit_code in (0, None):
        state.update(
            skipped="locked",
            next_retry_at=(finished + timedelta(seconds=30)).isoformat(),
        )
    elif exit_code == 0 and not timed_out and after is not None and not after_error:
        if scored == 0 and failed == 0 and before and after:
            # CLI 正常退出但一张都没打分：只可能是 pending 全在 error cooldown
            # （或扫描竞态）。这不是健康成功，保留连续失败并等冷却，避免每 2
            # 分钟空跑一次把退避清零。
            state.update(
                skipped="deferred",
                next_retry_at=(
                    finished + timedelta(seconds=max(float(error_cooldown_s), 0.0))
                ).isoformat(),
            )
        else:
            state.update(
                skipped="",
                consecutive_failures=0,
                next_retry_at=None,
            )
            if scored:
                state["last_success_at"] = finished.isoformat()
    else:
        failures = int(previous.get("consecutive_failures") or 0) + 1
        state.update(
            skipped="",
            consecutive_failures=failures,
            next_retry_at=(finished + timedelta(seconds=_retry_delay(failures, retry_base_s))).isoformat(),
        )

    state["stopped"] = stopped if timed_out is False else "timeout"
    state["updated_at"] = finished.isoformat()
    _write_runner_state(base, state)
    return state


def spawn_autorun(
    root: Path | str | None = None,
    *,
    limit: int = DEFAULT_BATCH_LIMIT,
    card_timeout_s: float = DEFAULT_CARD_TIMEOUT_S,
    max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
) -> bool:
    """结算后 fire-and-forget 触发一次补齐；任何异常返回 False，不影响结算主路径。"""
    base = Path(root).resolve() if root is not None else repo_root()
    if os.environ.get("LFL_KNOWLEDGE_SCORE_AUTORUN", "1").strip() == "0":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    script = base / "scripts" / "knowledge_score.py"
    if not script.is_file():
        return False
    try:
        subprocess.Popen(  # noqa: S603 - 固定脚本路径，无 shell 拼接
            [
                sys.executable,
                str(script),
                "--root",
                str(base),
                "--all-pending",
                "--limit",
                str(max(int(limit), 1)),
                "--timeout-seconds",
                str(float(card_timeout_s)),
                "--max-consecutive-failures",
                str(max(int(max_consecutive_failures), 0)),
                "--error-cooldown-seconds",
                "1800",
            ],
            cwd=str(base),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        return True
    except OSError:
        return False


class KnowledgeScoreLoop(threading.Thread):
    """daemon 线程：启动后先补一轮 backlog，之后按间隔巡检。"""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        interval_s: float = DEFAULT_INTERVAL_S,
        limit: int = DEFAULT_BATCH_LIMIT,
        card_timeout_s: float = DEFAULT_CARD_TIMEOUT_S,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        initial_delay_s: float = 8.0,
        enabled: bool | None = None,
    ) -> None:
        super().__init__(name="knowledge-score-loop", daemon=True)
        self.root = Path(root).resolve() if root is not None else repo_root()
        self.interval_s = max(float(interval_s), 10.0)
        self.limit = max(int(limit), 1)
        self.card_timeout_s = float(card_timeout_s)
        self.max_consecutive_failures = max(int(max_consecutive_failures), 0)
        self.initial_delay_s = max(float(initial_delay_s), 0.0)
        if enabled is None:
            enabled = (
                os.environ.get("LFL_KNOWLEDGE_SCORE_AUTORUN", "1").strip() != "0"
                and not os.environ.get("PYTEST_CURRENT_TEST")
            )
        self.enabled = bool(enabled)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:  # pragma: no cover - 线程调度由 main/wait 循环驱动
        if not self.enabled:
            return
        if self._stop_event.wait(self.initial_delay_s):
            return
        while not self._stop_event.is_set():
            try:
                result = run_once(
                    self.root,
                    limit=self.limit,
                    card_timeout_s=self.card_timeout_s,
                    max_consecutive_failures=self.max_consecutive_failures,
                    retry_base_s=self.interval_s,
                )
            except Exception:  # noqa: BLE001 - 调度线程必须自愈，不能因单轮异常退出
                logger.warning("knowledge score loop iteration failed", exc_info=True)
                result = {}
            delay = self.interval_s
            next_retry = result.get("next_retry_at") if isinstance(result, dict) else None
            seconds = retry_wait_seconds(next_retry)
            if seconds > 0:
                delay = max(delay, min(seconds, MAX_BACKOFF_S))
            if self._stop_event.wait(delay):
                return
