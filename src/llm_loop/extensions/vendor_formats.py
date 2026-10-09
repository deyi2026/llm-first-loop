"""外部生态配置 adapter（DESIGN-20261009 §3，分期 P2-A）.

将厂商插件/扩展格式解析为标准内部组件描述并产出组件级兼容报告：
- claude-code-plugin/1: Claude Code 插件（.claude-plugin/plugin.json + 标准布局）
- codex-plugin/1: Codex/ChatGPT 旧插件（.codex-plugin/plugin.json + .mcp.json + .app.json）
- gemini-extension/1: Gemini CLI 扩展（gemini-extension.json）
- cursor-mcp/1: Cursor MCP 配置（.cursor/mcp.json，顶层 mcpServers）
- vscode-mcp/1: VS Code MCP（.vscode/mcp.json servers 格式 / portable mcpServers）
- mcp-servers-json/1: 顶层 mcpServers 的通用 JSON（Codex .mcp.json 等同构形态）

原则（§3/§3.1/§5.1/§5.3）：
- 转换不偷换原义：仅在语义等价时映射字段；权限/凭证/沙盒语义不假定等价，
  未映射组件/字段在报告中给出 status 与原因（partial 可解释，验收 T24）；
- 厂商变量在厂商 adapter 内解析（§5.1）：${CLAUDE_PLUGIN_ROOT}/${extensionPath}
  展开为包根路径；${CLAUDE_PLUGIN_DATA} 重命名为标准 ${PLUGIN_DATA}；
  其余用户态/运行时变量标记 needs_configuration 并保留原值；
- 纯函数零副作用：不执行 hooks、不写包目录、不遍历用户目录（仅处理显式给定的路径）；
- 不影响标准加载（§11 P2-A 退出条件）：本模块不修改标准包解析路径。

外部格式事实核验来源（官方，2026-10-10）：
- Claude: code.claude.com/docs/en/plugins/manifest-reference、/plugins/components
- Codex: developers.openai.com/plugins/build/plugins
- Gemini: geminicli.com/docs/extensions/reference/、/docs/tools/mcp-server
- Cursor: cursor.com/docs/mcp
- VS Code: code.visualstudio.com/docs/agent-customization/mcp-servers
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from llm_loop.extensions.formats import (
    STATUS_CONVERTIBLE,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIG,
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
    CompatibilityReport,
    McpServerComponent,
    SkillComponent,
    _parse_skills,
)

# 标准 Agent Plugins 包格式标识（formats.SCHEMA_VERSION = "1.0.0"）。
# 仅用于 detect 提示与安装记录 provenance，标准解析仍由 formats.parse_plugin_package 负责。
FORMAT_STANDARD = "agent-plugins/1.0.0"

FORMAT_CLAUDE = "claude-code-plugin/1"
FORMAT_CODEX = "codex-plugin/1"
FORMAT_GEMINI = "gemini-extension/1"
FORMAT_CURSOR = "cursor-mcp/1"
FORMAT_VSCODE = "vscode-mcp/1"
FORMAT_MCP_JSON = "mcp-servers-json/1"

VENDOR_FORMATS = (FORMAT_CLAUDE, FORMAT_CODEX, FORMAT_GEMINI, FORMAT_CURSOR, FORMAT_VSCODE, FORMAT_MCP_JSON)

# P2-B：legacy HTTP+SSE 旧传输已交付（设计 §3/T04）。sse 仅在源配置显式声明时
# 映射为 sse 传输（显式选择；LFL 不自动从 HTTP 回退）；无自动 OAuth 凭证注入。
_SSE_LEGACY = "sse→sse：legacy HTTP+SSE 旧传输（源配置显式声明即显式选择；P2-B 支持；凭证不自动转换）"


@dataclass(frozen=True)
class UnmappedComponent:
    """未映射为标准组件的厂商条目（§3.1：状态与原因必须可解释）."""

    name: str
    kind: str
    status: str
    reason: str

    def as_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "status": self.status, "reason": self.reason}


@dataclass(frozen=True)
class VendorConversion:
    """厂商包 → 标准视图的一次转换结果.

    mcp_servers 是可直接进入标准装配层的 server 配置（§5.1 变量已在 adapter 内
    处理）；仅含 supported/needs_configuration 条目——invalid 与 unsupported
    条目不构造，避免以不完整字段伪装可用（§3.1 不偷换原义）。
    """

    source_format: str
    report: CompatibilityReport
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    unmapped: tuple[UnmappedComponent, ...] = ()

    def as_dict(self) -> dict:
        data = {
            "source_format": self.source_format,
            "report": self.report.as_dict(),
            "mcp_servers": self.mcp_servers,
            "unmapped": [item.as_dict() for item in self.unmapped],
        }
        return data


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    """读 JSON 文件；返回 (data, error)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"文件不存在: {path.name}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"JSON 解析失败: {exc}"
    if not isinstance(data, dict):
        return None, f"顶层必须是 JSON 对象: {path.name}"
    return data, None


def _plugin_name(manifest: dict | None, fallback: str) -> str:
    name = (manifest or {}).get("name")
    return name if isinstance(name, str) and name.strip() else fallback


def _version(manifest: dict | None) -> str:
    version = (manifest or {}).get("version")
    return version if isinstance(version, str) and version.strip() else ""


def _finish_report(
    plugin_name: str,
    version: str,
    root: Path,
    skills: tuple[SkillComponent, ...],
    servers: tuple[McpServerComponent, ...],
    warnings: list[str],
    unmapped: list[UnmappedComponent],
) -> CompatibilityReport:
    has_ready_skill = any(s.status in (STATUS_SUPPORTED, STATUS_NEEDS_CONFIG) for s in skills)
    has_ready_server = any(s.status in (STATUS_SUPPORTED, STATUS_NEEDS_CONFIG) for s in servers)
    has_degraded = has_ready_skill or has_ready_server
    has_invalid = any(s.status == STATUS_INVALID for s in (*skills, *servers)) or any(
        item.status == STATUS_INVALID for item in unmapped
    )
    if not has_degraded and (has_invalid or skills or servers or unmapped):
        overall = "unavailable"
    elif not skills and not servers and not unmapped:
        overall = "unavailable"
        warnings.append("未发现任何可识别组件")
    elif any(s.status != STATUS_SUPPORTED for s in (*skills, *servers)) or any(
        item.status != STATUS_SUPPORTED for item in unmapped
    ):
        overall = "partial"
    else:
        overall = "ready"
    return CompatibilityReport(
        plugin_name=plugin_name,
        version=version,
        overall=overall,
        root=str(root),
        skills=skills,
        servers=servers,
        warnings=warnings,
    )


# ---------------------------------------------------------------- 变量语义（§5.1）


def _expand_vendor_vars(value, root: Path, source_format: str) -> tuple[object, str | None]:
    """厂商变量在厂商 adapter 内解析（§5.1）.

    - ${CLAUDE_PLUGIN_ROOT}（Claude/Codex 布局）与 ${extensionPath}（Gemini）
      展开为包根实际路径；
    - ${CLAUDE_PLUGIN_DATA} 重命名为标准 ${PLUGIN_DATA}（语义等价：安装时提供的
      插件数据目录，装配层已支持展开）；
    - 其余 ${VAR}/$VAR 保留原值并返回说明（needs_configuration 依据）。
    """

    def expand(text: str) -> tuple[str, str | None]:
        notes: list[str] = []
        result = text
        if source_format in (FORMAT_CLAUDE, FORMAT_CODEX):
            if "${CLAUDE_PLUGIN_ROOT}" in result:
                result = result.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
                notes.append("${CLAUDE_PLUGIN_ROOT}→包根路径")
            if "${CLAUDE_PLUGIN_DATA}" in result:
                result = result.replace("${CLAUDE_PLUGIN_DATA}", "${PLUGIN_DATA}")
                notes.append("${CLAUDE_PLUGIN_DATA}→${PLUGIN_DATA}(标准)")
        elif source_format == FORMAT_GEMINI and "${extensionPath}" in result:
            result = result.replace("${extensionPath}", str(root))
            notes.append("${extensionPath}→包根路径")
        # 残余 ${VAR}（PLUGIN_DATA 为重命名后的标准占位符，装配层展开，不算残余）
        residual = result.replace("${PLUGIN_DATA}", "")
        names: list[str] = []
        if "${" in residual:
            for chunk in residual.split("${"):
                if not chunk:
                    continue
                var = chunk.split("}", 1)[0] if "}" in chunk else chunk
                if var:
                    names.append("${" + var + "}")
        if names:
            notes.append(f"含未识别变量（{', '.join(sorted(set(names)))}），需安装方提供值")
        return result, "; ".join(notes) if notes else None

    if isinstance(value, str):
        return expand(value)
    if isinstance(value, list):
        out, all_notes = [], []
        for item in value:
            converted, note = _expand_vendor_vars(item, root, source_format)
            out.append(converted)
            if note:
                all_notes.append(note)
        return out, "; ".join(sorted(set(all_notes))) if all_notes else None
    if isinstance(value, dict):
        out, all_notes = {}, []
        for key, item in value.items():
            converted, note = _expand_vendor_vars(item, root, source_format)
            out[key] = converted
            if note:
                all_notes.append(note)
        return out, "; ".join(sorted(set(all_notes))) if all_notes else None
    return value, None


# 各厂商 server 条目中不进入标准视图、但语义已知的字段 → (field, kind, reason)。
_KNOWN_UNMAPPED_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    FORMAT_GEMINI: (
        ("cwd", "server_field", "cwd: 标准装配层无工作目录语义，字段未映射"),
        ("timeout", "server_field", "timeout: 连接超时语义未映射"),
        ("trust", "server_field", "trust: 权限豁免语义不自动生效（§3 权限不假定等价）"),
        ("includeTools", "server_field", "includeTools: 工具暴露控制未映射"),
        ("excludeTools", "server_field", "excludeTools: 工具暴露控制未映射"),
    ),
    FORMAT_VSCODE: (
        ("sandboxEnabled", "server_field", "sandboxEnabled: 沙盒权限语义不假定等价（§3）"),
    ),
}


def _convert_server_entry(
    name: str,
    entry,
    root: Path,
    source_format: str,
    warnings: list[str],
) -> tuple[McpServerComponent, dict | None]:
    """厂商 server 条目 → (组件报告, 标准条目 dict).

    标准条目 schema（§5.1）：
    - stdio: {type: "stdio", command, args?, env?}
    - http:  {type: "http", url, headers?}
    仅在字段语义等价时映射；未映射字段剔除并在 warnings 说明，不静默丢弃。
    """
    if not isinstance(entry, dict):
        return (
            McpServerComponent(name=name, transport="", status=STATUS_INVALID, reason="server 条目必须是 JSON 对象"),
            None,
        )

    converted: dict = {}
    status = STATUS_SUPPORTED
    reasons: list[str] = []

    for field_name, _kind, reason in _KNOWN_UNMAPPED_FIELDS.get(source_format, ()):
        if field_name in entry:
            warnings.append(f"[{name}] {reason}")
            reasons.append(reason)

    transport: str | None = None
    if source_format == FORMAT_GEMINI:
        if "httpUrl" in entry:
            transport = "http"
            converted["url"] = entry["httpUrl"]
            reasons.append("httpUrl→url（Gemini HTTP streaming 字段重命名，语义等价）")
        elif "command" in entry:
            transport = "stdio"
            converted["command"] = entry["command"]
        elif "url" in entry:
            # Gemini 官方语义：无 httpUrl 的 url 字段为 SSE 端点（旧流式传输）
            transport = "sse"
            converted["url"] = entry["url"]
            reasons.append(_SSE_LEGACY)
            reasons.append("url（无 httpUrl）→sse 端点（Gemini 官方语义：url 为 SSE 流端点）")
        elif "authProviderType" in entry:
            transport = "http"
            converted["url"] = entry.get("authProviderType", "")
            status = STATUS_NEEDS_CONFIG
            reasons.append("authProviderType: Google 认证提供方语义无 LFL 等价映射")
    elif source_format == FORMAT_VSCODE:
        declared = entry.get("type")
        if declared == "http" and "url" in entry:
            transport = "http"
            converted["url"] = entry["url"]
        elif declared in (None, "stdio") and "command" in entry:
            transport = "stdio"
            converted["command"] = entry["command"]
            if declared is None:
                reasons.append("未声明 type，按 command 推断 stdio（VS Code 允许省略）")
        elif declared == "sse":
            transport = "sse"
            converted["url"] = entry.get("url", "")
            reasons.append(_SSE_LEGACY)
        else:
            status = STATUS_UNSUPPORTED
            reasons.append(f"未知传输声明 type={declared!r}")
    else:
        # Codex .mcp.json / Cursor .cursor/mcp.json / 顶层 mcpServers 通用 JSON
        declared = entry.get("type")
        if "command" in entry:
            transport = "stdio"
            converted["command"] = entry["command"]
        elif "url" in entry:
            url = entry["url"]
            if declared == "sse":
                # 显式声明 sse 的 url 端点 = legacy SSE（非 Streamable HTTP），不得按 http 装配
                transport = "sse"
                converted["url"] = url
                reasons.append(_SSE_LEGACY)
            else:
                transport = "http"
                converted["url"] = url

    if transport is None:
        status = STATUS_UNSUPPORTED
        reasons.append("缺少 command/url 等传输字段，无法映射到 stdio/http/sse")
    else:
        converted["type"] = transport
        if "args" in entry:
            converted["args"] = entry["args"]
        if "env" in entry:
            converted["env"] = entry["env"]
        if transport in ("http", "sse") and "headers" in entry:
            converted["headers"] = entry["headers"]

    if transport == "stdio" and not isinstance(converted.get("command"), str):
        status = STATUS_INVALID
        reasons.append("stdio 条目 command 必须是字符串")
    if transport in ("http", "sse") and not isinstance(converted.get("url"), str):
        status = STATUS_INVALID
        reasons.append(f"{transport} 条目 url 必须是字符串")

    # 形态校验：args 列表、env/headers 对象（不改变值，仅校验）
    if "args" in converted and not isinstance(converted["args"], list):
        status = STATUS_INVALID
        reasons.append("args 必须是数组")
    for obj_field in ("env", "headers"):
        if obj_field in converted and not isinstance(converted[obj_field], dict):
            status = STATUS_INVALID
            reasons.append(f"{obj_field} 必须是对象")

    # Cursor auth：静态 OAuth 凭证不自动映射（§3：认证由用户按 LFL 认证白名单配置）
    if source_format == FORMAT_CURSOR and "auth" in entry:
        status = STATUS_NEEDS_CONFIG
        reasons.append("auth: 静态 OAuth 凭证不自动注入，需在 LFL 认证白名单配置")

    # 值内厂商/用户变量（§5.1）
    if status != STATUS_INVALID:
        converted_values, note = _expand_vendor_vars(converted, root, source_format)
        if note:
            reasons.append(note)
            if "${input:" in json.dumps(converted_values, ensure_ascii=False):
                status = STATUS_NEEDS_CONFIG
                reasons.append("${input:*}: VS Code 交互输入无法自动转换（§3）")
            elif "需安装方提供值" in note:
                status = STATUS_NEEDS_CONFIG
            converted = converted_values if isinstance(converted_values, dict) else converted

    # 未识别字段剔除并说明（不静默丢弃）
    mapped = {"type", "command", "args", "env", "url", "headers", "httpUrl"}
    known_unmapped = {f for f, _k, _r in _KNOWN_UNMAPPED_FIELDS.get(source_format, ())}
    known_unmapped |= {"auth", "authProviderType", "type", "url"}
    for key in entry:
        if key not in mapped and key not in known_unmapped:
            warnings.append(f"[{name}] 字段 {key} 未映射，未进入标准视图")
            reasons.append(f"字段 {key} 未映射")

    argv: list[str] = []
    if transport == "stdio" and isinstance(converted.get("command"), str):
        argv = [converted["command"]]
        raw_args = converted.get("args")
        if isinstance(raw_args, list):
            argv += [str(a) for a in raw_args]
    component = McpServerComponent(
        name=name,
        transport=transport or "",
        status=status,
        reason="; ".join(reasons) if reasons else "",
        command=tuple(argv[:64]),
        url=str(converted.get("url", ""))[:2048],
    )
    if status in (STATUS_INVALID, STATUS_UNSUPPORTED):
        return component, None
    return component, converted


def _convert_mcp_servers_map(
    servers: dict,
    root: Path,
    source_format: str,
    warnings: list[str],
) -> tuple[tuple[McpServerComponent, ...], dict[str, dict]]:
    components: list[McpServerComponent] = []
    converted_map: dict[str, dict] = {}
    for name, entry in servers.items():
        component, converted = _convert_server_entry(name, entry, root, source_format, warnings)
        components.append(component)
        if converted is not None:
            converted_map[name] = converted
    return tuple(components), converted_map


# ---------------------------------------------------------------- Claude/Codex 布局

# Claude/Codex 旧插件共用组件目录布局（官方：Codex 旧格式兼容 Claude 布局）。
_LAYOUT_UNMAPPED_DIRS = (
    ("agents", "agent", "子代理人格定义：LFL 无对应执行语义，不自动执行（§3）"),
    ("hooks", "hook", "hooks 不在 LFL 执行模型内，不执行（§3）"),
    ("output-styles", "output_style", "输出样式无标准组件等价物"),
    ("outputStyles", "output_style", "输出样式无标准组件等价物"),
    ("themes", "theme", "主题无标准组件等价物"),
    ("workflows", "workflow", "工作流无标准组件等价物"),
    ("monitors", "monitor", "monitors 为实验性监控组件，无标准等价物"),
)


def _scan_layout_unmapped(root: Path, unmapped: list[UnmappedComponent]) -> None:
    for dirname, kind, reason in _LAYOUT_UNMAPPED_DIRS:
        directory = root / dirname
        if directory.is_dir():
            for item in sorted(directory.rglob("*")):
                if item.is_file():
                    unmapped.append(
                        UnmappedComponent(name=str(item.relative_to(root)), kind=kind, status=STATUS_UNSUPPORTED, reason=reason)
                    )


def _scan_claude_layout(
    root: Path, manifest: dict | None, source_format: str
) -> tuple[list, list, list, list, dict]:
    """Claude/Codex 共用布局扫描 → (skills, servers, warnings, unmapped, converted_servers)."""
    warnings: list[str] = []
    unmapped: list[UnmappedComponent] = []
    skills = _parse_skills(root, warnings)
    _scan_layout_unmapped(root, unmapped)

    commands = root / "commands"
    if commands.is_dir():
        for item in sorted(commands.rglob("*.md")):
            rel = str(item.relative_to(root))
            try:
                text = item.read_text(encoding="utf-8")
            except OSError as exc:
                unmapped.append(UnmappedComponent(name=rel, kind="command", status=STATUS_INVALID, reason=f"读取失败: {exc}"))
                continue
            has_permission_fields = any(
                marker in text for marker in ("allowed-tools", "allowedTools", "permissions", "tool-reference")
            )
            if has_permission_fields:
                reason = "命令含权限语义字段（allowed-tools 等）：权限语义无法等价映射（§3），不自动转换"
            else:
                reason = "命令模板语义可保留（无权限字段），转换为技能需显式确认（§5.3）"
            unmapped.append(UnmappedComponent(name=rel, kind="command", status=STATUS_CONVERTIBLE, reason=reason))

    server_components: list[McpServerComponent] = []
    converted_map: dict[str, dict] = {}
    mcp_doc: dict | None = None
    for candidate in (root / ".mcp.json", root / "mcp.json", root / ".claude-plugin" / "mcp.json"):
        data, error = _load_json(candidate)
        if data is not None:
            mcp_doc = data
            break
        if error and "文件不存在" not in error:
            warnings.append(f"{candidate.name}: {error}")
    if mcp_doc is not None:
        servers = mcp_doc.get("mcpServers")
        if isinstance(servers, dict):
            server_components, converted_map = _convert_mcp_servers_map(servers, root, source_format, warnings)
        elif isinstance(servers, str):
            kind = "mcp_bundle" if servers.endswith((".mcpb", ".dxt")) else "mcp_file_ref"
            status = STATUS_UNSUPPORTED if kind == "mcp_bundle" else STATUS_CONVERTIBLE
            reason = (
                "bundle（.mcpb/.dxt）二进制格式不解析（§3）"
                if kind == "mcp_bundle"
                else "mcpServers 引用外部 JSON 文件，未自动合并（需显式确认）"
            )
            unmapped.append(UnmappedComponent(name=servers, kind=kind, status=status, reason=reason))
        elif isinstance(servers, list):
            unmapped.append(
                UnmappedComponent(
                    name="mcpServers",
                    kind="mcp_servers_array",
                    status=STATUS_CONVERTIBLE,
                    reason="mcpServers 为混合数组形态，未自动展开（需显式确认）",
                )
            )
        elif servers is not None:
            warnings.append("mcpServers 必须是对象、字符串或数组")

    if manifest:
        known = {"name", "displayName", "version", "metadata", "mcpServers", "defaultEnabled", "dependencies"}
        for key in manifest:
            if key not in known:
                warnings.append(f"manifest 字段 {key} 未映射（官方行为：未知顶层字段 strip+警告）")
        mcp_field = manifest.get("mcpServers")
        if mcp_field is not None and not (root / ".mcp.json").exists() and not (root / "mcp.json").exists():
            if isinstance(mcp_field, dict):
                inline_components, inline_map = _convert_mcp_servers_map(mcp_field, root, source_format, warnings)
                server_components = inline_components
                converted_map = inline_map
            else:
                unmapped.append(
                    UnmappedComponent(
                        name="manifest.mcpServers",
                        kind="mcp_servers_decl",
                        status=STATUS_CONVERTIBLE,
                        reason="manifest 内 mcpServers 为路径/数组声明，未自动展开",
                    )
                )
        user_config = manifest.get("userConfig")
        if isinstance(user_config, dict) and user_config:
            unmapped.append(
                UnmappedComponent(
                    name="userConfig",
                    kind="user_config_schema",
                    status=STATUS_NEEDS_CONFIG,
                    reason="userConfig 定义用户可配置项；${user_config.*} 需安装方提供值（§5.1）",
                )
            )
    return list(skills), server_components, warnings, unmapped, converted_map


def _parse_claude(root: Path, source_format: str, manifest_dir: str, fallback_name: str) -> VendorConversion:
    manifest, error = _load_json(root / manifest_dir / "plugin.json")
    warnings: list[str] = []
    if error and "文件不存在" not in error:
        warnings.append(f"plugin.json: {error}")
    skills, server_components, layout_warnings, unmapped, converted_map = _scan_claude_layout(
        root, manifest, source_format
    )
    warnings.extend(layout_warnings)
    report = _finish_report(
        _plugin_name(manifest, fallback_name), _version(manifest), root, tuple(skills), tuple(server_components), warnings, unmapped
    )
    return VendorConversion(
        source_format=source_format, report=report, mcp_servers=converted_map, unmapped=tuple(unmapped)
    )


# ---------------------------------------------------------------- Gemini CLI 扩展


def _parse_gemini(root: Path) -> VendorConversion:
    manifest, error = _load_json(root / "gemini-extension.json")
    warnings: list[str] = []
    unmapped: list[UnmappedComponent] = []
    if manifest is None:
        report = _finish_report("gemini-extension", "", root, (), (), [f"gemini-extension.json: {error}"], unmapped)
        return VendorConversion(source_format=FORMAT_GEMINI, report=report)

    gemini_warnings: list[str] = []
    skills = list(_parse_skills(root, gemini_warnings))

    for dirname, kind, reason in (
        ("agents", "agent", "agents 定义无 LFL 执行语义，不自动执行（§3）"),
        ("hooks", "hook", "hooks 不在 LFL 执行模型内，不执行（§3）"),
        ("policies", "policy", "策略组件无标准等价物"),
        ("themes", "theme", "主题无标准组件等价物"),
    ):
        directory = root / dirname
        if directory.is_dir():
            for item in sorted(directory.rglob("*")):
                if item.is_file():
                    unmapped.append(UnmappedComponent(name=str(item.relative_to(root)), kind=kind, status=STATUS_UNSUPPORTED, reason=reason))

    commands = root / "commands"
    if commands.is_dir():
        for item in sorted(commands.rglob("*")):
            if item.is_file():
                unmapped.append(
                    UnmappedComponent(
                        name=str(item.relative_to(root)),
                        kind="command",
                        status=STATUS_CONVERTIBLE,
                        reason="Gemini 命令为 CLI 交互定义（§3：作为显式转换项），未自动转换",
                    )
                )

    context_file = manifest.get("contextFileName")
    if context_file is None and (root / "GEMINI.md").exists():
        context_file = "GEMINI.md"
    if isinstance(context_file, str) and context_file:
        unmapped.append(
            UnmappedComponent(
                name=context_file,
                kind="context_file",
                status=STATUS_CONVERTIBLE,
                reason="上下文文件不提升为 LFL 系统规则（§3）；可作为普通文档显式引用",
            )
        )

    settings = manifest.get("settings")
    if isinstance(settings, list):
        for item in settings:
            name = item.get("envVar") if isinstance(item, dict) else None
            unmapped.append(
                UnmappedComponent(
                    name=str(name or "settings[]"),
                    kind="setting",
                    status=STATUS_NEEDS_CONFIG,
                    reason="扩展设置需安装方在安装时提供值（§5.1）",
                )
            )

    for field_name, reason in (
        ("excludeTools", "excludeTools: 工具暴露控制未映射"),
        ("plan", "plan 组件无标准等价物"),
    ):
        if manifest.get(field_name) is not None:
            unmapped.append(UnmappedComponent(name=field_name, kind="manifest_field", status=STATUS_UNSUPPORTED, reason=reason))

    server_components: tuple[McpServerComponent, ...] = ()
    converted_map: dict[str, dict] = {}
    servers = manifest.get("mcpServers")
    if servers is None:
        standalone, load_error = _load_json(root / "mcp.json")
        if standalone is not None and isinstance(standalone.get("mcpServers"), dict):
            servers = standalone["mcpServers"]
        elif load_error and "文件不存在" not in load_error:
            warnings.append(f"mcp.json: {load_error}")
    if isinstance(servers, dict):
        server_components, converted_map = _convert_mcp_servers_map(servers, root, FORMAT_GEMINI, warnings)
    elif servers is not None:
        warnings.append("mcpServers 必须是对象")

    report = _finish_report(
        _plugin_name(manifest, "gemini-extension"),
        _version(manifest),
        root,
        tuple(skills),
        server_components,
        [*warnings, *gemini_warnings],
        unmapped,
    )
    return VendorConversion(source_format=FORMAT_GEMINI, report=report, mcp_servers=converted_map, unmapped=tuple(unmapped))


# ---------------------------------------------------------------- 单文件 MCP 配置（Cursor / VS Code / 通用）


def _load_mcp_file(root: Path, candidates: tuple[Path, ...]) -> tuple[dict | None, Path | None, list[str]]:
    warnings: list[str] = []
    for candidate in candidates:
        data, error = _load_json(candidate)
        if data is not None:
            return data, candidate, warnings
        if error and "文件不存在" not in error:
            warnings.append(f"{candidate}: {error}")
    return None, None, warnings


def _parse_cursor(root: Path) -> VendorConversion:
    doc, found, warnings = _load_mcp_file(root, (root / ".cursor" / "mcp.json", root / "mcp.json"))
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    if not isinstance(servers, dict):
        report = _finish_report("cursor-mcp", "", root, (), (), [*warnings, "未找到顶层 mcpServers"], [])
        return VendorConversion(source_format=FORMAT_CURSOR, report=report)
    server_components, converted_map = _convert_mcp_servers_map(servers, root, FORMAT_CURSOR, warnings)
    report = _finish_report("cursor-mcp", "", root, (), server_components, warnings, [])
    return VendorConversion(source_format=FORMAT_CURSOR, report=report, mcp_servers=converted_map)


def _parse_vscode(root: Path) -> VendorConversion:
    doc, found, warnings = _load_mcp_file(root, (root / ".vscode" / "mcp.json", root / "mcp.json", root / "mcp-config.json"))
    servers = None
    if isinstance(doc, dict):
        servers = doc.get("servers") if isinstance(doc.get("servers"), dict) else doc.get("mcpServers")
        if doc.get("sandbox") is not None:
            warnings.append("顶层 sandbox: 沙盒策略不假定等价（§3），未映射")
    if not isinstance(servers, dict):
        report = _finish_report("vscode-mcp", "", root, (), (), [*warnings, "未找到顶层 servers/mcpServers"], [])
        return VendorConversion(source_format=FORMAT_VSCODE, report=report)
    server_components, converted_map = _convert_mcp_servers_map(servers, root, FORMAT_VSCODE, warnings)
    report = _finish_report("vscode-mcp", "", root, (), server_components, warnings, [])
    return VendorConversion(source_format=FORMAT_VSCODE, report=report, mcp_servers=converted_map)


def _parse_mcp_json(root: Path) -> VendorConversion:
    doc, found, warnings = _load_mcp_file(root, (root / "mcp.json", root / ".mcp.json", root / "mcp-config.json"))
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    if not isinstance(servers, dict):
        report = _finish_report("mcp-servers-json", "", root, (), (), [*warnings, "未找到顶层 mcpServers"], [])
        return VendorConversion(source_format=FORMAT_MCP_JSON, report=report)
    server_components, converted_map = _convert_mcp_servers_map(servers, root, FORMAT_MCP_JSON, warnings)
    report = _finish_report("mcp-servers-json", "", root, (), server_components, warnings, [])
    return VendorConversion(source_format=FORMAT_MCP_JSON, report=report, mcp_servers=converted_map)


# ---------------------------------------------------------------- 公共入口


def detect_vendor_format(root: Path) -> str | None:
    """嗅探包根的厂商格式；标准 Agent Plugins 包返回 FORMAT_STANDARD."""
    root = Path(root)
    if (root / "plugin.json").exists():
        return FORMAT_STANDARD
    if (root / ".claude-plugin" / "plugin.json").exists():
        return FORMAT_CLAUDE
    if (root / ".codex-plugin" / "plugin.json").exists():
        return FORMAT_CODEX
    if (root / "gemini-extension.json").exists():
        return FORMAT_GEMINI
    if (root / ".vscode" / "mcp.json").exists():
        return FORMAT_VSCODE
    if (root / ".cursor" / "mcp.json").exists():
        return FORMAT_CURSOR
    for name in ("mcp.json", ".mcp.json", "mcp-config.json"):
        data, error = _load_json(root / name)
        if data is not None and isinstance(data.get("mcpServers"), dict):
            return FORMAT_MCP_JSON
    return None


def parse_vendor_package(root: Path, *, source_format: str | None = None) -> VendorConversion:
    """解析厂商插件/配置包 → 兼容报告 + 标准视图（纯函数）.

    source_format 缺省时自动嗅探；无已知厂商标记时抛 ValueError（调用方应
    走标准加载器 parse_plugin_package，本模块不替代标准路径）。
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"包根必须是已存在目录: {root}")
    fmt = source_format or detect_vendor_format(root)
    if fmt is None:
        raise ValueError(f"未识别的厂商格式（无厂商标记文件）: {root}")
    if fmt == FORMAT_STANDARD:
        raise ValueError("标准 Agent Plugins 包请使用标准加载器 parse_plugin_package")
    if fmt == FORMAT_CLAUDE:
        return _parse_claude(root, FORMAT_CLAUDE, ".claude-plugin", "claude-plugin")
    if fmt == FORMAT_CODEX:
        return _parse_codex(root)
    if fmt == FORMAT_GEMINI:
        return _parse_gemini(root)
    if fmt == FORMAT_CURSOR:
        return _parse_cursor(root)
    if fmt == FORMAT_VSCODE:
        return _parse_vscode(root)
    if fmt == FORMAT_MCP_JSON:
        return _parse_mcp_json(root)
    raise ValueError(f"未知 source_format: {fmt}")


def convert_mcp_servers(root: Path, source_format: str) -> dict[str, dict]:
    """装配层入口：厂商包 → 标准 mcpServers dict（仅含可构造条目）."""
    conversion = parse_vendor_package(root, source_format=source_format)
    return conversion.mcp_servers


def _parse_codex(root: Path) -> VendorConversion:
    warnings: list[str] = []
    unmapped: list[UnmappedComponent] = []
    manifest, error = _load_json(root / ".codex-plugin" / "plugin.json")
    if error and "文件不存在" not in error:
        warnings.append(f".codex-plugin/plugin.json: {error}")

    app_doc, app_error = _load_json(root / ".app.json")
    if app_doc is not None:
        apps = app_doc.get("apps")
        names = list(apps.keys()) if isinstance(apps, dict) else ["apps"]
        for name in names:
            unmapped.append(
                UnmappedComponent(
                    name=str(name),
                    kind="app",
                    status=STATUS_UNSUPPORTED,
                    reason="App 平台关联不自动转为 LFL 凭证（§3）",
                )
            )
    elif app_error and "文件不存在" not in app_error:
        warnings.append(f".app.json: {app_error}")

    skills, server_components, layout_warnings, layout_unmapped, converted_map = _scan_claude_layout(
        root, manifest, FORMAT_CODEX
    )
    warnings.extend(layout_warnings)
    unmapped.extend(layout_unmapped)

    if converted_map == {} and (root / ".mcp.json").exists():
        doc, mcp_error = _load_json(root / ".mcp.json")
        if mcp_error:
            warnings.append(f".mcp.json: {mcp_error}")
        elif isinstance(doc.get("mcpServers"), dict):
            server_components, converted_map = _convert_mcp_servers_map(doc["mcpServers"], root, FORMAT_CODEX, warnings)

    report = _finish_report(
        _plugin_name(manifest, "codex-plugin"), _version(manifest), root, tuple(skills), tuple(server_components), warnings, unmapped
    )
    return VendorConversion(source_format=FORMAT_CODEX, report=report, mcp_servers=converted_map, unmapped=tuple(unmapped))
