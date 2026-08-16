"""CodeArts 配置子集（design.md §2.1.2 配置表）.

纯数据结构定义（frozen dataclass），装配逻辑在 llm_loop.config.load_settings
中经环境变量读取完成。凭证类字段（ak/sk/iam_token/webhook_secret）仅从
os.environ 读取，不写入 .env 回显、不落盘、不进日志（DFX-SEC-02）。

全部字段可选，缺省 fail-open 零装配（enabled=False 时本组件不装配）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CodeArtsSettings:
    """CodeArts 集成配置（design.md §2.1.2 配置项与取值策略）.

    全部字段可选；enabled=False 或凭证缺失时本组件不装配（fail-open 零回归）。
    凭证类字段仅内存常驻，绝不落盘/日志/命令行参数（spec §4.3.1、§5.3.1.3）。
    """

    enabled: bool = False
    endpoint: str = ""
    region: str = "cn-north-4"
    project_id: str = ""
    ak: str = ""
    sk: str = ""
    iam_token: str = ""
    api_version: str = "v1"
    connect_timeout_s: int = 10
    call_timeout_s: int = 30
    exec_timeout_s: int = 1800
    poll_interval_s: int = 5
    max_concurrent: int = 10
    max_retries: int = 3
    result_max_bytes: int = 1048576
    webhook_enabled: bool = False
    webhook_secret: str = ""
    approval_required: bool = True

    def has_credential(self) -> bool:
        """是否提供任一形式凭证（AK/SK 或 IAM token）."""
        return bool((self.ak and self.sk) or self.iam_token)

    def credential_kind(self) -> str:
        """凭证类型标识（ak_sk / iam_token / none）；不含明文."""
        if self.ak and self.sk:
            return "ak_sk"
        if self.iam_token:
            return "iam_token"
        return "none"
