"""Task-scoped desktop AX tests: exact Host app scope, TCC and no terminal HID."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from llm_loop.core.run_context import current_task_execution
from llm_loop.desktop.models import PermissionSnapshot
from llm_loop.tools.task_execution import TaskExecutionError
from tests.unit.test_desktop_operate_m4_v01 import (
    FakeOperateBackend,
    _direct,
    _tool,
    _window,
)


@dataclass
class SignedTaskStub:
    allowed_bundle: str = "com.microsoft.VSCode"
    revoked: bool = False
    calls: list[tuple[str, str, bool]] = field(default_factory=list)

    def authorize_app(
        self,
        bundle_id: str,
        *,
        verb: str,
        os_permission_granted: bool,
    ) -> None:
        self.calls.append((bundle_id, verb, os_permission_granted))
        if self.revoked:
            raise TaskExecutionError("authority_lease_revoked")
        if bundle_id != self.allowed_bundle or verb != "edit":
            raise TaskExecutionError("capability_scope_missing")
        if not os_permission_granted:
            raise TaskExecutionError("task_os_tcc_required")


@pytest.fixture
def signed_task():
    task = SignedTaskStub()
    token = current_task_execution.set(task)
    try:
        yield task
    finally:
        current_task_execution.reset(token)


def _ide_backend(*, perms=None):
    return FakeOperateBackend(
        windows=[_window(app="Visual Studio Code", bundle_id="com.microsoft.VSCode")],
        perms=perms,
    )


def _type(tool, **extra):
    return _direct(
        tool,
        do="type",
        window_id=101,
        target={"ax_ref": "0.1"},
        text="safe text",
        **extra,
    )


def test_without_host_task_ide_remains_readonly():
    backend = _ide_backend()
    result = _type(_tool(backend), dry_run=True)
    assert result["error_code"] == "app_not_allowed"
    assert backend.act_calls == []


def test_exact_signed_ide_ax_type_with_confirmation(signed_task):
    backend = _ide_backend()
    tool = _tool(backend)
    dry = _type(tool, dry_run=True)
    assert dry["ok"] is True and dry["confirm_token"]
    applied = _type(tool, dry_run=False, confirm_token=dry["confirm_token"])
    assert applied["applied"] is True
    assert applied["verified"] is True
    assert backend.act_calls == [
        {"do": "type", "window_id": 101, "ax_ref": "0.1", "text": "safe text"},
    ]
    assert signed_task.calls == [
        ("com.microsoft.VSCode", "edit", True),
        ("com.microsoft.VSCode", "edit", True),
        ("com.microsoft.VSCode", "edit", True),
    ]


def test_unsigned_ide_and_missing_tcc_fail_before_dispatch(signed_task):
    backend = _ide_backend()
    signed_task.allowed_bundle = "com.apple.dt.Xcode"
    denied = _type(_tool(backend), dry_run=True)
    assert denied["error_code"] == "app_not_allowed"
    assert "capability_scope_missing" in denied["guidance"]
    assert backend.act_calls == []

    signed_task.allowed_bundle = "com.microsoft.VSCode"
    no_tcc = _ide_backend(
        perms=PermissionSnapshot(
            ax_trusted=False,
            screen_capture_granted=True,
            ax_error=None,
        ),
    )
    denied = _type(_tool(no_tcc), dry_run=True)
    assert denied["error_code"] == "ax_unavailable"
    assert "task_os_tcc_required" in denied["guidance"]
    assert no_tcc.act_calls == []


def test_revoked_between_dry_run_and_apply_never_dispatches(signed_task):
    backend = _ide_backend()
    tool = _tool(backend)
    dry = _type(tool, dry_run=True)
    assert dry["ok"] is True
    signed_task.revoked = True
    denied = _type(tool, dry_run=False, confirm_token=dry["confirm_token"])
    assert denied["ok"] is False
    assert "authority_lease_revoked" in denied["guidance"]
    assert backend.act_calls == []


def test_signed_ide_still_rejects_hid_and_terminal(signed_task):
    backend = _ide_backend()
    tool = _tool(backend)
    clicked = _direct(
        tool,
        do="click",
        window_id=101,
        target={"ax_ref": "0.0"},
        dry_run=True,
    )
    assert clicked["error_code"] == "app_not_allowed"
    assert backend.act_calls == []

    terminal = FakeOperateBackend(
        windows=[_window(app="Terminal", bundle_id="com.apple.Terminal")],
    )
    signed_task.allowed_bundle = "com.apple.Terminal"
    denied = _type(_tool(terminal), dry_run=True)
    assert denied["error_code"] == "app_not_allowed"
    assert terminal.act_calls == []


def test_exact_signed_ide_outside_legacy_allowlist_is_ax_only(signed_task):
    backend = FakeOperateBackend(
        windows=[_window(app="Sublime Text", bundle_id="com.sublimetext.4")],
    )
    signed_task.allowed_bundle = "com.sublimetext.4"
    dry = _type(_tool(backend), dry_run=True)
    assert dry["ok"] is True
    assert backend.act_calls == []
