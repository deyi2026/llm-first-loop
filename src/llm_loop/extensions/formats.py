"""Agent Plugins 1.0.0 标准包解析（DESIGN-20261009 §5.1，P1-A）.

固定位置（仅此三处，不执行包内任何代码/hooks）:
    plugin.json          包清单
    skills/<name>/SKILL.md   技能组件
    mcp.json             MCP 服务器组件（mcpServers 映射）

错误隔离（设计 §6，最窄失败边界）:
- 无效 manifest（缺失/坏 JSON/非对象/无 name）→ 整包 unavailable
- 单技能错误（frontmatter 坏/缺 name/SKILL.md 缺失）→ 该组件 invalid，其余保留
- mcp.json 整体坏 → 无 server 组件 + warning；单条目坏/未知 type → 组件级隔离
- 未知顶层字段、extensions 非对象 → 非致命 warning（T15）

安全（T17）:
- 越界引用（路径逃逸包根）与符号链接越界 → 组件 invalid
- PLUGIN_ROOT / PLUGIN_DATA 占位符仅验证拼写合法（未定义占位符 → needs_configuration）；
  不展开、不 shell 求值、不执行 install hook
- mcp.json 的 env/headers 值不写入组件记录（凭证运行时提供，记录不含明文 token）

上限（§10.2）: 单包组件 ≤200（超出截断 + warning）。

纯函数、仅标准库 + skills.loader（YAML frontmatter 校验复用）；可测零副作用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from llm_loop.skills.loader import parse_skill_md

MANIFEST_FILE = "plugin.json"
MCP_FILE = "mcp.json"
SKILLS_DIRNAME = "skills"
SCHEMA_VERSION = "1.0.0"
MAX_COMPONENTS = 200  # §10.2 单包组件上限

# 组件状态（§5.1 CompatibilityReport 语义，仅此五种）
STATUS_SUPPORTED = "supported"
STATUS_NEEDS_CONFIG = "needs_configuration"
STATUS_CONVERTIBLE = "convertible"
STATUS_UNSUPPORTED = "unsupported"
STATUS_INVALID = "invalid"

# 包状态
PACKAGE_READY = "ready"
PACKAGE_PARTIAL = "partial"
PACKAGE_UNAVAILABLE = "unavailable"

_KNOWN_MANIFEST_FIELDS = frozenset(
    {
        "name",
        "schema_version",
        "version",
        "description",
        "author",
        "homepage",
        "license",
        "keywords",
        "compatibility",
        "extensions",
    }
)
_PLACEHOLDER_RECOGNIZED = frozenset({"PLUGIN_ROOT", "PLUGIN_DATA"})


@dataclass(frozen=True)
class SkillComponent:
    """skills/<name>/ 组件记录."""

    name: str
    rel_path: str  # 相对包根（skills/<name>/SKILL.md）
    status: str
    reason: str = ""
    description: str = ""


@dataclass(frozen=True)
class McpServerComponent:
    """mcp.json servers 条目组件记录（不含 env/headers 明文值）."""

    name: str
    transport: str  # stdio | http | ""（未知）
    status: str
    reason: str = ""
    command: tuple[str, ...] = ()  # 仅 stdio 非敏感命令行
    url: str = ""


@dataclass(frozen=True)
class CompatibilityReport:
    """一个标准包的解析结果（组件级 + 总状态，如实报告）."""

    plugin_name: str
    version: str
    overall: str  # ready / partial / unavailable
    root: str
    skills: tuple[SkillComponent, ...] = ()
    servers: tuple[McpServerComponent, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "plugin_name": self.plugin_name,
            "version": self.version,
            "overall": self.overall,
            "root": self.root,
            "skills": [
                {
                    "name": s.name,
                    "rel_path": s.rel_path,
                    "status": s.status,
                    "reason": s.reason,
                    "description": s.description,
                }
                for s in self.skills
            ],
            "servers": [
                {
                    "name": s.name,
                    "transport": s.transport,
                    "status": s.status,
                    "reason": s.reason,
                }
                for s in self.servers
            ],
            "warnings": list(self.warnings),
        }


def _resolve_within(path: Path, root: Path) -> Path | None:
    """解析后仍位于 root 内 → 返回 resolved；越界（含符号链接逃逸）→ None（T17）."""
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root.resolve(strict=False))
        return resolved
    except (ValueError, OSError):
        return None


def _check_placeholders(values: list[str]) -> str | None:
    """检查字符串中的 ${NAME} 占位符拼写；未识别 → 返回说明（needs_configuration）."""
    import re

    for value in values:
        for match in re.findall(r"\$\{([A-Z_][A-Z0-9_]*)\}", str(value)):
            if match not in _PLACEHOLDER_RECOGNIZED:
                return f"unrecognized placeholder ${{{match}}}"
    return None


def _parse_skills(root: Path, warnings: list[str]) -> list[SkillComponent]:
    """扫描 skills/ 一层子目录；单技能错误组件级隔离（T16）。"""
    skills_root = root / SKILLS_DIRNAME
    if not skills_root.is_dir():
        return []
    out: list[SkillComponent] = []
    for sub in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        rel = f"{SKILLS_DIRNAME}/{sub.name}/SKILL.md"
        skill_file = sub / "SKILL.md"
        # T17: 子目录符号链接越界 → 组件 invalid
        if not _resolve_within(sub, root):
            out.append(
                SkillComponent(
                    name=sub.name,
                    rel_path=rel,
                    status=STATUS_INVALID,
                    reason="symlink escapes package root",
                )
            )
            continue
        if not skill_file.is_file():
            out.append(
                SkillComponent(
                    name=sub.name,
                    rel_path=rel,
                    status=STATUS_INVALID,
                    reason="missing SKILL.md",
                )
            )
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.append(
                SkillComponent(
                    name=sub.name,
                    rel_path=rel,
                    status=STATUS_INVALID,
                    reason=f"unreadable SKILL.md: {exc}",
                )
            )
            continue
        meta = parse_skill_md(text, fallback_name=sub.name, path=str(skill_file))
        if not meta.frontmatter_std:
            # T16: frontmatter 坏（降级路径）→ invalid（标准包要求标准 frontmatter）
            out.append(
                SkillComponent(
                    name=sub.name,
                    rel_path=rel,
                    status=STATUS_INVALID,
                    reason="SKILL.md frontmatter is not valid YAML mapping",
                )
            )
            continue
        name = str(meta.frontmatter.get("name") or "").strip()
        if not name:
            out.append(
                SkillComponent(
                    name=sub.name,
                    rel_path=rel,
                    status=STATUS_INVALID,
                    reason="frontmatter missing required field: name",
                )
            )
            continue
        out.append(
            SkillComponent(
                name=name,
                rel_path=rel,
                status=STATUS_SUPPORTED,
                description=meta.description[:2048],  # §10.2 description ≤2KB
            )
        )
    return out


def _parse_servers(
    root: Path, warnings: list[str]
) -> tuple[list[McpServerComponent], bool]:
    """解析 mcp.json；整体坏→空+degraded（overall 至少 partial）；单条目隔离（T16）."""
    mcp_file = root / MCP_FILE
    if not mcp_file.is_file():
        return [], False
    try:
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        warnings.append(f"mcp.json unreadable/invalid: {exc}")
        return [], True
    if not isinstance(data, dict):
        warnings.append("mcp.json must be a JSON object")
        return [], True
    servers = data.get("mcpServers")
    if servers is None:
        return [], False
    if not isinstance(servers, dict):
        warnings.append("mcp.json mcpServers must be an object")
        return [], True
    out: list[McpServerComponent] = []
    for name in sorted(servers):
        entry = servers[name]
        if not isinstance(entry, dict):
            out.append(
                McpServerComponent(
                    name=name,
                    transport="",
                    status=STATUS_INVALID,
                    reason="server entry must be an object",
                )
            )
            continue
        server_type = str(entry.get("type", "") or "").strip()
        if server_type == "stdio":
            command = entry.get("command")
            args = entry.get("args", [])
            if not isinstance(command, str) or not command.strip():
                out.append(
                    McpServerComponent(
                        name=name,
                        transport="stdio",
                        status=STATUS_NEEDS_CONFIG,
                        reason="stdio server missing command",
                    )
                )
                continue
            argv = [command] + [
                str(a) for a in (args if isinstance(args, list) else [])
            ]
            bad = _check_placeholders(argv)
            out.append(
                McpServerComponent(
                    name=name,
                    transport="stdio",
                    status=(
                        STATUS_NEEDS_CONFIG if bad else STATUS_SUPPORTED
                    ),
                    reason=f"{bad}; provide at install time" if bad else "",
                    command=tuple(argv[:64]),
                )
            )
            continue
        if server_type == "http":
            url = entry.get("url")
            if not isinstance(url, str) or not url.strip():
                out.append(
                    McpServerComponent(
                        name=name,
                        transport="http",
                        status=STATUS_NEEDS_CONFIG,
                        reason="http server missing url",
                    )
                )
                continue
            headers = entry.get("headers", {})
            header_values = (
                [str(v) for v in headers.values()]
                if isinstance(headers, dict)
                else []
            )
            bad = _check_placeholders(header_values)
            out.append(
                McpServerComponent(
                    name=name,
                    transport="http",
                    status=(
                        STATUS_NEEDS_CONFIG if bad else STATUS_SUPPORTED
                    ),
                    reason=f"{bad}; provide at install time" if bad else "",
                    url=url[:2048],
                )
            )
            continue
        out.append(
            McpServerComponent(
                name=name,
                transport=server_type,
                status=STATUS_UNSUPPORTED,
                reason=f"unsupported server type: {server_type!r}",
            )
        )
    return out, False


def parse_plugin_package(root: str | Path) -> CompatibilityReport:
    """解析标准包根目录 → CompatibilityReport（不抛业务异常，如实报告）."""
    pkg_root = Path(root)
    if not pkg_root.is_dir():
        return CompatibilityReport(
            plugin_name="",
            version="",
            overall=PACKAGE_UNAVAILABLE,
            root=str(pkg_root),
            warnings=("package root not found",),
        )
    manifest_file = pkg_root / MANIFEST_FILE
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return CompatibilityReport(
            plugin_name="",
            version="",
            overall=PACKAGE_UNAVAILABLE,
            root=str(pkg_root),
            warnings=(f"invalid manifest ({MANIFEST_FILE}): {exc}",),
        )
    if not isinstance(manifest, dict):
        return CompatibilityReport(
            plugin_name="",
            version="",
            overall=PACKAGE_UNAVAILABLE,
            root=str(pkg_root),
            warnings=(f"{MANIFEST_FILE} must be a JSON object",),
        )
    warnings: list[str] = []
    plugin_name = str(manifest.get("name") or "").strip()
    version = str(manifest.get("version") or "").strip()
    if not plugin_name:
        return CompatibilityReport(
            plugin_name="",
            version=version,
            overall=PACKAGE_UNAVAILABLE,
            root=str(pkg_root),
            warnings=("manifest missing required field: name",),
        )
    schema_version = manifest.get("schema_version")
    if schema_version is None:
        warnings.append("manifest missing schema_version; treated as 1.0.0")
    elif str(schema_version).strip() != SCHEMA_VERSION:
        warnings.append(
            f"unknown schema_version {schema_version!r}; treated as {SCHEMA_VERSION}"
        )
    unknown = sorted(set(manifest) - _KNOWN_MANIFEST_FIELDS)
    if unknown:
        warnings.append(f"unknown manifest fields ignored: {', '.join(unknown)}")
    if "extensions" in manifest and not isinstance(manifest["extensions"], dict):
        warnings.append("manifest extensions is not an object; ignored")  # T15
    skills = _parse_skills(pkg_root, warnings)
    servers, servers_degraded = _parse_servers(pkg_root, warnings)
    total = len(skills) + len(servers)
    if total > MAX_COMPONENTS:  # §10.2 上限：截断 + 如实标注
        keep = MAX_COMPONENTS
        kept_skills = skills[:keep]
        keep -= len(kept_skills)
        kept_servers = servers[:keep]
        warnings.append(
            f"components truncated: {total} > {MAX_COMPONENTS} (§10.2)"
        )
        skills, servers = kept_skills, kept_servers
    all_components = [c.status for c in skills] + [c.status for c in servers]
    if not all_components:
        overall = PACKAGE_UNAVAILABLE
    elif all(
        s == STATUS_SUPPORTED for s in all_components
    ) and not servers_degraded:
        overall = PACKAGE_READY
    elif any(s == STATUS_SUPPORTED for s in all_components):
        overall = PACKAGE_PARTIAL
    else:
        overall = PACKAGE_UNAVAILABLE
    return CompatibilityReport(
        plugin_name=plugin_name,
        version=version,
        overall=overall,
        root=str(pkg_root),
        skills=tuple(skills),
        servers=tuple(servers),
        warnings=tuple(warnings),
    )
