#!/usr/bin/env python3
"""独立 peer 服务端入口（uvicorn）：单机/试验部署用，不依赖主 Web app 装配。

用法：
    python scripts/peer_serve.py --data-dir data/peer --node-id deepin-01 --port 8791

前置：``<data-dir>/secrets/<node_id>.secret`` 已存在（配对产物，0600）。
未配对时进程直接退出并提示，不会以"无密钥但可访问"的状态起服务（fail-closed）。

边界：本脚本只起 peer 面；QR/headless 显示与 PAIR-OFFER 的飞书确认通道不在本切片。
"""

from __future__ import annotations

import argparse
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


def build_app(*, data_dir: Path, node_id: str, display_name: str | None) -> object:
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
    )
    authenticator = PeerAuthenticator(
        secret_for=lambda candidate: secret if candidate == node_id else None
    )
    return create_peer_app(service=service, authenticator=authenticator)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LFL peer 服务端（受控端）")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    args = parser.parse_args(argv)

    import uvicorn

    app = build_app(data_dir=args.data_dir, node_id=args.node_id, display_name=args.display_name)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
