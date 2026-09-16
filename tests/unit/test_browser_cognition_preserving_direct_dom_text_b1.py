from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    PlaywrightPageCaptureBackend,
)


class _TextCdp:
    def __init__(self, *, status_text: str = "Submitted", nested: bool = False) -> None:
        self.status_text = status_text
        self.nested = nested

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        del params
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": "target-text"}}
        if method == "Page.getFrameTree":
            return {
                "frameTree": {
                    "frame": {
                        "id": "frame-main",
                        "loaderId": "loader-text",
                        "url": "https://example.test/text",
                    }
                }
            }
        if method == "DOMSnapshot.captureSnapshot":
            return self._dom_snapshot()
        if method == "Accessibility.getFullAXTree":
            return self._ax_tree()
        if method == "Runtime.evaluate":
            return {"result": {"type": "string", "value": "complete"}}
        raise AssertionError(f"unexpected CDP method {method}")

    def _dom_snapshot(self) -> dict[str, Any]:
        strings = [
            "",
            "HTML",
            "BODY",
            "DIV",
            "SPAN",
            "#text",
            "SCRIPT",
            "aria-label",
            "Submission status",
            "Inner status",
            self.status_text,
            "window.__should_not_surface = 'secret'",
        ]
        if self.nested:
            node_name = [1, 2, 3, 4, 5, 6, 5]
            node_value = [0, 0, 0, 0, 10, 0, 11]
            parent_index = [-1, 0, 1, 2, 3, 1, 5]
            backend_ids = [1, 2, 3, 4, 5, 6, 7]
            attributes = [[], [], [7, 8], [7, 9], [], [], []]
        else:
            node_name = [1, 2, 3, 5, 6, 5]
            node_value = [0, 0, 0, 10, 0, 11]
            parent_index = [-1, 0, 1, 2, 1, 4]
            backend_ids = [1, 2, 3, 4, 6, 7]
            attributes = [[], [], [7, 8], [], [], []]
        return {
            "strings": strings,
            "documents": [
                {
                    "frameId": "frame-main",
                    "nodes": {
                        "nodeName": node_name,
                        "nodeValue": node_value,
                        "parentIndex": parent_index,
                        "backendNodeId": backend_ids,
                        "attributes": attributes,
                    },
                    "layout": {"nodeIndex": list(range(len(node_name)))},
                }
            ],
        }

    def _ax_tree(self) -> dict[str, Any]:
        parent_backend = 4 if self.nested else 3
        text_backend = 5 if self.nested else 4
        return {
            "nodes": [
                {
                    "nodeId": "ax-status",
                    "backendDOMNodeId": parent_backend,
                    "ignored": False,
                    "role": {"value": "generic"},
                    "name": {"value": "Inner status" if self.nested else "Submission status"},
                    "properties": [],
                },
                {
                    "nodeId": "ax-text",
                    "backendDOMNodeId": text_backend,
                    "parentId": "ax-status",
                    "ignored": False,
                    "role": {"value": "StaticText"},
                    "name": {"value": self.status_text},
                    "properties": [],
                },
            ]
        }


class _Context:
    def __init__(self, cdp: _TextCdp) -> None:
        self.cdp = cdp

    def new_cdp_session(self, page: Any) -> _TextCdp:
        del page
        return self.cdp


class _Page:
    def __init__(self, cdp: _TextCdp) -> None:
        self.context = _Context(cdp)
        self.url = "https://example.test/text"


def _capture(*, text: str = "Submitted", nested: bool = False) -> dict[str, Any]:
    return PlaywrightPageCaptureBackend(_Page(_TextCdp(status_text=text, nested=nested))).capture()


def _dom_named(raw: dict[str, Any], name: str) -> dict[str, Any]:
    for node in raw["dom"]["nodes"]:
        if (node.get("attributes") or {}).get("name") == name:
            return node
    raise AssertionError(f"DOM node {name!r} not found")


def _semantic_named(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    for obj in snapshot["objects"]:
        if (obj.get("attributes") or {}).get("name") == name:
            return obj
    raise AssertionError(f"semantic object {name!r} not found")


def test_b1_direct_dom_text_is_preserved_on_exact_parent_without_emitting_text_node() -> None:
    raw = _capture(text="Submitted")
    status = _dom_named(raw, "Submission status")

    assert status["attributes"]["text"] == "Submitted"
    assert all(node["attributes"].get("tag") != "#text" for node in raw["dom"]["nodes"])


def test_b1_nested_descendant_text_is_not_hoisted_to_grandparent() -> None:
    raw = _capture(text="Nested", nested=True)
    outer = _dom_named(raw, "Submission status")
    inner = _dom_named(raw, "Inner status")

    assert "text" not in outer["attributes"]
    assert inner["attributes"]["text"] == "Nested"


def test_b1_script_text_is_not_projected_as_model_visible_dom_text() -> None:
    raw = _capture(text="Submitted")
    script = next(
        node for node in raw["dom"]["nodes"] if (node.get("attributes") or {}).get("tag") == "script"
    )
    assert "text" not in script["attributes"]


def test_b1_stable_parent_text_change_flows_through_existing_semantic_diff(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "browser"))
    before = adapter.snapshot("s1", _capture(text="Not submitted"), projection_limit=50)
    after = adapter.snapshot("s1", _capture(text="Submitted"), projection_limit=50)

    before_status = _semantic_named(before, "Submission status")
    after_status = _semantic_named(after, "Submission status")
    assert before_status["id"] == after_status["id"]
    assert before_status["attributes"]["text"] == "Not submitted"
    assert after_status["attributes"]["text"] == "Submitted"

    diff = adapter.diff("s1", before["snapshot"]["snapshot_id"], after["snapshot"]["snapshot_id"])
    changed = {row["id"]: row["fields"] for row in diff["changed"] or []}
    assert "attributes.text" in changed[after_status["id"]]

    # B1 preserves source evidence instead of collapsing AX text into the parent object.
    assert _semantic_named(after, "Submitted")["id"] != after_status["id"]
