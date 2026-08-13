"""重试编排函数（design §2.3.2.6 / spec §5.1.1）.

按 RetryPolicy 常量重试写入函数，返回 RetryResult 回执。
重试复用既有原子写（write_fn 调 SessionStore.save / MemoryStore.flush，spec §4.4.1）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from llm_loop.recovery.policy import RetryPolicy, RetryResult


def retry_write(write_fn: Callable[[], None]) -> RetryResult:
    """按 RetryPolicy 常量重试 write_fn.

    首次调用算第 1 次尝试（不立即重试），失败后按 RETRY_INTERVAL_S 间隔重试，
    累计耗时超 RETRY_TOTAL_TIMEOUT_S 或达 MAX_RETRIES 上限停止。

    - 成功返回 RetryResult{success=True, attempts=N, elapsed_s}。
    - 耗尽返回 RetryResult{success=False, attempts, elapsed_s, final_error}。
    """
    start = time.monotonic()
    last_error: str | None = None
    max_attempts = RetryPolicy.MAX_RETRIES + 1  # 含首次

    for attempt in range(1, max_attempts + 1):
        try:
            write_fn()
            elapsed = time.monotonic() - start
            return RetryResult(success=True, attempts=attempt, elapsed_s=elapsed, final_error=None)
        except Exception as exc:  # noqa: BLE001 — 重试需捕获所有异常
            last_error = f"{type(exc).__name__}: {exc}"
            elapsed = time.monotonic() - start
            if attempt >= max_attempts:
                return RetryResult(
                    success=False, attempts=attempt, elapsed_s=elapsed, final_error=last_error
                )
            if elapsed >= RetryPolicy.RETRY_TOTAL_TIMEOUT_S:
                return RetryResult(
                    success=False, attempts=attempt, elapsed_s=elapsed, final_error=last_error
                )
            time.sleep(RetryPolicy.RETRY_INTERVAL_S)

    # 理论不可达（循环内所有路径均 return），防御性兜底
    elapsed = time.monotonic() - start
    return RetryResult(success=False, attempts=max_attempts, elapsed_s=elapsed, final_error=last_error)
