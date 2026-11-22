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
    _node,
    _tool,
    _view,
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


def test_exact_signed_ide_type_holds_without_editor_document_identity(signed_task):
    backend = _ide_backend()
    tool = _tool(backend)
    dry = _type(tool, dry_run=True)
    assert dry["ok"] is False
    assert dry["error_code"] == "app_not_allowed"
    assert "task_ide_editor_identity_unverified" in dry["guidance"]
    applied = _type(tool, dry_run=False)
    assert applied["ok"] is False
    assert applied["error_code"] == "app_not_allowed"
    assert backend.act_calls == []
    assert signed_task.calls == [
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


def test_revoked_ide_task_never_dispatches(signed_task):
    backend = _ide_backend()
    tool = _tool(backend)
    dry = _type(tool, dry_run=True)
    assert dry["error_code"] == "app_not_allowed"
    signed_task.revoked = True
    denied = _type(tool, dry_run=False)
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


def test_exact_signed_ide_outside_legacy_allowlist_still_holds(signed_task):
    backend = FakeOperateBackend(
        windows=[_window(app="Sublime Text", bundle_id="com.sublimetext.4")],
    )
    signed_task.allowed_bundle = "com.sublimetext.4"
    dry = _type(_tool(backend), dry_run=True)
    assert dry["error_code"] == "app_not_allowed"
    assert "task_ide_editor_identity_unverified" in dry["guidance"]
    assert backend.act_calls == []


@pytest.mark.parametrize("title", ["Terminal", "正文", "xterm-helper"])
def test_signed_vscode_integrated_terminal_textarea_cannot_receive_type(signed_task, title):
    """AXTextArea alone never proves an editor buffer, even if its title looks safe."""
    backend = FakeOperateBackend(
        windows=[_window(app="Visual Studio Code", bundle_id="com.microsoft.VSCode")],
        ax_views={101: _view(
            _node("0", "AXWindow", "main.py - Visual Studio Code"),
            _node("0.1", "AXTextArea", title, value="$ "),
        )},
    )
    tool = _tool(backend)
    for dry_run in (True, False):
        denied = _type(tool, dry_run=dry_run)
        assert denied["error_code"] == "app_not_allowed"
        assert "task_ide_editor_identity_unverified" in denied["guidance"]
    assert backend.act_calls == []


@dataclass
class _DocumentScopedTask(SignedTaskStub):
    allowed_path: str = ""
    file_calls: list[tuple[str, str]] = field(default_factory=list)

    def authorize_file(self, target: str, verb: str) -> str:
        self.file_calls.append((target, verb))
        if self.revoked:
            raise TaskExecutionError("authority_lease_revoked")
        if target != self.allowed_path or verb != "write":
            raise TaskExecutionError("capability_scope_missing")
        return self.allowed_path


def test_signed_ide_host_document_and_project_file_scope_allows_dry_run(tmp_path):
    path = tmp_path / "approved.py"
    path.write_text("print('safe')\n")
    backend = _ide_backend()
    from typing import Any
    host: Any = backend
    host.editor_document_path = lambda _window, _ref: str(path)
    task = _DocumentScopedTask(allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        dry = _type(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert dry["ok"] is True
    assert dry["needs_confirmation"] is True
    assert task.file_calls == [(str(path), "write")]
    assert backend.act_calls == []


def test_signed_ide_document_path_outside_lease_stays_denied(tmp_path):
    path = tmp_path / "unapproved.py"
    path.write_text("secret\n")
    backend = _ide_backend()
    from typing import Any
    host: Any = backend
    host.editor_document_path = lambda _window, _ref: str(path)
    task = _DocumentScopedTask(allowed_path=str(tmp_path / "approved.py"))
    token = current_task_execution.set(task)
    try:
        dry = _type(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert dry["ok"] is False
    assert dry["error_code"] == "app_not_allowed"
    assert "capability_scope_missing" in dry["guidance"]
    assert backend.act_calls == []


def test_signed_ide_integrated_terminal_denied_even_with_file_url(tmp_path):
    path = tmp_path / "approved.py"
    path.write_text("print('safe')\n")
    backend = FakeOperateBackend(
        windows=[_window(app="Visual Studio Code", bundle_id="com.microsoft.VSCode")],
        ax_views={101: _view(
            _node("0", "AXWindow", "approved.py - Visual Studio Code"),
            _node("0.1", "AXTextArea", "Terminal", value="$ "),
        )},
    )
    from typing import Any
    host: Any = backend
    host.editor_document_path = lambda _window, _ref: str(path)
    task = _DocumentScopedTask(allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        denied = _type(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert denied["error_code"] == "app_not_allowed"
    assert "task_ide_editor_identity_unverified" in denied["guidance"]
    assert task.file_calls == [] and backend.act_calls == []


def test_signed_ide_document_revalidated_at_physical_delivery(tmp_path):
    from typing import Any

    path = tmp_path / "approved.py"
    other = tmp_path / "swapped.py"
    path.write_text("safe\n")
    other.write_text("other\n")
    backend = _ide_backend()
    host: Any = backend
    calls = 0

    def document_probe(_window, _ref):
        nonlocal calls
        calls += 1
        return str(other if calls >= 3 else path)

    host.editor_document_path = document_probe
    task = _DocumentScopedTask(allowed_path=str(path))
    tool = _tool(backend)
    token = current_task_execution.set(task)
    try:
        dry = _type(tool, dry_run=True)
        assert dry["ok"] is True
        denied = _type(tool, dry_run=False, confirm_token=dry["confirm_token"])
    finally:
        current_task_execution.reset(token)
    assert denied["ok"] is False
    assert denied["error_code"] == "app_not_allowed"
    assert "Host 文档/祖先链已变化" in denied["guidance"]
    assert calls >= 3
    assert backend.act_calls == []


def test_signed_ide_document_stable_two_phase_fake_dispatch(tmp_path):
    from typing import Any

    path = tmp_path / "approved.py"
    path.write_text("safe\n")
    backend = _ide_backend()
    host: Any = backend
    host.editor_document_path = lambda _window, _ref: str(path)
    task = _DocumentScopedTask(allowed_path=str(path))
    tool = _tool(backend)
    token = current_task_execution.set(task)
    try:
        dry = _type(tool, dry_run=True)
        assert dry["ok"] is True
        applied = _type(tool, dry_run=False, confirm_token=dry["confirm_token"])
    finally:
        current_task_execution.reset(token)
    assert applied["ok"] is True
    assert applied["applied"] is True
    assert len(backend.act_calls) == 1
    assert task.file_calls == [(str(path), "write")] * 3
