#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        text = line.decode("utf-8", "replace").strip()
        if not text:
            break
        if ":" in text:
            key, _, value = text.partition(":")
            headers[key.strip().lower()] = value.strip()
    size = int(headers.get("content-length", "0"))
    if size <= 0:
        return None
    body = sys.stdin.buffer.read(size)
    return json.loads(body.decode("utf-8"))


def send(obj: dict[str, Any]) -> None:
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "protocol"
    marker = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    init = read_message()
    if not init or init.get("method") != "initialize":
        return 10

    # Server->client request during initialize. The client must answer it before
    # the initialize response is released, otherwise initialization stalls.
    send(
        {
            "jsonrpc": "2.0",
            "id": 9001,
            "method": "window/workDoneProgress/create",
            "params": {"token": "fake-init"},
        }
    )
    progress_reply = read_message()
    if not progress_reply or progress_reply.get("id") != 9001 or "result" not in progress_reply:
        return 11

    send(
        {
            "jsonrpc": "2.0",
            "id": init["id"],
            "result": {
                "capabilities": {
                    "referencesProvider": True,
                    "definitionProvider": True,
                    "callHierarchyProvider": True,
                    "documentSymbolProvider": True,
                }
            },
        }
    )

    initialized = read_message()
    if not initialized or initialized.get("method") != "initialized":
        return 12
    send(
        {
            "jsonrpc": "2.0",
            "method": "window/logMessage",
            "params": {"type": 3, "message": "initialized-seen"},
        }
    )

    if mode == "exit-after-initialized":
        return 23
    if mode == "malformed-after-initialized":
        sys.stdout.buffer.write(b"Content-Length: 5\r\n\r\nabcde")
        sys.stdout.buffer.flush()
        time.sleep(2.0)
        return 24

    if mode == "unknown-request":
        send(
            {
                "jsonrpc": "2.0",
                "id": 9002,
                "method": "workspace/notSupportedByClient",
                "params": {},
            }
        )
        reply = read_message()
        ok = bool(
            reply and reply.get("id") == 9002 and (reply.get("error") or {}).get("code") == -32601
        )
        send(
            {
                "jsonrpc": "2.0",
                "method": "test/unknownHandled",
                "params": {"ok": ok, "reply": reply},
            }
        )

    while True:
        msg = read_message()
        if msg is None:
            return 0
        method = msg.get("method")
        if method == "textDocument/didOpen":
            uri = ((msg.get("params") or {}).get("textDocument") or {}).get("uri")
            send(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": {"uri": uri, "diagnostics": []},
                }
            )
        elif method == "shutdown" and "id" in msg:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
        elif method == "exit":
            if marker is not None:
                marker.write_text("graceful\n", encoding="utf-8")
            return 0
        elif "id" in msg:
            send({"jsonrpc": "2.0", "id": msg["id"], "result": []})


if __name__ == "__main__":
    raise SystemExit(main())
