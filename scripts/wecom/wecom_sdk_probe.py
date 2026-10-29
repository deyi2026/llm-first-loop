"""企微 SDK 连接探针（只读探测，不发消息、不改状态）。

用途：在真实凭据到位后，第一时间区分「网络/鉴权/协议问题」与「桥接代码问题」。
用法：.venv/bin/python scripts/wecom/wecom_sdk_probe.py
需要环境变量：WECHAT_BOT_ID、WECHAT_BOT_SECRET（从主区 .env 读取）
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV = ROOT / ".env"


def _load_env() -> None:
    if not ENV.is_file():
        return
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


async def _probe() -> int:
    from aibot import WSClient, WSClientOptions

    bot_id = os.environ.get("WECHAT_BOT_ID", "").strip()
    secret = os.environ.get("WECHAT_BOT_SECRET", "").strip()
    if not bot_id or not secret:
        print("缺少 WECHAT_BOT_ID / WECHAT_BOT_SECRET（请写入主区 .env）", file=sys.stderr)
        return 2

    connected = asyncio.Event()
    authed = asyncio.Event()
    auth_fail = []

    client = WSClient(
        options=WSClientOptions(bot_id=bot_id, secret=secret),
    )
    client.on("connected", lambda *a: connected.set())
    client.on("authenticated", lambda *a: authed.set())
    client.on("error", lambda e: auth_fail.append(repr(e)))
    client.on("disconnected", lambda r: auth_fail.append(f"disconnected: {r!r}"))

    try:
        await client.connect()
    except Exception as exc:  # noqa: BLE001 - 探针需要打印原始异常
        print(f"连接失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        await asyncio.wait_for(authed.wait(), timeout=20)
    except TimeoutError:
        # 区分两种失败：连上了但鉴权未过（服务端可达，凭据错）
        #                vs 根本没连上（网络/代理/端点不可达）
        verdict = (
            "PROBE_REACHABLE_BUT_UNAUTHENTICATED：TCP/WS 已连通，20s 内未收到 authenticated"
            "（服务端可达；通常是 BotID/Secret 不正确或机器人未启用 API 模式）"
            if connected.is_set()
            else "PROBE_UNREACHABLE：未收到 connected 事件（网络/代理/端点不可达）"
        )
        print(verdict, file=sys.stderr)
        print("期间事件:", auth_fail, file=sys.stderr)
        # SDK 的 disconnect() 是同步方法（aibot/client.py:100），不可 await
        client.disconnect()
        return 1

    print("PROBE_OK: 已连接并完成鉴权订阅")
    if auth_fail:
        print("期间事件:", auth_fail, file=sys.stderr)
    # SDK 的 disconnect() 是同步方法（aibot/client.py:100），不可 await
    client.disconnect()
    return 0


def main() -> int:
    _load_env()
    return asyncio.run(_probe())


if __name__ == "__main__":
    raise SystemExit(main())
