"""LFL 对外导出 MCP server（P0-2 出向出口，stdio 只读）.

把 LFL 差异化能力面——经验库、方法库、证据 ledger、能力目录——以 MCP 协议
导出，供外部 Agent 宿主（Claude Desktop 及任何 MCP 客户端）直接复用。

协议形态：newline-delimited JSON-RPC 2.0 over stdio（MCP stdio wire format，
与 tests/fixtures/fake_mcp_server.py 同帧格式）。握手走 legacy ``initialize``：
客户端请求的 protocolVersion 在支持集内则原样 echo，否则回退默认版本。

安全边界：
- 硬只读：所有 store 以 ``write_guard`` 恒拒写构造；本模块无任何写路径。
- 证据面默认禁用（owner-scoped 隔离，外部消费者默认不持有任何 owner scope）。
  显式 ``LFL_EXPORT_EVIDENCE_OWNER="workspace_id/session_id"``（或 CLI
  ``--evidence-owner``）opt-in 后，仅暴露该 owner 的只读检索与有界水合。
- 不装配对话 engine，不执行模型调用。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from llm_loop.experiences.store import ExperienceStore
from llm_loop.export.capabilities import capability_catalog
from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceError,
    EvidenceHydration,
    EvidenceLedgerStore,
    EvidenceRef,
    EvidenceSearch,
    OwnerScope,
    RangeType,
)
from llm_loop.methods.store import MethodStore

SERVER_NAME = "lfl-export"
_SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2024-11-05", "2025-03-26", "2025-06-18"})
_DEFAULT_PROTOCOL_VERSION = "2024-11-05"
_EVIDENCE_OWNER_ENV = "LFL_EXPORT_EVIDENCE_OWNER"


class ToolError(Exception):
    """业务态工具失败：以 MCP isError 结果返回，不升级为协议错误。"""


class UnknownToolError(Exception):
    """tools/call 指向未注册工具：协议错误 -32602。"""


def _server_version() -> str:
    try:
        from importlib.metadata import version

        return version("llm-first-loop")
    except Exception:  # noqa: BLE001 — 元数据缺失时降级，不影响协议
        return "0.0.0"


def _deny_write() -> bool:
    """导出面恒拒写：任何经 store 的写路径在此被硬拦。"""
    return False


class _EvidenceAccess:
    """Opt-in 只读证据面：绑定单一 owner scope 的检索与有界水合。"""

    def __init__(self, evidence_root: Path, owner: OwnerScope) -> None:
        blobs = BlobStore(evidence_root / "blobs")
        ledger = EvidenceLedgerStore(evidence_root / "ledger")
        self.owner = owner
        self.search_engine = EvidenceSearch(blobs, ledger)
        self.hydration = EvidenceHydration(blobs, ledger)


@dataclass
class ExportBundle:
    """导出 server 的只读数据面绑定。``evidence is None`` 表示证据面禁用。"""

    experience_store: ExperienceStore
    method_store: MethodStore
    evidence: _EvidenceAccess | None


def _default_paths() -> tuple[str, str, str]:
    """缺省路径三元组（experiences/methods/evidence）.

    Settings 不可用（如无 LLM 凭证环境：load_settings 强校验 LLM_API_KEY）时
    回落纯文件默认值——导出面不依赖 LLM 凭证，不应被其配置校验阻塞。
    """
    try:
        from llm_loop.config import load_settings

        settings = load_settings()
        return (
            str(getattr(settings, "experiences_dir", "./experiences")),
            str(getattr(settings, "methods_dir", "./data/methods")),
            str(settings.evidence_dir),
        )
    except Exception:  # noqa: BLE001 — fail-open：配置不可用即走文件默认
        return "./experiences", "./data/methods", "./data/evidence"


def create_bundle(
    *,
    experiences_dir: str | Path | None = None,
    methods_dir: str | Path | None = None,
    method_seed_dir: str | Path | None = None,
    evidence_root: str | Path | None = None,
    evidence_owner: str | None = None,
) -> ExportBundle:
    """装配只读导出面；显式路径优先，缺省回落 Settings（不可用再回落文件默认）。"""
    default_exp, default_methods, default_evidence = _default_paths()
    exp_dir = Path(experiences_dir if experiences_dir else default_exp)
    m_dir = Path(methods_dir if methods_dir else default_methods)
    seed = method_seed_dir
    method_store = MethodStore(
        m_dir,
        seed_dir=Path(seed) if seed else None,
        write_guard=_deny_write,
    )
    experience_store = ExperienceStore(exp_dir, semantic_ranker=None, write_guard=_deny_write)
    evidence = _resolve_evidence_access(evidence_root, evidence_owner, default_evidence)
    return ExportBundle(
        experience_store=experience_store, method_store=method_store, evidence=evidence
    )


def _resolve_evidence_access(
    evidence_root: str | Path | None,
    evidence_owner: str | None,
    default_evidence_root: str,
) -> _EvidenceAccess | None:
    """证据面 opt-in 解析：未显式指定 owner、格式非法或 ledger 缺失 → 禁用（None）。"""
    raw = (evidence_owner or os.environ.get(_EVIDENCE_OWNER_ENV, "") or "").strip()
    if not raw or "/" not in raw:
        return None
    workspace_id, _, session_id = raw.partition("/")
    workspace_id = workspace_id.strip()
    session_id = session_id.strip()
    if not workspace_id or not session_id:
        return None
    root = Path(evidence_root) if evidence_root else Path(default_evidence_root)
    if not (root / "ledger").exists():  # 与 factory 判定一致：ledger 缺失即视为证据面未启用
        return None
    return _EvidenceAccess(root, OwnerScope(workspace_id=workspace_id, session_id=session_id))


# ---------------------------------------------------------------------------
# 工具面定义与实现（全部只读）
# ---------------------------------------------------------------------------


def _tool_specs(evidence_enabled: bool) -> list[dict[str, Any]]:
    """tools/list 静态定义；证据工具仅在 opt-in 后暴露。"""
    specs: list[dict[str, Any]] = [
        {
            "name": "search_experience",
            "description": "检索 LFL 经验库（lexical 相关性，仅 active 记录；空 query 列目录）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "关键词"},
                    "limit": {"type": "integer", "description": "返回上限，默认 8，最大 50"},
                },
            },
        },
        {
            "name": "read_experience",
            "description": "按 experience_id 水合读取经验全文（含正文与生命周期元数据）",
            "inputSchema": {
                "type": "object",
                "properties": {"experience_id": {"type": "string"}},
                "required": ["experience_id"],
            },
        },
        {
            "name": "search_method",
            "description": "检索 LFL 方法库（Method Learning 卡片）",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "默认 8，最大 50"},
                },
            },
        },
        {
            "name": "read_method",
            "description": "按 method_ref（形如 method:<id>）读取方法卡片",
            "inputSchema": {
                "type": "object",
                "properties": {"method_ref": {"type": "string"}},
                "required": ["method_ref"],
            },
        },
        {
            "name": "list_capabilities",
            "description": "列出 LFL 对外能力目录（导出面自描述）",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]
    if evidence_enabled:
        specs.extend(
            [
                {
                    "name": "search_evidence",
                    "description": "在指定 owner scope 内检索证据 ledger（exact blob 词法检索，返回摘要与 EvidenceRef）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "词组 AND/OR 检索语法"},
                            "limit": {"type": "integer", "description": "默认 8，最大 50"},
                        },
                    },
                },
                {
                    "name": "read_evidence",
                    "description": "按 evidence://v1/<record_id> 有界精确水合证据内容（range_type: text_char|line）",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "evidence_ref": {"type": "string"},
                            "range_type": {"type": "string", "enum": ["text_char", "line"]},
                            "start": {"type": "integer", "description": "0-based 起点"},
                            "limit": {"type": "integer", "description": "窗口长度，默认 200，最大 4000"},
                        },
                        "required": ["evidence_ref"],
                    },
                },
            ]
        )
    return specs


def _clamp_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, n))


def _t_search_experience(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    limit = _clamp_int(args.get("limit"), 8, minimum=1, maximum=50)
    outcome = bundle.experience_store.search_outcome(str(args.get("query", "")), limit)
    payload: dict[str, Any] = {
        "records": outcome.records,
        "count": len(outcome.records),
        "scanned": outcome.scanned_count,
        "skipped": outcome.skipped_count,
    }
    if outcome.scan_error:
        payload["scan_error"] = outcome.scan_error
    return payload


def _t_read_experience(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    experience_id = str(args.get("experience_id", "")).strip()
    if not experience_id:
        raise ToolError("experience_id is required")
    doc = bundle.experience_store.get(experience_id)
    if doc is None:
        raise ToolError(f"experience not found: {experience_id}")
    return ExperienceStore.to_hydrated_record(experience_id, doc)


def _t_search_method(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    limit = _clamp_int(args.get("limit"), 8, minimum=1, maximum=50)
    records = bundle.method_store.list(str(args.get("query", "")), limit)
    return {"records": records, "count": len(records)}


def _t_read_method(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    method_ref = str(args.get("method_ref", "")).strip()
    if not method_ref:
        raise ToolError("method_ref is required")
    record = bundle.method_store.get(method_ref)
    if record is None:
        raise ToolError(f"method not found: {method_ref}")
    card = record.card()
    payload: dict[str, Any] = dict(card) if isinstance(card, dict) else {"card": card}
    payload.setdefault("method_ref", method_ref)
    return payload


def _t_list_capabilities(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    return capability_catalog()


def _t_search_evidence(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    if bundle.evidence is None:
        raise ToolError(
            f"evidence layer disabled; set {_EVIDENCE_OWNER_ENV}=workspace_id/session_id to enable"
        )
    limit = _clamp_int(args.get("limit"), 8, minimum=1, maximum=50)
    try:
        result = bundle.evidence.search_engine.search(
            owner=bundle.evidence.owner, query=str(args.get("query", "")), limit=limit
        )
    except EvidenceError as exc:
        raise ToolError(f"evidence search failed: {exc}") from exc
    return {
        "hits": [
            {
                "evidence_ref": hit.evidence_ref.ref,
                "snippet": hit.snippet,
                "snippet_start_char": hit.snippet_start_char,
                "source_label": hit.source_label,
                "acquired_at": hit.acquired_at,
                "freshness": hit.freshness.value,
                "tool_name": hit.tool_name,
            }
            for hit in result.hits
        ],
        "total_hits": result.total_hits,
    }


def _t_read_evidence(bundle: ExportBundle, args: dict[str, Any]) -> dict[str, Any]:
    if bundle.evidence is None:
        raise ToolError(
            f"evidence layer disabled; set {_EVIDENCE_OWNER_ENV}=workspace_id/session_id to enable"
        )
    ref_raw = str(args.get("evidence_ref", "")).strip()
    if not ref_raw:
        raise ToolError("evidence_ref is required")
    try:
        evidence_ref = EvidenceRef(ref_raw)
        range_type = RangeType(str(args.get("range_type") or "text_char"))
    except ValueError as exc:
        raise ToolError(f"invalid argument: {exc}") from exc
    start = _clamp_int(args.get("start"), 0, minimum=0, maximum=10**9)
    limit = _clamp_int(args.get("limit"), 200, minimum=1, maximum=4000)
    try:
        hydrated = bundle.evidence.hydration.read(
            owner=bundle.evidence.owner,
            evidence_ref=evidence_ref,
            range_type=range_type,
            start=start,
            limit=limit,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except EvidenceError as exc:
        raise ToolError(f"evidence read failed: {exc}") from exc
    return {
        "evidence_ref": hydrated.evidence_ref.ref,
        "content": hydrated.content,
        "range_type": hydrated.range_type.value,
        "start": hydrated.start,
        "count": hydrated.count,
        "next_start": hydrated.next_start,
        "blob_sha256": hydrated.blob_sha256,
        "range_sha256": hydrated.range_sha256,
        "freshness": hydrated.freshness.value,
    }


_TOOL_HANDLERS: dict[str, Any] = {
    "search_experience": _t_search_experience,
    "read_experience": _t_read_experience,
    "search_method": _t_search_method,
    "read_method": _t_read_method,
    "list_capabilities": _t_list_capabilities,
    "search_evidence": _t_search_evidence,
    "read_evidence": _t_read_evidence,
}


# ---------------------------------------------------------------------------
# MCP 协议层（newline-delimited JSON-RPC 2.0 over stdio）
# ---------------------------------------------------------------------------


def _error_response(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _on_initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = str(params.get("protocolVersion", "") or "")
    protocol = requested if requested in _SUPPORTED_PROTOCOL_VERSIONS else _DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": protocol,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": _server_version()},
        "instructions": (
            "LFL read-only knowledge export: search/read experiences and methods, "
            "opt-in owner-scoped evidence, capability catalog."
        ),
    }


def _on_tools_call(bundle: ExportBundle, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if not isinstance(name, str):
        raise ToolError("tools/call requires a tool name")
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise UnknownToolError(f"unknown tool: {name}")
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    payload = handler(bundle, arguments)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": False,
    }


def handle_message(bundle: ExportBundle, message: Any) -> dict[str, Any] | None:
    """处理单条 stdio 消息；通知与畸形帧返回 None（不产生响应）。"""
    if not isinstance(message, dict):
        return None
    method = message.get("method")
    mid = message.get("id")
    if not isinstance(method, str) or mid is None:
        return None  # notification / 畸形帧：静默忽略
    try:
        if method == "initialize":
            params = message.get("params")
            result = _on_initialize(params if isinstance(params, dict) else {})
        elif method == "tools/list":
            result = {"tools": _tool_specs(bundle.evidence is not None)}
        elif method == "tools/call":
            params = message.get("params")
            result = _on_tools_call(bundle, params if isinstance(params, dict) else {})
        elif method == "ping":
            result = {}
        else:
            return _error_response(mid, -32601, f"unknown method: {method}")
    except UnknownToolError as exc:
        return _error_response(mid, -32602, str(exc))
    except ToolError as exc:
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True},
        }
    except Exception as exc:  # noqa: BLE001 — 服务端不因单帧异常退出
        return _error_response(mid, -32603, f"internal error: {exc}")
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(
    bundle: ExportBundle,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> None:
    """stdio 主循环：逐行 JSON-RPC；通知不回帧；畸形帧丢弃并记 stderr。"""
    inp = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            print(f"[{SERVER_NAME}] dropped malformed frame", file=sys.stderr)
            continue
        response = handle_message(bundle, message)
        if response is None:
            continue
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llm_loop export-serve-mcp",
        description="LFL 只读导出 MCP server（stdio）：经验/方法/能力目录，证据面 opt-in",
    )
    parser.add_argument("--experiences-dir", default=None, help="覆盖经验库目录（缺省读 Settings）")
    parser.add_argument("--methods-dir", default=None, help="覆盖方法库目录")
    parser.add_argument("--method-seed-dir", default=None, help="覆盖方法 seed 目录")
    parser.add_argument("--evidence-root", default=None, help="覆盖证据 ledger 根目录")
    parser.add_argument(
        "--evidence-owner",
        default=None,
        help="workspace_id/session_id；缺省读 LFL_EXPORT_EVIDENCE_OWNER",
    )
    args = parser.parse_args(argv)
    bundle = create_bundle(
        experiences_dir=args.experiences_dir,
        methods_dir=args.methods_dir,
        method_seed_dir=args.method_seed_dir,
        evidence_root=args.evidence_root,
        evidence_owner=args.evidence_owner,
    )
    print(
        f"[{SERVER_NAME}] read-only export ready; evidence layer:",
        "enabled" if bundle.evidence is not None else "disabled",
        file=sys.stderr,
    )
    serve(bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
