"""extensions/vendor_formats 单测（DESIGN-20261009 P2-A: §3/§5.1/§5.3 + T24）.

T24：Claude/Codex/Gemini 配置含不支持组件 → partial 可解释；
转换不偷换原义（未映射字段/组件剔除并说明，不静默丢弃）。
"""

import shutil
from pathlib import Path

import pytest

from llm_loop.extensions.formats import (
    STATUS_CONVERTIBLE,
    STATUS_INVALID,
    STATUS_NEEDS_CONFIG,
    STATUS_SUPPORTED,
    STATUS_UNSUPPORTED,
)
from llm_loop.extensions.vendor_formats import (
    FORMAT_CLAUDE,
    FORMAT_CODEX,
    FORMAT_CURSOR,
    FORMAT_GEMINI,
    FORMAT_STANDARD,
    FORMAT_VSCODE,
    convert_mcp_servers,
    detect_vendor_format,
    parse_vendor_package,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fixture(name: str, tmp_path: Path) -> Path:
    """复制 fixture 到 tmp（隔离，避免污染 tests/ 目录）."""
    root = tmp_path / name
    shutil.copytree(FIXTURES / name, root)
    return root


# ---------------------------------------------------------------- Claude Code


def test_claude_detect_and_overall(tmp_path):
    root = _fixture("vendor_claude_demo", tmp_path)
    assert detect_vendor_format(root) == FORMAT_CLAUDE
    conv = parse_vendor_package(root)
    assert conv.source_format == FORMAT_CLAUDE
    # T24：含 unsupported/convertible 组件 → partial
    assert conv.report.overall == "partial"
    assert conv.report.plugin_name == "claude-demo"
    assert conv.report.version == "1.2.0"


def test_claude_skills_supported(tmp_path):
    conv = parse_vendor_package(_fixture("vendor_claude_demo", tmp_path))
    skills = {s.name: s.status for s in conv.report.skills}
    assert skills == {"lint": STATUS_SUPPORTED}


def test_claude_variables_expanded_in_adapter(tmp_path):
    """§5.1：厂商变量在厂商 adapter 内解析；未知变量保留并 needs_configuration."""
    root = _fixture("vendor_claude_demo", tmp_path)
    conv = parse_vendor_package(root)
    by_name = {s.name: s for s in conv.report.servers}
    # ${CLAUDE_PLUGIN_ROOT} 已展开为包根；未知 ${APP_CONFIG} → needs_configuration
    entry = conv.mcp_servers["local-srv"]
    assert entry["command"] == str(root / "bin" / "srv")
    assert entry["args"] == ["--config", "${APP_CONFIG}"]
    assert entry["env"]["DATA_DIR"] == "${PLUGIN_DATA}"  # PLUGIN_DATA 重命名（语义等价）
    assert by_name["local-srv"].status == STATUS_NEEDS_CONFIG
    assert "APP_CONFIG" in by_name["local-srv"].reason
    # web-srv 字段全等价 → supported
    assert conv.mcp_servers["web-srv"] == {
        "type": "http",
        "url": "https://example.com/mcp",
        "headers": {"X-Api": "k"},
    }
    assert by_name["web-srv"].status == STATUS_SUPPORTED


def test_claude_invalid_entry_not_converted(tmp_path):
    """不偷换原义：invalid 条目不进转换产物."""
    conv = parse_vendor_package(_fixture("vendor_claude_demo", tmp_path))
    by_name = {s.name: s for s in conv.report.servers}
    assert by_name["broken"].status == STATUS_INVALID
    assert "broken" not in conv.mcp_servers


def test_claude_commands_agents_hooks_classified(tmp_path):
    """§3/§5.3：命令 convertible（区分权限语义）；agents/hooks unsupported."""
    conv = parse_vendor_package(_fixture("vendor_claude_demo", tmp_path))
    unmapped = {u.name: u for u in conv.unmapped}
    deploy = unmapped["commands/deploy.md"]
    assert deploy.kind == "command" and deploy.status == STATUS_CONVERTIBLE
    assert "权限" in deploy.reason
    hello = unmapped["commands/hello.md"]
    assert hello.status == STATUS_CONVERTIBLE
    assert "无权限字段" in hello.reason  # 与含权限语义的 deploy 相区分
    reviewer = unmapped["agents/reviewer.md"]
    assert reviewer.kind == "agent" and reviewer.status == STATUS_UNSUPPORTED
    hooks = unmapped["hooks/hooks.json"]
    assert hooks.kind == "hook" and hooks.status == STATUS_UNSUPPORTED
    # 每个非 supported 组件都有非空 reason（T24 可解释）
    for item in conv.unmapped:
        assert item.reason.strip(), item


def test_claude_unknown_manifest_fields_warned(tmp_path):
    conv = parse_vendor_package(_fixture("vendor_claude_demo", tmp_path))
    assert any("experimentalTop" in w for w in conv.report.warnings)


# ---------------------------------------------------------------- Gemini CLI


def test_gemini_overall_and_skills(tmp_path):
    root = _fixture("vendor_gemini_demo", tmp_path)
    assert detect_vendor_format(root) == FORMAT_GEMINI
    conv = parse_vendor_package(root)
    assert conv.source_format == FORMAT_GEMINI
    assert conv.report.overall == "partial"
    assert {s.name: s.status for s in conv.report.skills} == {"security-audit": STATUS_SUPPORTED}


def test_gemini_httpurl_renamed_sse_legacy_transport(tmp_path):
    """httpUrl→url 字段重命名；url-only 条目映射 sse 旧传输（P2-B 解挂账）."""
    conv = parse_vendor_package(_fixture("vendor_gemini_demo", tmp_path))
    by_name = {s.name: s for s in conv.report.servers}
    assert conv.mcp_servers["http-srv"] == {
        "type": "http",
        "url": "https://example.com/mcp",
        "headers": {"Authorization": "Bearer tok"},
    }
    assert by_name["http-srv"].status == STATUS_SUPPORTED
    # Gemini 官方语义：无 httpUrl 的 url 字段为 SSE 端点 → sse 旧传输（显式声明）
    assert conv.mcp_servers["legacy-sse"]["type"] == "sse"
    assert conv.mcp_servers["legacy-sse"]["url"].startswith("https://")
    assert by_name["legacy-sse"].transport == "sse"
    assert by_name["legacy-sse"].status == STATUS_SUPPORTED
    assert "sse→sse" in by_name["legacy-sse"].reason


def test_gemini_permission_fields_not_dropped_silently(tmp_path):
    """trust/excludeTools/cwd/timeout 等权限与本地语义字段剔除并说明，不假定等价."""
    conv = parse_vendor_package(_fixture("vendor_gemini_demo", tmp_path))
    entry = conv.mcp_servers["toolbox"]
    assert entry == {"type": "stdio", "command": "tbx", "args": ["--n", "5"]}
    for marker in ("trust", "excludeTools", "cwd", "timeout"):
        assert any(marker in w for w in conv.report.warnings), marker
    reasons = {s.name: s.reason for s in conv.report.servers}["toolbox"]
    assert "trust" in reasons


def test_gemini_context_settings_commands_policies(tmp_path):
    conv = parse_vendor_package(_fixture("vendor_gemini_demo", tmp_path))
    unmapped = {(u.kind, u.name): u for u in conv.unmapped}
    ctx = unmapped[("context_file", "GEMINI.md")]
    assert ctx.status == STATUS_CONVERTIBLE and "不提升" in ctx.reason  # §3
    setting = unmapped[("setting", "GEMINI_API_KEY")]
    assert setting.status == STATUS_NEEDS_CONFIG
    cmd = unmapped[("command", "commands/build.toml")]
    assert cmd.status == STATUS_CONVERTIBLE
    policy = unmapped[("policy", "policies/strict.json")]
    assert policy.status == STATUS_UNSUPPORTED


# ---------------------------------------------------------------- Cursor


def test_cursor_stdio_supported_auth_needs_config(tmp_path):
    root = _fixture("vendor_cursor_demo", tmp_path)
    assert detect_vendor_format(root) == FORMAT_CURSOR
    conv = parse_vendor_package(root)
    by_name = {s.name: s for s in conv.report.servers}
    assert conv.mcp_servers["pkg"] == {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "pkg-mcp"],
        "env": {"N": "1"},
    }
    assert by_name["pkg"].status == STATUS_SUPPORTED
    # auth：静态 OAuth 凭证不自动注入（§3）
    assert by_name["auth-srv"].status == STATUS_NEEDS_CONFIG
    assert "auth" in by_name["auth-srv"].reason
    assert "auth" not in conv.mcp_servers["auth-srv"]


# ---------------------------------------------------------------- VS Code


def test_vscode_servers_mapping(tmp_path):
    root = _fixture("vendor_vscode_demo", tmp_path)
    assert detect_vendor_format(root) == FORMAT_VSCODE
    conv = parse_vendor_package(root)
    by_name = {s.name: s for s in conv.report.servers}
    assert conv.mcp_servers["http-s"] == {"type": "http", "url": "https://example.com/mcp"}
    assert by_name["http-s"].status == STATUS_SUPPORTED
    assert any("sandboxEnabled" in w for w in conv.report.warnings)
    # 无 type + command → stdio 推断（VS Code 允许省略）
    assert conv.mcp_servers["cli"]["command"] == "python3"
    assert by_name["cli"].status == STATUS_NEEDS_CONFIG  # ${input:entry} 无法自动转换
    assert "input" in by_name["cli"].reason
    # type: sse → P2-B：映射 sse 旧传输（源配置显式声明即显式选择）
    assert conv.mcp_servers["legacy"]["type"] == "sse"
    assert by_name["legacy"].status == STATUS_SUPPORTED
    assert "sse→sse" in by_name["legacy"].reason


def test_vscode_top_level_sandbox_ignored_with_warning(tmp_path):
    conv = parse_vendor_package(_fixture("vendor_vscode_demo", tmp_path))
    assert any("sandbox" in w for w in conv.report.warnings)


# ---------------------------------------------------------------- Codex legacy


def test_codex_legacy_layout(tmp_path):
    root = _fixture("vendor_codex_demo", tmp_path)
    assert detect_vendor_format(root) == FORMAT_CODEX
    conv = parse_vendor_package(root)
    assert conv.source_format == FORMAT_CODEX
    assert conv.report.plugin_name == "codex-demo"
    assert {s.name: s.status for s in conv.report.skills} == {"metrics": STATUS_SUPPORTED}
    assert conv.mcp_servers["codex-srv"] == {
        "type": "stdio",
        "command": "codex-runner",
        "args": ["--json"],
    }
    apps = [u for u in conv.unmapped if u.kind == "app"]
    assert len(apps) == 1 and apps[0].status == STATUS_UNSUPPORTED
    assert "不自动转为 LFL 凭证" in apps[0].reason  # §3


# ---------------------------------------------------------------- 嗅探与入口契约


def test_standard_package_detected_and_rejected(tmp_path):
    std = FIXTURES / "std_plugin_demo"
    assert detect_vendor_format(std) == FORMAT_STANDARD
    with pytest.raises(ValueError, match="标准"):
        parse_vendor_package(std)


def test_unknown_root_raises(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError):
        parse_vendor_package(empty)


def test_convert_mcp_servers_entrypoint(tmp_path):
    root = _fixture("vendor_cursor_demo", tmp_path)
    servers = convert_mcp_servers(root, FORMAT_CURSOR)
    assert servers["pkg"]["type"] == "stdio"
    assert isinstance(servers, dict)


def test_t24_every_unmapped_has_reason_and_valid_status(tmp_path):
    """T24 总检：五种 fixture 全部 partial 场景下，非 supported 项均有 reason."""
    valid = {STATUS_SUPPORTED, STATUS_NEEDS_CONFIG, STATUS_CONVERTIBLE, STATUS_UNSUPPORTED, STATUS_INVALID}
    for name in (
        "vendor_claude_demo",
        "vendor_gemini_demo",
        "vendor_cursor_demo",
        "vendor_vscode_demo",
        "vendor_codex_demo",
    ):
        conv = parse_vendor_package(_fixture(name, tmp_path))
        assert conv.report.overall == "partial", (name, conv.report.overall)
        for item in (*conv.report.skills, *conv.report.servers, *conv.unmapped):
            assert item.status in valid
            if item.status != STATUS_SUPPORTED:
                assert (getattr(item, "reason", "") or "").strip(), (name, item)
