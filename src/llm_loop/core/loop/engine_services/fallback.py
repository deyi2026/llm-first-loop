"""FallbackService——模型降级链职责服务（R9-B5-W4-02c：_FallbackMixin 退役；宿主面显式经 self._host 标注，沿 runtime_params v4 惯例）.

design §5.4 行为规则表: 可降级 5xx/429/超时/网络；4xx 非 429 不降级（换模型无用）；
沿 fallback 链尝试候选，链全部失败如实汇总（原则 2 诚实反馈）。
(mixin 时代文件级 pyright 豁免已随宿主显式标注移除；如 pyright 报错回退并登记)
"""


from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import GuardRequestContext, LLMClient, LLMResponse
from llm_loop.llm.errors import (
    LLMError,
    LLMHTTPError,
    LLMNetworkError,
    LLMTimeoutError,
)

logger = logging.getLogger(__name__)


# ── EVO-20260816-37633629 ③: 降级提示 stamp 限频（nudge without nagging）──
# 同一降级对（from→to）在主消息流的提示 24h（FALLBACK_NOTICE_COOLDOWN_S）内只出现一次；
# 仅抑制消息注入，status.record_fallback / 审计 / action_trace 每次照常记录（可观测性不降级）。
# stamp 落盘 <data_dir>/state/fallback_notice_stamps.json（{kind: epoch}），进程重启仍生效；
# 路径随 Settings.data_dir 派生——测试/多工作区天然隔离，互不污染。
_DEFAULT_COOLDOWN_S = 86400.0  # 24h


def _notice_stamp_path(settings: object) -> Path:
    """stamp 文件路径（从 Settings.data_dir 派生；settings 缺失时回退 ./data）。"""
    base = getattr(settings, "data_dir", None) or "./data"
    return Path(str(base)) / "state" / "fallback_notice_stamps.json"


def _fallback_notice_cooldown_s() -> float:
    """限频间隔（秒）。env 每次调用重读，运行时调整即时生效；非法值回退默认 24h。"""
    raw = os.environ.get("FALLBACK_NOTICE_COOLDOWN_S", "").strip()
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError:
            pass  # 非法值 → 回落默认冷却时长（fail-open，不阻塞配置加载）
    return _DEFAULT_COOLDOWN_S


def _load_notice_stamps(path: Path) -> dict[str, float]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items()}
    except (OSError, ValueError, TypeError):
        pass  # 文件缺失/损坏 → 视为无历史（fail-open：下次提示照常注入）
    return {}


def _fallback_notice_suppressed(path: Path, kind: str) -> bool:
    """同类降级提示是否处于限频窗口内（True=应抑制消息注入）."""
    last = _load_notice_stamps(path).get(kind)
    return last is not None and (time.time() - last) < _fallback_notice_cooldown_s()


def _record_fallback_notice(path: Path, kind: str) -> None:
    """写入提示 stamp（best-effort：落盘失败不阻断降级主流程）."""
    try:
        stamps = _load_notice_stamps(path)
        stamps[kind] = time.time()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(stamps, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        logger.warning("fallback notice stamp 写入失败（fail-open，不影响降级）", exc_info=True)


class FallbackService:
    def __init__(self, host: LoopEngine) -> None:
        self._host = host
    # ── M49（design §5.4）: 降级逻辑辅助 ──

    @staticmethod
    def _is_fallback_eligible_error(exc: LLMError) -> bool:
        """判定异常是否可触发降级（design §5.4 行为规则表）.

        可降级:
        - LLMTimeoutError (请求超时)
        - LLMNetworkError (网络不可达)
        - LLMHTTPError(status_code >= 500)（上游服务错误）
        - LLMHTTPError(status_code == 429)（限流, design §5.4 表「5xx/429」）

        不可降级（design §5.4 行为规则表注: 4xx 非 429 请求本身有问题,换模型无用）:
        - LLMHTTPError(其他 4xx)：如 400（协议错误）、401（鉴权）、403（权限）、404（端点）
        - LLMProtocolError（响应解析异常, 非网络/上游问题）

        Args:
            exc: 当前 LLM 调用抛出的异常.

        Returns:
            True 可降级, False 走如实反馈路径.
        """
        if isinstance(exc, (LLMTimeoutError, LLMNetworkError)):
            return True
        if isinstance(exc, LLMHTTPError):
            return exc.status_code == 429 or exc.status_code >= 500
        return False

    @staticmethod
    def _merge_fallback_metadata(
        metadata: dict[str, Any], context_limit: Any, chars_per_token: float
    ) -> tuple[Any, float]:
        """把成功fallback的局部snapshot元数据合并回engine本轮响应观测。"""
        return (
            metadata.get("context_limit", context_limit),
            float(metadata.get("chars_per_token", chars_per_token)),
        )

    def _same_model_retry_gate(
        self,
        *,
        exc: LLMError,
        e1210_recovered: bool,
        is_default_assembled: bool,
        sess,
        messages: list[dict],
        tools_param: list[dict] | None,
        llm_client,
        chat_model_arg: str | None,
        session_id: str,
        effective_budget: int,
        rounds: int,
    ) -> LLMResponse | None:
        """D'-2.3 ②（R8.24 D-D6-5）engine 接线门（mixin 化——engine 只接线，
        行数预算见 test_loop_mixin_split 守卫）: 判定 + 限次重试。语义详见
        _same_model_retry_before_fallback docstring。"""
        if e1210_recovered or not is_default_assembled:
            return None
        if not self._is_fallback_eligible_error(exc):
            return None
        return self._same_model_retry_before_fallback(
            sess=sess, messages=messages, tools_param=tools_param,
            llm_client=llm_client, chat_model_arg=chat_model_arg,
            session_id=session_id, effective_budget=effective_budget, rounds=rounds,
        )

    def _same_model_retry_before_fallback(
        self,
        *,
        sess,
        messages: list[dict],
        tools_param: list[dict] | None,
        llm_client,
        chat_model_arg: str | None,
        session_id: str,
        effective_budget: int,
        rounds: int,
    ) -> LLMResponse | None:
        """D'-2.3 ②（R8.24 D-D6-5）: 切换降级前的同模型优先限次重试.

        触发条件: 会话存在工具回执（任务已有进行中产物——切换模型会改变工具
        协议投影/推理风格，代价高于原模型瞬时失败的重试）。无进行中产物的简单
        对话不重试（行为=现状零变化）。限次 ≤ LFL_SAME_MODEL_RETRY_MAX（默认 2，
        0=关闭回退现状；禁止无限次——限次防循环）。重试成功 → 返回响应（调用方
        落回正常路径，与 fallback 成功合流同构）；耗尽/不触发 → None（进链）。
        """
        try:
            max_retries = int(os.environ.get("LFL_SAME_MODEL_RETRY_MAX", "2"))
        except ValueError:
            max_retries = 2
        if max_retries <= 0:
            return None
        try:
            has_wip = any(
                getattr(m, "role", "") == "tool" for m in (sess.messages or [])
            )
        except Exception:  # noqa: BLE001 — 判据失败不重试（回退现状）
            has_wip = False
        if not has_wip:
            return None
        chat_kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools_param,
            "timeout_s": self._host._runtime_timeout(),
            "model": chat_model_arg,
        }
        if isinstance(llm_client, LLMClient):
            chat_kwargs["guard_context"] = GuardRequestContext(
                session_id=session_id,
                system_text=(
                    messages[0].get("content", "")
                    if messages and messages[0].get("role") == "system"
                    else None
                ),
                compress_count_this_run=getattr(self, "_compress_count_this_run", 0),
                history_budget=int(effective_budget or 0),
                breaker_active=self._host._cache_monitor.breaker_active_for(session_id),
                run_round=rounds,
                provider=getattr(llm_client, "provider", ""),
                model=chat_model_arg or getattr(llm_client, "model", ""),
            )
        for attempt in range(1, max_retries + 1):
            try:
                self._host._record_action(
                    "model.fallback",
                    "same_model_retry",
                    f"attempt={attempt}/{max_retries}",
                )
                return llm_client.chat(**chat_kwargs)
            except Exception as retry_exc:  # noqa: BLE001 — 单次失败继续限次
                logger.info(
                    "event=fallback.same_model_retry_failed attempt=%d/%d error=%s",
                    attempt,
                    max_retries,
                    type(retry_exc).__name__,
                )
        return None

    def _try_fallback_chain(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        timeout_s: float | None,
        primary_error: LLMError,
        session_id: str,
        run_round: int | None = None,
        metadata_out: dict[str, Any] | None = None,
        request_builder: Callable[[str, Any], tuple[list[dict], list[dict]]] | None = None,
    ) -> tuple[LLMResponse | None, list[Message], str | None]:
        """沿 fallback 链尝试下一个候选（design §5.4 行为规则表 + 原则 2 如实反馈）.

        行为:
        - 调用 pool.fallback_candidates() 取得合法降级候选列表
        - 空 → 返回 (None, [], None)（调用方走原异常如实反馈路径，零回归）
        - 逐个尝试,首个成功 → 返回 (resp, [notice_msg], 成功的模型 ref)（调用方把 notice_msg 注入 sess.messages）
        - 全部失败 → 返回 (None, [summary_msg], None)（调用方把 summary_msg 注入 sess.messages + 走原异常反馈路径）

        Args:
            messages: 本轮 LLM 调用所需消息列表.
            tools: 本轮工具 schema 列表.
            timeout_s: 本轮超时（继承当前循环超时）.
            primary_error: 主调用异常（用作首个原因 + 注入消息文本）.
            session_id: 当前会话 ID（供 record_fallback / 审计关联）.

        Returns:
            (resp, [messages_to_inject]).
            resp: 首个成功的降级响应（链全失败/无候选时为 None）。
            messages_to_inject: 提示消息（降级成功提示 / 链全失败汇总；空 list = 无需注入）。
        """
        if self._host.llm_pool is None:
            # 池未装配（如某些测试路径）→ 不启用降级, 调用方如实反馈
            return None, [], None

        # 真实ModelClientPool支持不可变snapshot：候选筛选、client构造和GuardRequestContext
        # 必须绑定同一表，避免refresh夹在fallback链中造成client=A而budget/context=B。
        # 最小duck pool（测试/外部注入）没有这些API时完整保留旧接口。
        snapshot_fn = getattr(self._host.llm_pool, "registry_snapshot", None)
        resolved_fn = getattr(self._host.llm_pool, "get_resolved_client", None)
        fallback_registry: Any = None
        if callable(snapshot_fn) and callable(resolved_fn):
            fallback_registry = snapshot_fn()

        if fallback_registry is not None:
            candidates = self._host.llm_pool.fallback_candidates(registry=fallback_registry)
        else:
            candidates = self._host.llm_pool.fallback_candidates()
        if not candidates:
            # MODEL_FALLBACKS 未配置/全非法 → 不启用降级（零回归路径）
            return None, [], None

        from_model = self._host.llm_pool.get_default_model()
        primary_reason = self._fallback_reason_label(primary_error)

        candidate_failures: list[tuple[str, str, str]] = []  # (model_ref, error_type, error_msg)
        provider_attempt_index = 0  # R8: count only requests that actually reach client.chat
        for ref in candidates:
            try:
                if fallback_registry is not None and callable(resolved_fn):
                    client, provider_id, model_id = cast(
                        Any, resolved_fn(ref, registry=fallback_registry)
                    )
                else:
                    # duck pool兼容：fallback_candidates公开契约仍是规范化provider/model ref。
                    # 模型id本身允许包含"/"，因此只切第一段provider。
                    provider_id, sep, model_id = ref.partition("/")
                    if not sep or not provider_id or not model_id:
                        raise ValueError(f"非法 fallback 模型引用: {ref!r}")
                    client = self._host.llm_pool.get_client(ref)
            except ValueError as exc:
                # 候选格式 / client 构造失败：记录后继续下一个候选（fail-soft）。
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            try:
                candidate_messages = messages
                candidate_tools = tools
                if request_builder is not None:
                    # R8.21/E05: a fallback may cross provider replay protocols.
                    # Never reuse a GLM/local-projected history for DeepSeek (missing
                    # required reasoning), nor leak DeepSeek historical CoT into a
                    # provider that does not require it. Rebuild from durable session
                    # truth using the exact same immutable fallback registry snapshot.
                    try:
                        candidate_messages, candidate_tools = request_builder(
                            f"{provider_id}/{model_id}", fallback_registry
                        )
                    except Exception as exc:  # noqa: BLE001 — wrong-provider reuse is unsafe
                        candidate_failures.append(
                            (ref, "RequestBuildError", str(exc)[:200])
                        )
                        continue
                chat_kwargs: dict = {
                    "messages": candidate_messages,
                    "tools": candidate_tools,
                    "timeout_s": timeout_s,
                    "model": model_id,
                }
                if isinstance(client, LLMClient):
                    fallback_label = f"{provider_id}/{model_id}"
                    fallback_budget = (
                        self._host._effective_history_budget(
                            fallback_label, registry_snapshot=fallback_registry
                        )
                        if fallback_registry is not None
                        else self._host._effective_history_budget(fallback_label)
                    )
                    chat_kwargs["guard_context"] = GuardRequestContext(
                        session_id=session_id,
                        system_text=(
                            candidate_messages[0].get("content", "")
                            if candidate_messages
                            and candidate_messages[0].get("role") == "system"
                            else None
                        ),
                        compress_count_this_run=getattr(
                            self, "_compress_count_this_run", 0
                        ),
                        history_budget=int(fallback_budget or 0),
                        run_round=run_round,
                        provider=provider_id,
                        model=model_id,
                    )
                # R8: attribution follows each actual fallback provider attempt,
                # not the primary request.meta snapshot.  Resolve failures are not
                # attempts and therefore do not consume an attempt index.
                provider_attempt_index += 1
                try:
                    from llm_loop.core.injection_profile import shadow_profile_event_payload
                    from llm_loop.event_log.model import EVENT_INJECTION_PROFILE_SHADOW

                    self._host._event_append(
                        session_id,
                        EVENT_INJECTION_PROFILE_SHADOW,
                        shadow_profile_event_payload(
                            model_label=f"{provider_id}/{model_id}",
                            registry=fallback_registry,
                            round_no=int(run_round or 0),
                            attempt_kind="fallback",
                            attempt_index=provider_attempt_index,
                        ),
                    )
                except Exception:  # noqa: BLE001 — audit must not affect fallback
                    logger.debug(
                        "fallback injection.profile.shadow 写入失败（fail-open）",
                        exc_info=True,
                    )
                resp = client.chat(**chat_kwargs)
            except LLMError as exc:
                # 该候选也失败, 继续尝试下一个; 记录 (model_ref, error_type, error_msg)
                candidate_failures.append((ref, type(exc).__name__, str(exc)[:200]))
                continue

            # ── 降级成功 ──
            to_model = ref
            if metadata_out is not None:
                label = f"{provider_id}/{model_id}"
                if fallback_registry is not None:
                    metadata_out["context_limit"] = self._host._current_context_limit(
                        label, registry_snapshot=fallback_registry
                    )
                    metadata_out["chars_per_token"] = self._host._provider_chars_per_token(
                        label, registry_snapshot=fallback_registry
                    )
                else:
                    metadata_out["context_limit"] = self._host._current_context_limit(label)
                    metadata_out["chars_per_token"] = self._host._provider_chars_per_token(label)
            reason = primary_reason
            self._host._record_action(
                "action.llm_decide",
                "fallback_success",
                f"{from_model}->{to_model}: {reason}",
            )
            notice = self._build_fallback_notice_message(
                from_model=from_model,
                to_model=to_model,
                reason=reason,
                primary_error=primary_error,
            )
            # 状态上报（architecture_status 可见降级态 + 原因, design §5.4）
            if self._host.status:
                self._host.status.record_fallback(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    session_id=session_id,
                )
            # 审计落盘
            if self._host.corrections is not None:
                self._host.corrections.audit_fallback_event(
                    from_model=from_model,
                    to_model=to_model,
                    reason=reason,
                    result_status="success",
                )
            # EVO-20260816-37633629 ③: stamp 限频——同类降级提示 24h 内主消息流只注入一次
            # （status/审计/action_trace 每次照常记录，可观测性不降级；仅消息注入被限频）。
            notices: list[Message] = []
            kind = f"{from_model}->{to_model}"
            stamp_path = _notice_stamp_path(getattr(self, "settings", None))
            if _fallback_notice_suppressed(stamp_path, kind):
                self._host._record_action(
                    "action.llm_decide",
                    "fallback_notice_suppressed",
                    f"{kind}（{int(_fallback_notice_cooldown_s())}s 内已提示, 本次仅记录不注入提示消息）",
                )
            else:
                _record_fallback_notice(stamp_path, kind)
                notices.append(notice)
            return resp, notices, ref

        # ── 链全失败 ──
        # 汇总提示: 包含主调用原因 + 每个候选失败原因（如实反馈, design §5.4 行为表）
        candidate_lines = [
            f"- {ref} ({etype}): {msg[:160]}" for ref, etype, msg in candidate_failures
        ]
        detail_lines = "\n".join(candidate_lines) if candidate_lines else "- (无可用候选)"
        summary = self._build_fallback_all_failed_message(
            from_model=from_model,
            primary_error=primary_error,
            candidate_lines=detail_lines,
        )
        # 审计（全失败 = result_status="all_failed"）
        if self._host.corrections is not None:
            self._host.corrections.audit_fallback_event(
                from_model=from_model,
                to_model="all_failed",
                reason=primary_reason,
                result_status="all_failed",
                detail=detail_lines,
            )
        # 状态: 不更新 record_fallback（链全失败不算"降级态"）
        return None, [summary], None

    @staticmethod
    def _fallback_reason_label(exc: LLMError) -> str:
        """将 LLM 异常映射为简短中文降级原因标注（注入消息用, 设计原则 2 如实反馈）."""
        if isinstance(exc, LLMTimeoutError):
            return "请求超时"
        if isinstance(exc, LLMNetworkError):
            return "网络不可达"
        if isinstance(exc, LLMHTTPError):
            if exc.status_code == 429:
                return "429 限流"
            return f"HTTP {exc.status_code} 上游错误"
        return type(exc).__name__

    @staticmethod
    def _build_fallback_notice_message(
        *,
        from_model: str,
        to_model: str,
        reason: str,
        primary_error: LLMError,
    ) -> Message:
        """构造降级成功提示消息（design §5.4 + 原则 2 如实反馈）.

        注入消息流后 AI 可见, 对齐 honesty.py 三件套格式（事实/原因/建议）。
        包含回执标识 [模型降级: X→Y, 原因: ...]（design §5.4 表标注, 设计要求必含）.
        """
        content = (
            f"[模型降级: {from_model}→{to_model}, 原因: {reason}] "
            f"事实: 默认模型 {from_model} 调用失败,已自动降级到 {to_model} 继续本次任务。\n"
            f"原因: {type(primary_error).__name__}: {str(primary_error)[:160]}。\n"
            f"建议: 当前已降级至 {to_model} 继续执行（可回退）；如需评估更合适模型，"
            f"可用 model_catalog 自主查看候选后决定（判断归你，程序仅提供事实）。"
        )
        return Message(
            role="system",
            content=content,
            source=MessageSource.SYSTEM,
        )

    @staticmethod
    def _build_fallback_all_failed_message(
        *,
        from_model: str,
        primary_error: LLMError,
        candidate_lines: str,
    ) -> Message:
        """构造链全失败汇总消息（design §5.4 行为规则表「链全部失败」+ 原则 2 如实反馈）."""
        content = (
            f"[模型降级] 事实: 默认模型 {from_model} 调用失败,降级链全部失败。\n"
            f"原因: 默认失败 {type(primary_error).__name__}: {str(primary_error)[:160]};\n"
            f"各候选失败:\n{candidate_lines}\n"
            f"建议: 检查网络/上游状态/降级链配置后重试。"
        )
        return Message(
            role="system",
            content=content,
            source=MessageSource.SYSTEM,
        )

