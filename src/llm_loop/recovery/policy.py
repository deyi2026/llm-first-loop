"""重试策略常量与重试结果数据模型（design §2.1.1 / §2.3.2.6）.

程序内常量，不暴露 env（对齐 RULE-AI-00 第 4 条"简化而非增加配置面"）。
"""

from __future__ import annotations

from dataclasses import dataclass


class RetryPolicy:
    """重试策略常量（程序内常量，不暴露 env）.

    - MAX_RETRIES=3：单次写失败最多重试 3 次（含首次共 4 次尝试）。
    - RETRY_INTERVAL_S=0.5：固定间隔 0.5s（不指数退避）。
    - RETRY_TOTAL_TIMEOUT_S=5.0：重试总耗时上限 5s（超限转备份）。
    - RETENTION_PERIOD_DAYS=7：备份保留 7 天。
    - MAX_PER_TARGET=5：同一 source_id+target_type 最多 5 份备份。
    """

    MAX_RETRIES = 3
    RETRY_INTERVAL_S = 0.5
    RETRY_TOTAL_TIMEOUT_S = 5.0
    RETENTION_PERIOD_DAYS = 7
    MAX_PER_TARGET = 5


@dataclass
class RetryResult:
    """重试结果回执（design §2.3.2.6）.

    - success：重试是否成功。
    - attempts：实际尝试次数（含首次）。
    - elapsed_s：累计耗时（秒）。
    - final_error：最后一次失败的错误信息（成功时 None）。
    """

    success: bool
    attempts: int
    elapsed_s: float
    final_error: str | None
