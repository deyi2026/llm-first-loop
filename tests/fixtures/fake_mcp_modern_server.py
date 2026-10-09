"""现代（2026-07-28）MCP stdio 测试服务器.

行为：
- server/discover：校验 _meta 协议版本；FAKE_MODERN_REJECT_FIRST=1 时第一次
  探测返回 UnsupportedProtocolVersionError（data.supported）→ 客户端应按
  列表选版本重试一次，不回退旧握手。
- tools/list：游标分页（每页 2 个工具）；校验 _meta 版本。
- tools/call：echo / get_last_meta（返回服务器看到的最近 _meta）/
  bump_list（推送 tools/list_changed 通知（_meta.subscriptionId 标记），
  下次 tools/list 增加 extra_tool）。
- subscriptions/listen：接受（长驻，不回响应帧）。
- 未知方法：-32601。
"""

from __future__ import annotations

import json
import os
import sys

SUPPORTED = ["2026-07-28"]
PAGE_SIZE = 2
BASE_TOOLS = ["echo", "get_last_meta", "bump_list"]

_meta_state = {"last": None}
_flags = {"rejected_first": False}
_extra_tool = {"on": False}


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def error(mid: int, code: int, message: str, data: dict | None = None) -> None:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    send({"jsonrpc": "2.0", "id": mid, "error": err})


def meta_version(msg: dict) -> str | None:
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    v = meta.get("io.modelcontextprotocol/protocolVersion")
    return v if isinstance(v, str) else None


def tools() -> list[dict]:
    names = BASE_TOOLS + (["extra_tool"] if _extra_tool["on"] else [])
    return [
        {
            "name": n,
            "description": f"modern fixture tool {n}",
            "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
        for n in names
    ]


def handle(msg: dict) -> None:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
    if not isinstance(method, str):
        return
    if method == "server/discover":
        version = meta_version(msg)
        if os.environ.get("FAKE_MODERN_REJECT_FIRST") == "1" and not _flags["rejected_first"]:
            _flags["rejected_first"] = True
            error(
                mid,
                -32070,
                "UnsupportedProtocolVersionError: server does not support requested version",
                {"supported": SUPPORTED},
            )
            return
        if version not in SUPPORTED:
            error(mid, -32070, "UnsupportedProtocolVersionError", {"supported": SUPPORTED})
            return
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "supportedVersions": SUPPORTED,
                    "capabilities": {"tools": {"listChanged": True}},
                    "serverInfo": {"name": "fake-modern", "version": "1.0"},
                    "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "fake-modern", "version": "1.0"}},
                },
            }
        )
        return
    if not isinstance(mid, int):
        return  # 通知：现代 fixture 忽略
    if method == "tools/list":
        if meta_version(msg) != "2026-07-28":
            error(mid, -32070, "UnsupportedProtocolVersionError", {"supported": SUPPORTED})
            return
        cursor = params.get("cursor")
        all_tools = tools()
        start_idx = {"p2": PAGE_SIZE, "p3": 2 * PAGE_SIZE}.get(cursor, 0)
        page = all_tools[start_idx : start_idx + PAGE_SIZE]
        result: dict = {"tools": page}
        if start_idx + PAGE_SIZE < len(all_tools):
            result["nextCursor"] = f"p{start_idx // PAGE_SIZE + 2}"
        send({"jsonrpc": "2.0", "id": mid, "result": result})
        return
    if method == "tools/call":
        if meta_version(msg) != "2026-07-28":
            error(mid, -32070, "UnsupportedProtocolVersionError", {"supported": SUPPORTED})
            return
        pmeta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
        _meta_state["last"] = pmeta
        name = params.get("name")
        if name == "echo":
            text = (params.get("arguments") or {}).get("text", "")
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"isError": False, "content": [{"type": "text", "text": f"echo:{text}"}]},
                }
            )
            return
        if name == "get_last_meta":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "isError": False,
                        "content": [{"type": "text", "text": json.dumps(_meta_state["last"], ensure_ascii=False)}],
                    },
                }
            )
            return
        if name == "bump_list":
            _extra_tool["on"] = True
            # 订阅通知：_meta.subscriptionId 标记（现代规范）
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/tools/list_changed",
                    "params": {"_meta": {"io.modelcontextprotocol/subscriptionId": "sub-1"}},
                }
            )
            send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"isError": False, "content": [{"type": "text", "text": "bumped"}]},
                }
            )
            return
        error(mid, -32602, f"Unknown tool: {name}")
        return
    if method == "subscriptions/listen":
        # 长驻：不回响应帧（客户端 fire-and-forget 派发）
        return
    error(mid, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            handle(msg)


if __name__ == "__main__":
    main()
