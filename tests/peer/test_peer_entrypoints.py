"""Normal Peer service entrypoints must persist nonce replay state across rebuilds."""

from __future__ import annotations

import base64
import importlib.util
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.testclient import TestClient

from llm_loop.peer.auth import sign_request
from llm_loop.peer.store import PeerStore
from llm_loop.web import _mount_peer_routes

REPO = Path(__file__).resolve().parents[2]
CONTROLLER = "controller-qa"
EXECUTOR = "executor-qa"
SECRET = b"\x35" * 32
NONCE = "a" * 32


def _request_headers() -> dict[str, str]:
    return sign_request(
        secret=SECRET,
        method="GET",
        path="/peer/v1/manifest",
        node_id=CONTROLLER,
        nonce=NONCE,
        timestamp=int(time.time()),
    )


def _assert_replay_survives_rebuild(tmp_path: Path, build: Callable[[Path], object]) -> None:
    data_dir = tmp_path / "peer-data"
    PeerStore(data_dir).write_secret(CONTROLLER, base64.b64encode(SECRET).decode("ascii"))
    headers = _request_headers()

    first = TestClient(build(data_dir)).get("/peer/v1/manifest", headers=headers)
    assert first.status_code == 200, first.text

    second = TestClient(build(data_dir)).get("/peer/v1/manifest", headers=headers)
    assert second.status_code == 401
    assert second.json()["reason_code"] == "peer_replay_detected"


def test_main_web_peer_mount_persists_nonce_across_rebuilds(tmp_path):
    def build(data_dir: Path):
        app = FastAPI()
        settings = SimpleNamespace(
            web_host="127.0.0.1",
            peer_allow_plaintext_bind=False,
            peer_data_dir=str(data_dir),
            data_dir=str(data_dir.parent),
            peer_node_id=EXECUTOR,
            peer_display_name="Peer QA",
            peer_kinds="fs.read,fs.list",
            peer_write_root=None,
        )
        _mount_peer_routes(app, settings)
        return app

    _assert_replay_survives_rebuild(tmp_path, build)


def test_standalone_peer_serve_persists_nonce_across_rebuilds(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "peer_serve_entrypoint_test", REPO / "scripts" / "peer_serve.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def build(data_dir: Path):
        return module.build_app(
            data_dir=data_dir,
            node_id=EXECUTOR,
            display_name="Peer QA",
            recover=False,
        )

    _assert_replay_survives_rebuild(tmp_path, build)
