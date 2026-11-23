"""Xcode Task-only exact AXDocument Save; no global HID or broad IDE allowance."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from llm_loop.core.run_context import current_task_execution
from llm_loop.desktop import macos_actuate
from llm_loop.desktop.models import ActOutcome
from tests.unit.test_desktop_operate_m4_v01 import (
    FakeOperateBackend,
    _direct,
    _node,
    _tool,
    _view,
    _window,
)
from tests.unit.test_desktop_task_capability import _DocumentScopedTask


def _xcode(path, *, os_attested=True, bundle="com.apple.dt.Xcode"):
    backend = FakeOperateBackend(
        windows=[_window(app="Xcode", bundle_id=bundle)],
        ax_views={101: _view(
            _node("0", "AXWindow", "receipt.txt"),
            replace(_node("0.1", "AXTextArea", "Source Editor", value="marker"),
                    editable=None if os_attested else True),
        )},
    )
    host: Any = backend
    host.editor_document_path = lambda _window, _ref: None if os_attested else str(path)
    host.editor_os_attested_document_path = lambda _window, _ref: str(path)
    host.act_save_document = lambda window, ax_ref, doc, pre_sha: (
        backend.act_calls.append({"do": "save_document", "ax_ref": ax_ref,
                                  "path": doc, "pre_sha": pre_sha})
        or ActOutcome(ok=True, verified=True, dispatch_state="dispatched",
                      effect_state="confirmed", verification_state="passed")
    )
    return backend


def _save(tool, **extra):
    return _direct(tool, do="save_document", window_id=101,
                   target={"ax_ref": "0.1"}, **extra)


@pytest.mark.parametrize("os_attested", [False, True])
def test_xcode_signed_save_exact_file_two_phase_and_new_token(tmp_path, os_attested):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    backend = _xcode(path, os_attested=os_attested)
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        tool = _tool(backend)
        dry = _save(tool, dry_run=True)
        if not os_attested:
            assert dry["error_code"] == "app_not_allowed"
            assert backend.act_calls == []
            return
        assert dry["ok"] and dry["risk_class"] == "irreversible"
        assert backend.act_calls == []
        applied = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
        assert applied["ok"] and applied["applied"] is True
        assert applied["verification"]["state"] == "passed"
        import hashlib
        assert backend.act_calls == [
            {"do": "save_document", "ax_ref": "0.1", "path": str(path),
             "pre_sha": hashlib.sha256(b"seed\n").hexdigest()}
        ]
        replay = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
        assert not replay["ok"]
        assert len(backend.act_calls) == 1
    finally:
        current_task_execution.reset(token)
    assert len(task.file_calls) >= 3 and all(call == (str(path), "write") for call in task.file_calls)


def test_xcode_save_without_task_or_outside_scope_never_dispatches(tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    backend = _xcode(path)
    assert _save(_tool(backend), dry_run=True)["error_code"] == "app_not_allowed"
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(tmp_path / "outside.txt"))
    token = current_task_execution.set(task)
    try:
        denied = _save(_tool(backend), dry_run=True)
        assert denied["error_code"] == "app_not_allowed"
        assert "capability_scope_missing" in denied["guidance"]
    finally:
        current_task_execution.reset(token)
    assert backend.act_calls == []


def test_xcode_save_rechecks_document_and_revocation_before_dispatch(tmp_path):
    path = tmp_path / "receipt.txt"
    other = tmp_path / "other.txt"
    path.write_text("seed\n")
    other.write_text("other\n")
    backend = _xcode(path)
    host: Any = backend
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    calls = 0
    def probe(_window, _ref):
        nonlocal calls
        calls += 1
        return str(other if calls >= 3 else path)
    host.editor_os_attested_document_path = probe
    token = current_task_execution.set(task)
    try:
        tool = _tool(backend)
        dry = _save(tool, dry_run=True)
        assert dry["ok"]
        denied = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
        assert denied["error_code"] == "app_not_allowed"
        assert "Host 文档/祖先链已变化" in denied["guidance"]
        host.editor_os_attested_document_path = lambda _w, _r: str(path)
        dry2 = _save(tool, dry_run=True)
        assert dry2["ok"]
        task.revoked = True
        revoked = _save(tool, dry_run=False, confirm_token=dry2["confirm_token"])
        assert "authority_lease_revoked" in revoked["guidance"]
    finally:
        current_task_execution.reset(token)
    assert backend.act_calls == []


@pytest.mark.parametrize("bundle", ["com.microsoft.VSCode", "com.apple.Terminal", "com.google.Chrome"])
def test_save_never_opens_other_apps_even_with_task(tmp_path, bundle):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    backend = _xcode(path, bundle=bundle)
    task = _DocumentScopedTask(allowed_bundle=bundle, allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        result = _save(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert not result["ok"]
    assert backend.act_calls == []


@pytest.mark.parametrize("bad", [
    {"text": "new"}, {"keys": "meta+s"}, {"target": {"point": {"x": 20, "y": 30}}},
])
def test_save_requires_exact_target_and_no_text_or_keys(bad):
    backend = _xcode("/tmp/unimportant")
    kwargs = {"do": "save_document", "window_id": 101,
              "target": {"ax_ref": "0.1"}, "dry_run": True}
    kwargs.update(bad)
    result = _direct(_tool(backend), **kwargs)
    assert result["error_code"] == "invalid_args"
    assert backend.act_calls == []


class FakeAx:
    def __init__(self, attrs=None, children=None):
        self.attrs = attrs or {}
        self.children = children or []
        self.ref = 101
        self.released = False

    def attr(self, name):
        return self.children if name == "AXChildren" else self.attrs.get(name)

    def release(self):
        self.released = True


@pytest.mark.parametrize("change", [
    None, "save_all_only", "wrong_identifier", "wrong_modifiers",
    "wrong_shortcut", "disabled", "ambiguous", "wrong_parent",
])
def test_native_menu_only_exact_xcode_file_save(monkeypatch, change):
    def save_item(**kw):
        return FakeAx({"AXRole": "AXMenuItem", "AXIdentifier": "ide_saveDocument:",
                       "AXMenuItemCmdChar": "S", "AXMenuItemCmdModifiers": 0,
                       "AXEnabled": True, **kw})
    entry = save_item()
    if change == "save_all_only":
        entry = save_item(AXIdentifier="saveAllEditorDocuments:", AXMenuItemCmdModifiers=2)
    if change == "wrong_identifier":
        entry = save_item(AXIdentifier="ide_saveDocumentAs:")
    if change == "wrong_modifiers":
        entry = save_item(AXMenuItemCmdModifiers=2)
    if change == "wrong_shortcut":
        entry = save_item(AXMenuItemCmdChar="X")
    if change == "disabled":
        entry = save_item(AXEnabled=False)
    entries = [entry, save_item()] if change == "ambiguous" else [entry]
    menu = FakeAx({"AXRole": "AXMenu"}, entries)
    file_item = FakeAx({"AXRole": "AXMenuBarItem",
                        "AXTitle": "Edit" if change == "wrong_parent" else "File"}, [menu])
    bar = FakeAx({"AXRole": "AXMenuBar"}, [file_item])
    app = FakeAx()
    pressed = []
    monkeypatch.setattr(macos_actuate, "app_element", lambda _pid: app)
    monkeypatch.setattr(macos_actuate, "ax_read_attr", lambda _ref, _name: (0, 77))
    monkeypatch.setattr(macos_actuate, "MacAxElement", lambda _ref: bar)
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_press", lambda el: pressed.append(el) or 0)
    window = _window(bundle_id="com.apple.dt.Xcode")
    err, reason = macos_actuate._xcode_press_exact_save_menu(window)
    if change is None:
        assert err == 0 and reason == "" and pressed == [entry]
    else:
        assert err is None and reason and pressed == []
    assert app.released and bar.released and file_item.released
    if change != "wrong_parent":
        assert menu.released
    if change != "wrong_parent":
        assert all(e.released for e in entries)


def test_native_xcode_save_requires_host_binding_and_disk_sha(monkeypatch, tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    window = _window(bundle_id="com.apple.dt.Xcode")
    target = FakeAx({"AXFocused": True})
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r: (target, None))
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda _el: "after\n")
    called = []
    def press(_w):
        called.append("File/Save")
        path.write_text("after\n")
        return 0, ""
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", press)
    import hashlib
    outcome = macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"seed\n").hexdigest(),
    )
    assert outcome.ok and outcome.verified is True
    assert outcome.verification_reason == "xcode_exact_file_saved_to_disk"
    assert called == ["File/Save"] and target.released
    # A swapped OS document cannot invoke the menu.
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(tmp_path / "wrong"))
    assert not macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"after\n").hexdigest(),
    ).ok
    assert called == ["File/Save"]


def test_native_xcode_save_disk_mismatch_is_dispatched_unknown(monkeypatch, tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    window = _window(bundle_id="com.apple.dt.Xcode")
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r: (FakeAx({"AXFocused": True}), None))
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda _el: "after\n")
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", lambda _w: (0, ""))
    # Avoid fake clocks shared across tests; a single real 8s wait is unnecessary.
    calls = iter((100.0, 109.0))
    monkeypatch.setattr(macos_actuate.time, "monotonic", lambda: next(calls, 109.0))
    import hashlib
    outcome = macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"seed\n").hexdigest(),
    )
    assert not outcome.ok
    assert outcome.dispatch_state == "dispatched"
    assert outcome.verification_reason == "xcode_disk_save_not_verified"
    assert path.read_text() == "seed\n"


def test_xcode_save_rejects_concurrent_disk_change_after_dry_run(tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    backend = _xcode(path)
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        tool = _tool(backend)
        dry = _save(tool, dry_run=True)
        assert dry["ok"]
        path.write_text("foreign-writer\n")
        denied = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
    finally:
        current_task_execution.reset(token)
    assert denied["error_code"] == "confirm_token_mismatch"
    assert path.read_text() == "foreign-writer\n"
    assert backend.act_calls == []


def test_xcode_save_hid_presence_and_foreground_deny(tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    backend = _xcode(path)
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        tool = _tool(backend)
        dry = _save(tool, dry_run=True)
        assert dry["ok"]
        backend.hid_idle = 10
        user_present = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
        assert user_present["error_code"] == "user_present"
        backend.hid_idle = 120_000
        backend.frontmost_override = "com.google.Chrome"
        not_frontmost = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
        assert not_frontmost["error_code"] == "foreground_changed"
    finally:
        current_task_execution.reset(token)
    assert backend.act_calls == []


def test_native_save_rejects_disk_preimage_swap_before_menu(monkeypatch, tmp_path):
    import hashlib
    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    pre_sha = hashlib.sha256(b"seed\n").hexdigest()
    window = _window(bundle_id="com.apple.dt.Xcode")
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r: (FakeAx({"AXFocused": True}), None))
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda _el: "after\n")
    called = []
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", lambda _w: called.append(True))
    path.write_text("foreign\n")
    outcome = macos_actuate.ax_save_xcode_document(window, "0.1", str(path), pre_sha)
    assert not outcome.ok and outcome.dispatch_state == "not_dispatched"
    assert outcome.verification_reason == "xcode_document_preimage_or_identity_changed"
    assert called == [] and path.read_text() == "foreign\n"


def test_native_focused_window_requires_os_axfrontmost(monkeypatch):
    app = FakeAx({"AXFrontmost": False})
    monkeypatch.setattr(macos_actuate, "app_element", lambda _pid: app)
    assert not macos_actuate._xcode_focused_window_matches(_window(bundle_id="com.apple.dt.Xcode"))
    assert app.released


def test_native_menu_press_exception_is_not_false_not_dispatched(monkeypatch):
    entry = FakeAx({"AXRole": "AXMenuItem", "AXIdentifier": "ide_saveDocument:",
                    "AXMenuItemCmdChar": "S", "AXMenuItemCmdModifiers": 0,
                    "AXEnabled": True})
    menu = FakeAx({"AXRole": "AXMenu"}, [entry])
    file_item = FakeAx({"AXRole": "AXMenuBarItem", "AXTitle": "File"}, [menu])
    bar = FakeAx({"AXRole": "AXMenuBar"}, [file_item])
    app = FakeAx()
    monkeypatch.setattr(macos_actuate, "app_element", lambda _pid: app)
    monkeypatch.setattr(macos_actuate, "ax_read_attr", lambda _ref, _name: (0, 77))
    monkeypatch.setattr(macos_actuate, "MacAxElement", lambda _ref: bar)
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_press", lambda _el: (_ for _ in ()).throw(OSError("uncertain")))
    err, reason = macos_actuate._xcode_press_exact_save_menu(_window(bundle_id="com.apple.dt.Xcode"))
    assert err == -1 and reason == "xcode_save_press_uncertain"
    assert app.released and bar.released and entry.released


def test_native_xcode_menu_rechecks_focus_after_discovering_save_item(monkeypatch):
    """An app-level File/Save must not dispatch after the bound window loses focus."""
    entry = FakeAx({"AXRole": "AXMenuItem", "AXIdentifier": "ide_saveDocument:",
                    "AXMenuItemCmdChar": "S", "AXMenuItemCmdModifiers": 0,
                    "AXEnabled": True})
    menu = FakeAx({"AXRole": "AXMenu"}, [entry])
    file_item = FakeAx({"AXRole": "AXMenuBarItem", "AXTitle": "File"}, [menu])
    bar = FakeAx({"AXRole": "AXMenuBar"}, [file_item])
    app = FakeAx()
    pressed = []
    monkeypatch.setattr(macos_actuate, "app_element", lambda _pid: app)
    monkeypatch.setattr(macos_actuate, "ax_read_attr", lambda _ref, _name: (0, 77))
    monkeypatch.setattr(macos_actuate, "MacAxElement", lambda _ref: bar)
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: False)
    monkeypatch.setattr(macos_actuate, "ax_press", lambda el: pressed.append(el) or 0)

    err, reason = macos_actuate._xcode_press_exact_save_menu(
        _window(bundle_id="com.apple.dt.Xcode"),
    )
    assert err is None and reason == "xcode_focus_changed_before_press"
    assert pressed == []
    assert app.released and bar.released and file_item.released
    assert menu.released and entry.released


def test_native_xcode_save_focus_changed_after_press_is_uncertain(monkeypatch, tmp_path):
    """A dispatched Save with changed foreground cannot be reported as verified."""
    import hashlib

    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    window = _window(bundle_id="com.apple.dt.Xcode")
    focus_checks = []
    def focused(_w):
        focus_checks.append(True)
        return len(focus_checks) <= 2

    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", focused)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref",
                        lambda _w, _r: (FakeAx({"AXFocused": True}), None))
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda _el: "after\n")
    pressed = []
    def press(_w):
        pressed.append(True)
        path.write_text("after\n")
        return 0, ""
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", press)

    outcome = macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"seed\n").hexdigest(),
    )
    assert pressed == [True] and len(focus_checks) == 3
    assert not outcome.ok and outcome.dispatch_state == "dispatched"
    assert outcome.effect_state == "unknown"
    assert outcome.verification_state == "failed"
    assert outcome.verification_reason == "xcode_focus_or_document_changed_after_press"


def test_xcode_save_rejects_same_content_different_document_within_broad_lease(tmp_path):
    """Window title/AX world and disk bytes can be identical across two tabs."""
    first = tmp_path / "one" / "receipt.txt"
    second = tmp_path / "two" / "receipt.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("same-bytes\\n")
    second.write_text("same-bytes\\n")
    backend = _xcode(first)
    host: Any = backend
    calls = 0
    def document(_window, _ref):
        nonlocal calls
        calls += 1
        return str(first if calls == 1 else second)
    host.editor_os_attested_document_path = document
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(first))
    # Simulate a broad project root Lease that authorizes BOTH files.
    scoped: Any = task
    scoped.authorize_file = lambda path, verb: path
    token = current_task_execution.set(task)
    try:
        tool = _tool(backend)
        dry = _save(tool, dry_run=True)
        assert dry["ok"]
        denied = _save(tool, dry_run=False, confirm_token=dry["confirm_token"])
    finally:
        current_task_execution.reset(token)
    assert denied["error_code"] == "confirm_token_mismatch"
    assert backend.act_calls == []
    assert first.read_text() == second.read_text() == "same-bytes\\n"


def test_save_dry_run_symlink_swap_during_open_is_denied(monkeypatch, tmp_path):
    import os

    from llm_loop.tools.builtin import desktop_operate as desktop_module

    path = tmp_path / "receipt.txt"
    secret = tmp_path / "private.txt"
    path.write_text("seed\n")
    secret.write_text("secret-unchanged\n")
    backend = _xcode(path, os_attested=True)
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    real_open = os.open
    swapped = False

    def race_open(name, flags, *args, **kwargs):
        nonlocal swapped
        if str(name) == str(path) and flags & os.O_NOFOLLOW and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(secret)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(desktop_module.os, "open", race_open)
    token = current_task_execution.set(task)
    try:
        denied = _save(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert swapped and denied["error_code"] == "app_not_allowed"
    assert backend.act_calls == []
    assert secret.read_text() == "secret-unchanged\n"


def test_native_preimage_symlink_swap_is_not_followed(monkeypatch, tmp_path):
    import hashlib
    import os

    path = tmp_path / "receipt.txt"
    secret = tmp_path / "private.txt"
    path.write_text("seed\n")
    secret.write_text("secret-unchanged\n")
    window = _window(bundle_id="com.apple.dt.Xcode")
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r: (FakeAx({"AXFocused": True}), None))
    monkeypatch.setattr(macos_actuate, "ax_read_value_string", lambda _el: "after\n")
    pressed = []
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", lambda _w: pressed.append(True))
    real_open = os.open
    swapped = False

    def race_open(name, flags, *args, **kwargs):
        nonlocal swapped
        if str(name) == str(path) and flags & os.O_NOFOLLOW and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(secret)
        return real_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(macos_actuate.os, "open", race_open)
    outcome = macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"seed\n").hexdigest(),
    )
    assert swapped and not outcome.ok and outcome.dispatch_state == "not_dispatched"
    assert outcome.verification_reason == "xcode_disk_preimage_unreadable"
    assert pressed == [] and secret.read_text() == "secret-unchanged\n"


def test_native_save_rejects_non_os_attested_editor_even_if_editable(monkeypatch, tmp_path):
    import hashlib

    path = tmp_path / "receipt.txt"
    path.write_text("seed\n")
    window = _window(bundle_id="com.apple.dt.Xcode")
    monkeypatch.setattr(macos_actuate, "_xcode_focused_window_matches", lambda _w: True)
    monkeypatch.setattr(macos_actuate, "ax_editor_os_attested_document_path", lambda _w, _r: None)
    monkeypatch.setattr(macos_actuate, "ax_editor_document_path", lambda _w, _r: str(path))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r: (FakeAx({"AXFocused": True}), None))
    pressed = []
    monkeypatch.setattr(macos_actuate, "_xcode_press_exact_save_menu", lambda _w: pressed.append(True))
    outcome = macos_actuate.ax_save_xcode_document(
        window, "0.1", str(path), hashlib.sha256(b"seed\n").hexdigest(),
    )
    assert not outcome.ok and outcome.dispatch_state == "not_dispatched"
    assert pressed == []


def test_save_rejects_large_document_before_confirmation(tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_bytes(b"x" * (1_048_576 + 1))
    backend = _xcode(path, os_attested=True)
    task = _DocumentScopedTask(allowed_bundle="com.apple.dt.Xcode", allowed_path=str(path))
    token = current_task_execution.set(task)
    try:
        result = _save(_tool(backend), dry_run=True)
    finally:
        current_task_execution.reset(token)
    assert result["error_code"] == "app_not_allowed"
    assert backend.act_calls == []
