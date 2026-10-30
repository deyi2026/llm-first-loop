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
import sys
import tomllib
import unicodedata
from collections.abc import Mapping, Sequence
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
        ("history", "working_set_first_view_chars"): TomlField(("LFL_TOOL_WORKING_SET_FIRST_VIEW_CHARS",), "int"),
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
        ("tools", "method_subject_binding_experimental"): TomlField(
            ("LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL",), "bool"
        ),
        ("tools", "exec_sandbox"): TomlField(("EXEC_SANDBOX",), "str"),
        ("tools", "exec_sandbox_image"): TomlField(("EXEC_SANDBOX_IMAGE",), "str"),
        ("tools", "nonconvergence_fuse_windows"): TomlField(("LFL_NONCONV_FUSE_WINDOWS",), "int"),
        ("tools", "nonconvergence_fuse_jaccard"): TomlField(("LFL_NONCONV_FUSE_JACCARD",), "float"),
        ("tools", "nonconvergence_fuse_min_delta"): TomlField(("LFL_NONCONV_FUSE_MIN_DELTA",), "int"),
        ("web", "host"): TomlField(("WEB_HOST",), "str"),
        ("web", "port"): TomlField(("WEB_PORT",), "int"),
        ("web", "task_budget_canary_config"): TomlField(
            ("LFL_TASK_BUDGET_WEB_CANARY_CONFIG",), "str"
        ),
        # web-carveout M3（D2/D3）：18 个 web 通道明细映射随 client 剥离迁出，
        # 仅保留外部注册模块入口。
        ("web_providers", "module"): TomlField(("LFL_WEB_PROVIDERS_MODULE",), "str"),
        ("web_providers", "module_path"): TomlField(
            ("LFL_WEB_PROVIDERS_MODULE_PATH",), "str"
        ),
        ("local_runtime", "observer"): TomlField(("LFL_LOCAL_RUNTIME_OBSERVER",), "str"),
        ("local_runtime", "admission_authority"): TomlField(("LFL_LOCAL_RUNTIME_ADMISSION_AUTHORITY",), "str"),
        ("local_runtime", "cli"): TomlField(("LFL_LFRT_CLI",), "str"),
        ("summary", "mode"): TomlField(("SUMMARY_MODE",), "str"),
        ("semantic", "memory"): TomlField(("SEMANTIC_MEMORY_ENABLED",), "bool"),
        ("semantic", "archive"): TomlField(("SEMANTIC_ARCHIVE_ENABLED",), "bool"),
        ("semantic", "method"): TomlField(("SEMANTIC_METHOD_ENABLED",), "bool"),
        ("semantic", "docs"): TomlField(("SEMANTIC_DOCS_ENABLED",), "bool"),
        ("semantic", "experience"): TomlField(("SEMANTIC_EXPERIENCE_ENABLED",), "bool"),
        # retrieval multiquery fusion rollout (v0.6.27 影子模式): off/shadow,
        # 非法值由 config._env_multiquery_mode fail-safe 回 off
        ("retrieval", "multiquery_mode"): TomlField(("RETRIEVAL_MULTIQUERY_MODE",), "str"),
        ("tools", "schema_lazy"): TomlField(("TOOL_SCHEMA_LAZY",), "bool"),
        # Execution-time Method/Experience/Lesson reference discovery is
        # deliberately limited to Web in the first live rollout. In particular,
        # a generic .env switch must never silently opt Feishu/Learning in.
        ("knowledge_advisor", "mode"): TomlField(("LFL_KNOWLEDGE_ADVISOR",), "str"),
        ("knowledge_advisor", "sessions"): TomlField(
            ("LFL_KNOWLEDGE_ADVISOR_SESSIONS",), "str"
        ),
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
        # EVO-20260928-e312b78f: 学习通道模型隔离入治理（此前 config 直接读
        # os.environ["LEARNING_MODEL"]，launch 链路不解析该键 → .env 配置对
        # dedicated learning 进程失效，source_model 指向下线 provider 的 job
        # 解析失败无限留队）。入 schema 后随 resolve_effective → dotenv/toml
        # → apply_to_environ → Settings.learning_model 全链生效。
        ("learning", "model"): TomlField(("LEARNING_MODEL",), "str"),
        ("learning", "independent_cloud_hosts"): TomlField(
            ("LEARNING_INDEPENDENT_CLOUD_HOSTS",), "str"
        ),
        # M0-7(wecom): 非敏感治理项入闭式 schema（凭据 WECHAT_BOT_ID/SECRET 不入
        # schema，仅 _SECRET_KEYS 拒绝写入 runtime.toml——照 feishu 先例：
        # FEISHU_APP_ID/SECRET 不在 schema，凭据从进程 env 直读）。
        ("wecom", "session_map_path"): TomlField(("WECHAT_SESSION_MAP_PATH",), "str"),
    }
)

_SERVICE_SCOPED_SECTIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "semantic": frozenset({"web", "feishu", "wecom", "learning"}),
        "knowledge_advisor": frozenset({"web"}),
        # 2026-10-30：LLM_MODEL 服务级覆盖（仅 wecom）。企业微信接入的模型可以
        # 与全局默认不同——本 key 的订阅套餐无 GLM-5.3-FlashX 权限（provider 报
        # 429/1311「当前订阅套餐暂未开放GLM-5.3-FlashX权限」），企微接入单独钉
        # minimax/MiniMax-M3.1-Flash，其余服务仍用全局默认。
        # 只放 wecom：其余服务的模型归属未被授权变更。
        "llm": frozenset({"wecom"}),
        # web-carveout M3：chatgpt_web/deepseek_web 两个 service-scoped section
        # 随通道明细配置迁出删除（浏览器通道现为 Web-only 由独立项目侧配置）。
    }
)

# web-carveout M3：已剥离前缀的显式 fail-closed 拒绝清单（见
# _parse_runtime_toml_layers 循环开头的迁移指引报错）。
_CARVED_OUT_WEB_SECTIONS = frozenset({"chatgpt_web", "deepseek_web"})

_TOML_ENV_KEYS = tuple(
    dict.fromkeys(key for spec in TOML_SCHEMA.values() for key in spec.env_keys)
)

# Existing non-TOML business keys kept under the same stale-shell governance until
# their schema migration.  Adding a key here is a compatibility decision, not a
# license for new direct os.environ reads in consumers.
_LEGACY_GOVERNED_KEYS = (
    "MODEL_PROVIDERS",
    "MODEL_FALLBACKS",
    # R2: 从 restart_system.sh shell 默认值等价迁移（.env 未定义时兜底），
    # schema 迁移前暂列 legacy 治理
    "SUMMARY_MODE",
    "TOOL_SCHEMA_LAZY",
    # R2 增补（2026-09-16 缓存互踩事故）: embedding 业务配置纳入治理——
    # shell 残留不再漂移 provider/base_url/model，只认 workspace .env 文件。
    # （自 evo-20260914-exec-surface-followup 832b4dfa 移植；TOML 迁移前留此清单）
    "EMBEDDING_PROVIDER",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "EMBEDDING_TIMEOUT_S",
    "EMBEDDING_API_TIMEOUT_S",
    "SEMANTIC_MEMORY_ENABLED",
    "SEMANTIC_ARCHIVE_ENABLED",
    "SEMANTIC_METHOD_ENABLED",
    "SEMANTIC_DOCS_ENABLED",
    "SEMANTIC_EXPERIENCE_ENABLED",
)

BUSINESS_KEYS = tuple(dict.fromkeys((*_TOML_ENV_KEYS, *_LEGACY_GOVERNED_KEYS)))
_WEB_ONLY_KNOWLEDGE_KEYS = frozenset({
    "LFL_KNOWLEDGE_ADVISOR", "LFL_KNOWLEDGE_ADVISOR_SESSIONS",
    "LFL_TASK_BUDGET_WEB_CANARY_CONFIG",
})

# Secret/credential material is never accepted by runtime.toml.
_SECRET_KEYS = (
    "LLM_API_KEY",
    "GLM_API_KEY",
    "DEEPSEEK_API_KEY",
    "MINIMAX_API_KEY",
    "ZHIPU_API_KEY",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    # M0-7(wecom): 企微桥凭据绝不入 runtime.toml（照 feishu 先例）
    "WECHAT_BOT_ID",
    "WECHAT_BOT_SECRET",
    "CODEARTS_AK",
    "CODEARTS_SK",
    "CODEARTS_IAM_TOKEN",
    "CODEARTS_WEBHOOK_SECRET",
    "EMBEDDING_API_KEY",
)

LAUNCH_DEFAULTS = {"SUMMARY_MODE": "off", "TOOL_SCHEMA_LAZY": "1"}

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMENT_RE = re.compile(r"\s+#.*$")
_SECRET_NAME_RE = re.compile(r"(?:api[_-]?key|secret|token|password|credential|\bak\b|\bsk\b)", re.I)


def _strip_invisible(name: str) -> str:
    """剥离全部 C* 类别不可见/控制字符（Cc/Cf/Cs/Co/Cn，含零宽、双向覆盖、私用区）后的名字提示.

    EVO-20261014-483ca6de 边界审计：密钥名混入零宽字符可绕过子串匹配
    （"API_KEY" in key）。入口层（parse_env_file 的 _KEY_RE、runtime.toml
    闭式 schema）已拒绝此类名字；本函数是 values 掩码处的 fail-closed
    纵深（RULE-AI-30：无法排除敏感 ⇒ 按敏感处理）。
    """
    return "".join(
        ch for ch in str(name or "") if not unicodedata.category(ch).startswith("C")
    )


def _redact_url_credentials(val: str) -> str:
    """URL userinfo 凭据掩码（EVO-20261014-483ca6de 边界审计）.

    - 密码可含 ``@`` ``:`` 等标点：以 authority 内最后一个 ``@`` 为界、
      userinfo 内第一个 ``:`` 之后整体掩码（不漏尾部密码片段）；
    - IPv6 括号主机（``[::1]:5432``）不含 ``@``：不受影响也不被误伤
      （colon 判定限定在 userinfo 段内，不把主机/端口冒号当凭据分隔）；
    - username-only userinfo（无 ``:``）无密码事实可泄，保持原样。
    仅处理显式 ``scheme://`` 形式；无 userinfo 的 URL 原样返回。
    """
    text = str(val or "")
    scheme_re = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://")
    parts: list[str] = []
    pos = 0
    while True:
        m = scheme_re.search(text, pos)
        if m is None:
            parts.append(text[pos:])
            break
        start = m.end()
        end = len(text)
        for i in range(start, len(text)):
            if text[i] in "/?#":
                end = i
                break
        # 多 URL 串值（前一 URL 无路径、逗号/空格直接接下一 scheme://）时，
        # 下一 scheme 不得被吞进当前 authority（审查 P1：否则后续 URL 密码泄漏）。
        m2 = scheme_re.search(text, start)
        if m2 is not None and m2.start() < end:
            end = m2.start()
        authority = text[start:end]
        at = authority.rfind("@")
        colon = authority[:at].find(":") if at > 0 else -1
        if at > 0 and colon >= 0:
            parts.append(text[pos:start])
            parts.append(f"{authority[:colon]}:***{authority[at:]}")
        else:
            parts.append(text[pos:end])
        pos = end
    return "".join(parts)


def _mask_secret(key: str, val: str) -> str:
    # fail-closed 纵深：不可见字符剥离后仍无法排除敏感 ⇒ 掩码。
    # compact 匹配兜底零宽插进词内的形态（"API\u200bKEY" → "APIKEY"）。
    hint = _strip_invisible(key)
    compact = hint.replace("_", "").replace("-", "").upper()
    if (
        hint in _SECRET_KEYS
        or "API_KEY" in hint
        or "SECRET" in hint
        or "TOKEN" in hint
        or "PASSWORD" in hint
        or hint == "LFL_KNOWLEDGE_ADVISOR_SESSIONS"
        or "APIKEY" in compact
        or "SECRET" in compact
        or "TOKEN" in compact
        or "PASSWORD" in compact
    ):
        return f"<secret:{len(val)}chars>"
    return _redact_url_credentials(val)


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


def _parse_runtime_toml_layers(
    path: str | Path,
    *,
    service: str | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Parse global and service-scoped runtime.toml projections.

    Only explicitly registered sections may be service-scoped.  This keeps the
    general model/runtime surface single-source while allowing deliberately local
    capabilities such as Web-only browser model I/O.
    """
    p = Path(path)
    if not p.is_file():
        return {}, {}
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"runtime.toml 无法解析: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"runtime.toml 顶层必须是 table: {p}")

    global_out: dict[str, str] = {}
    service_out: dict[str, str] = {}
    requested_service = str(service or "").strip().lower()
    for raw_path, value in _flatten_toml(data):
        if raw_path[0] in _CARVED_OUT_WEB_SECTIONS:
            # web-carveout M3：deepseek/chatgpt 页面自动化通道已剥离至
            # lfl-web-providers 独立项目。旧 section 显式 fail-closed
            # （带迁移指引），防止「写了但无人消费」的静默无效配置。
            raise ValueError(
                "runtime.toml section "
                f"[{raw_path[0]}] 已随 web provider 剥离迁移（web-carveout M3）；"
                "通道明细配置请写入 lfl-web-providers/.env"
            )
        if len(raw_path) == 3 and raw_path[0] in _SERVICE_SCOPED_SECTIONS:
            section = raw_path[0]
            scoped_service = raw_path[1]
            field_name = raw_path[2]
            where = ".".join(raw_path)
            if scoped_service not in _SERVICE_SCOPED_SECTIONS[section]:
                if any(_SECRET_NAME_RE.search(_strip_invisible(part)) for part in raw_path):
                    raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
                raise ValueError(f"runtime.toml 未知服务级 {section} scope: {where}")
            spec = TOML_SCHEMA.get((section, field_name))
            if spec is None:
                if any(_SECRET_NAME_RE.search(_strip_invisible(part)) for part in raw_path):
                    raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
                raise ValueError(f"runtime.toml 未知字段: {where}")
            legacy = _toml_value_to_legacy((section, field_name), value, spec.kind)
            if requested_service == scoped_service:
                for env_key in spec.env_keys:
                    service_out[env_key] = legacy
            continue

        if len(raw_path) != 2:
            where = ".".join(raw_path)
            if any(_SECRET_NAME_RE.search(_strip_invisible(part)) for part in raw_path):
                raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
            raise ValueError(f"runtime.toml 未知字段: {where}")
        field_path = (raw_path[0], raw_path[1])
        if field_path[0] == "knowledge_advisor":
            # A global activation could affect unrelated Feishu/Learning
            # services on a later independent restart, despite the first
            # rollout being Web-only. Fail before any process is restarted.
            raise ValueError(
                "runtime.toml knowledge_advisor 仅支持服务级 "
                "[knowledge_advisor.web]，不允许全局开启"
            )
        spec = TOML_SCHEMA.get(field_path)
        if spec is None:
            where = ".".join(field_path)
            if any(_SECRET_NAME_RE.search(_strip_invisible(part)) for part in field_path):
                raise ValueError(f"runtime.toml 禁止存放凭证/密钥字段: {where}")
            raise ValueError(f"runtime.toml 未知字段: {where}")
        legacy = _toml_value_to_legacy(field_path, value, spec.kind)
        for env_key in spec.env_keys:
            global_out[env_key] = legacy
    return global_out, service_out


def parse_runtime_toml(path: str | Path, *, service: str | None = None) -> dict[str, str]:
    """Parse the closed runtime.toml schema into the legacy-key projection.

    The parser is strict when the file exists: unknown fields, wrong types and any
    secret-looking field fail closed.  Missing default runtime.toml is allowed so a
    workspace can migrate from .env incrementally.  When ``service`` is supplied,
    matching service-scoped values (for example ``[semantic.web]``) override the corresponding global section values.
    """
    global_values, service_values = _parse_runtime_toml_layers(path, service=service)
    out = dict(global_values)
    out.update(service_values)
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

    toml_values, service_toml_values = _parse_runtime_toml_layers(
        toml_file, service=service
    )
    dotenv = parse_env_file(env_file)
    allow_override = env_values.get("LFL_ALLOW_RUNTIME_OVERRIDE", "") == "1"

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    ignored: dict[str, str] = {}

    for key in BUSINESS_KEYS:
        if (
            key in _WEB_ONLY_KNOWLEDGE_KEYS
            and str(service).strip().lower() != "web"
        ):
            # The service-specific runtime contract is authoritative even
            # under an operator's generic .env / shell override. No silent
            # expansion to Feishu or Learning, and no user-message veto.
            values[key] = "off" if key == "LFL_KNOWLEDGE_ADVISOR" else ""
            sources[key] = "service_scope:disabled"
            if env_values.get(key):
                ignored[key] = str(env_values[key])
            continue
        if cli_overrides and key in cli_overrides:
            values[key] = str(cli_overrides[key])
            sources[key] = "cli"
        elif allow_override and env_values.get(key):
            values[key] = env_values[key]
            sources[key] = "shell_override"
        elif key in service_toml_values:
            values[key] = service_toml_values[key]
            sources[key] = f"runtime_toml_service:{str(service).strip().lower()}"
            if env_values.get(key) and env_values[key] != service_toml_values[key]:
                ignored[key] = env_values[key]
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
    config: RuntimeConfig | None = None,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Copy the bootstrap environment, optionally projecting RuntimeConfig.

    Unconfigured application bootstrap uses this same process boundary before
    choosing its config file. Business consumers should receive Settings/config.
    """
    out = dict(os.environ if base_env is None else base_env)
    if config is not None:
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


def apply_to_environ(config: RuntimeConfig | Mapping[str, str]) -> None:
    """Project configuration at legacy process/bootstrap boundaries only.

    RuntimeConfig retains governed-key removal. An explicit bootstrap mapping
    applies exactly those bindings, preserving unrelated process settings.
    """
    if isinstance(config, RuntimeConfig):
        projected = legacy_env_snapshot(config)
        governed = set(BUSINESS_KEYS) | set(_SECRET_KEYS)
        governed.update(config.ignored_shell_env)
    else:
        projected = dict(config)
        governed = set(projected)
    for key in governed:
        if key in projected:
            os.environ[key] = projected[key]
        else:
            os.environ.pop(key, None)


def check_runtime_toml(path: str, services: Sequence[str]) -> tuple[bool, str]:
    """Check-only strict parse of a runtime.toml against THIS code's schema.

    EVO-20261009-9d116efa G1: the restart pipeline runs this through the TARGET
    release's own resolver (PYTHONPATH pinned to that release's src/) before
    stopping any live process, so a runtime.toml field that the target code has
    not registered aborts the restart with zero physical side effects instead
    of taking the service down after ``_stop_*``.

    Returns ``(ok, message)``. Never writes, never touches os.environ.
    """
    if not os.path.exists(path):
        return True, f"runtime.toml 不存在，跳过 schema 校验: {path}"
    problems: list[str] = []
    checked: list[str] = []
    for service in services:
        try:
            parse_runtime_toml(path, service=service)
            checked.append(service)
        except ValueError as exc:
            problems.append(f"[{service}] {exc}")
        except Exception as exc:  # fail closed on parser failures too
            problems.append(f"[{service}] 解析异常: {exc!r}")
    if problems:
        detail = "; ".join(problems)
        return (
            False,
            "runtime.toml 与目标代码 schema 不兼容（未知字段/类型/密钥违规），拒绝继续重启: "
            + detail,
        )
    return True, f"runtime.toml schema 校验通过 services={checked}"


def _cli_check_toml(argv: list[str]) -> int:
    """Dispatch schema checks separately from restart-script endpoint queries."""
    args = argv[1:]
    if len(args) == 1 and args[0] in {"WEB_PORT", "WEB_HOST"}:
        try:
            value = resolve_effective("web").values[args[0]]
        except (ValueError, OSError, KeyError) as exc:
            print(f"runtime endpoint query failed: {exc}", file=sys.stderr)
            return 1
        print(value)
        return 0
    if len(args) < 2 or args[0] != "--check-toml":
        print("usage: resolver WEB_PORT|WEB_HOST or --check-toml <runtime.toml> [service ...]", file=sys.stderr)
        return 2
    path = args[1]
    services = args[2:] or ["web", "feishu", "wecom", "learning"]
    if any(service not in {"web", "feishu", "wecom", "learning"} for service in services):
        print("service must be web, feishu, wecom or learning", file=sys.stderr)
        return 2
    ok, message = check_runtime_toml(path, services)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_cli_check_toml(sys.argv))
