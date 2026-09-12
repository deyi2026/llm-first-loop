from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest import mock

import pytest

from llm_loop.config import Settings, load_settings


class _FakeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        method = req["method"]
        result: dict[str, Any]
        if method == "Target.getTargetInfo":
            result = {"targetInfo": {"targetId": "target-1"}}
        elif method == "Page.getFrameTree":
            result = {
                "frameTree": {
                    "frame": {
                        "id": "frame-main",
                        "loaderId": "loader-1",
                        "url": "http://127.0.0.1:8765/a.html",
                    }
                }
            }
        elif method == "DOMSnapshot.captureSnapshot":
            result = {
                "strings": [
                    "HTML",
                    "BUTTON",
                    "role",
                    "button",
                    "aria-label",
                    "Go",
                    "frame-main",
                ],
                "documents": [
                    {
                        # Real CDP DOMSnapshot.Document.frameId is a StringIndex.
                        "frameId": 6,
                        "documentURL": 0,
                        "nodes": {
                            "nodeName": [0, 1],
                            "nodeValue": [0, 0],
                            "parentIndex": [-1, 0],
                            "backendNodeId": [1, 2],
                            "attributes": [[], [2, 3, 4, 5]],
                        },
                        "layout": {"nodeIndex": [0, 1]},
                    }
                ],
            }
        elif method == "Accessibility.getFullAXTree":
            result = {
                "nodes": [
                    {
                        "nodeId": "ax1",
                        "backendDOMNodeId": 2,
                        "ignored": False,
                        "role": {"value": "button"},
                        "name": {"value": "Go"},
                        "properties": [],
                    }
                ]
            }
        else:
            raise AssertionError(f"unexpected CDP method: {method}")
        self.pending.append(json.dumps({"id": req["id"], "result": result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        assert self.pending
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


def _settings(tmp_path, **kwargs: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_api_key": "k",
        "llm_base_url": "https://x/v1",
        "llm_model": "m",
        "data_dir": str(tmp_path / "data"),
        "self_inspection_enabled": True,
        "extract_enabled": False,
    }
    values.update(kwargs)
    return Settings(**values)


def test_live_browser_opt_in_settings_default_off_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = {field.name: field for field in dataclasses.fields(Settings)}
    assert fields["browser_perception_cdp_url"].default == ""
    assert fields["browser_perception_target_id"].default == ""

    monkeypatch.setenv("LFL_BROWSER_PERCEPTION_CDP_URL", "http://127.0.0.1:9222")
    monkeypatch.setenv("LFL_BROWSER_PERCEPTION_TARGET_ID", "target-1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    settings = load_settings()
    assert settings.browser_perception_cdp_url == "http://127.0.0.1:9222"
    assert settings.browser_perception_target_id == "target-1"


def test_readonly_cdp_host_is_loopback_only_and_blocks_mutation() -> None:
    from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost, _ReadOnlyCdpSession

    with pytest.raises(ValueError, match="loopback"):
        CdpReadOnlyBrowserHost("http://example.com:9222")

    session = _ReadOnlyCdpSession(_FakeWs())
    for method in ("Page.navigate", "Runtime.evaluate", "Input.dispatchMouseEvent"):
        with pytest.raises(PermissionError, match="read-only"):
            session.send(method, {})


def test_cdp_host_persists_exact_target_and_never_silently_rebinds() -> None:
    from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost

    targets: list[dict[str, Any]] = [
        {
            "id": "target-1",
            "type": "page",
            "url": "http://127.0.0.1:8765/a.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
        }
    ]
    sockets: list[_FakeWs] = []

    def _http_get(url: str) -> list[dict[str, Any]]:
        assert url == "http://127.0.0.1:9222/json/list"
        return json.loads(json.dumps(targets))

    def _ws_connect(url: str) -> _FakeWs:
        assert url.endswith("/target-1")
        sock = _FakeWs()
        sockets.append(sock)
        return sock

    host = CdpReadOnlyBrowserHost(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=_http_get,
        ws_connect=_ws_connect,
    )
    first = host.capture()
    assert first["page_token"] == "target:target-1"
    assert first["dom"]["nodes"][0]["frame_token"] is None
    assert host.bound_target_id == "target-1"
    assert len(sockets) == 1

    targets[0]["url"] = "http://127.0.0.1:8765/b.html"
    second = host.capture()
    assert second["page_token"] == "target:target-1"
    assert len(sockets) == 1, "same exact page target must reuse one persistent CDP connection"

    targets[:] = [
        {
            "id": "target-2",
            "type": "page",
            "url": "http://127.0.0.1:8765/c.html",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-2",
        }
    ]
    with pytest.raises(RuntimeError, match="bound Browser target disappeared"):
        host.capture()
    assert host.bound_target_id == "target-1"
    host.close()
    assert sockets[0].closed is True


def test_factory_registers_browser_perceive_only_when_explicitly_opted_in(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import llm_loop.factory as factory

    default_engine = factory.build_engine(_settings(tmp_path))
    assert "browser_perceive" not in default_engine.registry.names()

    fake_host = mock.Mock()
    monkeypatch.setattr(factory, "CdpReadOnlyBrowserHost", mock.Mock(return_value=fake_host))
    settings = _settings(
        tmp_path,
        browser_perception_cdp_url="http://127.0.0.1:9222",
        browser_perception_target_id="target-1",
    )
    engine = factory.build_engine(settings)
    assert "browser_perceive" in engine.registry.names()
    factory.CdpReadOnlyBrowserHost.assert_called_once_with(
        "http://127.0.0.1:9222",
        target_id="target-1",
    )
    tool = engine.registry.get("browser_perceive")
    assert tool._backend is fake_host
