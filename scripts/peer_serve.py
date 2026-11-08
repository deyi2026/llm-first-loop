#!/usr/bin/env python3
"""独立 peer 服务端入口（uvicorn）：单机/试验部署用，不依赖主 Web app 装配。

用法：
    python scripts/peer_serve.py --data-dir data/peer --node-id deepin-01 --port 8791

前置：``<data-dir>/secrets/<node_id>.secret`` 已存在（配对产物，0600）。
未配对时进程直接退出并提示，不会以"无密钥但可访问"的状态起服务（fail-closed）。

边界：本脚本只起 peer 面；QR/headless 显示与 PAIR-OFFER 的飞书确认通道不在本切片。
明文监听只允许回环（LAN 走 SSH 隧道，DESIGN §7 禁裸 HTTP）；非回环 host 直接拒启。
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from llm_loop.peer.admission import AdmissionStore  # noqa: E402
from llm_loop.peer.artifacts import ArtifactStore  # noqa: E402
from llm_loop.peer.auth import PeerAuthenticator  # noqa: E402
from llm_loop.peer.pair import secret_key_from_store  # noqa: E402
from llm_loop.peer.service import PeerService  # noqa: E402
from llm_loop.peer.store import PeerStore  # noqa: E402
from llm_loop.web.peer_routes import create_peer_app  # noqa: E402


def build_app(
    *,
    data_dir: Path,
    node_id: str,
    display_name: str | None,
    write_root: str | None = None,
    display_protocol: str = "none",
    audit_watermark_pct: int = 90,
    max_concurrency: int = 1,
    enabled_kinds: set[str] | None = None,
    health: str | None = None,
    recover: bool = True,
) -> object:
    store = PeerStore(data_dir)
    stored = store.read_secret(node_id)
    if not stored:
        raise SystemExit(
            f"未配对：{data_dir / 'secrets' / (node_id + '.secret')} 不存在。"
            " 先完成 PAIR-OFFER/PAIR-CONFIRM 落盘 link_secret，再启动。"
        )
    secret = secret_key_from_store(stored)
    service = PeerService(
        store=store,
        admissions=AdmissionStore(data_dir),
        artifacts=ArtifactStore(data_dir / "artifacts"),
        node_id=node_id,
        display_name=display_name,
        display_protocol=display_protocol,
        audit_watermark_pct=audit_watermark_pct,
        max_concurrency=max_concurrency,
        enabled_kinds=enabled_kinds,
        write_root=write_root,
        health=health,
    )
    if recover:
        recovered = service.recover_interrupted()
        if recovered:
            print(
                f"[peer] 恢复中断任务 {len(recovered)} 条：" + ", ".join(
                    f"{t.task_id}={t.state}({t.reason_code})" for t in recovered
                ),
                file=sys.stderr,
            )
    authenticator = PeerAuthenticator(
        secret_for=lambda candidate: secret if candidate == node_id else None
    )
    return create_peer_app(service=service, authenticator=authenticator)


def _is_loopback(host: str) -> bool:
    """明文监听只允许回环：TLS 未实现，非回环等于把 HMAC 签名暴露在链路上。"""
    if host in {"localhost", ""}:
        return host == "localhost"
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LFL peer 服务端（受控端）")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument(
        "--display-protocol",
        default="none",
        choices=["none", "x11", "wayland"],
        help="desktop.* kind 的显示协议事实；非 x11 一律 unsupported_display_protocol",
    )
    parser.add_argument("--audit-watermark-pct", type=int, default=90)
    parser.add_argument(
        "--health",
        default=None,
        choices=["ok", "degraded"],
        help="运维覆盖（演练/维护期）；缺省按磁盘水位自动判定",
    )
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument(
        "--enabled-kinds",
        default=None,
        help="逗号分隔的 kind 白名单；缺省用注册表 default_enabled",
    )
    parser.add_argument(
        "--write-root",
        default=None,
        help="闸4 写域根（绝对路径）；缺省=远程写全拒",
    )
    args = parser.parse_args(argv)

    if not _is_loopback(args.host):
        print(
            f"拒绝启动：--host={args.host} 不是回环地址。TLS 未实现，"
            "明文 peer 端点只允许绑 127.0.0.1/::1，LAN 访问请走 SSH 隧道。",
            file=sys.stderr,
        )
        return 2

    enabled = None
    if args.enabled_kinds is not None:
        enabled = {k.strip() for k in args.enabled_kinds.split(",") if k.strip()}

    import uvicorn

    app = build_app(
        data_dir=args.data_dir,
        node_id=args.node_id,
        display_name=args.display_name,
        display_protocol=args.display_protocol,
        audit_watermark_pct=args.audit_watermark_pct,
        max_concurrency=args.max_concurrency,
        enabled_kinds=enabled,
        write_root=args.write_root,
        health=args.health,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
