"""LLM 客户端路由池（M48 / design §5.3 + M49 / design §5.4）.

- 持有 ProviderRegistry（M47）+ 装配默认 LLMClient + provider 级客户端缓存
- get_client(model_override) 按会话级 override 路由：None → 默认；非空 → resolve → 缓存/新建
- fallback_candidates() 解析 MODEL_FALLBACKS env 为合法 provider/model 列表（M49）；
  非法条目跳过并 logging.warning（如实标注），空 = 不启用降级（零回归）
- 零回归: 装配默认 client 始终可路由（未配置注册表时, 仅默认 client 命中）
- 思考参数: 按 registry.supports_thinking 显式传入（M47 §5.5 衔接, 消除硬编码 deepseek.com）

不修改任何环境变量 / 配置文件 / 跨会话状态 (design §七 安全边界).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from llm_loop.llm.client import LLMClient
from llm_loop.llm.providers import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class ModelClientPool:
    """Provider 级 LLMClient 缓存 + 路由 (M48 / design §5.3).

    工作流程:
    - get_client(None)            → 直接返回装配默认 client (零回归快路径)
    - get_client(model_ref)       → registry.resolve → client_params → 缓存/构造 client
    - get_thinking(model_ref)     → registry.supports_thinking 显式判定 (衔接 M47)
    - get_default_model()         → 默认 client 的模型名（model_catalog 工具复用）
    - fallback_candidates()       → 解析 MODEL_FALLBACKS env 为合法 (provider, model) 列表 (design §5.4)

    线程安全: dict 操作 GIL 保护；如需严格并发由外层加锁（本池本身不假设并发）。
    """

    registry: ProviderRegistry
    default_client: LLMClient
    _provider_cache: dict[str, LLMClient] = field(default_factory=dict)
    # M49（design §5.4）: MODEL_FALLBACKS env 原始字符串（构造时由 builder 注入）
    # 解析在 fallback_candidates() 中按调用执行（每次取最新值，避免启动时缓存过期）
    model_fallbacks_raw: str = ""

    def get_client(self, model_override: str | None) -> LLMClient:
        """按会话级 model_override 路由到对应 LLMClient.

        Args:
            model_override: 会话级模型覆盖（None=用装配默认; "provider/model" 或裸模型名）.

        Returns:
            LLMClient 实例. None 永远返回 default_client；非空 resolve 失败抛 ValueError
            （带候选列表，如实反馈）。
        """
        if model_override is None:
            return self.default_client
        provider_id, model_id = self.registry.resolve(model_override)
        cached = self._provider_cache.get(provider_id)
        if cached is not None:
            return cached
        params = self.registry.client_params(provider_id, model_id)
        # 思考参数按注册表元数据判定（消除原 _thinking_supported 硬编码 deepseek.com）
        thinking_supported = self.registry.supports_thinking(provider_id, model_id)
        # 继承默认 client 的运行参数（超时/思考模式/effort），仅切换 provider/model/key/base_url
        client = LLMClient(
            api_key=params["api_key"],
            base_url=params["base_url"],
            model=params["model"],
            timeout_s=self.default_client.timeout_s,
            thinking_mode=self.default_client.thinking_mode,
            reasoning_effort=self.default_client.reasoning_effort,
            thinking_supported=thinking_supported,
        )
        self._provider_cache[provider_id] = client
        return client

    def get_thinking(self, model_override: str | None) -> bool:
        """查询指定 override 是否支持思考参数（model_catalog / switch_model 回执复用）.

        Args:
            model_override: 会话级模型覆盖（None → 用默认 client 的模型判定）.
        """
        if model_override is None:
            return self.default_client.thinking_supported is True
        try:
            provider_id, model_id = self.registry.resolve(model_override)
        except ValueError:
            return False
        return self.registry.supports_thinking(provider_id, model_id)

    def get_default_model(self) -> str:
        """装配默认 client 的模型名（model_catalog 当前模型标注用）."""
        return self.default_client.model

    def cached_provider_ids(self) -> list[str]:
        """已缓存的 provider id 列表（测试/调试用）."""
        return sorted(self._provider_cache.keys())

    def clear_cache(self) -> None:
        """清空 provider 缓存（refresh_config / 测试用；不影响 default_client）."""
        self._provider_cache.clear()

    def fallback_candidates(self) -> list[str]:
        """解析 MODEL_FALLBACKS env 为合法 provider/model 引用列表 (M49 / design §5.4).

        返回:
            list[str]: 全限定 `provider/model` 形式的合法降级候选（如 ["deepseek/deepseek-v4-flash", "local/qwen3.6-27b"]）.
            空 list = 未配置/配置全部非法 = 不启用降级（调用方应保持现状行为，零回归）.

        非法条目处理（fail-soft + 如实标注，不静默吞）:
        - 空条目（连续逗号/首尾逗号）→ 跳过
        - resolve 失败（未知 provider/model/裸名歧义）→ 跳过 + logging.warning 含原因
        - client_params 失败（api_key 缺失）→ 跳过 + logging.warning 含 env var 名字

        设计原则（design §三 原则 2 如实反馈 + 原则 4 密钥不出域）:
        - 仅返回 model 引用（不含 key/base_url），降级链明细不外泄
        - 解析结果不缓存（每次调用重读 model_fallbacks_raw, 便于运行时调整 env；零回归下开销可忽略）

        注意事项:
        - 返回的列表是"当前合法候选"，实际降级触发在 loop.py（M49 降级逻辑）
        - 本方法仅做"候选筛选"，不构造 LLMClient；构造在降级触发时按需走 get_client
        """
        raw = (self.model_fallbacks_raw or "").strip()
        if not raw:
            return []

        out: list[str] = []
        for raw_item in raw.split(","):
            ref = raw_item.strip()
            if not ref:
                # 空条目（如连续逗号/首尾逗号）→ 静默跳过
                continue
            try:
                provider_id, model_id = self.registry.resolve(ref)
            except ValueError as exc:
                # resolve 失败 → 跳过 + 如实标注（fail-soft；非法配置不阻断降级链）
                logger.warning("MODEL_FALLBACKS 跳过非法条目 '%s': %s", ref, exc)
                continue
            # 预检 api_key（client_params 触发按需读取 env var）
            try:
                self.registry.client_params(provider_id, model_id)
            except ValueError as exc:
                # key 缺失 → 跳过 + 如实标注含 env var 名字（设计原则 4 密钥不出域: 仅日志回显 env 名, 不回显 key）
                logger.warning(
                    "MODEL_FALLBACKS 跳过候选 '%s'（api_key 不可用）: %s",
                    f"{provider_id}/{model_id}",
                    exc,
                )
                continue
            out.append(f"{provider_id}/{model_id}")
        return out
