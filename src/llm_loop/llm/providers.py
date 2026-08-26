"""Provider 注册表 + 模型能力元数据（M47 / design §5.1/§5.2/§5.5）.

设计要点:
- ProviderSpec.api_key_env 只存 env var 名字, 密钥从不落代码/JSON/日志 (DFX-SEC-02)
- 加载优先级: MODEL_PROVIDERS env JSON > {data_dir}/providers.json > LLM_* env 合成单 provider
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
    - thinking: 是否支持思考参数 (M47 泛化前硬编码在 _thinking_supported 中)
    - cost_tier: 成本档 (free/low/mid/high, 仅供展示, 不参与路由)
    - reasoning: 强推理能力 (R5: model_catalog 展示, AI 自主选模型)
    - long_context: 长上下文档 (R5: context >= 256K)
    - multimodal: 多模态（图片/音频/视频, R5)
    """

    context: int = 131072
    thinking: bool = False
    cost_tier: str = "mid"
    reasoning: bool = False
    long_context: bool = False
    multimodal: bool = False
    wire_protocol: str = "openai"  # P3-5: openai / anthropic / google（客户端协议分发）
    capability_tier: str = "unknown"  # T-P2-1-1: strong/weak/unknown（spec §6.5 漂移治理动态调权依据; unknown=保守视为弱模型）


@dataclass(frozen=True)
class ProviderSpec:
    """单个 provider 元数据.

    api_key_env 存 **env var 名字** (如 "DEEPSEEK_API_KEY"), 不存 key 本体.
    timeout_s: provider 级 LLM 调用超时（秒）; None = 用全局 LLM_TIMEOUT_S。
    本地慢模型（LM Studio 大模型 prefill 慢）在此放大, 云端保持全局默认（零回归）。
    history_budget_chars: provider 级历史注入预算（字符）; None = 用全局
    HISTORY_MAX_CHARS。本地模型 prefill 成本随上下文线性涨, 收紧预算可显著缩短
    首 token 时延（旧长历史经压缩归档可检索, 信息零丢失, 不损失可用性）。
    """

    id: str
    base_url: str
    api_key_env: str
    models: dict[str, ModelSpec] = field(default_factory=dict)
    default_model: str = ""
    fast_model: str = ""  # 2026-08-21 分级路由: 简单任务快速模型 ref（无配置=不走分级, 零回归）
    timeout_s: float | None = None
    history_budget_chars: int | None = None
    max_tokens: int | None = None  # 2026-08-15: provider 级输出预算（None=全局 LLM_MAX_TOKENS）
    chars_per_token: float | None = None  # EVO-20260824: provider 级字符/token 估算（None=全局 0.6）
    # deepseek 中文混合实测 1.676 tok/char → 0.6 chars/token；local qwen 中文 tokenizer 效率更高
    # （1 token≈1-1.5 中文字）→ 0.9。守卫/预算按 provider 取值，未配置回退全局（零回归）。
    inject_system_notices: bool = True  # 推送式 system 注入（架构上报/预警/快照）是否进提交视图;
    # False（本地慢模型用）= 仅落会话不进提交 —— system 前缀保持静态, llama.cpp 引擎前缀缓存
    # 每轮命中（首 token 大幅缩短）; 功能性注入（压缩标注/降级通知/overflow 回注等）不受影响。
    tool_round_zero_history: bool = False  # 2026-08-24 本地工具轮极小窗口:
    # True（本地用）= 工具轮只发 system+工具 schema+最近完整协议配对组（assistant(tool_calls)+
    # 全部 tool 回执）——KV 前缀稳定 + prefill 秒级; env TOOL_ROUND_ZERO_HISTORY 显式覆盖
    # （未设时取本配置）; 其他 provider 缺省 False 零回归。


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
        """
        if "/" in model_ref:
            pid, mid = model_ref.split("/", 1)
            spec = self.providers.get(pid)
            if spec is None:
                raise ValueError(f"未知 provider: {pid}")
            if mid not in spec.models:
                raise ValueError(f"provider '{pid}' 不存在模型 '{mid}'")
            return pid, mid

        # 裸名查找: 跨 provider 扫描
        matches: list[tuple[str, str]] = []
        for pid, spec in self.providers.items():
            if model_ref in spec.models:
                matches.append((pid, model_ref))

        if not matches:
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
            if spec.max_tokens:
                tags.append(f"max_tokens={spec.max_tokens}")
            tag_str = (" " + " ".join(tags)) if tags else ""
            lines.append(f"[{pid}] base_url={spec.base_url}{tag_str}")
            for mid, mspec in spec.models.items():
                thinking = "✓" if mspec.thinking else "✗"
                lines.append(
                    f"  - {mid}: context={mspec.context}, "
                    f"thinking={thinking}, cost={mspec.cost_tier}"
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
            **({"max_tokens": spec.max_tokens} if spec.max_tokens is not None else {}),
            # P3-5: 协议（模型级元数据；默认 openai 零回归）
            **({"wire_protocol": spec.models[model_id].wire_protocol} if spec.models[model_id].wire_protocol != "openai" else {}),
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


def _parse_bool_field(pid: str, mid: str, field: str, mval: dict[str, Any]) -> bool:
    """解析单布尔字段（P1-3 审计 #14: bool("false")==True 陷阱修复）.

    仅接受真正的 bool / 整数 1/0（与 bool() 一致, 零回归）/ 白名单字符串
    "1/true/yes/on"（True）/ "0/false/no/off"（False）, 大小写不敏感;
    其余值（含任意非白名单字符串）→ logger.warning 如实告警 + 回退字段默认 False
    （不静默 bool(), 禁用配置不再被静默启用）.
    """
    value = mval.get(field, False)
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
        "回退默认 False",
        pid, mid, field, value,
    )
    return False


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

    缺失 → unknown + 降级日志（保守视为弱模型, 完整三层拷问）;
    非法 → unknown + warning 如实告警（不拖垮注册表加载）。
    """
    if "capability_tier" not in mval:
        logger.info(
            "模型 %s/%s 未配置 capability_tier，按 unknown 处理（保守视为弱模型，"
            "建议显式配置 strong/weak）", pid, mid,
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
    return ModelSpec(
        context=_parse_context(mval.get("context")),
        thinking=_parse_bool_field(pid, mid, "thinking", mval),
        cost_tier=str(mval.get("cost_tier", "mid")),
        reasoning=_parse_bool_field(pid, mid, "reasoning", mval),
        long_context=_parse_bool_field(pid, mid, "long_context", mval),
        multimodal=_parse_bool_field(pid, mid, "multimodal", mval),
        # P3-5: 协议白名单（非法值回退 openai + 如实告警，不拖垮注册表）
        wire_protocol=_parse_wire_protocol(pid, mid, mval),
        # T-P2-1-1: 能力档白名单（缺失/非法 → unknown + 降级日志，不拖垮注册表）
        capability_tier=_parse_capability_tier(pid, mid, mval),
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
            base_url = str(val.get("base_url", ""))
            api_key_env = str(val.get("api_key_env", ""))
            models_raw = val.get("models", {})
            models: dict[str, ModelSpec] = {}
            if isinstance(models_raw, dict):
                for mid, mval in models_raw.items():
                    try:
                        # P1-3: 单模型条目独立 try/except（非法条目跳过, 不拖垮同 provider 其余模型）
                        if isinstance(mval, dict):
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
            # 非法/缺失 → None（全局 HISTORY_MAX_CHARS 兜底）
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
            # 推送式 system 注入开关（本地慢模型关 → system 前缀静态 → 引擎前缀缓存命中）;
            # 严格布尔解析（复用白名单语义）; 非法 → warning + 默认 True（零回归）
            inject_notices: bool = True
            raw_inject = val.get("inject_system_notices", True)
            if isinstance(raw_inject, bool):
                inject_notices = raw_inject
            elif isinstance(raw_inject, int):
                inject_notices = bool(raw_inject)
            elif isinstance(raw_inject, str) and raw_inject.strip().lower() in _TRUTHY_STRINGS:
                inject_notices = True
            elif isinstance(raw_inject, str) and raw_inject.strip().lower() in _FALSY_STRINGS:
                inject_notices = False
            else:
                logger.warning(
                    "provider 条目 %r 的 inject_system_notices=%r 非法, 回退默认 True",
                    pid, raw_inject,
                )
            # 2026-08-24 本地工具轮极小窗口开关（严格布尔语义同 inject_system_notices）;
            # 非法 → warning + 默认 False（零回归）
            tool_round_zero: bool = False
            raw_tool_zero = val.get("tool_round_zero_history", False)
            if isinstance(raw_tool_zero, bool):
                tool_round_zero = raw_tool_zero
            elif isinstance(raw_tool_zero, int):
                tool_round_zero = bool(raw_tool_zero)
            elif isinstance(raw_tool_zero, str) and raw_tool_zero.strip().lower() in _TRUTHY_STRINGS:
                tool_round_zero = True
            elif isinstance(raw_tool_zero, str) and raw_tool_zero.strip().lower() in _FALSY_STRINGS:
                tool_round_zero = False
            else:
                logger.warning(
                    "provider 条目 %r 的 tool_round_zero_history=%r 非法, 回退默认 False",
                    pid, raw_tool_zero,
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
                fast_model=str(val.get("fast_model", "") or ""),  # 2026-08-21 分级路由
                timeout_s=timeout_s,
                history_budget_chars=history_budget_chars,
                max_tokens=max_tokens,
                chars_per_token=chars_per_token,
                inject_system_notices=inject_notices,
                tool_round_zero_history=tool_round_zero,
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
    """加载 Provider 注册表（优先级: env JSON > 文件 > L0 合成）.

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

    # 优先级 2: {data_dir}/providers.json
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

    # 优先级 3: L0 合成单 provider (零回归路径)
    return ProviderRegistry(providers=_synthesize_single_provider(settings))
