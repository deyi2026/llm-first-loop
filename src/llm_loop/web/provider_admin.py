"""Authenticated-human Web control plane for provider/model configuration.

This module owns only operator configuration facts and safe persistence mechanics:
- Web edits an ignored full local snapshot ``data/providers.local.json``, never the
  tracked seed ``data/providers.json``.
- Provider secret plaintext stays in the local ``.env`` file and process environment;
  it is never written to provider JSON, API responses, logs, or audit records.
- Registry reload is atomic at ``ModelClientPool.replace_registry``.  The shared
  default client remains a startup snapshot, so changing ``LLM_MODEL`` reports
  ``restart_required`` rather than pretending it hot-switched.
- Mutations use exact file-version compare-and-swap inside a thread/process write
  lock so provider JSON and dotenv read-modify-write operations cannot lose updates.

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
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET_ENV_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")


class ProviderAdminError(RuntimeError):
    """Expected operator/config conflict with an HTTP-safe code/detail.

    model-admin design §6.1.4/§7.2: 冲突类错误附带 ``extra``（如 current_version），
    供 UI 显示字段路径、原因与当前 revision；不静默覆盖。
    """

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 400,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.extra: dict[str, Any] = dict(extra or {})


def _current_version_of(engine: Any) -> dict[str, Any]:
    """冲突错误体的 current_version 附件（读取失败时如实缺省，不伪装）。"""
    try:
        _raw, version, _source, _path = _effective_config(engine)
        return {"current_version": version}
    except Exception:  # noqa: BLE001 — 附属事实读取失败不掩盖主错误
        return {}


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


_PROVIDER_WRITE_GUARD = threading.RLock()


@contextlib.contextmanager
def _provider_write_lock(engine: Any):
    """Serialize provider/.env mutations across threads and POSIX processes.

    Compare-and-swap is only a real CAS when the version re-check and write share
    one exclusion boundary. The process guard is always active; macOS/Linux also
    use flock so duplicate Web control-plane processes cannot lose updates.
    """
    with _PROVIDER_WRITE_GUARD:
        lock_path = _data_dir(engine) / ".provider-admin.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:
            yield
            return

        fd: int | None = None
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.chmod(lock_path, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            if fd is not None:
                os.close(fd)
            raise ProviderAdminError(
                "provider_config_lock_unavailable",
                f"Provider 配置写锁不可用：{type(exc).__name__}",
                status_code=503,
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


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
    """当前 live 默认模型引用（model-admin design §7.1 default.runtime_model）.

    pool 暴露 get_default_ref 时优先（热切换优先，未热切换返回启动默认 canonical）；
    旧 duck pool/测试 FakeLLM 回退启动 client 的 provider/model 拼接（零回归）。
    """
    pool = getattr(engine, "llm_pool", None)
    getter = getattr(pool, "get_default_ref", None)
    if callable(getter):
        try:
            ref = str(getter() or "").strip()
            if ref:
                return ref
        except Exception:  # noqa: BLE001 — 展示事实读取失败回退旧口径
            pass
    client = getattr(pool, "default_client", None) or getattr(engine, "llm", None)
    if client is None:
        return ""
    provider = str(getattr(client, "provider", "") or "").strip()
    model = str(getattr(client, "model", "") or "").strip()
    if provider and model and not model.startswith(provider + "/"):
        return f"{provider}/{model}"
    return model


def _default_model_refs(engine: Any) -> tuple[str, str]:
    """(配置默认, 运行默认) 引用对（model-admin design §6.2.3-4 守卫口径）.

    删除/停用保护必须同时检查两者：runtime-only 默认（外部 env 场景）不能被
    只看配置的守卫误删。
    """
    return _configured_default_ref(engine), _runtime_default_ref(engine)


def _ref_hosts_default(engine: Any, provider_id: str, model_id: str | None = None) -> bool:
    """该 provider（或具体模型）是否承载配置/运行默认引用."""
    prefix = provider_id + "/"
    for ref in _default_model_refs(engine):
        ref = str(ref or "").strip()
        if not ref:
            continue
        if model_id is None:
            if ref.startswith(prefix):
                return True
        elif ref == f"{provider_id}/{model_id}":
            return True
    return False


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
    # model-admin design §5.2/§7.1: 默认模型分层事实块。
    # persistence: dotenv/external-env/missing——外部 env 拥有 LLM_MODEL 时 Web 默认
    # 只能 runtime-only，标 "process" 不假装 durable（design §8.2）。
    persistence = (
        "process"
        if default_source == "external_env"
        else ("dotenv" if default_source == "dotenv" else "missing")
    )
    restart_required = bool(configured_default and configured_default != runtime_default)
    return {
        "source": source,
        "mutable": source != "env",
        "config_version": version,
        "configured_default_model": configured_default,
        "runtime_default_model": runtime_default,
        "default_source": default_source,
        "restart_required": restart_required,
        "default": {
            "model": configured_default,
            "runtime_model": runtime_default,
            "configured_source": default_source,
            "persistence": persistence,
            "applied": bool(not configured_default or configured_default == runtime_default),
            "restart_required": restart_required,
        },
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
    # Mutations always land in the ignored full local snapshot. If source is the tracked base,
    # copy its exact semantic content first rather than modifying the tracked seed.
    if source not in {"base", "local", "missing"}:
        raise ProviderAdminError("provider_config_readonly", "当前 Provider 配置不可由 Web 修改。", status_code=409)
    return copy.deepcopy(raw), version


def _apply_local_config(engine: Any, payload: dict[str, Any], *, expected_version: str) -> dict[str, Any]:
    with _provider_write_lock(engine):
        return _apply_local_config_locked(engine, payload, expected_version=expected_version)


def _apply_local_config_locked(engine: Any, payload: dict[str, Any], *, expected_version: str) -> dict[str, Any]:
    current, current_version = _seed_for_mutation(engine)
    del current  # caller already built payload from a version-checked mutation base
    if expected_version != current_version:
        raise ProviderAdminError(
            "provider_config_conflict",
            "Provider 配置已被其它操作更新；请刷新设置页后重试。",
            status_code=409,
            extra={"current_version": current_version},
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
            extra={"current_version": version},
        )
    change(payload)
    return _apply_local_config(engine, payload, expected_version=version)


# model-admin design §5.2/§8.1（未知字段保留）：Web 输入 schema 的已知配置字段集。
# 写回时以这些字段为界合并：客户端未展示/未发送的未知字段原样保留在文件里，
# 但疑似密钥的未知键在合并时丢弃（防御手写配置中的明文残留）。
def _provider_config_fields() -> frozenset[str]:
    from .schemas import ProviderAdminProviderInput

    return frozenset(ProviderAdminProviderInput.model_fields) | {"models"}


def _model_config_fields() -> frozenset[str]:
    from .schemas import ProviderModelAdminInput

    return frozenset(ProviderModelAdminInput.model_fields)


def _looks_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return key != "api_key_env" and ("api_key" in lowered or "secret" in lowered or "token" in lowered)


def merge_model_unknown(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """模型级写回合并：保留旧条目中 schema 之外的未知字段（design FR-13）."""
    prev = existing if isinstance(existing, dict) else {}
    keep = {
        str(k): v
        for k, v in prev.items()
        if k not in _model_config_fields() and not _looks_secret_key(str(k))
    }
    return {**keep, **incoming}


def merge_provider_unknown(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    """Provider 级写回合并：保留未知字段与旧模型条目中的未知字段（design FR-13）."""
    prev = existing if isinstance(existing, dict) else {}
    keep = {
        str(k): v
        for k, v in prev.items()
        if k not in _provider_config_fields() and not _looks_secret_key(str(k))
    }
    prev_models_raw = prev.get("models")
    prev_models: dict[str, Any] = prev_models_raw if isinstance(prev_models_raw, dict) else {}
    incoming_models_raw = incoming.get("models")
    incoming_models: dict[str, Any] = (
        incoming_models_raw if isinstance(incoming_models_raw, dict) else {}
    )
    merged_models = {
        str(mid): merge_model_unknown(prev_models.get(mid), mval)
        for mid, mval in incoming_models.items()
    }
    return {**keep, **incoming, "models": merged_models}


def _format_validation_error(exc: Any) -> str:
    """Pydantic ValidationError → 可读字段路径 + 原因（design §6.1.4 错误可诊断）."""
    parts: list[str] = []
    for item in getattr(exc, "errors", lambda: [])():
        loc = [str(seg) for seg in item.get("loc", ())]
        path = ".".join(seg for seg in loc if seg != "models__root")
        msg = str(item.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{path}: {msg}" if path else msg)
    return "；".join(parts) or str(exc)


def validate_provider_raw(pid: str, raw: dict[str, Any]) -> None:
    """按 ProviderAdminProviderInput 语义校验一个 raw provider dict（PATCH/合并路径复用）.

    只校验已知配置字段（未知字段保留策略见 merge_provider_unknown）；
    非法时抛 422 ProviderAdminError（含字段路径与原因）。
    """
    from pydantic import ValidationError

    from .schemas import ProviderAdminProviderInput

    known = {k: v for k, v in raw.items() if k in _provider_config_fields() and k != "models"}
    models_raw_value = raw.get("models")
    models_raw: dict[str, Any] = models_raw_value if isinstance(models_raw_value, dict) else {}
    model_items: list[dict[str, Any]] = []
    for mid, mval in models_raw.items():
        mval = mval if isinstance(mval, dict) else {}
        mknown = {k: v for k, v in mval.items() if k in _model_config_fields() and k != "id"}
        model_items.append({"id": str(mid), **mknown})
    try:
        ProviderAdminProviderInput.model_validate({**known, "id": pid, "models": model_items})
    except ValidationError as exc:
        raise ProviderAdminError(
            "invalid_field",
            f"Provider 配置字段非法：{_format_validation_error(exc)}",
            status_code=422,
        ) from exc


def patch_provider(
    engine: Any, provider_id: str, expected_version: str, fields: dict[str, Any]
) -> dict[str, Any]:
    """行级 PATCH（model-admin design §6.1.3/§7.2）：只改指定字段，复用 CAS + 回滚.

    fields 只含调用方显式提供的键（None 值应已在路由层剔除）。
    """
    def _patch(config: dict[str, Any]) -> None:
        raw = config.get(provider_id)
        if not isinstance(raw, dict):
            raise ProviderAdminError(
                "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
            )
        merged = {**raw, **fields}
        # design §7.7 default_provider_cannot_disable：配置/运行默认都不允许被停用承载。
        if fields.get("enabled") is False and _ref_hosts_default(engine, provider_id):
            raise ProviderAdminError(
                "default_provider_cannot_disable",
                "该 Provider 当前承载默认模型（配置或运行默认）；请先切换默认模型。",
                status_code=409,
            )
        validate_provider_raw(provider_id, merged)
        config[provider_id] = merged

    return mutate(engine, expected_version=expected_version, change=_patch)


def set_credential(engine: Any, provider_id: str, api_key: str) -> dict[str, Any]:
    with _provider_write_lock(engine):
        return _set_credential_locked(engine, provider_id, api_key)


def _set_credential_locked(engine: Any, provider_id: str, api_key: str) -> dict[str, Any]:
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
    with _provider_write_lock(engine):
        return _set_default_model_locked(engine, model_ref)


def _set_default_model_locked(engine: Any, model_ref: str) -> dict[str, Any]:
    """设置全局默认模型（model-admin design §6.2.3/§7.4）：先构造后提交，live 生效.

    - dotenv/missing 来源：先原子写 .env LLM_MODEL，成功后 pool.set_default_model；
      pool 提交失败（构造/解析失败）时回滚 .env 与 os.environ 到修改前。
    - external_env 来源（design §8.2 开放问题 2 推荐项）：不写 .env，仅 runtime
      切换；snapshot 的 default.persistence="process" 如实标注，不假装 durable。
    """
    registry = _runtime_registry(engine)
    if registry is None:
        raise ProviderAdminError("provider_admin_unavailable", "Registry 未装配。", status_code=503)
    pool = getattr(engine, "llm_pool", None)
    setter = getattr(pool, "set_default_model", None)
    if pool is None or not callable(setter):
        raise ProviderAdminError("provider_admin_unavailable", "模型客户端池未装配。", status_code=503)
    try:
        pid, mid = registry.resolve(model_ref)
    except ValueError as exc:
        raise ProviderAdminError("model_not_found", str(exc), status_code=404) from exc
    canonical = f"{pid}/{mid}"

    env_path = env_file_path(engine)
    source = _dotenv_value_source(env_path, "LLM_MODEL")
    if source == "external_env":
        # runtime-only：外部 env 拥有 LLM_MODEL；只切本进程路由事实，不碰 .env。
        try:
            setter(canonical)
        except ValueError as exc:
            raise ProviderAdminError("model_not_found", str(exc), status_code=404) from exc
        result = snapshot(engine)
        result["default_persistence"] = "process"
        result["default"]["persistence"] = "process"
        return result

    # dotenv/missing：先持久化，再 live 提交；live 提交失败回滚持久化。
    old_env_bytes = env_path.read_bytes() if env_path.exists() else None
    old_env_value = os.environ.get("LLM_MODEL")
    _set_dotenv_value(engine, "LLM_MODEL", canonical, secret=False)
    try:
        setter(canonical)
    except Exception as exc:
        if old_env_bytes is None:
            env_path.unlink(missing_ok=True)
        else:
            _atomic_write(env_path, old_env_bytes, mode=0o600)
        if old_env_value is None:
            os.environ.pop("LLM_MODEL", None)
        else:
            os.environ["LLM_MODEL"] = old_env_value
        if isinstance(exc, ValueError):
            raise ProviderAdminError(
                "runtime_apply_failed",
                f"默认模型运行时应用失败：{str(exc)[:200]}；已恢复修改前 .env。",
                status_code=500,
            ) from exc
        raise ProviderAdminError(
            "runtime_apply_failed",
            f"默认模型运行时应用失败：{type(exc).__name__}；已恢复修改前 .env。",
            status_code=500,
        ) from exc
    return snapshot(engine)


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
        reasoning_efforts=params.get("reasoning_efforts"),
        reasoning_default_effort=params.get("reasoning_default_effort"),
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
        # Provider/library exception text is untrusted transport material: it may
        # contain URL userinfo/query credentials, Authorization headers, or raw
        # response bodies.  The authenticated Web operator only needs mechanical
        # failure facts here, never reflected provider text.
        error_type = type(exc).__name__
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None:
            status = getattr(exc, "status_code", None)
        suffix = f"（HTTP {status}）" if isinstance(status, int) else ""
        if not suffix and "timeout" in error_type.lower():
            suffix = "（timeout）"
        raise ProviderAdminError(
            "provider_test_failed",
            f"连接测试失败：{error_type}{suffix}",
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
    with _provider_write_lock(engine):
        return _reload_registry_locked(engine)


def _reload_registry_locked(engine: Any) -> dict[str, Any]:
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


# ── 模型发现（model-admin design §6.3.1/§7.5）─────────────────────────────
# 只返回候选，不写任何配置；认证继承 Web 控制面；出站请求有界（超时/大小/候选数/
# 禁跨 host 重定向）；错误只含机械事实（类型/HTTP status/timeout），不反射
# provider 响应体、URL userinfo 或密钥。

_DISCOVER_TIMEOUT_S = 10.0
_DISCOVER_MAX_BYTES = 2 * 1024 * 1024
_DISCOVER_MAX_CANDIDATES = 2000
_DISCOVER_MAX_REDIRECTS = 3


def _new_discover_http_client() -> Any:
    """发现请求专用 httpx client（follow_redirects=False：跨 host 重定向由本模块显式裁决）."""
    import httpx

    return httpx.Client(
        timeout=_DISCOVER_TIMEOUT_S,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    )


def _discover_fetch_json(url: str, headers: dict[str, str]) -> Any:
    """有界 GET（重定向仅同 host；响应大小封顶）→ 解析后的 JSON 对象；2xx 之外为失败."""
    from urllib.parse import urlsplit

    current = url
    with _new_discover_http_client() as client:
        for _hop in range(_DISCOVER_MAX_REDIRECTS + 1):
            response = client.get(current, headers=headers)
            if response.status_code // 100 == 3:
                location = response.headers.get("location", "").strip()
                response.close()
                if not location:
                    raise ProviderAdminError(
                        "discovery_failed", "模型发现失败：重定向缺少 Location。", status_code=502
                    )
                from urllib.parse import urljoin

                target = urljoin(current, location)
                parsed_old, parsed_new = urlsplit(current), urlsplit(target)
                if parsed_new.scheme not in {"http", "https"} or not parsed_new.hostname:
                    raise ProviderAdminError(
                        "discovery_failed", "模型发现失败：重定向目标不是 http/https。", status_code=502
                    )
                same_host = (
                    parsed_old.hostname == parsed_new.hostname
                    and parsed_old.port == parsed_new.port
                    and parsed_old.scheme == parsed_new.scheme
                )
                if not same_host:
                    raise ProviderAdminError(
                        "discovery_failed", "模型发现失败：跨 host 重定向已拒绝。", status_code=502
                    )
                current = target
                continue
            if response.status_code >= 400:
                status = int(response.status_code)
                response.close()
                raise ProviderAdminError(
                    "discovery_failed", f"模型发现失败：HTTP {status}", status_code=502
                )
            chunks: list[bytes] = []
            total = 0
            try:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > _DISCOVER_MAX_BYTES:
                        raise ProviderAdminError(
                            "discovery_failed",
                            f"模型发现失败：响应超过 {_DISCOVER_MAX_BYTES // (1024 * 1024)}MB 上限。",
                            status_code=502,
                        )
                    chunks.append(chunk)
            finally:
                response.close()
            import json as _json

            try:
                return _json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeDecodeError, _json.JSONDecodeError) as exc:
                raise ProviderAdminError(
                    "discovery_failed",
                    f"模型发现失败：响应不是合法 JSON（{type(exc).__name__}）。",
                    status_code=502,
                ) from exc
    raise ProviderAdminError(
        "discovery_failed", f"模型发现失败：重定向超过 {_DISCOVER_MAX_REDIRECTS} 次。", status_code=502
    )


def _discover_candidates(payload: Any) -> list[dict[str, Any]]:
    """解析 openai 兼容 data[]/models{} 与 anthropic data[] 形态 → 有界候选列表."""
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            items = [x for x in data if isinstance(x, dict)]
        elif isinstance(payload.get("models"), dict):
            items = [
                {"id": str(k), **(v if isinstance(v, dict) else {})}
                for k, v in payload["models"].items()
            ]
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        mid = str(item.get("id", "") or "").strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        modalities = item.get("input_modalities")
        if not isinstance(modalities, list):
            modalities = None
        out.append(
            {
                "id": mid,
                "name": str(item.get("display_name") or item.get("name") or mid)[:256],
                "context_window": item.get("context_window")
                if isinstance(item.get("context_window"), int)
                else None,
                "max_output_tokens": item.get("max_output_tokens")
                if isinstance(item.get("max_output_tokens"), int)
                else None,
                "input_modalities": modalities,
            }
        )
        if len(out) >= _DISCOVER_MAX_CANDIDATES:
            break
    return out


def discover_models(
    engine: Any,
    *,
    base_url: str,
    wire_protocol: str,
    api_key: str | None = None,
    provider_id: str | None = None,
) -> dict[str, Any]:
    """保存前拉取端点候选模型（design §6.3.1）：仅候选，不写配置、不落盘密钥."""
    if wire_protocol not in {"openai", "anthropic"}:
        raise ProviderAdminError(
            "unsupported_protocol",
            f"协议 {wire_protocol} 暂不支持模型发现；请手填模型 ID。",
            status_code=400,
        )
    key = str(api_key or "").strip()
    if not key and provider_id:
        raw, _version, _source, _path = _effective_config(engine)
        val = raw.get(str(provider_id))
        if not isinstance(val, dict):
            raise ProviderAdminError(
                "provider_not_found", f"Provider 不存在：{provider_id}", status_code=404
            )
        env_name = str(val.get("api_key_env", "") or "").strip()
        if env_name:
            key = str(os.environ.get(env_name, "") or "").strip()

    if wire_protocol == "openai":
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
    else:
        root = base_url.rstrip("/")
        url = (root + "/models?limit=1000") if root.endswith("/v1") else (root + "/v1/models?limit=1000")
        headers = {"anthropic-version": "2023-06-01"}
        if key:
            headers["x-api-key"] = key

    try:
        payload = _discover_fetch_json(url, headers)
    except ProviderAdminError:
        raise
    except Exception as exc:  # noqa: BLE001 — 出站异常只保留机械事实
        error_type = type(exc).__name__
        suffix = "（timeout）" if "timeout" in error_type.lower() else ""
        raise ProviderAdminError(
            "discovery_failed", f"模型发现失败：{error_type}{suffix}", status_code=502
        ) from exc
    return {"candidates": _discover_candidates(payload), "diagnostics": None}
