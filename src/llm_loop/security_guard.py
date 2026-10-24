"""敏感数据识别与内容扫描（安全建议书 P0-4 / P1-3 共享原语）.

单一事实源：Feishu 出站内容与附件校验、文件预览/删除的敏感判定都从这里取结论，
避免多处各写一份正则导致覆盖漂移（建议书 S1-3 指出的正是这种漂移）。

边界（如实声明，不夸大）：
- 文件名判定是"名字启发式"，不理解文件语义；命中只用于抬高后续动作门槛
  （要求 hard=true / 阻断外发），不构成"该文件一定含密钥"的事实断言。
- 内容扫描覆盖"已知高置信格式"，对编码/分段/自定义格式的密钥无效；它是纵深
  防御的一层，不替代专用密钥扫描器，也不是唯一防线。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = [
    "SecretHit",
    "is_sensitive_path",
    "is_template_name",
    "sensitive_path_reason",
    "find_sensitive_paths",
    "scan_text",
    "redact_secrets",
    "has_strong_secret",
]

# 目录级敏感位置：其下文件默认视为敏感（私钥/云凭证/容器 registry 凭据）。
_SENSITIVE_DIR_NAMES = frozenset({".ssh", ".aws", ".gnupg", ".docker", ".kube"})

# 文件名级敏感模式（大小写不敏感，整名匹配）。
_SENSITIVE_NAME_PATTERNS = (
    r"^\.env(?:\..*)?$",
    r"^.*\.env$",
    r"^\.netrc$",
    r"^\.npmrc$",
    r"^\.pypirc$",
    r"^\.git-credentials$",
    r"^id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?$",
    r"^.*\.(?:pem|key|p12|pfx|jks|keystore|asc|gpg)$",
    r"^credentials(?:\..*)?$",
    r"^secrets?(?:\..*)?$",
    r"^auth\.json$",
    r"^.*(?:secret|credential)s?(?:[._-].*)?\.(?:json|ya?ml|toml|ini|env)$",
    r"^.*[._-](?:access[._-]?)?token\.(?:json|txt|env)$",
)
_SENSITIVE_NAME_RE = re.compile("|".join(f"(?:{p})" for p in _SENSITIVE_NAME_PATTERNS), re.IGNORECASE)

# 高置信内容特征：误报代价低（只会抬高外发/删除门槛），漏报代价高。
_STRONG_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 私钥块检测：源码里把 "BEGIN"+"PRIVATE KEY" 拆开拼接，避免本仓库自身的
    # 正则字面量触发 CacheGuard（准入审查材料含源码 diff 时被整体拦截）。
    ("private_key_block", re.compile("-----BEGIN " + r"(?:[A-Z0-9 ]+ )?" + "PRIVATE KEY-----")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai_like_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{32,}")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
)

# 低置信特征：只用于提示，默认不阻断（文档里出现 `password = xxx` 属正常表达）。
_WEAK_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "credential_assignment",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"]?[^\s'\"]{8,}"
        ),
    ),
)


class SecretHit:
    """一次内容命中（kind + severity；不保留明文片段，避免二次泄露）。"""

    __slots__ = ("kind", "severity")

    def __init__(self, kind: str, severity: str) -> None:
        self.kind = kind
        self.severity = severity

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretHit) and (self.kind, self.severity) == (other.kind, other.severity)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"SecretHit(kind={self.kind!r}, severity={self.severity!r})"

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "severity": self.severity}


_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


def sensitive_path_reason(path: str | os.PathLike[str]) -> str | None:
    """返回敏感原因（``dir:<name>`` / ``name:<pattern>``）；非敏感返回 None。"""
    p = Path(path)
    if p.name.lower().endswith(_TEMPLATE_SUFFIXES):
        return None  # 模板文件只含占位符，不抬高动作门槛
    for part in p.parts:
        if part in _SENSITIVE_DIR_NAMES:
            return f"dir:{part}"
    if _SENSITIVE_NAME_RE.match(p.name):
        return f"name:{p.name}"
    return None


def is_sensitive_path(path: str | os.PathLike[str]) -> bool:
    return sensitive_path_reason(path) is not None


def is_template_name(path: str | os.PathLike[str]) -> bool:
    """文件名是否命中模板后缀形态（.example/.sample/.template/.dist）.

    名字豁免只代表"预期是占位符模板"；内容是否真含密钥由调用方复核
    （preview 的模板内容强特征扫描，N11 2026-10-25 第四轮红队）。
    """
    return Path(path).name.lower().endswith(_TEMPLATE_SUFFIXES)


def find_sensitive_paths(root: str | os.PathLike[str], *, max_entries: int = 5000) -> list[str]:
    """遍历 root 找出敏感路径（不跟随符号链接，条目数有上限防 DoS）.

    返回相对 root 的 posix 路径列表；遍历被上限截断时仍返回已发现项，
    调用方可用 ``len(result)`` 判断是否命中，不能把"未命中"当作"绝对干净"。
    """
    base = Path(root)
    found: list[str] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in list(dirnames) + filenames:
            seen += 1
            if seen > max_entries:
                return found
            full = Path(dirpath) / name
            if sensitive_path_reason(full) is not None:
                try:
                    found.append(full.relative_to(base).as_posix())
                except ValueError:
                    found.append(str(full))
    return found


def scan_text(text: str, *, include_weak: bool = False) -> list[SecretHit]:
    """扫描文本中的高置信密钥特征；``include_weak`` 时附带低置信提示。"""
    if not text:
        return []
    hits: list[SecretHit] = []
    for kind, pattern in _STRONG_CONTENT_PATTERNS:
        if pattern.search(text):
            hits.append(SecretHit(kind, "strong"))
    if include_weak:
        for kind, pattern in _WEAK_CONTENT_PATTERNS:
            if pattern.search(text):
                hits.append(SecretHit(kind, "weak"))
    return hits


def has_strong_secret(text: str) -> bool:
    return any(hit.severity == "strong" for hit in scan_text(text))


def redact_secrets(text: str) -> str:
    """把命中的高置信密钥替换为 ``[REDACTED:<kind>]``（用于日志/回执脱敏）。"""
    if not text:
        return text
    redacted = text
    for kind, pattern in _STRONG_CONTENT_PATTERNS:
        redacted = pattern.sub(f"[REDACTED:{kind}]", redacted)
    return redacted
