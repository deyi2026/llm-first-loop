"""Provider 注册表 + 模型能力元数据（M47 / design §5.1/§5.2/§5.5）.

设计要点:
- ProviderSpec.api_key_env 只存 env var 名字, 密钥从不落代码/JSON/日志 (DFX-SEC-02)
- 加载优先级: MODEL_PROVIDERS env JSON > {data_dir}/providers.json > LLM_* env 合成单 provider
- fail-soft: JSON 解析失败 → 回退 L0 合成 + degraded=True + degraded_reason 字段（如实标注, 不崩）
- resolve 支持 "provider/model" 全限定 + 裸模型名唯一匹配; 歧义/未知抛 ValueError 列候选

参考: docs/model_switch_config_design.md §5.1/§5.2/§5.5
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_loop.config import Settings


@dataclass(frozen=True)
class ModelSpec:
    """模型能力元数据 (design §5.1).

    - context: 上下文窗口 (token 数)
    - thinking: 是否支持思考参数 (M47 泛化前硬编码在 _thinking_supported 中)
    - cost_tier: 成本档 (free/low/mid/high, 仅供展示, 不参与路由)
    """

    context: int = 131072
    thinking: bool = False
    cost_tier: str = "mid"


@dataclass(frozen=True)
class ProviderSpec:
    """单个 provider 元数据.

    api_key_env 存 **env var 名字** (如 "DEEPSEEK_API_KEY"), 不存 key 本体.
    """

    id: str
    base_url: str
    api_key_env: str
    models: dict[str, ModelSpec] = field(default_factory=dict)
    default_model: str = ""


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
            lines.append(f"[{pid}] base_url={spec.base_url}")
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

        return {
            "api_key": api_key,
            "base_url": spec.base_url,
            "model": model_id,
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


def _parse_providers_dict(raw: dict[str, Any]) -> dict[str, ProviderSpec]:
    """解析 JSON dict → ProviderSpec dict.

    单条 provider 配置非法（非 dict / 缺 base_url 等）→ 静默跳过该条,
    JSON 整体非法 → 由上层 catch 触发 fail-soft. 此处不抛异常.
    """
    out: dict[str, ProviderSpec] = {}
    for pid, val in raw.items():
        if not isinstance(val, dict):
            continue
        base_url = str(val.get("base_url", ""))
        api_key_env = str(val.get("api_key_env", ""))
        models_raw = val.get("models", {})
        models: dict[str, ModelSpec] = {}
        if isinstance(models_raw, dict):
            for mid, mval in models_raw.items():
                if isinstance(mval, dict):
                    models[mid] = ModelSpec(
                        context=int(mval.get("context", 131072)),
                        thinking=bool(mval.get("thinking", False)),
                        cost_tier=str(mval.get("cost_tier", "mid")),
                    )
                else:
                    models[mid] = ModelSpec()
        default_model = str(val.get("default_model", "")) or ""
        out[str(pid)] = ProviderSpec(
            id=str(pid),
            base_url=base_url,
            api_key_env=api_key_env,
            models=models,
            default_model=default_model,
        )
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
                context=131072,
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
