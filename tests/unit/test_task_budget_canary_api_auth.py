"""Real API authentication at the selected budget boundary; no Provider calls."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.applications import Starlette
from starlette.requests import Request

from llm_loop.resources.task_budget_store import TaskBudgetDeniedError
from llm_loop.web.auth import (
    SESSION_COOKIE_NAME,
    WebSessionStore,
    request_authenticated,
    request_is_trusted_local,
)
from llm_loop.web.task_budget_canary import choose_signed_web_canary

_KEY = "unit-test-web-api-key"


def _request(header: str = "") -> Request:
    app = Starlette()
    app.state.task_budget_web_canary = SimpleNamespace(session_id="selected")
    headers = [(b"host", b"127.0.0.1:8903")]
    if header:
        headers.append((b"authorization", header.encode()))
    return Request(
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/api/v1/chat/stream",
            "scheme": "http",
            "headers": headers,
            "server": ("127.0.0.1", 8903),
            "client": ("127.0.0.1", 1),
            "query_string": b"",
        }
    )


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (f"Bearer {_KEY}", True),
        (f"bEaReR {_KEY}", True),
        ("", False),
        ("Bearer wrong", False),
        (f"Basic {_KEY}", False),
        ("Bearer", False),
        ("Bearer ", False),
        (f"Bearer {_KEY} extra", False),
    ],
)
def test_request_header_uses_existing_bearer_validator(monkeypatch, header, expected):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    assert request_authenticated(_request(header)) is expected


@pytest.mark.parametrize("configured_key", ["", "different-key"])
def test_header_cannot_authenticate_without_matching_operator_key(monkeypatch, configured_key):
    monkeypatch.setenv("WEB_API_KEY", configured_key)
    assert request_authenticated(_request(f"Bearer {_KEY}")) is False


def test_explicit_credentials_are_not_overridden_by_request_header(monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="wrong")
    assert request_authenticated(_request(f"Bearer {_KEY}"), credentials) is False


def test_explicit_credentials_remain_valid_without_request(monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=_KEY)
    assert request_authenticated(None, credentials) is True
    assert request_authenticated(None) is False


@pytest.mark.parametrize("header", ["", "Bearer wrong"])
def test_browser_session_remains_valid_and_revocable(monkeypatch, header):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    request = _request(header)
    store = WebSessionStore()
    request.app.state.web_sessions = store
    token = store.create(ttl_seconds=60)
    request.scope["headers"].append((b"cookie", f"{SESSION_COOKIE_NAME}={token}".encode()))
    assert request_authenticated(request) is True
    store.revoke(token)
    assert request_authenticated(request) is False


def test_selected_canary_accepts_real_api_auth_and_stays_session_pinned(monkeypatch):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    request = _request(f"Bearer {_KEY}")
    selected = choose_signed_web_canary(
        request,
        "selected",
        model="glm/glm-5.3",
        resume=False,
        queued=False,
        attachments=False,
    )
    assert selected is request.app.state.task_budget_web_canary
    assert (
        choose_signed_web_canary(
            request,
            "unselected",
            model="glm/glm-5.3",
            resume=False,
            queued=False,
            attachments=False,
        )
        is None
    )


@pytest.mark.parametrize("header", ["", "Bearer wrong", f"Basic {_KEY}"])
def test_trusted_loopback_does_not_bypass_selected_canary_auth(monkeypatch, header):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    request = _request(header)
    assert request_is_trusted_local(request)
    with pytest.raises(TaskBudgetDeniedError, match="web_task_budget_canary_unqualified"):
        choose_signed_web_canary(
            request,
            "selected",
            model="glm/glm-5.3",
            resume=False,
            queued=False,
            attachments=False,
        )


@pytest.mark.parametrize(
    "changed",
    [
        {"model": "other/model"},
        {"queued": True},
        {"attachments": True},
    ],
)
def test_valid_bearer_cannot_bypass_other_canary_boundaries(monkeypatch, changed):
    monkeypatch.setenv("WEB_API_KEY", _KEY)
    options = {"model": "glm/glm-5.3", "resume": False, "queued": False, "attachments": False}
    options.update(changed)
    with pytest.raises(TaskBudgetDeniedError, match="web_task_budget_canary_unqualified"):
        choose_signed_web_canary(_request(f"Bearer {_KEY}"), "selected", **options)
