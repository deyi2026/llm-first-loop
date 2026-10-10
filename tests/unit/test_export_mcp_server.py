"""export MCP server（P0-2 出向出口）协议与工具面测试.

覆盖：legacy initialize 握手（版本 echo/回退）、通知静默、tools/list 随证据面
opt-in 变化、四类只读数据源（经验/方法/证据/能力目录）各自至少一次成功调用、
业务错误（isError）与协议错误（-32601/-32602）分型、stdio 主循环与子进程端到端。
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from llm_loop.export.mcp_server import create_bundle, handle_message, serve

EXPERIENCE_MD = """---
title: stdio 导出连通经验
scenario: 外部 MCP 客户端连通 LFL 导出 server
root_cause: 无现成出向出口
solution: 手写 newline-delimited JSON-RPC stdio server，复用 store 只读层
evidence: tests/unit/test_export_mcp_server.py 通过
tags: [mcp, export, test]
source:
  raw: test-fixture
status: active
created_at: 2026-10-10T08:00:00+08:00
updated_at: 2026-10-10T08:00:00+08:00
---
正文：stdio 导出连通验证数据。
"""

METHOD_MD = """---
method_id: stdio-export-method
name: 测试导出方法
description: 导出测试造数方法
status: candidate
---
方法正文：stdio 导出测试。
"""


def _make_bundle(tmp_path: Path, evidence_owner: str | None = None):
    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir(exist_ok=True)
    (exp_dir / "EXPERIENCE-test-stdio.md").write_text(EXPERIENCE_MD, encoding="utf-8")
    method_dir = tmp_path / "methods" / "stdio-export-method"
    method_dir.mkdir(parents=True, exist_ok=True)
    (method_dir / "METHOD.md").write_text(METHOD_MD, encoding="utf-8")
    return create_bundle(
        experiences_dir=exp_dir,
        methods_dir=tmp_path / "methods",
        evidence_root=tmp_path / "evidence",
        evidence_owner=evidence_owner,
    )


def _seed_evidence(tmp_path: Path) -> str:
    """用正式 EvidenceCapture 写一条记录，返回 evidence://v1/... 引用。"""
    from llm_loop.memory.evidence import (
        BlobStore,
        CaptureRequest,
        Coverage,
        EvidenceCapture,
        EvidenceLedgerStore,
        OwnerScope,
        Provenance,
        SourceIdentity,
        SourceKind,
        SourceVersionPolicy,
    )

    root = tmp_path / "evidence"
    capture = EvidenceCapture(
        BlobStore(root / "blobs"), EvidenceLedgerStore(root / "ledger")
    )
    result = capture.capture(
        CaptureRequest(
            owner=OwnerScope(workspace_id="ws-test", session_id="sess-test"),
            stable_capture_id="cap-001",
            raw_observation="证据正文：stdio 导出连通验证数据 export-proof-12345",
            acquired_at=datetime(2026, 10, 10, 8, 0, 0, tzinfo=UTC),
            tool_name="read_file",
            tool_call_id=None,
            source=SourceIdentity(
                kind=SourceKind.FILE,
                locator="tests/fixtures/demo.txt",
                version_policy=SourceVersionPolicy.PROBEABLE,
                version_token="tok-1",
            ),
            coverage=Coverage(unit="text_char", start=0, end_exclusive=41, source_complete=True),
            provenance=Provenance(producer="test"),
        )
    )
    return result.evidence_ref.ref


def _request(bundle, method: str, params=None, mid: int = 1):
    message: dict = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        message["params"] = params
    return handle_message(bundle, message)


def _call(bundle, name: str, arguments: dict | None = None):
    """tools/call 成功路径 helper：返回解析后的工具载荷。"""
    response = _request(
        bundle, "tools/call", {"name": name, "arguments": arguments or {}}
    )
    assert response is not None and "result" in response, response
    assert response["result"]["isError"] is False, response
    return json.loads(response["result"]["content"][0]["text"])


# ── 协议层 ────────────────────────────────────────────────────────────────────


def test_initialize_echoes_supported_version(tmp_path):
    bundle = _make_bundle(tmp_path)
    response = _request(
        bundle, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert response["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert response["result"]["serverInfo"]["name"] == "lfl-export"


def test_initialize_falls_back_for_unknown_version(tmp_path):
    bundle = _make_bundle(tmp_path)
    response = _request(bundle, "initialize", {"protocolVersion": "1999-01-01"})
    assert response["result"]["protocolVersion"] == "2024-11-05"


def test_notification_produces_no_response(tmp_path):
    bundle = _make_bundle(tmp_path)
    assert (
        handle_message(bundle, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        is None
    )


def test_unknown_method_is_protocol_error(tmp_path):
    bundle = _make_bundle(tmp_path)
    response = _request(bundle, "resources/list")
    assert response["error"]["code"] == -32601


def test_unknown_tool_is_protocol_error(tmp_path):
    bundle = _make_bundle(tmp_path)
    response = _request(bundle, "tools/call", {"name": "no_such_tool"})
    assert response["error"]["code"] == -32602


def test_tools_list_hides_evidence_until_opt_in(tmp_path):
    disabled = _make_bundle(tmp_path)
    names_disabled = {t["name"] for t in _request(disabled, "tools/list")["result"]["tools"]}
    assert "search_evidence" not in names_disabled
    assert "read_evidence" not in names_disabled

    _seed_evidence(tmp_path)
    enabled = _make_bundle(tmp_path, evidence_owner="ws-test/sess-test")
    names_enabled = {t["name"] for t in _request(enabled, "tools/list")["result"]["tools"]}
    assert {"search_evidence", "read_evidence"} <= names_enabled


# ── 四类只读数据源：各自至少一次成功调用 ─────────────────────────────────────


def test_search_experience_finds_seeded_record(tmp_path):
    bundle = _make_bundle(tmp_path)
    payload = _call(bundle, "search_experience", {"query": "stdio"})
    assert payload["count"] >= 1
    assert payload["scanned"] >= 1
    assert any("stdio" in str(r) for r in payload["records"])


def test_read_experience_returns_hydrated_body(tmp_path):
    bundle = _make_bundle(tmp_path)
    payload = _call(bundle, "read_experience", {"experience_id": "EXPERIENCE-test-stdio.md"})
    assert "正文：stdio 导出连通验证数据" in str(payload)


def test_search_and_read_method(tmp_path):
    bundle = _make_bundle(tmp_path)
    found = _call(bundle, "search_method", {"query": "导出"})
    assert found["count"] >= 1
    card = _call(bundle, "read_method", {"method_ref": "method:stdio-export-method"})
    assert card.get("method_ref") == "method:stdio-export-method"


def test_list_capabilities_describes_layers(tmp_path):
    bundle = _make_bundle(tmp_path)
    catalog = _call(bundle, "list_capabilities")
    layer_ids = {layer["id"] for layer in catalog["exported_layers"]}
    assert {"experience", "method", "evidence", "capabilities"} <= layer_ids


def test_evidence_disabled_tool_error_mentions_opt_in_env(tmp_path):
    bundle = _make_bundle(tmp_path)
    response = _request(
        bundle, "tools/call", {"name": "search_evidence", "arguments": {"query": "x"}}
    )
    assert response["result"]["isError"] is True
    assert "LFL_EXPORT_EVIDENCE_OWNER" in response["result"]["content"][0]["text"]


def test_evidence_search_and_bounded_read(tmp_path):
    _seed_evidence(tmp_path)
    bundle = _make_bundle(tmp_path, evidence_owner="ws-test/sess-test")
    hits = _call(bundle, "search_evidence", {"query": "export-proof"})
    assert hits["total_hits"] >= 1
    ref = hits["hits"][0]["evidence_ref"]
    hydrated = _call(
        bundle,
        "read_evidence",
        {"evidence_ref": ref, "range_type": "text_char", "start": 0, "limit": 40},
    )
    assert hydrated["count"] == 38  # 观测全文 38 字符，limit=40 一次读完
    assert hydrated["next_start"] is None
    line_view = _call(
        bundle,
        "read_evidence",
        {"evidence_ref": ref, "range_type": "line", "start": 0, "limit": 10},
    )
    assert "export-proof-12345" in line_view["content"]


def test_evidence_rejects_foreign_owner(tmp_path):
    """owner 隔离：不同 scope 即使指向同一 ledger 也读不到记录。"""
    _seed_evidence(tmp_path)
    bundle = _make_bundle(tmp_path, evidence_owner="ws-other/sess-other")
    hits = _call(bundle, "search_evidence", {"query": "export-proof"})
    assert hits["total_hits"] == 0


# ── stdio 主循环与子进程端到端 ───────────────────────────────────────────────


def test_stdio_loop_serves_frames_in_order(tmp_path):
    bundle = _make_bundle(tmp_path)
    frames = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            }
        ),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_experience", "arguments": {"query": "stdio"}},
            }
        ),
        "not-json-line",  # 畸形帧：丢弃不崩
    ]
    out = io.StringIO()
    serve(bundle, stdin=io.StringIO("\n".join(frames) + "\n"), stdout=out)
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert len(responses) == 3  # 通知与畸形帧不回帧
    assert responses[0]["result"]["protocolVersion"] == "2024-11-05"
    assert any(t["name"] == "search_experience" for t in responses[1]["result"]["tools"])
    payload = json.loads(responses[2]["result"]["content"][0]["text"])
    assert payload["count"] >= 1


def test_subprocess_end_to_end(tmp_path):
    """真实子进程形态：python -m llm_loop.export.mcp_server 起服，管道双端往返。"""
    exp_dir = tmp_path / "experiences"
    exp_dir.mkdir(exist_ok=True)
    (exp_dir / "EXPERIENCE-e2e.md").write_text(EXPERIENCE_MD, encoding="utf-8")
    mdir = tmp_path / "methods"
    (mdir / "e2e-method").mkdir(parents=True)
    (mdir / "e2e-method" / "METHOD.md").write_text(METHOD_MD, encoding="utf-8")
    frames = [
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
            }
        ),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "read_experience",
                    "arguments": {"experience_id": "EXPERIENCE-e2e.md"},
                },
            }
        ),
    ]
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "llm_loop.export.mcp_server",
            "--experiences-dir",
            str(exp_dir),
            "--methods-dir",
            str(mdir),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    try:
        out, err = proc.communicate("\n".join(frames) + "\n", timeout=60)
    except subprocess.TimeoutExpired:  # pragma: no cover — 防御挂死
        proc.kill()
        raise
    assert proc.returncode == 0, err
    responses = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert responses[0]["result"]["serverInfo"]["name"] == "lfl-export"
    payload = json.loads(responses[1]["result"]["content"][0]["text"])
    assert "正文：stdio 导出连通验证数据" in str(payload)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("read_experience", {"experience_id": "no-such-id"}),
        ("read_method", {"method_ref": "method:no-such-method"}),
    ],
)
def test_not_found_is_business_error_not_crash(tmp_path, tool, arguments):
    bundle = _make_bundle(tmp_path)
    response = _request(bundle, "tools/call", {"name": tool, "arguments": arguments})
    assert response["result"]["isError"] is True
