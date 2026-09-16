"""Runtime configuration resolver and compatibility boundary.

The resolver makes business configuration ownership explicit:

1. explicit CLI values;
2. process environment only when ``LFL_ALLOW_RUNTIME_OVERRIDE=1``;
3. canonical runtime-root ``runtime.toml`` (typed, non-secret business configuration);
4. legacy workspace ``.env`` during migration;
5. built-in launch defaults / downstream Settings defaults.

Secrets remain outside ``runtime.toml`` and may come from the process environment
(or legacy ``.env`` while that compatibility path exists).  Stale inherited shell
business values are observable but are not authoritative by default.

``apply_to_environ`` is intentionally a *legacy adapter*.  It exists so old modules
that still read ``os.environ`` keep their current behaviour while consumers migrate
to explicit ``RuntimeConfig`` / ``Settings`` injection.  New code must not depend on
that adapter as a configuration API.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

ValueKind = Literal["str", "int", "bool", "float", "json"]


@dataclass(frozen=True)
class TomlField:
    """One closed-schema runtime.toml field and its legacy environment projection."""

    env_keys: tuple[str, ...]
    kind: ValueKind


# v1 deliberately starts with configuration that controls process identity, model
# routing, context size and service binding.  Provider registry details remain in
# providers*.json; credentials are forbidden here.
TOML_SCHEMA: Mapping[tuple[str, str], TomlField] = MappingProxyType(
    {
        ("llm", "model"): TomlField(("LLM_MODEL",), "str"),
        ("llm", "base_url"): TomlField(("LLM_BASE_URL",), "str"),
        ("llm", "thinking_mode"): TomlField(("LLM_THINKING_MODE",), "str"),
        ("llm", "reasoning_effort"): TomlField(("LLM_REASONING_EFFORT",), "str"),
        ("llm", "max_iterations"): TomlField(("LLM_MAX_ITERATIONS",), "int"),
        ("llm", "timeout_s"): TomlField(("LLM_TIMEOUT_S",), "int"),
        ("llm", "max_tokens"): TomlField(("LLM_MAX_TOKENS",), "int"),
        ("llm", "wire_protocol"): TomlField(("LLM_WIRE_PROTOCOL",), "str"),
        ("llm", "trust_env"): TomlField(("LLM_TRUST_ENV",), "bool"),
        ("llm", "retry_disconnect"): TomlField(("LLM_RETRY_DISCONNECT",), "int"),
        ("llm", "anthropic_cache_control"): TomlField(("ANTHROPIC_CACHE_CONTROL",), "bool"),
        ("llm", "cache_guard_hit_telemetry"): TomlField(("CACHE_GUARD_HIT_TELEMETRY",), "bool"),
        ("runtime", "data_dir"): TomlField(("DATA_DIR",), "str"),
        ("runtime", "lfl_data_dir"): TomlField(("LFL_DATA_DIR",), "str"),
        ("runtime", "history_max_chars"): TomlField(("HISTORY_MAX_CHARS",), "int"),
        ("runtime", "identity_mode"): TomlField(("RUNTIME_IDENTITY_MODE",), "str"),
        ("runtime", "wire_contract_mode"): TomlField(("WIRE_CONTRACT_MODE",), "str"),
        ("history", "working_set_receipts"): TomlField(("LFL_TOOL_WORKING_SET_RECEIPTS",), "bool"),
        ("history", "working_set_batch_chars"): TomlField(("LFL_TOOL_WORKING_SET_BATCH_CHARS",), "int"),
        ("history", "working_set_grace_groups"): TomlField(("LFL_TOOL_WORKING_SET_GRACE_GROUPS",), "int"),
        ("history", "working_set_soft_result_cap"): TomlField(("LFL_TOOL_WORKING_SET_SOFT_RESULT_CAP",), "int"),
        ("history", "working_set_hard_result_cap"): TomlField(("LFL_TOOL_WORKING_SET_HARD_RESULT_CAP",), "int"),
        ("history", "working_set_min_net_gain_chars"): TomlField(("LFL_TOOL_WORKING_SET_MIN_NET_GAIN_CHARS",), "int"),
        ("history", "compress_target_ratio"): TomlField(("COMPRESS_TARGET_RATIO",), "float"),
        ("history", "compact_ratio"): TomlField(("COMPACT_RATIO",), "float"),
        ("history", "nudge_growth_chars"): TomlField(("NUDGE_GROWTH_CHARS",), "int"),
        ("history", "head_keep_ratio"): TomlField(("HEAD_KEEP_RATIO",), "float"),
        ("history", "head_keep_force_ratio"): TomlField(("HEAD_KEEP_FORCE_RATIO",), "float"),
        ("history", "head_keep_target_ratio"): TomlField(("HEAD_KEEP_TARGET_RATIO",), "float"),
        ("tools", "breaker_pressure_narrow"): TomlField(("LFL_BREAKER_PRESSURE_NARROW",), "bool"),
        ("tools", "e18_hard_stop"): TomlField(("LFL_E18_HARD_STOP",), "bool"),
        ("tools", "tool_octet"): TomlField(("LFL_TOOL_OCTET",), "bool"),
        ("tools", "dsh_home"): TomlField(("DSH_HOME",), "str"),
        ("tools", "job_max_concurrent"): TomlField(("JOB_MAX_CONCURRENT",), "int"),
        ("tools", "evidence_capsule"): TomlField(("LFL_EVIDENCE_CAPSULE",), "str"),
        ("tools", "tool_guidance"): TomlField(("LFL_TOOL_GUIDANCE",), "str"),
        ("tools", "exec_sandbox"): TomlField(("EXEC_SANDBOX",), "str"),
        ("tools", "exec_sandbox_image"): TomlField(("EXEC_SANDBOX_IMAGE",), "str"),
        ("tools", "nonconvergence_fuse_windows"): TomlField(("LFL_NONCONV_FUSE_WINDOWS",), "int"),
        ("tools", "nonconvergence_fuse_jaccard"): TomlField(("LFL_NONCONV_FUSE_JACCARD",), "float"),
        ("tools", "nonconvergence_fuse_min_delta"): TomlField(("LFL_NONCONV_FUSE_MIN_DELTA",), "int"),
        ("web", "host"): TomlField(("WEB_HOST",), "str"),
        ("web", "port"): TomlField(("WEB_PORT",), "int"),
        ("local_runtime", "observer"): TomlField(("LFL_LOCAL_RUNTIME_OBSERVER",), "str"),
        ("local_runtime", "admission_authority"): TomlField(("LFL_LOCAL_RUNTIME_ADMISSION_AUTHORITY",), "str"),
        ("local_runtime", "cli"): TomlField(("LFL_LFRT_CLI",), "str"),
        ("summary", "mode"): TomlField(("SUMMARY_MODE",), "str"),
        ("tools", "schema_lazy"): TomlField(("TOOL_SCHEMA_LAZY",), "bool"),
        ("dsh", "home"): TomlField(("DSH_HOME",), "str"),
        ("dsh", "sessions_root"): TomlField(("DSH_SESSIONS_ROOT",), "str"),
        ("cache_guard", "perf_block_mode"): TomlField(("CACHE_GUARD_PERF_BLOCK",), "str"),
        ("cache_guard", "hit_block"): TomlField(("CACHE_GUARD_HIT_BLOCK",), "float"),
        ("cache_guard", "hit_warn"): TomlField(("CACHE_GUARD_HIT_WARN",), "float"),
        ("cache_guard", "hit_warn_adaptive"): TomlField(("CACHE_GUARD_HIT_WARN_ADAPTIVE",), "bool"),
        ("cache_guard", "hit_warn_tiers"): TomlField(("CACHE_GUARD_HIT_WARN_TIERS",), "json"),
        ("cache_guard", "hit_sample"): TomlField(("CACHE_GUARD_HIT_SAMPLE",), "int"),
        ("cache_guard", "block_escape"): TomlField(("CACHE_GUARD_BLOCK_ESCAPE",), "int"),
        ("cache_health", "breaker_trigger_runs"): TomlField(("BREAKER_TRIGGER_RUNS",), "int"),
        ("cache_health", "breaker_cooldown_rounds"): TomlField(("BREAKER_COOLDOWN_ROUNDS",), "int"),
        ("cache_health", "breaker_exit_stable_runs"): TomlField(("BREAKER_EXIT_STABLE_RUNS",), "int"),
        ("cache_health", "breaker_exit_chars_ratio"): TomlField(("BREAKER_EXIT_CHARS_RATIO",), "float"),
        ("cache_health", "breaker_pressure_ratio"): TomlField(("BREAKER_PRESSURE_RATIO",), "float"),
        ("cache_health", "breaker_pressure_escape_max"): TomlField(("BREAKER_PRESSURE_ESCAPE_MAX",), "int"),
        ("cache_health", "breaker_hit_thr"): TomlField(("BREAKER_HIT_THR",), "float"),
        ("cache_health", "breaker_over_ratio"): TomlField(("BREAKER_OVER_RATIO",), "float"),
        ("cache_health", "telemetry_strip_audit_log"): TomlField(("CACHE_TELEMETRY_STRIP_AUDIT_LOG",), "bool"),
        ("cache_health", "telemetry_strip_tail_lines"): TomlField(("CACHE_TELEMETRY_STRIP_TAIL_LINES",), "int"),
        ("interop", "watch_poll_s"): TomlField(("INBOX_WATCH_POLL_S",), "float"),
        ("interop", "wakeup"): TomlField(("INBOX_WAKEUP",), "bool"),
        ("interop", "wakeup_min_interval_s"): TomlField(("INBOX_WAKEUP_MIN_INTERVAL_S",), "float"),
        ("interop", "pending_ttl_hours"): TomlField(("INBOX_PENDING_TTL_HOURS",), "float"),
        ("interop", "pending_cleanup_on_start"): TomlField(("INBOX_PENDING_CLEANUP_ON_START",), "bool"),
        ("interop", "pending_max"): TomlField(("INBOX_PENDING_MAX",), "int"),
        ("run_cleanup", "stale_run_inspect_hours"): TomlField(("STALE_RUN_INSPECT_HOURS",), "float"),
        ("run_cleanup", "shutdown_timeout_s"): TomlField(("RUN_CLEANUP_SHUTDOWN_TIMEOUT_SEC",), "float"),
        ("run_cleanup", "confirmation_required"): TomlField(("RUN_CLEANUP_CONFIRMATION_REQUIRED",), "bool"),
        ("feishu", "ws_watchdog_poll_s"): TomlField(("FEISHU_WS_WATCHDOG_POLL_S",), "int"),
        ("feishu", "ws_watchdog_lock_s"): TomlField(("FEISHU_WS_WATCHDOG_LOCK_S",), "float"),
        ("feishu", "heartbeat_path"): TomlField(("FEISHU_HEARTBEAT_PATH",), "str"),
        ("feishu", "dedup_path"): TomlField(("FEISHU_DEDUP_PATH",), "str"),
        ("feishu", "heartbeat_history_path"): TomlField(("FEISHU_HEARTBEAT_HISTORY_PATH",), "str"),
        ("feishu", "ws_queue_max"): TomlField(("FEISHU_WS_QUEUE_MAX",), "int"),
        ("feishu", "exit_wait_s"): TomlField(("FEISHU_EXIT_WAIT_S",), "float"),
        ("feishu", "exit_drain_s"): TomlField(("FEISHU_EXIT_DRAIN_S",), "float"),
        ("feishu", "msg_process_timeout_s"): TomlField(("FEISHU_MSG_PROCESS_TIMEOUT_S",), "float"),
        ("feishu", "silent_threshold_s"): TomlField(("FEISHU_SILENT_THRESHOLD_S",), "float"),
        ("feishu", "interrupt_notify_timeout_s"): TomlField(("FEISHU_INTERRUPT_NOTIFY_TIMEOUT_S",), "float"),
        ("feishu", "cross_sync_poll_s"): TomlField(("FEISHU_CROSS_SYNC_POLL_S",), "float"),
        ("feishu", "cross_sync_min_interval_s"): TomlField(("FEISHU_CROSS_SYNC_MIN_INTERVAL_S",), "float"),
        ("feishu", "cross_sync_max_chars"): TomlField(("FEISHU_CROSS_SYNC_MAX_CHARS",), "int"),
        ("feishu", "cross_sync"): TomlField(("FEISHU_CROSS_SYNC",), "bool"),
        ("feishu", "audit_dir"): TomlField(("FEISHU_AUDIT_DIR",), "str"),
    }
)

_TOML_ENV_KEYS = tuple(
    dict.fromkeys(key for spec in TOML_SCHEMA.values() for key in spec.env_keys)
)

# Existing non-TOML business keys kept under the same stale-shell governance until
# their schema migration.  Adding a key here is a compatibility decision, not a
# license for new direct os.environ reads in consumers.
_LEGACY_GOVERNED_KEYS = (
    "MODEL_PROVIDERS",
    "MODEL_FALLBACKS",
)

BUSINESS_KEYS = tuple(dict.fromkeys((*_TOML_ENV_KEYS, *_LEGACY_GOVERNED_KEYS)))

# Secret/credential material is never accepted by runtime.toml.
_SECRET_KEYS = (
    "LLM_API_KEY",
    "DEEPSEEK_API_KEY",
    "MINIMAX_API_KEY",
    "ZHIPU_API_KEY",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "CODEARTS_AK",
    "CODEARTS_SK",
    "CODEARTS_IAM_TOKEN",
    "CODEARTS_WEBHOOK_SECRET",
)

LAUNCH_DEFAULTS = {"SUMMARY_MODE": "off", "TOOL_SCHEMA_LAZY": "1"}

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMENT_RE = re.compile(r"\s+#.*$")
_SECRET_NAME_RE = re.compile(r"(?:api[_-]?key|secret|token|password|credential|\bak\b|\bsk\b)", re.I)


def _mask_secret(key: str, val: str) -> str:
    if (
        key in _SECRET_KEYS
        or "API_KEY" in key
        or "SECRET" in key
        or "TOKEN" in key
        or "PASSWORD" in key
    ):
        return f"<secret:{len(val)}chars>"
    return val


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Parse legacy .env without mutating process-global environment."""
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().rstrip("\r")
        if not _KEY_RE.match(key):
            continue
        val = _COMMENT_RE.sub("", val).strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key] = val
    return out


def _flatten_toml(data: Mapping[str, Any], prefix: tuple[str, ...] = ()):
    for raw_key, value in data.items():
        key = str(raw_key)
        path = (*prefix, key)
        if isinstance(value, dict):
            yield from _flatten_toml(value, path)
        else:
            yield path, value


def _toml_value_to_legacy(path: tuple[str, str], value: Any, kind: ValueKind) -> str:
    where = ".".join(path)
    if kind == "str":
        if not isinstance(value, str):
            raise ValueError(f"runtime.toml {where} 必须是字符串")
        return value.strip()
    if kind == "int":
        # bool is an int subclass in Python; reject it explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"runtime.toml {where} 必须是整数")
        return str(value)
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"runtime.toml {where} 必须是数字")
        return str(float(value))
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"runtime.toml {where} 必须是布尔值")
        return "1" if value else "0"
    if kind == "json":
        if not isinstance(value, (list, dict)):
            raise ValueError(f"runtime.toml {where} 必须是数组或 table")
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise AssertionError(f"unsupported runtime.toml kind: {kind}")


def parse_runtime_toml(path: str | Path) -> dict[str, str]:
    """Parse the closed runtime.toml schema into the legacy-key projection.

    The parser is strict when the file exists: unknown fields, wrong types and any
    secret-looking field fail closed.  Missing default runtime.toml is allowed so a
    workspace can migrate from .env incrementally.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"runtime.toml 无法解析: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"runtime.toml 顶层必须是 table: {p}")

    out: dict[str, str] = {}
    for raw_path, value in _flatten_toml(data):
        if len(raw_path) != 2:
            where = ".".join(raw_path)
            if any(_SECRET_NAME_RE.search(part) for part in raw_path):
                raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
            raise ValueError(f"runtime.toml 未知字段: {where}")
        field_path = (raw_path[0], raw_path[1])
        spec = TOML_SCHEMA.get(field_path)
        if spec is None:
            where = ".".join(field_path)
            if any(_SECRET_NAME_RE.search(part) for part in field_path):
                raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
            raise ValueError(f"runtime.toml 未知字段: {where}")
        legacy = _toml_value_to_legacy(field_path, value, spec.kind)
        for env_key in spec.env_keys:
            out[env_key] = legacy
    return out


class _FrozenJsonDict(dict[str, str]):
    """JSON-serializable dict snapshot that rejects every mutating operation."""

    def _readonly(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError("RuntimeConfig snapshot is immutable")

    __setitem__ = _readonly  # type: ignore[assignment]
    __delitem__ = _readonly  # type: ignore[assignment]
    clear = _readonly  # type: ignore[assignment]
    pop = _readonly  # type: ignore[assignment]
    popitem = _readonly  # type: ignore[assignment]
    setdefault = _readonly  # type: ignore[assignment]
    update = _readonly  # type: ignore[assignment]
    __ior__ = _readonly  # type: ignore[assignment]


@dataclass(frozen=True)
class RuntimeConfig:
    """Immutable, provenance-carrying effective runtime configuration snapshot."""

    service: str
    workspace_root: str
    runtime_root: str
    config_file: str
    toml_file: str
    env_file: str
    values: Mapping[str, str] = field(default_factory=dict)
    sources: Mapping[str, str] = field(default_factory=dict)
    ignored_shell_env: Mapping[str, str] = field(default_factory=dict)
    allow_runtime_override: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "sources", _FrozenJsonDict(self.sources))
        object.__setattr__(
            self, "ignored_shell_env", MappingProxyType(dict(self.ignored_shell_env))
        )

    def to_summary(self) -> dict[str, object]:
        return {
            "service": self.service,
            "workspace_root": self.workspace_root,
            "runtime_root": self.runtime_root,
            "config_file": self.config_file,
            "toml_file": self.toml_file,
            "env_file": self.env_file,
            "values": {k: _mask_secret(k, v) for k, v in self.values.items()},
            "sources": dict(self.sources),
            "ignored_shell_env": {
                k: f"<len:{len(v)}>" for k, v in self.ignored_shell_env.items()
            },
            "allow_runtime_override": self.allow_runtime_override,
        }


# Compatibility name used by manifest/tests while callers migrate to RuntimeConfig.
EffectiveConfig = RuntimeConfig


def business_config_snapshot(
    service: str,
    *,
    env: Mapping[str, str] | None = None,
    workspace_root: str | Path | None = None,
    config_file: str | Path | None = None,
) -> Mapping[str, str]:
    """Return an immutable non-secret business configuration snapshot.

    P1 migration adapter for legacy modules that historically froze environment-
    driven constants at import time.  Values now come through the canonical
    RuntimeConfig resolver (runtime.toml > legacy .env > defaults), without
    projecting secrets or mutating process-global environment.
    """
    config = resolve_effective(
        service,
        env=env,
        workspace_root=workspace_root,
        config_file=config_file,
    )
    return MappingProxyType(
        {key: value for key, value in config.values.items() if key in BUSINESS_KEYS}
    )


def resolve_effective(
    service: str,
    cli_overrides: Mapping[str, str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    workspace_root: str | Path | None = None,
    config_file: str | Path | None = None,
) -> RuntimeConfig:
    """Resolve one immutable effective business-configuration snapshot."""
    env_values = dict(os.environ if env is None else env)
    # Backward-compatible ``workspace_root`` here means the operational/config root.
    # In dual-root deployments the source checkout lives under LFL_WORKSPACE_ROOT,
    # while configuration belongs to the stable LFL_RUNTIME_ROOT.
    ws = (
        Path(workspace_root).expanduser().resolve()
        if workspace_root is not None
        else _default_runtime_root(env_values)
    )
    env_file = ws / ".env"
    toml_file = Path(config_file).expanduser().resolve() if config_file else ws / "runtime.toml"
    if config_file is not None and not toml_file.is_file():
        raise ValueError(f"显式 runtime config 不存在: {toml_file}")

    toml_values = parse_runtime_toml(toml_file)
    dotenv = parse_env_file(env_file)
    allow_override = env_values.get("LFL_ALLOW_RUNTIME_OVERRIDE", "") == "1"

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    ignored: dict[str, str] = {}

    for key in BUSINESS_KEYS:
        if cli_overrides and key in cli_overrides:
            values[key] = str(cli_overrides[key])
            sources[key] = "cli"
        elif allow_override and env_values.get(key):
            values[key] = env_values[key]
            sources[key] = "shell_override"
        elif key in toml_values:
            values[key] = toml_values[key]
            sources[key] = "runtime_toml"
            if env_values.get(key) and env_values[key] != toml_values[key]:
                ignored[key] = env_values[key]
        elif key in dotenv:
            values[key] = dotenv[key]
            sources[key] = "dotenv"
            if env_values.get(key) and env_values[key] != dotenv[key]:
                ignored[key] = env_values[key]
        elif key in LAUNCH_DEFAULTS:
            values[key] = LAUNCH_DEFAULTS[key]
            sources[key] = "launch_default"
        elif env_values.get(key):
            ignored[key] = env_values[key]

    # Secret boundary: environment first; legacy .env only for compatibility.
    for key in _SECRET_KEYS:
        if env_values.get(key):
            values[key] = env_values[key]
            sources[key] = "secret_env"
        elif dotenv.get(key):
            values[key] = dotenv[key]
            sources[key] = "dotenv_secret"

    actual_config = toml_file if toml_file.is_file() else env_file
    return RuntimeConfig(
        service=service,
        workspace_root=str(ws),
        runtime_root=str(ws),
        config_file=str(actual_config),
        toml_file=str(toml_file),
        env_file=str(env_file),
        values=values,
        sources=sources,
        ignored_shell_env=ignored,
        allow_runtime_override=allow_override,
    )


def _default_runtime_root(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the canonical operational/config root without consulting code identity.

    ``LFL_RUNTIME_ROOT`` wins in dual-root deployments.  ``LFL_WORKSPACE_ROOT`` is
    retained only as the historical single-root fallback.
    """
    values = os.environ if env is None else env
    runtime_root = str(values.get("LFL_RUNTIME_ROOT", "") or "").strip()
    if runtime_root:
        return Path(runtime_root).expanduser().resolve()
    workspace_root = str(values.get("LFL_WORKSPACE_ROOT", "") or "").strip()
    if workspace_root:
        return Path(workspace_root).expanduser().resolve()
    p = Path.cwd().resolve()
    for cand in (p, *p.parents):
        if (cand / "pyproject.toml").is_file():
            return cand
    return p


def _default_workspace() -> Path:
    """Compatibility alias for older callers/tests."""
    return _default_runtime_root()


def legacy_env_snapshot(
    config: RuntimeConfig,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the legacy environment projection without mutating process state."""
    out = dict(os.environ if base_env is None else base_env)
    out.update(config.values)
    for key in config.ignored_shell_env:
        if key not in config.values:
            out.pop(key, None)
    return out


def legacy_settings_snapshot(
    config: RuntimeConfig,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the full legacy Settings input without mutating process state.

    Unmigrated keys keep historical env-first/.env-fallback semantics, while keys
    governed by RuntimeConfig are projected from the resolved snapshot so stale
    inherited business values cannot silently win.
    """
    out = dict(os.environ if base_env is None else base_env)
    for key, value in parse_env_file(config.env_file).items():
        out.setdefault(key, value)
    for key in config.ignored_shell_env:
        if key not in config.values:
            out.pop(key, None)
    out.update(config.values)
    return out


def apply_to_environ(config: RuntimeConfig) -> None:
    """Legacy adapter: project RuntimeConfig into os.environ for unmigrated readers.

    Keep this call at process/bootstrap compatibility boundaries only.  New business
    logic should receive RuntimeConfig/Settings explicitly instead of reading env.
    """
    projected = legacy_env_snapshot(config)
    governed = set(BUSINESS_KEYS) | set(_SECRET_KEYS)
    governed.update(config.ignored_shell_env)
    for key in governed:
        if key in projected:
            os.environ[key] = projected[key]
        else:
            os.environ.pop(key, None)
