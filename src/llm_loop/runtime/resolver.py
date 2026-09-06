"""Runtime Resolver（RUNTIME-SOT-WIRE R2）。

统一 effective configuration 计算语义，消灭 shell 侧多真相源：

权威层（design §2.3，自上而下）：
  1. 显式 CLI 参数（--model/--port 等）
  2. LFL_ALLOW_RUNTIME_OVERRIDE=1 时的进程环境（显式开启才构成 override 层）
  3. workspace .env（业务配置唯一常规来源）
  4. built-in defaults（config.load_settings 兜底）

关键规则：**陈旧 shell env ≠ 配置 override**。
默认情况下 shell inherited 的业务配置键（LLM_MODEL 等）不参与 effective 计算，
被忽略并记录到 ignored_shell_env——防止环境残留静默覆盖 .env（实测事故：
.env=glm/glm-5.3 而进程跑 deepseek-v4-flash；PYTHONPATH=mirror/src 劫持主区 venv）。

密钥类例外（_SECRET_KEYS）：API key 等凭据允许环境优先（CI/secret manager 惯例），
但同样记录来源。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# 参与权威层治理的业务配置键（LLM 运行身份相关）
BUSINESS_KEYS = (
    "LLM_MODEL", "LLM_BASE_URL", "LLM_THINKING_MODE", "LLM_REASONING_EFFORT",
    "HISTORY_MAX_CHARS", "WEB_PORT", "LFL_DATA_DIR", "DSH_HOME",
    "RUNTIME_IDENTITY_MODE",
    "WIRE_CONTRACT_MODE",
    # R2: 从 restart_system.sh shell 默认值等价迁移（.env 未定义时兜底）
    "SUMMARY_MODE", "TOOL_SCHEMA_LAZY",
)
# 密钥类：允许 shell 环境优先（secret manager 惯例），但记录来源
_SECRET_KEYS = ("LLM_API_KEY", "DEEPSEEK_API_KEY", "FEISHU_APP_ID", "FEISHU_APP_SECRET")

# R2 等价迁移：shell 时代（restart_system.sh _load_llm）注入的启动默认值。
# .env 未定义且无显式 override 时兜底（sources 标记 launch_default；
# shell 残留不覆盖 launch 默认——与 dotenv 同权重的防残留语义）。
LAUNCH_DEFAULTS = {"SUMMARY_MODE": "off", "TOOL_SCHEMA_LAZY": "1"}

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMENT_RE = re.compile(r"\s+#.*$")


def _mask_secret(key: str, val: str) -> str:
    """密钥类键脱敏：值只保留长度信息，不回显任何明文片段。"""
    if (key in _SECRET_KEYS or "API_KEY" in key or "SECRET" in key
            or "TOKEN" in key or "PASSWORD" in key):
        return f"<secret:{len(val)}chars>"
    return val


def parse_env_file(path: str | Path) -> dict[str, str]:
    """解析 .env 为 dict（语义与 config.load_env_file 对齐：剥行内注释/尾空格/跳过非法键名）。

    与 config.load_env_file 的区别：不写入 os.environ（纯函数，供 effective 计算）。
    """
    out: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip().rstrip("\r")
        if not _KEY_RE.match(key):
            continue
        val = _COMMENT_RE.sub("", val)
        val = val.strip()
        out[key] = val
    return out


@dataclass
class EffectiveConfig:
    service: str
    workspace_root: str
    env_file: str
    values: dict[str, str] = field(default_factory=dict)          # effective 业务键值
    sources: dict[str, str] = field(default_factory=dict)         # 键→来源(cli/shell_override/dotenv/secret_env)
    ignored_shell_env: dict[str, str] = field(default_factory=dict)  # 被忽略的 shell 残留（脱敏值长度）
    allow_runtime_override: bool = False

    def to_summary(self) -> dict:
        """不含密钥明文的摘要（R3 manifest 数据源）。

        密钥类键脱敏为 <secret:Nchars>（实测教训 2026-08-29：dry-run 输出
        曾把 LLM_API_KEY 明文带进日志——to_summary 是落盘/打日志的唯一口径，
        必须在源头脱敏，靠调用方自觉不可靠）。
        """
        return {
            "service": self.service,
            "workspace_root": self.workspace_root,
            "env_file": self.env_file,
            "values": {k: _mask_secret(k, v) for k, v in self.values.items()},
            "sources": dict(self.sources),
            "ignored_shell_env": {k: f"<len:{len(v)}>" for k, v in self.ignored_shell_env.items()},
            "allow_runtime_override": self.allow_runtime_override,
        }


def resolve_effective(
    service: str,
    cli_overrides: dict[str, str] | None = None,
    *,
    env: dict[str, str] | None = None,
    workspace_root: str | Path | None = None,
) -> EffectiveConfig:
    """计算 effective 业务配置。纯函数（不写 os.environ）。

    env 默认取 os.environ 快照；测试可注入。
    """
    env = dict(os.environ if env is None else env)
    ws = Path(workspace_root) if workspace_root else _default_workspace()
    env_file = ws / ".env"
    dotenv = parse_env_file(env_file)
    allow_override = (env.get("LFL_ALLOW_RUNTIME_OVERRIDE", "") == "1")

    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    ignored: dict[str, str] = {}

    for key in BUSINESS_KEYS:
        if cli_overrides and key in cli_overrides:
            values[key] = cli_overrides[key]
            sources[key] = "cli"
        elif allow_override and env.get(key):
            values[key] = env[key]
            sources[key] = "shell_override"
        elif key in dotenv:
            values[key] = dotenv[key]
            sources[key] = "dotenv"
            # 权威 dotenv 生效，但 shell 存在不同残留值时记录冲突（审计可见，
            # R2 核心语义：残留不覆盖，但"曾有残留"是事实必须可溯）
            if env.get(key) and env[key] != dotenv[key]:
                ignored[key] = env[key]
        elif key in LAUNCH_DEFAULTS:
            # R2 等价迁移：.env 未定义时用 shell 时代等价默认（sync/1）
            values[key] = LAUNCH_DEFAULTS[key]
            sources[key] = "launch_default"
        elif env.get(key):
            # 权威层外（.env 未定义但 shell 有值）：记录为被忽略残留
            ignored[key] = env[key]

    # 密钥类：shell 环境优先（惯例），.env 兜底
    for key in _SECRET_KEYS:
        if env.get(key):
            values[key] = env[key]
            sources[key] = "secret_env"
        elif dotenv.get(key):
            values[key] = dotenv[key]
            sources[key] = "dotenv_secret"

    return EffectiveConfig(
        service=service,
        workspace_root=str(ws),
        env_file=str(env_file),
        values=values,
        sources=sources,
        ignored_shell_env=ignored,
        allow_runtime_override=allow_override,
    )


def _default_workspace() -> Path:
    env = os.environ.get("LFL_WORKSPACE_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    p = Path.cwd().resolve()
    for cand in (p, *p.parents):
        if (cand / "pyproject.toml").is_file():
            return cand
    return p


def apply_to_environ(ec: EffectiveConfig) -> None:
    """把 effective 值写入 os.environ（供下游 config.load_settings 装配）。

    仅写 values 中实际有来源的键；被忽略的 shell 残留键若已存在于 os.environ
    且 .env 未定义，予以 unset——防止下游直读环境拿到漂移值。
    """
    for key, val in ec.values.items():
        os.environ[key] = val
    for key in ec.ignored_shell_env:
        if key in os.environ and key not in ec.values:
            del os.environ[key]
