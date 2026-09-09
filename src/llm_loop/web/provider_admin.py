"""Authenticated-human Web control plane for provider/model configuration.

This module owns only operator configuration facts and safe persistence mechanics:
- Web edits an ignored ``data/providers.local.json`` overlay, never the tracked seed
  ``data/providers.json``.
- Provider secret plaintext stays in the local ``.env`` file and process environment;
  it is never written to provider JSON, API responses, logs, or audit records.
- Registry reload is atomic at ``ModelClientPool.replace_registry``.  The shared
  default client remains a startup snapshot, so changing ``LLM_MODEL`` reports
  ``restart_required`` rather than pretending it hot-switched.
- Mutations use exact file-version compare-and-swap to avoid lost updates.

The control plane does not infer model quality/capability. Values shown in the UI are
operator-configured facts unless separately qualified elsewhere.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")


class ProviderAdminError(RuntimeError):
    """Expected operator/config conflict with an HTTP-safe code/detail."""

    def __init__(self, code: str, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def _engine_settings(engine: Any) -> Any:
    settings = getattr(engine, "settings", None)
    if settings is None:
        raise ProviderAdminError(
            "provider_admin_unavailable", "当前引擎未暴露 Settings，无法管理 Provider。", status_code=503
        )
    return settings


def _data_dir(engine: Any) -> Path:
    settings = _engine_settings(engine)
    return Path(str(getattr(settings, "data_dir", "") or "./data")).expanduser().resolve()


def base_provider_path(engine: Any) -> Path:
    return _data_dir(engine) / "providers.json"


def local_provider_path(engine: Any) -> Path:
    return _data_dir(engine) / "providers.local.json"


def env_file_path(engine: Any) -> Path:
    explicit = os.environ.get("LFL_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    # Embedded/tests: data_dir normally lives at <workspace>/data.
    return (_data_dir(engine).parent / ".env").resolve()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_json_object(path: Path) -> tuple[dict[str, Any], bytes]:
    if not path.exists():
        return {}, b""
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderAdminError(
            "provider_config_invalid",
            f"Provider 配置不可读取/解析：{type(exc).__name__}。请先修复配置文件。",
            status_code=409,
        ) from exc
    if not isinstance(parsed, dict):
        raise ProviderAdminError(
            "provider_config_invalid", "Provider 配置顶层必须是 JSON object。", status_code=409
        )
    return parsed, raw


def _effective_config(engine: Any) -> tuple[dict[str, Any], str, str, Path | None]:
    settings = _engine_settings(engine)
    raw_env = str(getattr(settings, "model_providers_raw", "") or os.environ.get("MODEL_PROVIDERS", "")).strip()
    if raw_env:
        try:
            parsed = json.loads(raw_env)
        except json.JSONDecodeError as exc:
            raise ProviderAdminError(
                "provider_config_invalid",
                "MODEL_PROVIDERS 当前不是合法 JSON；Web 仅能只读观察，不能安全覆盖。",
                status_code=409,
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderAdminError(
                "provider_config_invalid",
                "MODEL_PROVIDERS 顶层不是 object；Web 仅能只读观察。",
                status_code=409,
            )
        return parsed, _sha(raw_env.encode("utf-8")), "env", None

    local = local_provider_path(engine)
    if local.exists():
        parsed, raw = _read_json_object(local)
        return parsed, _sha(raw), "local", local

    base = base_provider_path(engine)
    if base.exists():
        parsed, raw = _read_json_object(base)
        return parsed, _sha(raw), "base", base

    return {}, "missing", "missing", None


def _ensure_mutable(engine: Any) -> None:
    settings = _engine_settings(engine)
    if str(getattr(settings, "model_providers_raw", "") or os.environ.get("MODEL_PROVIDERS", "")).strip():
        raise ProviderAdminError(
            "provider_config_managed_by_env",
            "当前 MODEL_PROVIDERS 环境变量拥有最高优先级；Web 修改本地文件不会生效，因此已拒绝写入。",
            status_code=409,
        )


def _atomic_write(path: Path, raw: bytes, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        if mode is not None:
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        if mode is not None:
            os.chmod(path, mode)
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(path, raw)


def _dotenv_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    out: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        if _ENV_NAME_RE.fullmatch(key):
            out.add(key)
    return out


def _dotenv_value_source(path: Path, key: str) -> str:
    keys = _dotenv_keys(path)
    if key in keys:
        return "dotenv"
    if os.environ.get(key, ""):
        return "external_env"
    return "missing"


def _safe_env_value(value: str, *, secret: bool) -> str:
    # load_env_file strips surrounding whitespace/quotes and supports ordinary token
    # values. Provider API keys are expected to be opaque non-whitespace tokens; fail
    # closed rather than silently changing a pasted credential.
    if not value:
        return ""
    if any(ch in "\r\n\x00" or ch.isspace() for ch in value):
        label = "API Key" if secret else "配置值"
        raise ProviderAdminError(
            "unsupported_env_value",
            f"{label} 含空白/控制字符；为避免 .env 往返后字节变化，本版本拒绝保存。",
            status_code=400,
        )
    return value


def _set_dotenv_value(engine: Any, key: str, value: str, *, secret: bool = False) -> None:
    if _ENV_NAME_RE.fullmatch(key) is None:
        raise ProviderAdminError("invalid_env_name", "环境变量名不合法。")
    path = env_file_path(engine)
    source = _dotenv_value_source(path, key)
    if source == "external_env":
        raise ProviderAdminError(
            "config_managed_externally",
            f"{key} 来自进程外部环境而非本地 .env；Web 不覆盖更高优先级的外部配置。",
            status_code=409,
        )
    encoded = _safe_env_value(value, secret=secret)
    lines: list[str] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ProviderAdminError(
                "dotenv_unavailable", f"无法读取本地 .env：{type(exc).__name__}", status_code=500
            ) from exc
    replacement = f"{key}={encoded}"
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            existing = stripped.partition("=")[0].strip()
            if existing == key:
                if not replaced:
                    out.append(replacement)
                    replaced = True
                continue
        out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(replacement)
    raw = ("\n".join(out).rstrip("\n") + "\n").encode("utf-8")
    _atomic_write(path, raw, mode=0o600)
    os.environ[key] = value


def _clear_dotenv_value(engine: Any, key: str) -> None:
    path = env_file_path(engine)
    source = _dotenv_value_source(path, key)
    if source == "external_env":
        raise ProviderAdminError(
            "config_managed_externally",
            f"{key} 由外部环境管理，Web 不删除。",
            status_code=409,
        )
    if not path.exists():
        os.environ.pop(key, None)
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ProviderAdminError(
            "dotenv_unavailable", f"无法读取本地 .env：{type(exc).__name__}", status_code=500
        ) from exc
    out = []
    for line in lines:
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and "=" in stripped
            and stripped.partition("=")[0].strip() == key
        ):
            continue
        out.append(line)
    _atomic_write(path, ("\n".join(out).rstrip("\n") + "\n").encode("utf-8"), mode=0o600)
    os.environ.pop(key, None)


def generated_api_key_env(provider_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "_", provider_id).strip("_").upper() or "PROVIDER"
    return f"LFL_PROVIDER_{safe}_API_KEY"


def _credential_fact(engine: Any, api_key_env: str) -> tuple[bool, str]:
    if not api_key_env:
        return False, "none"
    path = env_file_path(engine)
    source = _dotenv_value_source(path, api_key_env)
    return bool(os.environ.get(api_key_env, "")), source


def _runtime_registry(engine: Any) -> Any | None:
    pool = getattr(engine, "llm_pool", None)
    if pool is None:
        return None
    snapshot = getattr(pool, "registry_snapshot", None)
    return snapshot() if callable(snapshot) else getattr(pool, "registry", None)


def _runtime_default_ref(engine: Any) -> str:
    client = getattr(getattr(engine, "llm_pool", None), "default_client", None) or getattr(engine, "llm", None)
    if client is None:
        return ""
    provider = str(getattr(client, "provider", "") or "").strip()
    model = str(getattr(client, "model", "") or "").strip()
    if provider and model and not model.startswith(provider + "/"):
        return f"{provider}/{model}"
    return model


def _configured_default_ref(engine: Any) -> str:
    return str(os.environ.get("LLM_MODEL", "") or getattr(_engine_settings(engine), "llm_model", "") or "").strip()


def _sanitize_model(mid: str, raw: Any, *, effective: bool) -> dict[str, Any]:
    item = dict(raw) if isinstance(raw, dict) else {}
    item.pop("api_key", None)
    item["id"] = str(mid)
    item["enabled"] = bool(item.get("enabled", True))
    item["effective"] = bool(effective)
    return item


def _sanitize_provider(engine: Any, pid: str, raw: Any, registry: Any | None) -> dict[str, Any]:
    val = dict(raw) if isinstance(raw, dict) else {}
    # Legacy/raw secret fields must never cross the Web boundary even if a hand-edited
    # config contains them. Only api_key_env is allowed to describe credential wiring.
    for key in list(val):
        lowered = str(key).lower()
        if key != "api_key_env" and ("api_key" in lowered or "secret" in lowered or "token" in lowered):
            val.pop(key, None)
    models_raw = val.pop("models", {})
    effective_spec = getattr(registry, "providers", {}).get(pid) if registry is not None else None
    effective_models = set(getattr(effective_spec, "models", {}) or {})
    api_key_env = str(val.get("api_key_env", "") or "")
    credential_configured, credential_source = _credential_fact(engine, api_key_env)
    return {
        "id": pid,
        **val,
        "enabled": bool(val.get("enabled", True)),
        "effective": effective_spec is not None,
        "credential_configured": credential_configured,
        "credential_source": credential_source,
        "models": [
            _sanitize_model(str(mid), mval, effective=str(mid) in effective_models)
            for mid, mval in (models_raw.items() if isinstance(models_raw, dict) else [])
        ],
    }


def snapshot(engine: Any) -> dict[str, Any]:
    raw, version, source, _ = _effective_config(engine)
    registry = _runtime_registry(engine)
    configured_default = _configured_default_ref(engine)
    runtime_default = _runtime_default_ref(engine)
    env_path = env_file_path(engine)
    default_source = _dotenv_value_source(env_path, "LLM_MODEL")
    providers = [
        _sanitize_provider(engine, str(pid), value, registry)
        for pid, value in raw.items()
        if isinstance(pid, str)
    ]
    return {
        "source": source,
        "mutable": source != "env",
        "config_version": version,
        "configured_default_model": configured_default,
        "runtime_default_model": runtime_default,
        "default_source": default_source,
        "restart_required": bool(configured_default and configured_default != runtime_default),
        "providers": providers,
        "effective_provider_count": len(getattr(registry, "providers", {}) or {}) if registry is not None else 0,
        "effective_model_count": sum(
            len(getattr(spec, "models", {}) or {})
            for spec in (getattr(registry, "providers", {}) or {}).values()
        ) if registry is not None else 0,
    }


def _seed_for_mutation(engine: Any) -> tuple[dict[str, Any], str]:
    _ensure_mutable(engine)
    raw, version, source, _ = _effective_config(engine)
    # Mutations always land in the ignored local overlay. If source is the tracked base,
    # copy its exact semantic content first rather than modifying the tracked seed.
    if source not in {"base", "local", "missing"}:
        raise ProviderAdminError("provider_config_readonly", "当前 Provider 配置不可由 Web 修改。", status_code=409)
    return copy.deepcopy(raw), version


def _apply_local_config(engine: Any, payload: dict[str, Any], *, expected_version: str) -> dict[str, Any]:
    current, current_version = _seed_for_mutation(engine)
    del current  # caller already built payload from a version-checked mutation base
    if expected_version != current_version:
        raise ProviderAdminError(
            "provider_config_conflict",
            "Provider 配置已被其它操作更新；请刷新设置页后重试。",
            status_code=409,
        )
    target = local_provider_path(engine)
    old_bytes = target.read_bytes() if target.exists() else None
    _atomic_write_json(target, payload)
    pool = getattr(engine, "llm_pool", None)
    if pool is None:
        if old_bytes is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, old_bytes)
        raise ProviderAdminError(
            "provider_admin_unavailable", "模型客户端池未装配，配置未应用。", status_code=503
        )
    try:
        from llm_loop.llm.providers import load_registry

        registry = load_registry(_engine_settings(engine))
        if getattr(registry, "degraded", False):
            raise ProviderAdminError(
                "provider_config_invalid",
                f"新配置未通过 Registry 加载：{getattr(registry, 'degraded_reason', 'unknown')}。",
                status_code=400,
            )
        pool.replace_registry(registry)
    except Exception as exc:
        if old_bytes is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, old_bytes)
        if isinstance(exc, ProviderAdminError):
            raise
        raise ProviderAdminError(
            "provider_reload_failed",
            f"Provider Registry 重载失败：{type(exc).__name__}；已恢复修改前配置。",
            status_code=500,
        ) from exc
    return snapshot(engine)


def mutate(engine: Any, *, expected_version: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    payload, version = _seed_for_mutation(engine)
    if expected_version != version:
        raise ProviderAdminError(
            "provider_config_conflict",
            "Provider 配置已变化；请刷新后基于最新版本重试。",
            status_code=409,
        )
    change(payload)
    return _apply_local_config(engine, payload, expected_version=version)


def set_credential(engine: Any, provider_id: str, api_key: str) -> dict[str, Any]:
    raw, _version, _source, _path = _effective_config(engine)
    val = raw.get(provider_id)
    if not isinstance(val, dict):
        raise ProviderAdminError("provider_not_found", f"Provider 不存在：{provider_id}", status_code=404)
    api_key_env = str(val.get("api_key_env", "") or "").strip()
    if not api_key_env:
        raise ProviderAdminError(
            "credential_not_applicable", "该 Provider 未配置 api_key_env（本地/免认证 Provider 无需密钥）。", status_code=409
        )
    if _ENV_NAME_RE.fullmatch(api_key_env) is None or not api_key_env.endswith(_SECRET_ENV_SUFFIXES):
        raise ProviderAdminError(
            "credential_env_unsafe", "api_key_env 不是受支持的密钥变量名（需以 _API_KEY/_TOKEN/_SECRET 结尾）。", status_code=409
        )
    if api_key:
        _set_dotenv_value(engine, api_key_env, api_key, secret=True)
    else:
        _clear_dotenv_value(engine, api_key_env)
    # No registry rewrite is required: client_params resolves secrets lazily from
    # os.environ. Clear cached dynamic clients so the next selection constructs with
    # the new credential; the startup default client remains intentionally frozen.
    pool = getattr(engine, "llm_pool", None)
    clear = getattr(pool, "clear_cache", None)
    if callable(clear):
        clear()
    return snapshot(engine)


def set_default_model(engine: Any, model_ref: str) -> dict[str, Any]:
    registry = _runtime_registry(engine)
    if registry is None:
        raise ProviderAdminError("provider_admin_unavailable", "Registry 未装配。", status_code=503)
    try:
        pid, mid = registry.resolve(model_ref)
    except ValueError as exc:
        raise ProviderAdminError("model_not_found", str(exc), status_code=404) from exc
    canonical = f"{pid}/{mid}"
    _set_dotenv_value(engine, "LLM_MODEL", canonical, secret=False)
    result = snapshot(engine)
    result["restart_required"] = canonical != _runtime_default_ref(engine)
    return result


def test_provider(engine: Any, provider_id: str, model_id: str = "") -> dict[str, Any]:
    registry = _runtime_registry(engine)
    if registry is None or provider_id not in getattr(registry, "providers", {}):
        raise ProviderAdminError(
            "provider_not_effective", "Provider 当前未启用/未进入有效 Registry。", status_code=409
        )
    spec = registry.providers[provider_id]
    chosen = model_id.strip() or str(getattr(spec, "default_model", "") or "")
    if not chosen:
        chosen = next(iter(spec.models), "")
    if chosen not in spec.models:
        raise ProviderAdminError("model_not_found", f"Provider 中不存在模型：{chosen}", status_code=404)
    try:
        params = registry.client_params(provider_id, chosen)
    except ValueError as exc:
        raise ProviderAdminError("credential_missing", str(exc), status_code=409) from exc

    # Explicit user-triggered connectivity test. It makes one bounded, no-tool model
    # request and returns only mechanical success/latency facts, never response text.
    from llm_loop.llm.client import LLMClient

    mspec = spec.models[chosen]
    capable, control = registry.reasoning_contract(provider_id, chosen)
    client = LLMClient(
        api_key=params.get("api_key", ""),
        base_url=params["base_url"],
        model=params["model"],
        timeout_s=min(float(params.get("timeout_s", 30.0) or 30.0), 30.0),
        max_tokens=8,
        wire_protocol=params.get("wire_protocol", "openai"),
        thinking_mode=False,
        reasoning_effort="low",
        reasoning_effort_map=params.get("reasoning_effort_map"),
        thinking_supported=registry.supports_thinking(provider_id, chosen),
        reasoning_capable=capable,
        reasoning_control=control,
        provider=provider_id,
        send_tool_choice=bool(params.get("send_tool_choice", True)),
        reasoning_split=bool(params.get("reasoning_split", False)),
        temperature=getattr(mspec, "temperature", None),
        top_p=getattr(mspec, "top_p", None),
        top_k=getattr(mspec, "top_k", None),
        min_p=getattr(mspec, "min_p", None),
    )
    started = time.monotonic()
    try:
        client.chat([{"role": "user", "content": "Reply OK."}], [], timeout_s=client.timeout_s)
    except Exception as exc:
        detail = str(exc)[:300]
        secret = str(params.get("api_key") or "")
        if secret:
            detail = detail.replace(secret, "***")
        detail = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1***", detail)
        raise ProviderAdminError(
            "provider_test_failed",
            f"连接测试失败：{type(exc).__name__}: {detail}",
            status_code=502,
        ) from exc
    finally:
        with contextlib.suppress(Exception):
            client.close()
    return {
        "ok": True,
        "provider": provider_id,
        "model": chosen,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "response_received": True,
    }


def reload_registry(engine: Any) -> dict[str, Any]:
    """Explicitly reload the effective registry file; default startup client is untouched."""
    _ensure_mutable(engine)
    pool = getattr(engine, "llm_pool", None)
    if pool is None:
        raise ProviderAdminError("provider_admin_unavailable", "模型客户端池未装配。", status_code=503)
    try:
        from llm_loop.llm.providers import load_registry

        registry = load_registry(_engine_settings(engine))
        if getattr(registry, "degraded", False):
            raise ProviderAdminError(
                "provider_config_invalid",
                f"Registry 加载处于 degraded：{getattr(registry, 'degraded_reason', 'unknown')}。",
                status_code=409,
            )
        pool.replace_registry(registry)
    except ProviderAdminError:
        raise
    except Exception as exc:
        raise ProviderAdminError(
            "provider_reload_failed", f"Registry 重载失败：{type(exc).__name__}", status_code=500
        ) from exc
    return snapshot(engine)
