"""Host AXDocument evidence is a file:// URL on an editable exact AX target."""
from __future__ import annotations

from dataclasses import dataclass

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
