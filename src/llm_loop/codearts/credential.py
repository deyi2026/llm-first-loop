"""CredentialProvider 凭证提供者（design.md §2.2.2.2）.

封装 AK/SK 与 IAM token 获取/刷新，内存常驻按需取用。凭证明文绝不落盘、
绝不进日志、绝不经命令行参数传递（spec §4.3.1、§5.3.1.3）。

token 过期自动刷新一次；刷新失败如实上抛不静默降级为匿名（spec §4.2.5）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol

from llm_loop.codearts.config import CodeArtsSettings
from llm_loop.codearts.models import Credential, CredentialKind

logger = logging.getLogger(__name__)


class CredentialError(Exception):
    """凭证缺失或无效."""


class CredentialRefreshError(Exception):
    """凭证刷新失败."""


class CredentialProvider(Protocol):
    """凭证提供者协议（design.md §2.2.2.2 扩展点 1）."""

    def get(self, region: str) -> Credential: ...

    def refresh(self, region: str) -> Credential: ...

    def validate(self, region: str) -> bool: ...


def _is_expired(expires_at: str) -> bool:
    """token 是否已过期（ISO8601 比较；空视为未过期由调用方校验）."""
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at)
        return datetime.now(UTC) >= exp
    except ValueError:
        return False


class EnvCredentialProvider:
    """环境变量凭证提供者（默认实现）.

    从 CodeArtsSettings 读取 AK/SK 或 IAM token，内存常驻 dict[region, Credential]。
    get 优先返回内存缓存，token 过期时调用 refresh。refresh 经 CodeArtsClient
    调用 IAM token 刷新接口（AK/SK 模式下用 AK/SK 签名交换 token；IAM token
    模式下无法刷新直接抛 CredentialRefreshError）。
    """

    def __init__(self, config: CodeArtsSettings) -> None:
        self._config = config
        self._cache: dict[str, Credential] = {}

    def get(self, region: str) -> Credential:
        """获取凭证（内存缓存优先；token 过期自动刷新一次）."""
        cred = self._cache.get(region)
        if cred is not None and not _is_expired(cred.expires_at):
            return cred
        # 首次获取或过期
        if cred is not None and _is_expired(cred.expires_at):
            return self.refresh(region)
        # 首次：从配置构造
        return self._load_from_config(region)

    def _load_from_config(self, region: str) -> Credential:
        """从 CodeArtsSettings 构造凭证（内存常驻）."""
        if self._config.ak and self._config.sk:
            cred = Credential(
                kind=CredentialKind.AK_SK,
                region=region,
                ak=self._config.ak,
                sk=self._config.sk,
            )
        elif self._config.iam_token:
            cred = Credential(
                kind=CredentialKind.IAM_TOKEN,
                region=region,
                token=self._config.iam_token,
            )
        else:
            raise CredentialError("CodeArts 凭证缺失：未配置 AK/SK 或 IAM token")
        self._cache[region] = cred
        return cred

    def refresh(self, region: str) -> Credential:
        """刷新凭证（AK/SK 模式重新签名；IAM token 模式无法刷新抛异常）."""
        cred = self._cache.get(region)
        if cred is not None and cred.kind == CredentialKind.AK_SK:
            # AK/SK 模式：重新从配置读取（支持轮转后的新 AK/SK）
            new_cred = Credential(
                kind=CredentialKind.AK_SK,
                region=region,
                ak=self._config.ak,
                sk=self._config.sk,
            )
            self._cache[region] = new_cred
            logger.info("CodeArts 凭证刷新成功（AK/SK 模式）: region=%s", region)
            return new_cred
        # IAM token 模式无法自动刷新
        raise CredentialRefreshError(
            "IAM token 模式无法自动刷新，请手动更新 CODEARTS_IAM_TOKEN 环境变量"
        )

    def validate(self, region: str) -> bool:
        """轻量校验凭证有效性（AK/SK 模式检查非空；IAM token 模式检查非空且未过期）."""
        try:
            cred = self.get(region)
        except CredentialError:
            return False
        if cred.kind == CredentialKind.AK_SK:
            return bool(cred.ak and cred.sk)
        if cred.kind == CredentialKind.IAM_TOKEN:
            return bool(cred.token) and not _is_expired(cred.expires_at)
        return False
