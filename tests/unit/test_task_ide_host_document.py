"""Host AXDocument evidence is a file:// URL on an editable exact AX target."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from llm_loop.desktop import macos_actuate
from tests.unit.test_desktop_operate_m4_v01 import _window


@dataclass
class _FakeAx:
    attrs: dict[str, object]
    released: bool = False

    def attr(self, key: str) -> object | None:
        return self.attrs.get(key)

    def release(self) -> None:
        self.released = True


def test_host_editor_document_path_requires_editable_file_url(monkeypatch, tmp_path):
    path = tmp_path / "real.py"
    path.write_text("safe\n")
    el = _FakeAx({
        "AXRole": "AXTextArea", "AXEditable": True, "AXEnabled": True,
        "AXDocument": path.as_uri(),
    })
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r, el=el: (el, None))
    assert macos_actuate.ax_editor_document_path(_window(), "0.1") == str(path)
    assert el.released


def test_host_editor_document_rejects_terminal_missing_doc_and_remote_url(monkeypatch, tmp_path):
    for doc in (None, "https://example.org/file.py", "file://remotehost/tmp/file.py"):
        el = _FakeAx({"AXRole": "AXTextArea", "AXEditable": True, "AXDocument": doc})
        monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r, el=el: (el, None))
        assert macos_actuate.ax_editor_document_path(_window(), "0.1") is None
        assert el.released


def test_host_editor_document_rejects_symlink_and_readonly(monkeypatch, tmp_path):
    path = tmp_path / "real.py"
    path.write_text("safe\n")
    link = tmp_path / "link.py"
    link.symlink_to(path)
    for document, editable in ((link.as_uri(), True), (path.as_uri(), False)):
        el = _FakeAx({"AXRole": "AXTextArea", "AXEditable": editable, "AXDocument": document})
        monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, _r, el=el: (el, None))
        assert macos_actuate.ax_editor_document_path(_window(), "0.1") is None
        assert el.released


def _native_editor_fake(monkeypatch, path, *, bundle, target_attrs=None, context_attrs=None, root_doc=None, settable=True):
    """Host-only AX tree: the file:// document lives on AXWindow, not AXTextArea."""
    from dataclasses import replace

    window = replace(_window(), bundle_id=bundle)
    root = _FakeAx({"AXRole": "AXWindow", "AXDocument": path.as_uri() if root_doc is None else root_doc})
    context = _FakeAx(context_attrs or {
        "AXRole": "AXGroup",
        "AXIdentifier": "editor context" if bundle == "com.apple.dt.Xcode" else None,
        "AXDescription": path.name,
    })
    target = _FakeAx({
        "AXRole": "AXTextArea",
        "AXEditable": None,
        "AXEnabled": True,
        "AXFocused": True,
        "AXDescription": "Source Editor" if bundle == "com.apple.dt.Xcode" else path.name,
        **(target_attrs or {}),
    })
    mapping = {"0": root, "0.0": context, "0.0.1": target}
    monkeypatch.setattr(macos_actuate, "resolve_window_element", lambda _w: (root, None))
    monkeypatch.setattr(macos_actuate, "resolve_element_by_axref", lambda _w, ref: (mapping.get(ref), None))
    monkeypatch.setattr(macos_actuate, "_ax_value_is_settable", lambda _el: settable)
    return window, (root, context, target)


@pytest.mark.parametrize("bundle", ["com.apple.dt.Xcode", "com.microsoft.VSCode"])
def test_native_os_attested_editor_window_document(monkeypatch, tmp_path, bundle):
    path = tmp_path / "receipt.txt"
    path.write_text("safe\n")
    window, elements = _native_editor_fake(monkeypatch, path, bundle=bundle)
    assert macos_actuate.ax_editor_os_attested_document_path(window, "0.0.1") == str(path)
    assert all(el.released for el in elements)


@pytest.mark.parametrize("change", [
    "not_settable", "not_focused", "ax_editable_false", "not_textarea",
    "terminal_ancestor", "wrong_editor_description", "remote_document",
    "symlink_document", "unsupported_bundle",
])
def test_native_os_attested_editor_fail_closed(monkeypatch, tmp_path, change):
    path = tmp_path / "receipt.txt"
    path.write_text("safe\n")
    attrs = {}
    context = {"AXRole": "AXGroup", "AXDescription": path.name}
    root_doc = None
    bundle = "com.microsoft.VSCode"
    settable = change != "not_settable"
    if change == "not_focused":
        attrs["AXFocused"] = False
    elif change == "ax_editable_false":
        attrs["AXEditable"] = False
    elif change == "not_textarea":
        attrs["AXRole"] = "AXButton"
    elif change == "terminal_ancestor":
        context["AXDescription"] = "integrated terminal"
    elif change == "wrong_editor_description":
        attrs["AXDescription"] = "another.txt"
    elif change == "remote_document":
        root_doc = "file://remote.example/tmp/receipt.txt"
    elif change == "symlink_document":
        link = tmp_path / "link.txt"
        link.symlink_to(path)
        root_doc = link.as_uri()
    elif change == "unsupported_bundle":
        bundle = "com.apple.Terminal"
    window, _ = _native_editor_fake(
        monkeypatch, path, bundle=bundle, target_attrs=attrs,
        context_attrs=context, root_doc=root_doc, settable=settable,
    )
    assert macos_actuate.ax_editor_os_attested_document_path(window, "0.0.1") is None


def test_ax_file_url_rejects_encoded_nul_and_query(tmp_path):
    path = tmp_path / "receipt.txt"
    path.write_text("safe\n")
    assert macos_actuate._validated_ax_file_url(path.as_uri() + "%00") is None
    assert macos_actuate._validated_ax_file_url(path.as_uri() + "?x=1") is None
