"""mcp_protocol 纯逻辑单元测试（版本协商 / _meta / 错误识别）— P1-B."""

import pytest

from llm_loop.tools.mcp_protocol import (
    LEGACY_VERSIONS,
    MODERN_VERSIONS,
    SUPPORTED_VERSIONS,
    build_call_tool_request,
    build_discover_request,
    build_initialize_request,
    build_list_tools_request,
    build_subscribe_request,
    client_identity,
    extract_supported_versions,
    is_known_version,
    modern_request_meta,
    negotiate_initialize_result,
    parse_discover_result,
    select_mutual_modern_version,
    select_mutual_version,
    with_modern_meta,
)


# ── 版本与时代 ──
def test_supported_set_covers_design_minimum():
    """设计文档 §6.2 最低明确支持集：2024-11-05 stdio；2025-11-25 与 2026-07-28 双传输."""
    assert "2024-11-05" in SUPPORTED_VERSIONS
    assert "2025-11-25" in SUPPORTED_VERSIONS
    assert MODERN_VERSIONS == ["2026-07-28"]


def test_select_mutual_version_prefers_highest_known():
    assert select_mutual_version(["2024-11-05", "2025-03-26"]) == "2025-03-26"
    assert select_mutual_version(["1999-01-01"]) is None
    assert select_mutual_version([]) is None


def test_select_mutual_modern_version_only_modern():
    assert select_mutual_modern_version(["2025-11-25"]) is None
    assert select_mutual_modern_version(["2026-07-28"]) == "2026-07-28"


def test_is_known_version_rejects_shape():
    assert is_known_version("2026-07-28")
    assert not is_known_version("2026-13-28")
    assert not is_known_version(20260728)


# ── UnsupportedProtocolVersionError 识别 ──
def test_extract_supported_versions_from_data():
    err = {"code": -32070, "message": "UnsupportedProtocolVersionError", "data": {"supported": ["2026-07-28"]}}
    assert extract_supported_versions(err) == ["2026-07-28"]


def test_extract_supported_versions_rejects_non_version_shapes():
    assert extract_supported_versions({"data": {"supported": ["latest"]}}) is None
    assert extract_supported_versions({"data": "oops"}) is None
    assert extract_supported_versions({"code": -32601, "message": "Method not found"}) is None


def test_extract_supported_versions_message_signal_without_list():
    """有信号但无结构化列表 → 空列表（上层报协议错误而非回退）."""
    assert extract_supported_versions({"message": "UnsupportedProtocolVersionError"}) == []


# ── 现代 _meta ──
def test_modern_request_meta_carries_version_identity_capabilities():
    meta = modern_request_meta("2026-07-28")
    assert meta["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    info = meta["io.modelcontextprotocol/clientInfo"]
    assert isinstance(info["name"], str) and info["name"]
    assert isinstance(info["version"], str) and info["version"]
    assert "io.modelcontextprotocol/clientCapabilities" in meta


def test_with_modern_meta_preserves_caller_keys():
    params = {"name": "t", "_meta": {"custom": 1}}
    merged = with_modern_meta("2026-07-28", params)
    assert merged["_meta"]["custom"] == 1
    assert merged["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert params["_meta"] == {"custom": 1}  # 原对象不被改写


def test_client_identity_shape():
    info = client_identity()
    assert info["name"] == "llm-first-loop"


# ── 请求构造 ──
def test_build_discover_request():
    req = build_discover_request(7, "2026-07-28")
    assert req["method"] == "server/discover" and req["id"] == 7
    assert req["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"


def test_build_initialize_request_legacy_shape():
    req = build_initialize_request(3, "2025-11-25")
    assert req["method"] == "initialize"
    assert req["params"]["protocolVersion"] == "2025-11-25"
    assert "_meta" not in req["params"]  # 旧时代无逐请求 _meta


def test_build_list_tools_request_cursor_and_meta():
    from llm_loop.tools.mcp_protocol import ProtocolProfile

    profile = ProtocolProfile(era="modern", version="2026-07-28")
    req = build_list_tools_request(5, "p2", profile)
    assert req["params"]["cursor"] == "p2"
    assert req["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"


def test_build_call_tool_request_meta_only_modern():
    from llm_loop.tools.mcp_protocol import ProtocolProfile

    legacy = ProtocolProfile(era="legacy", version="2024-11-05")
    req = build_call_tool_request(1, "echo", {"text": "x"}, legacy)
    assert req["params"] == {"name": "echo", "arguments": {"text": "x"}}


def test_build_subscribe_request_types():
    from llm_loop.tools.mcp_protocol import ProtocolProfile

    profile = ProtocolProfile(era="modern", version="2026-07-28")
    req = build_subscribe_request(9, ["toolsListChanged"], profile)
    assert req["method"] == "subscriptions/listen"
    assert req["params"]["types"] == ["toolsListChanged"]


# ── DiscoverResult / initialize 协商 ──
def test_parse_discover_result_tolerates_meta_server_info():
    supported, caps, info = parse_discover_result(
        {"supportedVersions": ["2026-07-28"], "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "s", "version": "1"}}}
    )
    assert supported == ["2026-07-28"] and info["name"] == "s" and caps == {}


def test_parse_discover_result_rejects_missing_versions():
    from llm_loop.tools.mcp_protocol import McpProtocolError

    with pytest.raises(McpProtocolError):
        parse_discover_result({"capabilities": {}})


def test_negotiate_initialize_accepts_known_server_version():
    assert negotiate_initialize_result({"protocolVersion": "2024-11-05"}, "2025-11-25") == "2024-11-05"


def test_negotiate_initialize_rejects_unknown_server_version():
    from llm_loop.tools.mcp_protocol import McpProtocolError

    with pytest.raises(McpProtocolError):
        negotiate_initialize_result({"protocolVersion": "2030-01-01"}, "2025-11-25")
    with pytest.raises(McpProtocolError):
        negotiate_initialize_result({"protocolVersion": None}, "2025-11-25")


def test_legacy_offer_is_newest_legacy():
    """旧时代握手优先报价最新旧版本（2025-11-25）."""
    assert LEGACY_VERSIONS[0] == "2025-11-25"
