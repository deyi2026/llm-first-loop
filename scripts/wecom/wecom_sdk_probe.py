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
from urllib.parse import urlsplit

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


def _ensure_proxy_bypass(hosts: list[str]) -> None:
    """把给定主机加入 no_proxy 绕过列表（强制直连，不经系统/环境代理）.

    与 src/llm_loop/wecom/config.py 的 ensure_proxy_bypass 语义等价的最小
    实现（探针刻意不 import llm_loop 包，保持零依赖、可独立排障）：
    no_proxy 与 NO_PROXY 两个环境变量都要写——urllib 的
    getproxies_environment() 只有在 no_proxy 非空时才返回非空 dict，单写
    NO_PROXY 不生效。写入后 urllib.request.getproxies() 走 env 分支，
    websockets>=15 不再读 macOS 系统代理（其 socks 项会把 wss:// 改写成
    socks5h://，企微域名不在 ExceptionsList 内 → 隧道不通 → 连接超时）。
    幂等：重复调用结果相同（与 config.ensure_proxy_bypass 一致）。
    """
    entries: list[str] = []
    seen: set[str] = set()
    existing = os.environ.get("no_proxy", "") + "," + os.environ.get("NO_PROXY", "")
    for raw in existing.split(","):
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            entries.append(item)
    for raw in hosts:
        item = raw.strip()
        if item and item not in seen:
            seen.add(item)
            entries.append(item)
    value = ",".join(entries)
    os.environ["no_proxy"] = value
    os.environ["NO_PROXY"] = value


async def _probe() -> int:
    from aibot import WSClient, WSClientOptions
    from aibot.ws import DEFAULT_WS_URL

    bot_id = os.environ.get("WECHAT_BOT_ID", "").strip()
    secret = os.environ.get("WECHAT_BOT_SECRET", "").strip()
    if not bot_id or not secret:
        print("缺少 WECHAT_BOT_ID / WECHAT_BOT_SECRET（请写入主区 .env）", file=sys.stderr)
        return 2

    # 连接前把企微 WS 端点主机加入 no_proxy/NO_PROXY（与桥的
    # _ensure_endpoint_direct 同源：主机取 SDK 默认常量，不硬编码）。
    _ensure_proxy_bypass([urlsplit(DEFAULT_WS_URL).hostname or "openws.work.weixin.qq.com"])

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
