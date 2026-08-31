"""LLM 客户端路由池（M48 / design §5.3 + M49 / design §5.4）.

- 持有 ProviderRegistry（M47）+ 装配默认 LLMClient + provider/model 级客户端缓存
- get_client(model_override) 按会话级 override 路由：None → 默认；非空 → resolve → 缓存/新建
- fallback_candidates() 解析 MODEL_FALLBACKS env 为合法 provider/model 列表（M49）；
  非法条目跳过并 logging.warning（如实标注），空 = 不启用降级（零回归）
- 零回归: 装配默认 client 始终可路由（未配置注册表时, 仅默认 client 命中）
- 思考参数: 按 registry.supports_thinking 显式传入（M47 §5.5 衔接, 消除硬编码 deepseek.com）

不修改任何环境变量 / 配置文件 / 跨会话状态 (design §七 安全边界).
"""

from __future__ import annotations

import logging
import os
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any

from llm_loop.llm.client import LLMClient
from llm_loop.llm.providers import ProviderRegistry, is_below_capability_floor

logger = logging.getLogger(__name__)


@dataclass
class ModelClientPool:
    """Provider/model 级 LLMClient 缓存 + 路由 (M48 / design §5.3).

    工作流程:
    - get_client(None)            → 直接返回装配默认 client (零回归快路径)
    - get_client(model_ref)       → registry.resolve → client_params → 缓存/构造 client
    - get_thinking(model_ref)     → registry.supports_thinking 显式判定 (衔接 M47)
    - get_default_model()         → 默认 client 的模型名（model_catalog 工具复用）
    - fallback_candidates()       → 解析 MODEL_FALLBACKS env 为合法 (provider, model) 列表 (design §5.4)

    线程安全: registry/cache 读写由内部 RLock 保护；热重载通过 replace_registry 原子切表。
    """

    registry: ProviderRegistry
    default_client: LLMClient
    _provider_cache: dict[str, LLMClient] = field(default_factory=dict)
    _guard: Any = field(default_factory=threading.RLock, init=False, repr=False)
    _default_registry: ProviderRegistry = field(init=False, repr=False)
    _retired_refs: list[tuple[weakref.ReferenceType[LLMClient], Any]] = field(
        default_factory=list, init=False, repr=False
    )
    _retired_ducks: list[Any] = field(default_factory=list, init=False, repr=False)
    # M49（design §5.4）: MODEL_FALLBACKS env 原始字符串（构造时由 builder 注入）
    # 解析在 fallback_candidates() 中按调用执行（每次取最新值，避免启动时缓存过期）
    model_fallbacks_raw: str = ""

    def __post_init__(self) -> None:
        # default_client 不参与 provider 热重载；其能力/窗口元数据也必须绑定启动快照。
        self._default_registry = self.registry

    def registry_snapshot(self) -> ProviderRegistry:
        """返回当前不可变 ProviderRegistry 快照（与replace_registry互斥读取）."""
        with self._guard:
            return self.registry

    def default_registry_snapshot(self) -> ProviderRegistry:
        """返回 default_client 对应的启动 registry 快照。"""
        return self._default_registry

    def _get_client_locked(
        self,
        registry: ProviderRegistry,
        provider_id: str,
        model_id: str,
        *,
        use_cache: bool = True,
    ) -> LLMClient:
        """_guard 已持有时按已解析 provider/model 取或构造 client。"""
        cache_key = f"{provider_id}/{model_id}"
        if use_cache:
            cached = self._provider_cache.get(cache_key)
            if cached is not None:
                return cached
            # 兼容测试/外部旧注入：历史上 provider-only key 用于预置 FakeLLM 避免触网。
            legacy_cached = self._provider_cache.get(provider_id)
            if legacy_cached is not None:
                return legacy_cached
        params = registry.client_params(provider_id, model_id)
        thinking_supported = registry.supports_thinking(provider_id, model_id)
        provider_timeout = params.get("timeout_s")
        provider_max_tokens = params.get("max_tokens")
        provider_wire_protocol = params.get("wire_protocol")
        client = LLMClient(
            api_key=params["api_key"],
            base_url=params["base_url"],
            model=params["model"],
            timeout_s=(
                provider_timeout
                if provider_timeout is not None
                else self.default_client.timeout_s
            ),
            max_tokens=(
                provider_max_tokens
                if provider_max_tokens is not None
                else self.default_client.max_tokens
            ),
            wire_protocol=(
                provider_wire_protocol
                if provider_wire_protocol is not None
                else self.default_client.wire_protocol
            ),
            thinking_mode=self.default_client.thinking_mode,
            reasoning_effort=self.default_client.reasoning_effort,
            thinking_supported=thinking_supported,
        )
        if use_cache:
            self._provider_cache[cache_key] = client
        return client

    def get_resolved_client(
        self, model_ref: str, *, registry: ProviderRegistry | None = None
    ) -> tuple[LLMClient, str, str]:
        """在指定不可变registry快照内解析并取client；stale快照不污染current cache。"""
        retire_after = False
        with self._guard:
            selected = registry if registry is not None else self.registry
            provider_id, model_id = selected.resolve(model_ref)
            use_cache = selected is self.registry
            client = self._get_client_locked(
                selected, provider_id, model_id, use_cache=use_cache
            )
            retire_after = not use_cache
        if retire_after:
            # round已捕获旧快照而refresh已切表：本轮仍按旧快照完成；一次性client最后引用释放后关闭。
            self._retire_client(client)
        return client, provider_id, model_id

    def get_client(self, model_override: str | None) -> LLMClient:
        """按会话级 model_override 路由到对应 LLMClient。"""
        if model_override is None:
            with self._guard:
                return self.default_client
        client, _provider_id, _model_id = self.get_resolved_client(model_override)
        return client

    def get_thinking(self, model_override: str | None) -> bool:
        """查询指定 override 是否支持思考参数（与热重载 registry 取同一快照）."""
        with self._guard:
            if model_override is None:
                return self.default_client.thinking_supported is True
            registry = self.registry
            try:
                provider_id, model_id = registry.resolve(model_override)
            except ValueError:
                return False
            return registry.supports_thinking(provider_id, model_id)

    def get_default_model(self) -> str:
        """装配默认 client 的模型名（默认 client 热重载不原地改写）."""
        with self._guard:
            return self.default_client.model

    def cached_provider_ids(self) -> list[str]:
        """已缓存的 provider id 列表（隐藏 per-model cache key 细节）."""
        with self._guard:
            return sorted({key.split("/", 1)[0] for key in self._provider_cache})

    @staticmethod
    def _close_transport(transport: Any) -> None:
        """退休 finalizer 使用：只持底层 transport，不反向持有 LLMClient。"""
        closer = getattr(transport, "close", None)
        if not callable(closer):
            return
        try:
            closer()
        except Exception:  # noqa: BLE001 — GC/退休清理绝不能抛穿
            logger.warning("退休 LLM transport 关闭失败（fail-open）", exc_info=True)

    def _retire_client(self, client: Any) -> None:
        """热重载退休旧 client；真实 LLMClient 最后引用释放后再关闭 transport。"""
        if isinstance(client, LLMClient):
            transport = getattr(client, "_client", None)
            if transport is not None:
                finalizer = weakref.finalize(
                    client, ModelClientPool._close_transport, transport
                )
                with self._guard:
                    self._retired_refs = [
                        pair for pair in self._retired_refs if pair[0]() is not None
                    ]
                    self._retired_refs.append((weakref.ref(client), finalizer))
            return
        # duck/injected client 无法安全拆出 transport；保守持有到 pool.close。
        with self._guard:
            if all(existing is not client for existing in self._retired_ducks):
                self._retired_ducks.append(client)

    def replace_registry(self, new_registry: ProviderRegistry) -> None:
        """原子替换 registry 并退休旧 cache（refresh_config 并发安全入口）."""
        with self._guard:
            old_clients = list({id(c): c for c in self._provider_cache.values()}.values())
            self.registry = new_registry
            self._provider_cache.clear()
        for client in old_clients:
            self._retire_client(client)

    def close(self) -> None:
        """关闭 default/current/退休 clients；单对象或 finalizer 只执行一次。"""
        with self._guard:
            clients = [self.default_client, *self._provider_cache.values(), *self._retired_ducks]
            retired_finalizers = [finalizer for _ref, finalizer in self._retired_refs]
            self._provider_cache.clear()
            self._retired_refs.clear()
            self._retired_ducks.clear()
        seen: set[int] = set()
        for client in clients:
            ident = id(client)
            if ident in seen:
                continue
            seen.add(ident)
            self._close_client(client)
        for finalizer in retired_finalizers:
            if getattr(finalizer, "alive", False):
                finalizer()

    def clear_cache(self) -> None:
        """显式清缓存：立即关闭当前缓存 client（保留既有管理/测试契约）."""
        with self._guard:
            clients = list({id(c): c for c in self._provider_cache.values()}.values())
            self._provider_cache.clear()
        for client in clients:
            self._close_client(client)

    def _close_client(self, client: LLMClient) -> None:
        """P2-4(2026-08-15): 单个 client 关闭（duck-typing getattr 防御 + fail-open）.

        无 close 方法的可注入实现（如测试 FakeLLM）跳过；关闭异常记 warning 继续。
        """
        closer = getattr(client, "close", None)
        if closer is None:
            return
        try:
            closer()
        except Exception as exc:  # noqa: BLE001 — 单个关闭失败 fail-open
            logger.warning("LLM 客户端关闭失败（fail-open）: %s", exc)

    def fallback_candidates(
        self, *, registry: ProviderRegistry | None = None
    ) -> list[str]:
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
        with self._guard:
            raw = (self.model_fallbacks_raw or "").strip()
            selected_registry = registry if registry is not None else self.registry
        if not raw:
            return []

        out: list[str] = []
        for raw_item in raw.split(","):
            ref = raw_item.strip()
            if not ref:
                # 空条目（如连续逗号/首尾逗号）→ 静默跳过
                continue
            try:
                provider_id, model_id = selected_registry.resolve(ref)
            except ValueError as exc:
                # resolve 失败 → 跳过 + 如实标注（fail-soft；非法配置不阻断降级链）
                logger.warning("MODEL_FALLBACKS 跳过非法条目 '%s': %s", ref, exc)
                continue
            # 预检 api_key（client_params 触发按需读取 env var）
            try:
                selected_registry.client_params(provider_id, model_id)
            except ValueError as exc:
                # key 缺失 → 跳过 + 如实标注含 env var 名字（设计原则 4 密钥不出域: 仅日志回显 env 名, 不回显 key）
                logger.warning(
                    "MODEL_FALLBACKS 跳过候选 '%s'（api_key 不可用）: %s",
                    f"{provider_id}/{model_id}",
                    exc,
                )
                continue
            out.append(f"{provider_id}/{model_id}")
        return self._apply_capability_floor(out, selected_registry)

    def _apply_capability_floor(
        self, candidates: list[str], registry: ProviderRegistry
    ) -> list[str]:
        """D'-2.2/D'-2.3（R8.24 D-D6）: capability floor——shadow 标记 / enforce 过滤.

        - shadow（LFL_FALLBACK_FLOOR 默认）: 链行为与现状零变化——仅对低于 floor
          候选记录 would_downgrade_below_floor 观测事件（含候选 ref、capability
          档位、task_complexity 标签字段——pool 层无任务上下文，登记 unknown 由
          engine 消费侧观测补全；对照 D6 场景: 9B 档候选在链中应被标记）。
        - enforce: 低于下限候选剔除 + 如实日志含剔除原因（不静默吞）；
          全部候选被剔除时回退原链（不启用降级优于空链死锁——回退现状可回滚）。
        判据唯一入口 = providers.is_below_capability_floor（三档: weak/unknown 低于
        下限，strong 进链；细粒度定标为待验证假设不进配置——见其 docstring）。
        """
        mode = os.environ.get("LFL_FALLBACK_FLOOR", "shadow").strip().lower()
        if not candidates:
            return candidates
        kept: list[str] = []
        for ref in candidates:
            try:
                pid, mid = ref.split("/", 1)
                spec = registry.providers[pid].models.get(mid)
                below = spec is not None and is_below_capability_floor(spec)
            except Exception:  # noqa: BLE001 — 判据失败 fail-open 不动链
                below = False
            tier = getattr(spec, "capability_tier", "unknown")
            if not below:
                kept.append(ref)
                continue
            if mode == "enforce":
                logger.info(
                    "event=fallback.floor_filtered ref=%s capability_tier=%s"
                    "（低于能力下限，自动链剔除——shadow 观测达标后 enforce，LFL_FALLBACK_FLOOR 可回滚）",
                    ref, tier,
                )
                continue
            logger.info(
                "event=fallback.would_downgrade_below_floor ref=%s capability_tier=%s"
                " task_complexity=unknown（shadow 观测——链行为不变，仅登记）",
                ref, tier,
            )
            kept.append(ref)
        if mode == "enforce" and not kept:
            logger.warning(
                "event=fallback.floor_exhausted candidates=%d（全部低于能力下限——"
                "回退原链防空链死锁，可 LFL_FALLBACK_FLOOR=shadow 回滚）", len(candidates),
            )
            return candidates
        return kept
