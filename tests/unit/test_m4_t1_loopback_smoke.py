"""M4: real loopback HTTP process over the released T1 canary chain.

This deliberately reuses the existing M2 assertions and fixtures; the only
change is replacing the in-process TestClient transport with a real socket.
The Provider response remains synthetic, so no external API is contacted.
"""

from __future__ import annotations

import importlib.util
import socket
import threading
import time
from pathlib import Path
from typing import Any

import fastapi.testclient
import httpx
import pytest
import uvicorn

_m2_spec = importlib.util.spec_from_file_location(
    "_m4_reused_m2", Path(__file__).with_name("test_task_budget_t1_web_profile.py")
)
assert _m2_spec is not None and _m2_spec.loader is not None
m2 = importlib.util.module_from_spec(_m2_spec)
_m2_spec.loader.exec_module(m2)


class _LoopbackTestClient:
    """Single request via a real local Uvicorn server, then clean shutdown."""

    def __init__(self, app: Any) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(64)
        self._sock = sock
        self._port = sock.getsockname()[1]
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=0,
                lifespan="off",
                access_log=False,
                log_level="error",
            )
        )
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [sock]},
            daemon=True,
            name="m4-t1-loopback-only",
        )
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self._close()
                raise AssertionError("isolated loopback server failed to start")
            time.sleep(0.02)

    def _close(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10)
        self._sock.close()
        assert not self._thread.is_alive(), "loopback server did not stop"

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            with httpx.Client(trust_env=False, timeout=40) as client:
                return client.post(f"http://127.0.0.1:{self._port}{path}", **kwargs)
        finally:
            self._close()


@pytest.fixture
def loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    # M2 module-level TestClient and its inner imports must both use the
    # socket-backed adapter. Do not patch any production transport code.
    monkeypatch.setattr(m2, "TestClient", _LoopbackTestClient)
    monkeypatch.setattr(fastapi.testclient, "TestClient", _LoopbackTestClient)


def test_m4_real_socket_full_chain(
    build_test_engine, tmp_path, monkeypatch: pytest.MonkeyPatch, loopback: None
) -> None:
    m2.test_t1_full_stack_stream_route_real_runner_real_llmclient_synthetic_sse(
        build_test_engine, tmp_path, monkeypatch
    )


def test_m4_real_socket_operator_revocation(
    build_test_engine, tmp_path, monkeypatch: pytest.MonkeyPatch, loopback: None
) -> None:
    m2.test_t1_build_app_autowires_real_operator_config_loader_to_fence(
        build_test_engine, tmp_path, monkeypatch
    )


def test_m4_real_socket_stream_and_sync_fence(
    build_test_engine, tmp_path, monkeypatch: pytest.MonkeyPatch, loopback: None
) -> None:
    m2.test_t1_real_web_stream_passes_pinned_plan_to_background_runner(
        build_test_engine, tmp_path, monkeypatch
    )


@pytest.mark.parametrize(
    "model,queue_id,attachments,authenticated",
    [
        ("glm/glm-5.3", None, False, False),
        ("glm/glm-5.2", None, False, True),
        ("glm/glm-5.3", "q-unclaimed", False, True),
        ("glm/glm-5.3", None, True, True),
    ],
)
def test_m4_real_socket_denies_unqualified(
    build_test_engine,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    loopback: None,
    model: str,
    queue_id: str | None,
    attachments: bool,
    authenticated: bool,
) -> None:
    m2.test_t1_web_stream_route_denies_unqualified_requests(
        build_test_engine, tmp_path, monkeypatch,
        model, queue_id, attachments, authenticated,
    )
