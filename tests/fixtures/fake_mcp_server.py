#!/usr/bin/env python
"""伪造 MCP stdio 服务器（测试夹具，P3-1）.

按 MCP 协议响应：initialize → notifications/initialized → tools/list → tools/call。
tools/call: name=echo → 回显 text；name=boom → isError=true；name=sleep → 睡 30s（超时用）。
"""

import json
import sys
import time


def send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method", "")
        mid = req.get("id")
        if method == "initialize":
            send({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "1.0"},
                },
            })
        elif method == "tools/list":
            send({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "回显输入文本",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string", "description": "要回显的内容"}},
                                "required": ["text"],
                            },
                        },
                        {
                            "name": "boom",
                            "description": "返回错误",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "sleep",
                            "description": "长时间睡眠（超时测试）",
                            "inputSchema": {"type": "object", "properties": {"seconds": {"type": "number"}}},
                        },
                    ]
                },
            })
        elif method == "tools/call":
            params = req.get("params") or {}
            tname = params.get("name")
            args = params.get("arguments") or {}
            if tname == "echo":
                send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"echo:{args.get('text', '')}"}], "isError": False},
                })
            elif tname == "boom":
                send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": "boom 错误详情"}], "isError": True},
                })
            elif tname == "sleep":
                time.sleep(float(args.get("seconds", 30)))
                send({"jsonrpc": "2.0", "id": mid, "result": {"content": [], "isError": False}})
        elif mid is None:
            continue  # notifications/initialized 等通知：忽略
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown {method}"}})


if __name__ == "__main__":
    main()
