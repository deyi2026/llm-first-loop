"""RoutingService——模型路由职责服务（R9-B5-W4-02b：_RoutingMixin 退役；宿主面显式经 self._host 标注，沿 runtime_params v4 惯例）.

move 自 engine.py 内联路由段与守卫段（327-368）及辅助方法（648-735）与估算常量（77-80）：
- 三级路由（per-call override > 会话 override > 默认装配），model_used 如实标注（M51）
- context/window metadata and model-aware history budget planning; actual provider overflow remains authoritative
"""

# (W4-02b) mixin 时代文件级 pyright 豁免已随宿主显式标注移除；如 pyright 报错回退并登记

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_loop.feedback.honesty import model_unavailable_text
from llm_loop.llm.client import LLMClient

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.llm.providers import ProviderRegistry

logger = logging.getLogger(__name__)


# M53: 上下文守卫估算口径（chars/token 保守估计）
# 2026-08-24 校准（拷问产出）: 2 → 0.6 —— 实测大上下文 1.676 tok/char（见 runtime.py 同源注释）
_CHARS_PER_TOKEN_EST = 0.6
# 安全边距: 预留 10% 给响应生成
_CONTEXT_SAFETY_MARGIN = 0.9
# EVO-20260811-10dc2533 P0: 未注册模型保守默认窗口预算（字符）——本地 Ollama/llama.cpp/mlx
# 等未配置 context 的模型，用 8K 保守预算替代全局 budget，防小窗口模型超限硬拒绝。
_UNKNOWN_MODEL_BUDGET_CHARS = 8000


@dataclass
class _RouteDecision:
    """内部路由决策容器（仅内部使用，非对外契约）.

    final_answer_override is reserved for factual routing/resolve failure, never an estimated context rejection.
    """

    llm_client: LLMClient
    model_used: str
    chat_model_arg: str | None
    final_answer_override: str | None = None
    context_limit: int | None = None
    chars_per_token: float = _CHARS_PER_TOKEN_EST
    # R8: exact immutable registry snapshot that supplied metadata for the
    # routed model.  Observational only; never consumed by prompt assembly.
    metadata_registry: ProviderRegistry | None = None


class RoutingService:
    def __init__(self, host: LoopEngine) -> None:
        self._host = host

    def _pool_registry_snapshot(self) -> Any:
        """读取current registry快照；兼容仅暴露 `.registry` 的旧duck pool。"""
        pool = self._host.llm_pool
        if pool is None:
            return None
        getter = getattr(pool, "registry_snapshot", None)
        if callable(getter):
            return getter()
        return getattr(pool, "registry", None)

    def _pool_default_registry_snapshot(self) -> Any:
        """default client启动快照；旧duck pool无该API时回退其当前registry。"""
        pool = self._host.llm_pool
        if pool is None:
            return None
        getter = getattr(pool, "default_registry_snapshot", None)
        if callable(getter):
            return getter()
        return self._pool_registry_snapshot()

    def _round_registry_snapshots(
        self, model: str | None, sess
    ) -> tuple[Any, Any, Any]:
        """返回(current, default-startup, planning)三个本轮不可变快照。"""
        current = self._pool_registry_snapshot()
        default = self._pool_default_registry_snapshot()
        planning = current if model is not None or bool(sess.model_override) else default
        return current, default, planning

    def _route_model(
        self,
        model,
        sess,
        *,
        registry_snapshot: ProviderRegistry | None = None,
        default_registry_snapshot: ProviderRegistry | None = None,
    ) -> _RouteDecision:
        """Resolve the explicit per-call/session/default model route.

        Context metadata is returned for budgeting/telemetry. Estimated payload size is not
        a second hard authority; actual provider overflow drives deterministic recovery.
        """
        # M48（design §5.3）: 路由决策——
        # - per-call Web model（run() 参数）优先级最高：经池路由到对应 provider client
        #   （正确 base_url/key），并把发送给 LLM 的 model 归一化为裸模型名
        #   （M50 修复: 全限定 provider/model 不得直接透传 LLM API，否则 400）
        # - 否则按会话级 model_override 经 pool 路由（switch_model 设置，持久生效）
        # - pool 未装配（None）→ 用默认 client（零回归）
        current_registry = None
        default_registry = None
        if self._host.llm_pool is not None:
            current_registry = registry_snapshot or self._pool_registry_snapshot()
            default_registry = (
                default_registry_snapshot or self._pool_default_registry_snapshot()
            )
        metadata_registry = current_registry

        chat_model_arg = model  # per-call Web override（None 表示不覆盖）
        if chat_model_arg is not None and self._host.llm_pool is not None:
            # per-call 覆盖：解析 provider/model → 对应 provider client
            try:
                llm_client, pid, resolved_model_id = self._host.llm_pool.get_resolved_client(
                    chat_model_arg, registry=current_registry
                )
                metadata_registry = current_registry
                chat_model_arg = resolved_model_id
                model_used = f"{pid}/{resolved_model_id}"  # M51: 如实标注实际模型
            except ValueError as exc:
                # 模型不在注册表 / 凭据缺失：如实反馈，不静默降级（PREFERENCE_1）
                self._host._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                return _RouteDecision(
                    llm_client=self._host.llm,
                    model_used=self._default_model_label(),
                    chat_model_arg=chat_model_arg,
                    final_answer_override=model_unavailable_text(chat_model_arg, exc),
                )
        elif chat_model_arg is None and self._host.llm_pool is not None:
            # 会话级 override 路由：不仅换 client，还必须显式传裸 model id。
            # legacy provider-key FakeLLM/共享 client 以及同provider多模型都依赖该不变量。
            try:
                if sess.model_override:
                    llm_client, pid, resolved_model_id = self._host.llm_pool.get_resolved_client(
                        sess.model_override, registry=current_registry
                    )
                    metadata_registry = current_registry
                    chat_model_arg = resolved_model_id
                    model_used = f"{pid}/{resolved_model_id}"
                else:
                    llm_client = self._host.llm_pool.get_client(None)
                    model_used = self._default_model_label(
                        registry_snapshot=default_registry
                    )
                    metadata_registry = default_registry
            except ValueError as exc:
                # resolve 失败（override 在 refresh_config 后失效等）：如实反馈，走默认 client
                self._host._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                llm_client = self._host.llm
                model_used = self._default_model_label(
                    registry_snapshot=default_registry
                )
                metadata_registry = default_registry
        else:
            llm_client = self._host.llm
            model_used = self._default_model_label()
            metadata_registry = None
        # Rule-first: model selection is explicit user/session/default state.
        # No program-side "simple task" classifier may silently substitute a faster model.
        # Physical context metadata is still needed by history budgeting, overflow
        # attribution and telemetry. Do not turn an approximate chars/token conversion
        # into a pre-provider hard rejection.
        context_limit = self._current_context_limit(
            model_used, registry_snapshot=metadata_registry
        )
        chars_per_token = self._provider_chars_per_token(
            model_used, registry_snapshot=metadata_registry
        )
        return _RouteDecision(
            llm_client=llm_client, model_used=model_used, chat_model_arg=chat_model_arg,
            context_limit=context_limit, chars_per_token=chars_per_token,
            metadata_registry=metadata_registry,
        )

    def _default_model_label(
        self, *, registry_snapshot: ProviderRegistry | None = None
    ) -> str:
        """M51: 装配默认模型的全限定标签（provider/model）.

        有 pool 时经注册表 resolve 为全限定 ref；无 pool / resolve 失败 → 裸模型名（零回归）.
        client 无 model 属性（如测试 FakeLLM）→ 返回空串（不伪造标签, 无 footer）.
        """
        model = getattr(self._host.llm, "model", "")
        if not model:
            return ""
        if self._host.llm_pool is not None:
            try:
                registry = registry_snapshot or self._pool_registry_snapshot()
                if registry is None:
                    return model
                pid, mid = registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError as exc:  # fail-open：模型标签 resolve 失败回退裸名
                logger.debug("模型标签 resolve 失败，回退裸名（fail-open）: %s", exc)
        return model

    def _current_context_limit(
        self,
        model_label: str,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> int | None:
        """M53: 查询当前模型的上下文上限（注册表 ModelSpec.context 元数据）.

        model_label 为全限定 "provider/model"（M51 路由已保证）；无 pool / 裸名 / 未知 → None（守卫跳过）.
        """
        if self._host.llm_pool is None or not model_label or "/" not in model_label:
            return None
        pid, mid = model_label.split("/", 1)
        registry = registry_snapshot or self._pool_registry_snapshot()
        if registry is None:
            return None
        spec = registry.providers.get(pid)
        if spec is None or mid not in spec.models:
            return None
        context = spec.models[mid].context
        return context if context and context > 0 else None

    # ── 辅助 ──
    def _planned_model_label(
        self,
        model: str | None,
        sess,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> str:
        """M54: 预测本轮将使用的模型标签（仅标签解析, 不建 client）.

        与路由同序: per-call override > 会话 override > 默认装配。
        用于在构造消息前计算模型窗口感知的压缩预算。
        """
        if model is not None and self._host.llm_pool is not None:
            try:
                registry = registry_snapshot or self._pool_registry_snapshot()
                if registry is None:
                    return model
                pid, mid = registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError:
                return model
        if self._host.llm_pool is not None and sess.model_override:
            try:
                registry = registry_snapshot or self._pool_registry_snapshot()
                if registry is None:
                    return sess.model_override
                pid, mid = registry.resolve(sess.model_override)
                return f"{pid}/{mid}"
            except ValueError:
                return sess.model_override
        if registry_snapshot is None:
            return self._default_model_label()
        return self._default_model_label(registry_snapshot=registry_snapshot)

    def _provider_chars_per_token(
        self,
        model_label: str,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> float:
        """EVO-20260824: provider 级字符/token 估算.

        deepseek 0.6（中文混合实测 1.676 tok/char）/ local 0.9（qwen tokenizer 效率更高,
        统一 0.6 会让本地载荷高估 1.7-2 倍 → 守卫误拦 + 预算过紧）。
        未配置 / 无 pool / 未知 provider → 全局默认 0.6（零回归）。
        """
        if self._host.llm_pool is None or "/" not in model_label:
            return _CHARS_PER_TOKEN_EST
        pid, _mid = model_label.split("/", 1)
        registry = registry_snapshot or self._pool_registry_snapshot()
        if registry is None:
            return _CHARS_PER_TOKEN_EST
        spec = registry.providers.get(pid)
        if spec is None:
            return _CHARS_PER_TOKEN_EST
        provider_cpt = getattr(spec, "chars_per_token", None)
        if provider_cpt is not None and provider_cpt > 0:
            return provider_cpt
        return _CHARS_PER_TOKEN_EST

    def _resolve_history_budget(
        self,
        model_label: str,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> dict:
        """T5(GPT 复审) 单源 resolver: effective history budget 全口径归因.

        原实现 detail 与 _effective_history_budget 是两份独立 min 链（漂移
        风险：显示值与执行值可能脱节），T5 收敛为本方法单源，两个公开方法
        均为薄委托。2026-09-04 再收敛：history_max_chars=None 表示没有独立
        全局 cap，不能拿默认模型的兼容/诊断预算去限制当前路由模型——
        architecture_status.context_usage.budget 直接展示，AI 与人无需自行推算。
        limited_by ∈ {runtime_override, global_budget, window_adaptive,
        provider_budget, model_window, unknown_model_default}。
        """
        configured_global = getattr(self._host.settings, "history_max_chars", None)
        runtime_override = None
        # T5 修正: 防御式访问（旧 _effective_history_budget 路径不触 self.runtime，
        # 测试桩/老调用方最小依赖面无该属性——单源化后统一 fail-open 风格）
        runtime_view = getattr(self._host, "runtime", None)
        if runtime_view is not None:
            try:
                runtime_override = runtime_view.get("history_budget", None)
            except Exception:  # noqa: BLE001 — 归因失败不阻塞预算计算
                runtime_override = None
        if runtime_override is not None:
            global_budget: int | None = int(runtime_override)
            limited_by = "runtime_override"
        elif configured_global is not None:
            global_budget = int(configured_global)
            limited_by = "global_budget"
        else:
            # None 是真实“无独立全局 cap”，后续由 provider cap / 当前模型物理
            # window / output reserve 决定；不要把 _runtime_history_budget() 的
            # 兼容诊断值重新引入执行 min 链。
            global_budget = None
            limited_by = "model_window"
        provider_budget: int | None = None
        cpt = (
            self._provider_chars_per_token(model_label)
            if registry_snapshot is None
            else self._provider_chars_per_token(
                model_label, registry_snapshot=registry_snapshot
            )
        )
        if self._host.llm_pool is not None and "/" in model_label:
            pid, _mid = model_label.split("/", 1)
            registry = registry_snapshot or self._pool_registry_snapshot()
            spec = registry.providers.get(pid) if registry is not None else None
            if spec is not None:
                provider_budget = spec.history_budget_chars
        if provider_budget and (
            global_budget is None or provider_budget < global_budget
        ):
            global_budget = provider_budget
            limited_by = "provider_budget"
        limit = (
            self._current_context_limit(model_label)
            if registry_snapshot is None
            else self._current_context_limit(
                model_label, registry_snapshot=registry_snapshot
            )
        )
        model_budget: int | None = None
        if not limit:
            # EVO-20260811-10dc2533 P0: 未注册模型保守默认窗口预算（防本地小窗口必超限）。
            if self._host.llm_pool is not None and "/" in model_label:
                eff = (
                    min(global_budget, _UNKNOWN_MODEL_BUDGET_CHARS)
                    if global_budget is not None
                    else _UNKNOWN_MODEL_BUDGET_CHARS
                )
                if global_budget is None or global_budget > _UNKNOWN_MODEL_BUDGET_CHARS:
                    limited_by = "unknown_model_default"
                return {
                    "configured_global_budget": configured_global,
                    "runtime_override": runtime_override,
                    "provider_budget": provider_budget,
                    "model_window_budget": None,
                    "effective_budget": eff,
                    "limited_by": limited_by,
                    "model": model_label,
                }
            # 无 pool/裸模型且窗口未知：保持保守 100K fallback；这不是已知大窗口
            # 模型的隐藏 cap，而是“没有任何窗口事实”时的 fail-safe。
            eff = global_budget if global_budget is not None else 100_000
            if global_budget is None:
                limited_by = "unknown_model_default"
            return {
                "configured_global_budget": configured_global,
                "runtime_override": runtime_override,
                "provider_budget": provider_budget,
                "model_window_budget": None,
                "effective_budget": eff,
                "limited_by": limited_by,
                "model": model_label,
            }
        # Agency-first: history budget tracks the model's physical context boundary.
        # Reserve concrete output capacity here; if the provider still reports overflow,
        # that real response is the authoritative trigger for deterministic recovery.
        output_tokens = int(getattr(self._host.settings, "llm_max_tokens", 0) or 0)
        if self._host.llm_pool is not None and "/" in model_label:
            pid, mid = model_label.split("/", 1)
            registry = registry_snapshot or self._pool_registry_snapshot()
            spec = registry.providers.get(pid) if registry is not None else None
            if spec is not None:
                model_spec = (getattr(spec, "models", None) or {}).get(mid)
                if model_spec is not None and getattr(model_spec, "max_tokens", None):
                    output_tokens = int(model_spec.max_tokens or 0)
                elif getattr(spec, "max_tokens", None):
                    output_tokens = int(spec.max_tokens or 0)
        allowed_input_tokens = int(limit * _CONTEXT_SAFETY_MARGIN)
        if output_tokens > 0:
            allowed_input_tokens = min(allowed_input_tokens, max(1, limit - output_tokens))
        model_budget = int(allowed_input_tokens * cpt)
        if global_budget is None or model_budget < global_budget:
            eff, limited_by = model_budget, "model_window"
        else:
            eff = global_budget
        return {
            "configured_global_budget": configured_global,
            "runtime_override": runtime_override,
            "provider_budget": provider_budget,
            "model_window_budget": model_budget,
            "effective_budget": eff,
            "limited_by": limited_by,
            "model": model_label,
        }

    def _effective_history_budget_detail(
        self,
        model_label: str,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> dict:
        """T5: 单源委托（防双实现漂移）."""
        return self._resolve_history_budget(
            model_label, registry_snapshot=registry_snapshot
        )

    def _effective_history_budget(
        self,
        model_label: str,
        *,
        registry_snapshot: ProviderRegistry | None = None,
    ) -> int:
        """M54: 模型窗口感知的历史压缩预算（T5: resolver 单源投影）.

        effective = min(全局预算, 与最终 context guard 同口径的模型输入字符预算
        （90% 物理窗口安全边距并预留 max_tokens）, provider history_budget_chars 若配置)。完整归因字段见
        _resolve_history_budget。
        """
        return self._resolve_history_budget(
            model_label, registry_snapshot=registry_snapshot
        )["effective_budget"]
