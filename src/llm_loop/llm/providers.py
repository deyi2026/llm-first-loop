"""Provider 注册表 + 模型能力元数据（M47 / design §5.1/§5.2/§5.5）.

设计要点:
- ProviderSpec.api_key_env 只存 env var 名字, 密钥从不落代码/JSON/日志 (DFX-SEC-02)
- 加载优先级: MODEL_PROVIDERS env JSON > {data_dir}/providers.local.json > {data_dir}/providers.json > LLM_* env 合成单 provider
- fail-soft: JSON 解析失败 → 回退 L0 合成 + degraded=True + degraded_reason 字段（如实标注, 不崩）
- resolve 支持 "provider/model" 全限定 + 裸模型名唯一匹配; 歧义/未知抛 ValueError 列候选

"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_loop.config import Settings
from llm_loop.llm.model_ids import canonical_model_id, loose_key

logger = logging.getLogger(__name__)

# P1-3（审计 #14）: 严格布尔解析白名单（bool("false")==True 陷阱修复）.
# 仅接受真正的 bool / 整数 1/0 / 以下字符串（大小写不敏感）; 其余值回退字段默认并告警.
_TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})
_FALSY_STRINGS = frozenset({"0", "false", "no", "off"})
# P1-3: context 缺失回退默认值（与 ModelSpec.context 默认一致, 全项目 context window 既有默认值）.
_DEFAULT_CONTEXT = 131072


@dataclass(frozen=True)
class ModelSpec:
    """模型能力元数据 (design §5.1).

    - context: 上下文窗口 (token 数)
    - thinking: legacy 兼容字段；历史含义为“是否支持显式思考控制参数”
    - reasoning_capable: 是否有事实证据可产生/返回 reasoning（与可否显式控制分离）
    - reasoning_control: 显式控制协议；legacy 保持旧行为，unknown/none 不发送控制字段
    - cost_tier: 成本档 (free/low/mid/high, 仅供展示, 不参与路由)
    - reasoning: 强推理能力 (R5: model_catalog 展示, AI 自主选模型)
    - long_context: 长上下文档 (R5: context >= 256K)
    - multimodal: 多模态（图片/音频/视频, R5)
    """

    context: int = 131072
    thinking: bool = False
    reasoning_capable: bool = False
    reasoning_control: str = "legacy"
    cost_tier: str = "mid"
    reasoning: bool = False
    long_context: bool = False
    multimodal: bool = False
    # Model-specific input/output budgets. These are operational caps, distinct from
    # the model's physical context window. None inherits the provider-level value.
    max_input_tokens: int | None = None
    max_tokens: int | None = None
    wire_protocol: str = "openai"  # P3-5: openai / anthropic / google（客户端协议分发）
    capability_tier: str = "unknown"  # strong/weak/unknown；unknown=无结论，禁止负面能力推断
    # Provider wire contract: whether this model accepts an explicit
    # ``tool_choice`` field.  True is the OpenAI-compatible default; models that
    # require provider-default tool selection (e.g. DeepSeek V4 thinking tool
    # calls) opt out in registry data instead of client-side provider guessing.
    send_tool_choice: bool = True
    # OpenAI-compatible reasoning representation contract. MiniMax-M3 recommends
    # reasoning_split=true so interleaved thinking is returned as structured
    # reasoning_details and can be replayed losslessly. This changes representation,
    # not whether the model is allowed/asked to think.
    reasoning_split: bool = False
    # Historical reasoning replay is a provider/model wire capability, not a quality heuristic.
    # Values: configured / none / tool_calls / full.
    reasoning_replay: str = "configured"
    # Optional model-owned mapping from LFL effort labels to chat-template effort labels.
    # Empty means do not send reasoning_effort through chat_template_kwargs (legacy behavior).
    reasoning_effort_map: dict[str, str] = field(default_factory=dict)
    # Factual runtime identity for observability only; never used for routing or prompt policy.
    runtime_identity: str = ""
    # Optional explicit generation profile. None means do not send that wire field.
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    min_p: float | None = None


@dataclass(frozen=True)
class ProviderSpec:
    """单个 provider 元数据.

    api_key_env 存 **env var 名字** (如 "DEEPSEEK_API_KEY"), 不存 key 本体.
    timeout_s: provider 级 LLM 调用超时（秒）; None = 用全局 LLM_TIMEOUT_S。
    本地慢模型（LM Studio 大模型 prefill 慢）在此放大, 云端保持全局默认（零回归）。
    history_budget_chars: provider 级历史/性能预算（字符）; None = 不增加 provider cap，
    由显式 runtime/global cap（如有）与当前模型物理窗口共同决定。本地模型 prefill 成本随上下文线性涨, 收紧预算可显著缩短
    首 token 时延（旧长历史经压缩归档可检索, 信息零丢失, 不损失可用性）。
    """

    id: str
    base_url: str
    api_key_env: str
    models: dict[str, ModelSpec] = field(default_factory=dict)
    default_model: str = ""
    timeout_s: float | None = None
    history_budget_chars: int | None = None
    max_input_tokens: int | None = None  # provider 级输入 token 预算（None=仅物理窗口/其它 cap）
    max_tokens: int | None = None  # 2026-08-15: provider 级输出预算（None=全局 LLM_MAX_TOKENS）
    chars_per_token: float | None = None  # EVO-20260824: provider 级字符/token 估算（None=全局 0.6）
    # deepseek 中文混合实测 1.676 tok/char → 0.6 chars/token；local qwen 中文 tokenizer 效率更高
    # （1 token≈1-1.5 中文字）→ 0.9。守卫/预算按 provider 取值，未配置回退全局（零回归）。


@dataclass(frozen=True)
class ProviderRegistry:
    """Provider 注册表（不可变快照）.

    degraded=True 表示加载过程中发生降级（JSON malformed → 回退 L0 合成）,
    此时 degraded_reason 字段如实说明原因, AI 工具应据此如实回执.
    """

    providers: dict[str, ProviderSpec]
    degraded: bool = False
    degraded_reason: str = ""

    def resolve(self, model_ref: str) -> tuple[str, str]:
        """解析 model_ref → (provider_id, model_id).

        支持:
        - "provider/model" 全限定: 直接按字段匹配
        - 裸模型名: 在所有 provider 中唯一匹配则解析; 歧义/未知抛 ValueError 列候选
        - 双命名归一（2026-09-12）: exact 未命中时, 同一物理模型的别名形态
          （LM Studio 绝对路径 ↔ HF org/name）唯一则解析; 多候选仍拒绝（fail-loud）
        """
        if "/" in model_ref:
            pid, mid = model_ref.split("/", 1)
            spec = self.providers.get(pid)
            if spec is None:
                # 2026-09-12: 引用可能是裸的 org/name 或 LM Studio 路径形态
                # （如 "ornith-ai/X" 或 "/Users/.../.lmstudio/models/org/X"）,
                # 它们含 "/" 但不是 provider 前缀。pid 未知时把**整串**按裸名解析,
                # 唯一命中才接受, 否则保持原"未知 provider"错误语义。
                try:
                    return self._resolve_bare(model_ref)
                except ValueError as bare_err:
                    # 保持"未知 provider"语义（既有契约）, 但带上裸名解析的具体错误,
                    # 避免吞掉短名桥接的歧义/候选信息。
                    detail = str(bare_err).splitlines()[0]
                    raise ValueError(f"未知 provider: {pid}（{detail}）") from None
            if mid not in spec.models:
                # 归一回退（限定 provider 内）: 引用形态与注册形态不同但规范形态相同
                canonical_ref = canonical_model_id(mid)
                within = [
                    m for m in spec.models if canonical_model_id(m) == canonical_ref
                ]
                if len(within) == 1:
                    return pid, within[0]
                # 短名桥接（唯一匹配守卫）: 服务端 /v1/models 的 HF/路径形态
                # 与注册短名（org 段剥离 + casefold 后一致）唯一对应时解析。
                # 例: 注册 "ornith-1.5-35b-a3b-mlx" ← 引用 "ornith-ai/Ornith-1.5-35B-A3B-MLX"
                if len(within) == 0:
                    loose = loose_key(mid)
                    within_loose = [m for m in spec.models if loose_key(m) == loose]
                    if len(within_loose) == 1:
                        return pid, within_loose[0]
                listed = ", ".join(sorted(spec.models)) or "(无)"
                raise ValueError(
                    f"provider '{pid}' 不存在模型 '{mid}'"
                    f"（规范形态 '{canonical_ref}' 候选: {listed}）"
                )
            return pid, mid

        return self._resolve_bare(model_ref)

    def _resolve_bare(self, model_ref: str) -> tuple[str, str]:
        """裸模型名解析（跨 provider）: exact 优先 → 规范归一回退 → 歧义/未知拒绝."""
        matches: list[tuple[str, str]] = []
        for pid, spec in self.providers.items():
            if model_ref in spec.models:
                matches.append((pid, model_ref))

        if not matches:
            # 归一回退（跨 provider）: 别名形态与注册形态不同但规范形态相同
            canonical_ref = canonical_model_id(model_ref)
            alias_matches: list[tuple[str, str]] = [
                (pid, mid)
                for pid, spec in self.providers.items()
                for mid in spec.models
                if canonical_model_id(mid) == canonical_ref
            ]
            if len(alias_matches) == 1:
                return alias_matches[0]
            if len(alias_matches) > 1:
                listed = ", ".join(f"{p}/{m}" for p, m in alias_matches)
                raise ValueError(
                    f"模型 '{model_ref}'（规范形态 '{canonical_ref}'）"
                    f"存在多个注册条目: {listed}，请用全限定名"
                )
            # 短名桥接（唯一匹配守卫）: HF/路径形态 → 注册短名
            loose = loose_key(model_ref)
            loose_matches: list[tuple[str, str]] = [
                (pid, mid)
                for pid, spec in self.providers.items()
                for mid in spec.models
                if loose_key(mid) == loose
            ]
            if len(loose_matches) == 1:
                return loose_matches[0]
            if len(loose_matches) > 1:
                listed = ", ".join(f"{p}/{m}" for p, m in loose_matches)
                raise ValueError(
                    f"模型 '{model_ref}' 短名桥接命中多个条目: {listed}，请用全限定名"
                )
            candidates = [f"{p}/{m}" for p, s in self.providers.items() for m in s.models]
            raise ValueError(
                f"模型 '{model_ref}' 不在注册表中。候选: {', '.join(candidates) or '(无)'}"
            )
        if len(matches) > 1:
            listed = ", ".join(f"{p}/{m}" for p, m in matches)
            raise ValueError(f"模型 '{model_ref}' 存在多个 provider 匹配: {listed}")
        return matches[0]

    def supports_thinking(self, provider_id: str, model_id: str) -> bool:
        """查询 ModelSpec.thinking 字段 (消除原 _thinking_supported() 硬编码 deepseek.com)."""
        spec = self.providers.get(provider_id)
        if spec is None or model_id not in spec.models:
            return False
        return spec.models[model_id].thinking

    def reasoning_contract(self, provider_id: str, model_id: str) -> tuple[bool, str]:
        """返回 (reasoning_capable, reasoning_control) 的模型事实合同。"""
        spec = self.providers.get(provider_id)
        if spec is None or model_id not in spec.models:
            return False, "unknown"
        model = spec.models[model_id]
        # Direct programmatic ModelSpec(...) construction predates the new field;
        # affirmative legacy reasoning/thinking facts remain capability evidence.
        capable = bool(model.reasoning_capable or model.reasoning or model.thinking)
        return capable, model.reasoning_control

    def catalog_summary(self) -> str:
        """人类可读目录（供后续 model_catalog 工具复用, M48 对接）.

        格式:
          [provider_id] base_url=...
            - model_id: context=..., thinking=✓/✗, cost=...
        """
        lines: list[str] = []
        for pid, spec in self.providers.items():
            tags = []
            if spec.timeout_s:
                tags.append(f"timeout={spec.timeout_s:g}s")
            if spec.history_budget_chars:
                tags.append(f"history_budget={spec.history_budget_chars}")
            if spec.max_input_tokens:
                tags.append(f"max_input_tokens={spec.max_input_tokens}")
            if spec.max_tokens:
                tags.append(f"max_tokens={spec.max_tokens}")
            tag_str = (" " + " ".join(tags)) if tags else ""
            lines.append(f"[{pid}] base_url={spec.base_url}{tag_str}")
            shown_canonical: set[str] = set()
            for mid, mspec in spec.models.items():
                capable, control = self.reasoning_contract(pid, mid)
                canon = canonical_model_id(mid)
                if canon in shown_canonical and canon != mid:
                    # 同一物理模型的别名形态: 只显示一行别名指向, 不重复规格
                    lines.append(f"  - {mid} → alias of {canon}")
                    continue
                shown_canonical.add(canon)
                alias_note = "" if canon == mid else f", canonical={canon}"
                lines.append(
                    f"  - {mid}: context={mspec.context}, "
                    f"max_input_tokens={mspec.max_input_tokens or spec.max_input_tokens or 'physical'}, "
                    f"max_tokens={mspec.max_tokens or spec.max_tokens or 'global'}, "
                    f"reasoning_capable={'✓' if capable else '✗'}, "
                    f"reasoning_control={control}, cost={mspec.cost_tier}{alias_note}"
                )
        if self.degraded:
            lines.append(f"[degraded: {self.degraded_reason}]")
        return "\n".join(lines)

    def client_params(self, provider_id: str, model_id: str) -> dict[str, Any]:
        """返回构造 LLMClient 所需的 dict: {api_key, base_url, model}.

        api_key **此时才**从 os.environ[api_key_env] 读取（按需、不预读、不落内部状态）.
        api_key_env 为空字符串表示无需认证（如本地 provider）.
        key 缺失时如实报错（不在加载时崩, 调用时崩, 含 env var 名字）.
        """
        spec = self.providers.get(provider_id)
        if spec is None:
            raise ValueError(f"未知 provider: {provider_id}")
        if model_id not in spec.models:
            raise ValueError(f"provider '{provider_id}' 不存在模型 '{model_id}'")

        api_key = ""
        if spec.api_key_env:
            api_key = os.environ.get(spec.api_key_env, "")
            if not api_key:
                raise ValueError(
                    f"provider '{provider_id}' 缺少 api_key: "
                    f"环境变量 {spec.api_key_env} 未设置或为空"
                )

        base_url = spec.base_url
        # 2026-08-22 直连 llama-server（输入提速, KV 缓存命中）: local provider 指向
        # LM Studio 代理（1234）时自动发现真实 llama-server 端口/key 直连——代理每次
        # 新请求不复用 KV（全量 prefill 慢）; 直连同 slot 固定前缀 → KV 命中 97%
        # （只 prefill 增量 → 输入秒级）。LMS_DIRECT=0 关闭（回退代理, 零回归）。
        if (
            provider_id == "local"
            and os.environ.get("LMS_DIRECT", "1") == "1"
            and ("localhost" in base_url or "127.0.0.1" in base_url)
        ):
            try:
                _lms = _discover_llama_server(model_id)
                if _lms:
                    base_url, api_key = _lms
            except Exception:  # noqa: BLE001 — 发现失败回退配置（fail-open）
                pass

        return {
            "api_key": api_key,
            "base_url": base_url,
            "model": model_id,
            # provider 级超时仅显式配置时下发（None 由 pool 回退全局 LLM_TIMEOUT_S）;
            # 未配置不含该键, 与既有返回契约零差异
            **({"timeout_s": spec.timeout_s} if spec.timeout_s is not None else {}),
            **(
                {"max_tokens": spec.models[model_id].max_tokens}
                if spec.models[model_id].max_tokens is not None
                else ({"max_tokens": spec.max_tokens} if spec.max_tokens is not None else {})
            ),
            # P3-5: 协议（模型级元数据；默认 openai 零回归）
            **({"wire_protocol": spec.models[model_id].wire_protocol} if spec.models[model_id].wire_protocol != "openai" else {}),
            # 仅非默认值下发，保持旧 client_params 结构零回归。
            **({"send_tool_choice": False} if not spec.models[model_id].send_tool_choice else {}),
            **({"reasoning_split": True} if spec.models[model_id].reasoning_split else {}),
            **({"reasoning_effort_map": dict(spec.models[model_id].reasoning_effort_map)} if spec.models[model_id].reasoning_effort_map else {}),
            **({"temperature": spec.models[model_id].temperature} if spec.models[model_id].temperature is not None else {}),
            **({"top_p": spec.models[model_id].top_p} if spec.models[model_id].top_p is not None else {}),
            **({"top_k": spec.models[model_id].top_k} if spec.models[model_id].top_k is not None else {}),
            **({"min_p": spec.models[model_id].min_p} if spec.models[model_id].min_p is not None else {}),
        }


# ── 加载通道 ──


def _provider_id_from_base_url(base_url: str) -> str:
    """从 base_url 推导 provider id (L0 合成路径, zero regression).

    推导规则:
    - 含 deepseek.com → "deepseek"
    - 含 minimax → "minimax"
    - 其他 → "default"
    """
    url = base_url.lower()
    if "deepseek.com" in url:
        return "deepseek"
    if "minimax" in url:
        return "minimax"
    return "default"


def _parse_bool_field(
    pid: str,
    mid: str,
    field: str,
    mval: dict[str, Any],
    *,
    default: bool = False,
) -> bool:
    """解析单布尔字段（P1-3 审计 #14: bool("false")==True 陷阱修复）.

    仅接受真正的 bool / 整数 1/0（与 bool() 一致, 零回归）/ 白名单字符串
    "1/true/yes/on"（True）/ "0/false/no/off"（False）, 大小写不敏感;
    其余值（含任意非白名单字符串）→ logger.warning 如实告警 + 回退字段默认 False
    （不静默 bool(), 禁用配置不再被静默启用）.
    """
    value = mval.get(field, default)
    if isinstance(value, int):  # bool 是 int 子类, 一并覆盖
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUTHY_STRINGS:
            return True
        if v in _FALSY_STRINGS:
            return False
    logger.warning(
        "模型 %s/%s 字段 %s=%r 非合法布尔（仅接受 true/false/1/0/yes/no/on/off），"
        "回退默认 %s",
        pid, mid, field, value, default,
    )
    return default


def _parse_context(value: Any) -> int:
    """解析 context（P1-3 审计 #14: int() 转换异常不再杀死整个注册表）.

    缺失 → 回退 131072（与 ModelSpec.context 默认一致）;
    非法（非整数, 如 "abc"）→ 抛 ValueError, 由调用方 per-条目 try/except
    跳过该条并告警（含 provider id / model 名, 不拖垮整个注册表加载）.
    """
    if value is None:
        return _DEFAULT_CONTEXT
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"context={value!r} 非整数: {exc}") from exc


def _parse_model_max_tokens(pid: str, mid: str, value: Any) -> int | None:
    """Parse optional per-model output ceiling; invalid values fail open to provider default."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "模型 %s/%s max_tokens=%r 非整数，回退 provider/global 输出预算",
            pid, mid, value,
        )
        return None
    if parsed <= 0:
        logger.warning(
            "模型 %s/%s max_tokens=%r 非正数，回退 provider/global 输出预算",
            pid, mid, value,
        )
        return None
    return parsed


def _parse_model_max_input_tokens(pid: str, mid: str, value: Any) -> int | None:
    """Parse optional per-model input-token budget; invalid values inherit provider cap."""
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning(
            "模型 %s/%s max_input_tokens=%r 非整数，回退 provider/物理窗口预算",
            pid, mid, value,
        )
        return None
    if parsed <= 0:
        logger.warning(
            "模型 %s/%s max_input_tokens=%r 非正数，回退 provider/物理窗口预算",
            pid, mid, value,
        )
        return None
    return parsed


def _parse_optional_float(pid: str, mid: str, field: str, value: Any, *, minimum: float = 0.0, maximum: float | None = None, exclusive_min: bool = False) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        logger.warning("模型 %s/%s %s=%r 非数字，忽略该显式生成参数", pid, mid, field, value)
        return None
    if (parsed <= minimum if exclusive_min else parsed < minimum) or (maximum is not None and parsed > maximum):
        logger.warning("模型 %s/%s %s=%r 超出允许范围，忽略该显式生成参数", pid, mid, field, value)
        return None
    return parsed


def _parse_optional_nonnegative_int(pid: str, mid: str, field: str, value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        logger.warning("模型 %s/%s %s=%r 非整数，忽略该显式生成参数", pid, mid, field, value)
        return None
    if parsed < 0:
        logger.warning("模型 %s/%s %s=%r 为负数，忽略该显式生成参数", pid, mid, field, value)
        return None
    return parsed


def _parse_wire_protocol(pid: str, mid: str, mval: dict[str, Any]) -> str:
    """P3-5: 协议字段解析（openai/anthropic/google/lms-chat 白名单；非法回退 openai 如实告警）.

    lms-chat（EVO-20260817 用户需求）: LM Studio 新版 /api/v1/chat 端点——input 模态数组、
    SSE 流式、reasoning/message 分离；无原生工具，走文本工具协议（见 client.py _stream_lms_chat）。
    """
    raw = str(mval.get("wire_protocol", "openai")).strip().lower()
    if raw in {"openai", "anthropic", "google", "lms-chat"}:
        return raw
    if raw != "openai":
        logger.warning(
            "模型 %s/%s 的 wire_protocol=%r 非法（支持 openai/anthropic/google/lms-chat），回退 openai",
            pid, mid, raw,
        )
    return "openai"


def _parse_reasoning_control(pid: str, mid: str, mval: dict[str, Any]) -> str:
    """解析 reasoning 控制协议；非法显式值 fail-safe 到 unknown，不猜控制格式。"""
    raw = str(mval.get("reasoning_control", "legacy")).strip().lower()
    allowed = {
        "legacy", "unknown", "none", "thinking_type", "chat_template",
        "always_on_effort",
    }
    if raw in allowed:
        return raw
    logger.warning(
        "模型 %s/%s 的 reasoning_control=%r 非法（支持 %s），回退 unknown",
        pid, mid, raw, "/".join(sorted(allowed)),
    )
    return "unknown"




def _parse_reasoning_effort_map(pid: str, mid: str, mval: dict[str, Any]) -> dict[str, str]:
    """Parse explicit model-owned effort label mapping for chat-template control.

    The runtime never guesses template vocabulary. Missing/invalid mappings preserve
    legacy behavior (enable_thinking only). Keys are LFL request labels; values are
    provider/template labels and are kept short/opaque after a conservative token check.
    """
    raw = mval.get("reasoning_effort_map")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        logger.warning(
            "模型 %s/%s reasoning_effort_map=%r 非对象，忽略该映射", pid, mid, raw
        )
        return {}
    allowed_keys = {"low", "medium", "high", "max", "xhigh"}
    out: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key).strip().lower()
        v = str(value).strip().lower()
        if k not in allowed_keys or not re.fullmatch(r"[a-z0-9_.-]{1,32}", v):
            logger.warning(
                "模型 %s/%s reasoning_effort_map 条目 %r:%r 非法，忽略",
                pid, mid, key, value,
            )
            continue
        out[k] = v
    return out


def _parse_reasoning_replay(pid: str, mid: str, mval: dict[str, Any]) -> str:
    """Parse the model historical-reasoning replay wire contract."""
    raw = str(mval.get("reasoning_replay", "configured")).strip().lower()
    allowed = {"configured", "none", "tool_calls", "full"}
    if raw in allowed:
        return raw
    logger.warning(
        "模型 %s/%s 的 reasoning_replay=%r 非法（支持 %s），回退 configured",
        pid, mid, raw, "/".join(sorted(allowed)),
    )
    return "configured"


def _qwen_model_signature(text: str) -> tuple[str, str] | None:
    """提取 Qwen 主版本/规模（如 Qwen3.8-27B → ("3.8", "27")）供安全消歧。"""
    match = re.search(
        r"qwen\s*([0-9]+(?:[._][0-9]+)*)[^0-9a-z]+([0-9]+(?:\.[0-9]+)?)b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    return match.group(1).replace("_", "."), match.group(2)


def _discover_llama_server(requested_model: str | None = None) -> tuple[str, str] | None:
    """扫描本地 llama-server；多候选时仅在 requested model 可唯一匹配时直连。

    LM Studio 可能同时托管多个 Qwen llama-server。旧实现返回 ``ps aux`` 中第一个
    Qwen 进程，会把请求模型 B 静默送到模型 A，同时上层仍标注 B。现在先收集全部
    有效候选：
    - 只有一个候选：requested model 无可识别签名时保持旧兼容；若双方签名可识别则必须一致；
    - 多候选：按模型名紧凑匹配或 Qwen 主版本+规模签名唯一消歧；
    - 无法唯一匹配：返回 None，让调用方回退配置 base_url，绝不猜第一个。
    """
    try:
        import subprocess

        out = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        ).stdout
        candidates: list[tuple[str, str, str]] = []
        for line in out.splitlines():
            lower_line = line.lower()
            if "llama-server" not in lower_line or "qwen" not in lower_line:
                continue
            parts = line.split()
            port: str | None = None
            api_key = ""
            for i, part in enumerate(parts):
                if part == "--port" and i + 1 < len(parts):
                    port = parts[i + 1]
                elif part.startswith("--port="):
                    port = part.split("=", 1)[1]
                elif part == "--api-key" and i + 1 < len(parts):
                    api_key = parts[i + 1]
                elif part.startswith("--api-key="):
                    api_key = part.split("=", 1)[1]
            if not port:
                continue
            try:
                port_num = int(port)
            except ValueError:
                continue
            if not 1 <= port_num <= 65535:
                continue
            candidates.append((f"http://127.0.0.1:{port_num}/v1", api_key, line))

        if not candidates:
            return None
        if len(candidates) == 1:
            base_url, api_key, line = candidates[0]
            requested_sig = _qwen_model_signature(requested_model or "")
            if requested_sig is not None:
                candidate_sig = _qwen_model_signature(line)
                if candidate_sig != requested_sig:
                    return None
            return base_url, api_key
        if not requested_model:
            return None

        requested_leaf = requested_model.rsplit("/", 1)[-1]
        requested_compact = re.sub(r"[^a-z0-9]+", "", requested_leaf.lower())
        exactish = [
            candidate
            for candidate in candidates
            if requested_compact
            and requested_compact in re.sub(r"[^a-z0-9]+", "", candidate[2].lower())
        ]
        if len(exactish) == 1:
            base_url, api_key, _line = exactish[0]
            return base_url, api_key
        if len(exactish) > 1:
            return None

        requested_sig = _qwen_model_signature(requested_model)
        if requested_sig is None:
            return None
        signature_matches = [
            candidate
            for candidate in candidates
            if _qwen_model_signature(candidate[2]) == requested_sig
        ]
        if len(signature_matches) == 1:
            base_url, api_key, _line = signature_matches[0]
            return base_url, api_key
        return None
    except Exception:  # noqa: BLE001 — 发现失败 fail-open
        return None


def _parse_capability_tier(pid: str, mid: str, mval: dict[str, Any]) -> str:
    """T-P2-1-1: capability_tier 解析（白名单 strong/weak/unknown, spec §10.4）.

    缺失 → unknown（无能力结论，不作负面推断）;
    非法 → unknown + warning 如实告警（不拖垮注册表加载）。
    """
    if "capability_tier" not in mval:
        logger.info(
            "模型 %s/%s 未配置 capability_tier，按 unknown 处理（无能力结论，fail-open）",
            pid, mid,
        )
        return "unknown"
    v = str(mval["capability_tier"]).strip().lower()
    if v in ("strong", "weak", "unknown"):
        return v
    logger.warning(
        "模型 %s/%s capability_tier=%r 非白名单值（strong/weak/unknown），回退 unknown",
        pid, mid, mval["capability_tier"],
    )
    return "unknown"


def _parse_model_spec(pid: str, mid: str, mval: dict[str, Any]) -> ModelSpec:
    """解析单模型条目 → ModelSpec（P1-3 审计 #14 加固）.

    布尔字段走严格解析（bool("false")==True 陷阱修复）+ context 非法如实报错;
    context 非法抛 ValueError, 由调用方 per-条目 try/except 跳过该条（不拖垮注册表）.
    """
    thinking = _parse_bool_field(pid, mid, "thinking", mval)
    reasoning = _parse_bool_field(pid, mid, "reasoning", mval)
    reasoning_capable = (
        _parse_bool_field(pid, mid, "reasoning_capable", mval)
        if "reasoning_capable" in mval
        else bool(reasoning or thinking)
    )
    return ModelSpec(
        context=_parse_context(mval.get("context")),
        thinking=thinking,
        reasoning_capable=reasoning_capable,
        reasoning_control=_parse_reasoning_control(pid, mid, mval),
        cost_tier=str(mval.get("cost_tier", "mid")),
        reasoning=reasoning,
        long_context=_parse_bool_field(pid, mid, "long_context", mval),
        multimodal=_parse_bool_field(pid, mid, "multimodal", mval),
        max_input_tokens=_parse_model_max_input_tokens(pid, mid, mval.get("max_input_tokens")),
        max_tokens=_parse_model_max_tokens(pid, mid, mval.get("max_tokens")),
        # P3-5: 协议白名单（非法值回退 openai + 如实告警，不拖垮注册表）
        wire_protocol=_parse_wire_protocol(pid, mid, mval),
        # T-P2-1-1: 能力档白名单（缺失/非法 → unknown + 降级日志，不拖垮注册表）
        capability_tier=_parse_capability_tier(pid, mid, mval),
        send_tool_choice=_parse_bool_field(
            pid, mid, "send_tool_choice", mval, default=True
        ),
        reasoning_split=_parse_bool_field(
            pid, mid, "reasoning_split", mval, default=False
        ),
        reasoning_replay=_parse_reasoning_replay(pid, mid, mval),
        reasoning_effort_map=_parse_reasoning_effort_map(pid, mid, mval),
        runtime_identity=str(mval.get("runtime_identity", "") or "").strip(),
        temperature=_parse_optional_float(pid, mid, "temperature", mval.get("temperature")),
        top_p=_parse_optional_float(pid, mid, "top_p", mval.get("top_p"), maximum=1.0, exclusive_min=True),
        top_k=_parse_optional_nonnegative_int(pid, mid, "top_k", mval.get("top_k")),
        min_p=_parse_optional_float(pid, mid, "min_p", mval.get("min_p"), maximum=1.0),
    )


def _parse_providers_dict(raw: dict[str, Any]) -> dict[str, ProviderSpec]:
    """解析 JSON dict → ProviderSpec dict.

    P1-3（审计 #14）: 每条 provider / 模型配置独立 try/except——单条非法
    （context 非整数等）→ 跳过该条 + logger.warning 如实记录原因（含 provider id /
    model 名）, 不再让 ValueError 杀死整个注册表加载（此前会触发 fail-soft 回落 L0,
    所有 provider 全灭）。
    JSON 整体非法 → 由上层 catch 触发 fail-soft. 此处不抛异常.
    """
    out: dict[str, ProviderSpec] = {}
    for pid, val in raw.items():
        try:
            if not isinstance(val, dict):
                logger.warning("provider 条目 %r 非 dict, 跳过", pid)
                continue
            raw_enabled = val.get("enabled", True)
            if isinstance(raw_enabled, bool):
                provider_enabled = raw_enabled
            elif isinstance(raw_enabled, int) and raw_enabled in (0, 1):
                provider_enabled = bool(raw_enabled)
            elif isinstance(raw_enabled, str) and raw_enabled.strip().lower() in (_TRUTHY_STRINGS | _FALSY_STRINGS):
                provider_enabled = raw_enabled.strip().lower() in _TRUTHY_STRINGS
            else:
                logger.warning("provider 条目 %r enabled=%r 非合法布尔，按启用处理", pid, raw_enabled)
                provider_enabled = True
            if not provider_enabled:
                continue
            base_url = str(val.get("base_url", ""))
            api_key_env = str(val.get("api_key_env", ""))
            models_raw = val.get("models", {})
            models: dict[str, ModelSpec] = {}
            if isinstance(models_raw, dict):
                for mid, mval in models_raw.items():
                    try:
                        # P1-3: 单模型条目独立 try/except（非法条目跳过, 不拖垮同 provider 其余模型）
                        if isinstance(mval, dict):
                            if not _parse_bool_field(pid, mid, "enabled", mval, default=True):
                                continue
                            models[mid] = _parse_model_spec(pid, mid, mval)
                        else:
                            models[mid] = ModelSpec()
                    except (ValueError, TypeError) as exc:
                        logger.warning(
                            "模型条目 %s/%s 配置非法, 跳过该条（其余模型/Provider 正常加载）: %s",
                            pid, mid, exc,
                        )
            default_model = str(val.get("default_model", "")) or ""
            # provider 级超时（秒）: 仅合法正数接受; 非法/缺失 → None（全局 LLM_TIMEOUT_S 兜底）
            timeout_s: float | None = None
            raw_timeout = val.get("timeout_s")
            if raw_timeout is not None:
                try:
                    parsed = float(raw_timeout)
                    if parsed > 0:
                        timeout_s = parsed
                    else:
                        logger.warning(
                            "provider 条目 %r 的 timeout_s=%r 非正数, 回退全局超时",
                            pid, raw_timeout,
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        "provider 条目 %r 的 timeout_s=%r 非法, 回退全局超时",
                        pid, raw_timeout,
                    )
            # provider 级输入 token 预算：只限制模型可见输入，不伪造物理 context。
            # 非法/缺失 → None（由物理窗口 / output reserve / 其它显式 cap 决定）。
            max_input_tokens: int | None = None
            raw_input_tokens = val.get("max_input_tokens")
            if raw_input_tokens is not None:
                try:
                    parsed_input_tokens = int(raw_input_tokens)
                    if parsed_input_tokens > 0:
                        max_input_tokens = parsed_input_tokens
                    else:
                        logger.warning(
                            "provider 条目 %r 的 max_input_tokens=%r 非正数, 回退物理窗口预算",
                            pid, raw_input_tokens,
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        "provider 条目 %r 的 max_input_tokens=%r 非法, 回退物理窗口预算",
                        pid, raw_input_tokens,
                    )
            # provider 级输出预算（token）: 2026-08-15 显式 max_tokens（长分析模型放大）;
            # 非法/缺失 → None（全局 LLM_MAX_TOKENS 兜底）
            max_tokens: int | None = None
            raw_tokens = val.get("max_tokens")
            if raw_tokens is not None:
                try:
                    parsed_tokens = int(raw_tokens)
                    if parsed_tokens > 0:
                        max_tokens = parsed_tokens
                    else:
                        logger.warning(
                            "provider 条目 %r 的 max_tokens=%r 非正数, 回退全局预算",
                            pid, raw_tokens,
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        "provider 条目 %r 的 max_tokens=%r 非法, 回退全局预算",
                        pid, raw_tokens,
                    )
            # provider 级历史注入预算（字符）: 本地慢模型收紧以缩短 prefill;
            # 非法/缺失 → None（不增加 provider cap；交由显式全局 cap/模型物理窗口）
            history_budget_chars: int | None = None
            raw_budget = val.get("history_budget_chars")
            if raw_budget is not None:
                try:
                    parsed_budget = int(raw_budget)
                    if parsed_budget > 0:
                        history_budget_chars = parsed_budget
                    else:
                        logger.warning(
                            "provider 条目 %r 的 history_budget_chars=%r 非正数, 回退全局预算",
                            pid, raw_budget,
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        "provider 条目 %r 的 history_budget_chars=%r 非法, 回退全局预算",
                        pid, raw_budget,
                    )
            # EVO-20260824: provider 级字符/token 估算（chars_per_token）——本地 qwen tokenizer
            # 效率高于 deepseek（1 token≈1-1.5 中文字），统一 0.6 会让本地载荷高估 1.7-2 倍
            # → 守卫误拦 + 预算过紧。非法/缺失 → None（全局 0.6 兜底，零回归）。
            chars_per_token: float | None = None
            raw_cpt = val.get("chars_per_token")
            if raw_cpt is not None:
                try:
                    parsed_cpt = float(raw_cpt)
                    if parsed_cpt > 0:
                        chars_per_token = parsed_cpt
                    else:
                        logger.warning(
                            "provider 条目 %r 的 chars_per_token=%r 非正数, 回退全局估算",
                            pid, raw_cpt,
                        )
                except (ValueError, TypeError):
                    logger.warning(
                        "provider 条目 %r 的 chars_per_token=%r 非法, 回退全局估算",
                        pid, raw_cpt,
                    )
            out[str(pid)] = ProviderSpec(
                id=str(pid),
                base_url=base_url,
                api_key_env=api_key_env,
                models=models,
                default_model=default_model,
                timeout_s=timeout_s,
                history_budget_chars=history_budget_chars,
                max_input_tokens=max_input_tokens,
                max_tokens=max_tokens,
                chars_per_token=chars_per_token,
            )
        except (ValueError, TypeError) as exc:
            # P1-3: provider 条目级兜底（意外转换异常也不拖垮整个注册表）
            logger.warning("provider 条目 %r 配置非法, 跳过: %s", pid, exc)
    return out


def _synthesize_single_provider(settings: Settings) -> dict[str, ProviderSpec]:
    """从 LLM_* env 合成单 provider 注册表（L0 零回归路径）.

    零回归语义: 仅 deepseek.com URL 触发 thinking=True（与原 _thinking_supported 行为一致）.
    """
    is_deepseek_compat = "deepseek.com" in settings.llm_base_url.lower()
    pid = _provider_id_from_base_url(settings.llm_base_url)
    spec = ProviderSpec(
        id=pid,
        base_url=settings.llm_base_url,
        api_key_env="LLM_API_KEY",
        models={
            settings.llm_model: ModelSpec(
                context=_DEFAULT_CONTEXT,
                thinking=is_deepseek_compat,
                cost_tier="mid",
            )
        },
        default_model=settings.llm_model,
    )
    return {pid: spec}


def load_registry(settings: Settings) -> ProviderRegistry:
    """加载 Provider 注册表（优先级: env JSON > full local snapshot > tracked seed > L0 合成）.

    fail-soft: 任意通道 JSON 解析失败 → 回退 L0 合成 + degraded=True + degraded_reason 如实标注.
    """
    raw_env = settings.model_providers_raw.strip()

    # 优先级 1: MODEL_PROVIDERS env JSON
    if raw_env:
        try:
            data = json.loads(raw_env)
            if not isinstance(data, dict):
                raise ValueError("MODEL_PROVIDERS must be a JSON object at top level")
            providers = _parse_providers_dict(data)
            # 即便为空 dict 也返回（用户显式提供空配置 = 显式意图）
            return ProviderRegistry(providers=providers)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            providers = _synthesize_single_provider(settings)
            return ProviderRegistry(
                providers=providers,
                degraded=True,
                degraded_reason=f"MODEL_PROVIDERS env JSON malformed: {exc}",
            )

    # 优先级 2: Web/本机管理的 ignored full local snapshot。它允许私有 endpoint/模型配置
    # 留在本机，不污染公开仓库 tracked seed。
    local_path = Path(settings.data_dir) / "providers.local.json"
    if local_path.exists():
        try:
            data = json.loads(local_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("providers.local.json must be a JSON object at top level")
            providers = _parse_providers_dict(data)
            return ProviderRegistry(providers=providers)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            providers = _synthesize_single_provider(settings)
            return ProviderRegistry(
                providers=providers,
                degraded=True,
                degraded_reason=f"providers.local.json malformed: {exc}",
            )

    # 优先级 3: {data_dir}/providers.json tracked seed
    file_path = Path(settings.data_dir) / "providers.json"
    if file_path.exists():
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("providers.json must be a JSON object at top level")
            providers = _parse_providers_dict(data)
            return ProviderRegistry(providers=providers)
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            providers = _synthesize_single_provider(settings)
            return ProviderRegistry(
                providers=providers,
                degraded=True,
                degraded_reason=f"providers.json malformed: {exc}",
            )

    # 优先级 4: L0 合成单 provider (零回归路径)
    return ProviderRegistry(providers=_synthesize_single_provider(settings))
