"""LoopEngine 模型路由职责 mixin（M53 拆分: engine.py 946 行→按职责分文件，纯重构行为零变化）.

move 自 engine.py 内联路由段与守卫段（327-368）及辅助方法（648-735）与估算常量（77-80）：
- 三级路由（per-call override > 会话 override > 默认装配），model_used 如实标注（M51）
- 上下文超限前置守卫（M53，估算口径 _CHARS_PER_TOKEN_EST/_CONTEXT_SAFETY_MARGIN）
"""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
# (mixin 模式: self 属性来自混入类 LoopEngine.__init__，pyright 无法静态解析，故文件级关闭这两条；参数/返回类型等其余检查保留)

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from llm_loop.core.loop.tool_exec import _json_dumps_args
from llm_loop.feedback.honesty import model_unavailable_text
from llm_loop.llm.client import LLMClient

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


# M53: 上下文守卫估算口径（chars/token 保守估计, 中文混合内容约 2 字符/token）
_CHARS_PER_TOKEN_EST = 2
# 安全边距: 预留 10% 给响应生成
_CONTEXT_SAFETY_MARGIN = 0.9


@dataclass
class _RouteDecision:
    """内部路由决策容器（仅内部使用，非对外契约）.

    final_answer_override 非 None 时主链路直接以其结束本轮（守卫拒绝 / per-call resolve 失败）。
    """

    llm_client: LLMClient
    model_used: str
    chat_model_arg: str | None
    final_answer_override: str | None = None


class _RoutingMixin:
    def _route_model(self: LoopEngine, model, sess, messages, tools_param) -> _RouteDecision:
        """行动：模型三级路由 + 上下文守卫（move 自 engine.py:327-368）.

        路由判定序: per-call override > 会话 override > 默认装配；
        守卫拒绝 / per-call resolve 失败 → final_answer_override 非 None（主链路 break）。
        """
        # M48（design §5.3）: 路由决策——
        # - per-call Web model（run() 参数）优先级最高：经池路由到对应 provider client
        #   （正确 base_url/key），并把发送给 LLM 的 model 归一化为裸模型名
        #   （M50 修复: 全限定 provider/model 不得直接透传 LLM API，否则 400）
        # - 否则按会话级 model_override 经 pool 路由（switch_model 设置，持久生效）
        # - pool 未装配（None）→ 用默认 client（零回归）
        chat_model_arg = model  # per-call Web override（None 表示不覆盖）
        if chat_model_arg is not None and self.llm_pool is not None:
            # per-call 覆盖：解析 provider/model → 对应 provider client
            try:
                llm_client = self.llm_pool.get_client(chat_model_arg)
                pid, resolved_model_id = self.llm_pool.registry.resolve(chat_model_arg)
                chat_model_arg = resolved_model_id
                model_used = f"{pid}/{resolved_model_id}"  # M51: 如实标注实际模型
            except ValueError as exc:
                # 模型不在注册表 / 凭据缺失：如实反馈，不静默降级（PREFERENCE_1）
                self._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                return _RouteDecision(
                    llm_client=self.llm,
                    model_used=self._default_model_label(),
                    chat_model_arg=chat_model_arg,
                    final_answer_override=model_unavailable_text(chat_model_arg, exc),
                )
        elif chat_model_arg is None and self.llm_pool is not None:
            # 会话级 override 路由：取 switch_model 写入的覆盖
            try:
                llm_client = self.llm_pool.get_client(sess.model_override)
                # M51: override 为全限定 ref；None 时为装配默认标签
                model_used = sess.model_override or self._default_model_label()
            except ValueError as exc:
                # resolve 失败（override 在 refresh_config 后失效等）：如实反馈，走默认 client
                self._record_action("action.llm_decide", "pool_resolve_failed", str(exc)[:200])
                llm_client = self.llm
                model_used = self._default_model_label()
        else:
            llm_client = self.llm
            model_used = self._default_model_label()
        # ── M53: 上下文超限前置守卫 ──
        # 载荷估算超模型注册表 context 上限 → 如实拒绝, 不发注定失败的请求
        # (如 kimi/k3-256k 仅 256K 窗口, 1M 预算装配的历史必被 provider 拒绝)
        # 未知模型 context（无 pool/裸标签）→ 跳过守卫, 不阻断
        context_limit = self._current_context_limit(model_used)
        if context_limit:
            refusal = self._check_context_fit(
                messages,
                tools_param,
                context_limit,
                model_used,
                # EVO-20260818: 输出预算占用窗口——local(16384)/minimax(65536) 等
                max_tokens=getattr(llm_client, "max_tokens", 0) or 0,
            )
            if refusal is not None:
                self._record_action("action.llm_decide", "context_overflow", refusal[:200])
                return _RouteDecision(
                    llm_client=llm_client,
                    model_used=model_used,
                    chat_model_arg=chat_model_arg,
                    final_answer_override=refusal,
                )
        return _RouteDecision(
            llm_client=llm_client,
            model_used=model_used,
            chat_model_arg=chat_model_arg,
        )

    def _default_model_label(self: LoopEngine) -> str:
        """M51: 装配默认模型的全限定标签（provider/model）.

        有 pool 时经注册表 resolve 为全限定 ref；无 pool / resolve 失败 → 裸模型名（零回归）.
        client 无 model 属性（如测试 FakeLLM）→ 返回空串（不伪造标签, 无 footer）.
        """
        model = getattr(self.llm, "model", "")
        if not model:
            return ""
        if self.llm_pool is not None:
            try:
                pid, mid = self.llm_pool.registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError as exc:  # fail-open：模型标签 resolve 失败回退裸名
                logger.debug("模型标签 resolve 失败，回退裸名（fail-open）: %s", exc)
        return model

    def _current_context_limit(self: LoopEngine, model_label: str) -> int | None:
        """M53: 查询当前模型的上下文上限（注册表 ModelSpec.context 元数据）.

        model_label 为全限定 "provider/model"（M51 路由已保证）；无 pool / 裸名 / 未知 → None（守卫跳过）.
        """
        if self.llm_pool is None or not model_label or "/" not in model_label:
            return None
        pid, mid = model_label.split("/", 1)
        spec = self.llm_pool.registry.providers.get(pid)
        if spec is None or mid not in spec.models:
            return None
        context = spec.models[mid].context
        return context if context and context > 0 else None

    def _provider_inject_notices(self: LoopEngine, model_label: str) -> bool:
        """该 provider 的推送式 system 注入是否进提交视图（P1-7 本地慢模型接入）.

        ⚠️ 2026-08-18 审计断点归因后废弃（spec §5.3.1-5 绝对化）: 提交层
        skip_injected_system 恒 True，推送式注入一律不进提交视图——本函数不再被调用，
        保留仅作 provider 配置面（inject_system_notices 字段解析）兼容与回退参考。
        provider 配置 inject_system_notices=false（本地模型用）→ False: 架构上报/预警/
        快照等仅落会话不进提交, system 前缀保持静态 → llama.cpp 引擎前缀缓存每轮命中
        （首 token 大幅缩短）。未知/未配置 → True（零回归）。
        """
        if self.llm_pool is None or "/" not in model_label:
            return True
        pid, _mid = model_label.split("/", 1)
        spec = self.llm_pool.registry.providers.get(pid)
        if spec is None:
            return True
        return spec.inject_system_notices

    @staticmethod
    def _local_tool_allowlist() -> frozenset[str]:
        """本地模型工具白名单（EVO-20260817 用户需求: 固化精简工具集 + 尾部追加）.

        lms-chat 文本工具协议/本地模型 prefill 下，全量 40+ 工具每轮文本化是 token 大头；
        只注入核心常用工具（固定前缀稳定），完整目录仍可经 get_tool_schema 按需读取。
        可经 env LOCAL_TOOL_NAMES 覆盖（逗号分隔）。
        """
        import os

        names = os.environ.get(
            "LOCAL_TOOL_NAMES",
            # 核心集: 信息获取+执行+检索+架构自查（get_tool_schema 自举完整 schema）
            "read_file,execute_command,search_files,web_fetch,web_search,"
            "get_tool_schema,architecture_status,search_records,search_archive,"
            "schedule,job_output,adjust_strategy",
        )
        return frozenset(n.strip() for n in names.split(",") if n.strip())

    def _filter_local_tools(
        self: LoopEngine, tool_schemas: list[dict], model_label: str
    ) -> list[dict]:
        """本地 provider（local/*）工具精简: 只注入白名单核心工具（固定前缀+省 token）.

        非 local provider → 原样返回（零回归）。
        """
        if not (model_label and "/" in model_label and model_label.split("/", 1)[0] == "local"):
            return tool_schemas
        allow = _RoutingMixin._local_tool_allowlist()
        kept = [t for t in tool_schemas if t.get("name") in allow]
        return kept if kept else tool_schemas

    @staticmethod
    def _check_context_fit(
        messages: list[dict],
        tools_param: list[dict],
        context_limit: int,
        model_label: str,
        max_tokens: int = 0,  # EVO-20260818: 输出预算（占用窗口，边距须扣除）
    ) -> str | None:
        """M53: 载荷 vs 模型上下文上限校验.

        估算口径: JSON 序列化字符数 / 2 ≈ tokens（中文混合保守估计）+ 10% 安全边距。
        EVO-20260818: 0.9 边距未覆盖 max_tokens 的场景（如 local 131K 窗口 +
        16K 输出 = 12.2% > 10%）——允许输入须再扣除输出预算，防"输入+输出超窗口"。
        超限 → 返回如实拒绝文案（不发送请求）；未超 → None。
        """
        payload_chars = sum(len(_json_dumps_args(m)) for m in messages) + len(
            _json_dumps_args({"tools": tools_param})
        )
        est_tokens = payload_chars // _CHARS_PER_TOKEN_EST
        allowed = int(context_limit * _CONTEXT_SAFETY_MARGIN)
        if max_tokens and max_tokens > 0:
            allowed = min(allowed, context_limit - max_tokens)
        if est_tokens <= allowed:
            return None
        return (
            f"[上下文超限] 本次请求载荷约 {est_tokens} tokens（按 {_CHARS_PER_TOKEN_EST} 字符/token 估算），"
            f"超过当前模型 {model_label} 的上下文上限 {context_limit}（安全边距后可用 {allowed}）。\n"
            f"建议：① /model 切换到更大窗口模型；② /new 开新会话（历史另存可经 search_archive 找回）；"
            f"③ 缩短本次输入。\n"
            f"（程序守卫：未发送请求，避免必失败调用；估算口径可能有误差，以 provider 实际判定为准）"
        )

    # ── 辅助 ──
    def _planned_model_label(self: LoopEngine, model: str | None, sess) -> str:
        """M54: 预测本轮将使用的模型标签（仅标签解析, 不建 client）.

        与路由同序: per-call override > 会话 override > 默认装配。
        用于在构造消息前计算模型窗口感知的压缩预算。
        """
        if model is not None and self.llm_pool is not None:
            try:
                pid, mid = self.llm_pool.registry.resolve(model)
                return f"{pid}/{mid}"
            except ValueError:
                return model
        if self.llm_pool is not None and sess.model_override:
            return sess.model_override
        return self._default_model_label()

    def _effective_history_budget(self: LoopEngine, model_label: str) -> int:
        """M54: 模型窗口感知的历史压缩预算.

        effective = min(全局预算, 模型 context × 2字符/token × 0.5 压缩系数,
        provider history_budget_chars 若配置)。
        例: k3-256k (262144 tokens) → ~26万字符（而不是全局 1M）→ 历史先压到窗口内再调用。
        例: local provider 配 history_budget_chars=12000（本地模型 prefill 随上下文线性涨,
        收紧预算显著缩短首 token 时延; 旧历史经压缩归档可检索, 信息零丢失）。
        无 pool / 未知模型 → 全局预算（零回归）。
        """
        global_budget = self._runtime_history_budget()
        # provider 级预算（本地慢模型收紧; 未配置 None → 跳过）
        provider_budget: int | None = None
        if self.llm_pool is not None and "/" in model_label:
            pid, _mid = model_label.split("/", 1)
            spec = self.llm_pool.registry.providers.get(pid)
            if spec is not None:
                provider_budget = spec.history_budget_chars
        if provider_budget:
            global_budget = min(global_budget, provider_budget)
        limit = self._current_context_limit(model_label)
        if not limit:
            return global_budget
        model_budget = int(limit * _CHARS_PER_TOKEN_EST * 0.5)
        return min(global_budget, model_budget)
