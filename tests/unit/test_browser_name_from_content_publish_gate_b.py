"""EVO-20261018: ARIA name-from-content in the DOM projection + publish-gate label.

Defect A: a control whose label lives in a child element
(``<button><span>确认发布</span></button>``) carries neither ``aria-label`` nor
``name``, so it was published with an empty name.

Defect B: the RULE-AI-28 publish gate resolved labels straight off
``attributes["name"]`` only, so such a control was invisible to the gate and the
admission permit was never consumed.  Both sides now share one resolution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import llm_loop.browser.perception as perception_module
from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    PlaywrightPageCaptureBackend,
)
from llm_loop.tools.review_host_admission import (
    _is_article_publish,
    is_publication_button,
)

_STRINGS = [
    "",              # 0
    "HTML",          # 1
    "BODY",          # 2
    "BUTTON",        # 3
    "SPAN",          # 4
    "#text",         # 5
    "DIV",           # 6
    "aria-label",    # 7
    "确认发布",       # 8   nested label (button > span > #text)
    "直接按钮",       # 9   direct label (button > #text)
    "明确覆盖",       # 10  aria-label that must win
    "内容应被aria压过",  # 11
    "普通容器文字",   # 12  generic container, must stay unnamed
]

_NODE_NAME = [1, 2, 3, 4, 5, 3, 5, 3, 5, 6, 5]
_NODE_VALUE = [0, 0, 0, 0, 8, 0, 9, 0, 11, 0, 12]
_PARENT_INDEX = [-1, 0, 1, 2, 3, 1, 5, 1, 7, 1, 9]
_ATTRIBUTES = [[], [], [], [], [], [], [], [7, 10], [], [], []]

# <button>甲<span>乙</span>丙</button> -- interleaved, so the own-text-first
# order would yield 甲丙乙 instead of 甲乙丙.
_INTERLEAVED_STRINGS = ["", "HTML", "BODY", "BUTTON", "#text", "SPAN", "甲", "乙", "丙"]
_INTERLEAVED_NODE_NAME = [1, 2, 3, 4, 5, 4, 4]
_INTERLEAVED_NODE_VALUE = [0, 0, 0, 6, 0, 7, 8]
_INTERLEAVED_PARENT_INDEX = [-1, 0, 1, 2, 2, 4, 2]
_INTERLEAVED_ATTRIBUTES = [[], [], [], [], [], [], []]


def _make_backend(strings, node_name, node_value, parent_index, attributes) -> type:
    class _Cdp:
        def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            del params
            if method == "Target.getTargetInfo":
                return {"targetInfo": {"targetId": "target-nfc"}}
            if method == "Page.getFrameTree":
                return {
                    "frameTree": {
                        "frame": {
                            "id": "frame-main",
                            "loaderId": "loader-nfc",
                            "url": "https://example.test/publish",
                        }
                    }
                }
            if method == "DOMSnapshot.captureSnapshot":
                return {
                    "strings": list(strings),
                    "documents": [
                        {
                            "frameId": "frame-main",
                            "nodes": {
                                "nodeName": list(node_name),
                                "nodeValue": list(node_value),
                                "parentIndex": list(parent_index),
                                "backendNodeId": list(range(1, len(node_name) + 1)),
                                "attributes": [list(a) for a in attributes],
                            },
                            "layout": {"nodeIndex": list(range(len(node_name)))},
                        }
                    ],
                }
            if method == "Accessibility.getFullAXTree":
                return {"nodes": []}
            if method == "Runtime.evaluate":
                return {"result": {"type": "string", "value": "complete"}}
            raise AssertionError(f"unexpected CDP method {method}")

    class _Context:
        def new_cdp_session(self, page: Any) -> _Cdp:
            del page
            return _Cdp()

    class _Page:
        context = _Context()
        url = "https://example.test/publish"

    return PlaywrightPageCaptureBackend(_Page())


def _capture(
    strings=_STRINGS,
    node_name=_NODE_NAME,
    node_value=_NODE_VALUE,
    parent_index=_PARENT_INDEX,
    attributes=_ATTRIBUTES,
) -> dict[str, Any]:
    return _make_backend(strings, node_name, node_value, parent_index, attributes).capture()


def _buttons() -> list[dict[str, Any]]:
    raw = _capture()
    return [
        node
        for node in raw["dom"]["nodes"]
        if (node.get("attributes") or {}).get("tag") == "button"
    ]


def test_defect_a_nested_label_gives_the_button_a_name() -> None:
    buttons = _buttons()
    assert len(buttons) == 3
    assert buttons[0]["attributes"]["name"] == "确认发布"


def test_defect_a_direct_label_gives_the_button_a_name() -> None:
    assert _buttons()[1]["attributes"]["name"] == "直接按钮"


def test_defect_a_aria_label_still_wins_over_content() -> None:
    assert _buttons()[2]["attributes"]["name"] == "明确覆盖"


def test_name_from_content_follows_document_order() -> None:
    """<button>甲<span>乙</span>丙</button> reads 甲乙丙, not 甲丙乙."""
    raw = _capture(
        _INTERLEAVED_STRINGS,
        _INTERLEAVED_NODE_NAME,
        _INTERLEAVED_NODE_VALUE,
        _INTERLEAVED_PARENT_INDEX,
        _INTERLEAVED_ATTRIBUTES,
    )
    buttons = [
        node
        for node in raw["dom"]["nodes"]
        if (node.get("attributes") or {}).get("tag") == "button"
    ]
    assert [node["attributes"].get("name") for node in buttons] == ["甲乙丙"]


def test_generic_container_tags_stay_unnamed() -> None:
    raw = _capture()
    divs = [
        node
        for node in raw["dom"]["nodes"]
        if (node.get("attributes") or {}).get("tag") == "div"
    ]
    assert divs and all("name" not in node["attributes"] for node in divs)


def test_semantic_projection_exposes_the_recovered_name(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "browser"), capture_node_cap=10_000
    )
    snapshot = adapter.snapshot("s1", _capture())
    names = {(o.get("attributes") or {}).get("name") for o in snapshot["objects"]}
    assert "确认发布" in names


def test_gate_now_sees_the_previously_invisible_button() -> None:
    obj = {"kind": "button", "attributes": {"name": "确认发布"}}
    assert is_publication_button(obj)


def test_gate_falls_back_to_text_when_name_is_absent() -> None:
    obj = {"kind": "button", "attributes": {"text": "确认发布"}}
    assert is_publication_button(obj)


def test_gate_still_rejects_submit_and_non_buttons() -> None:
    assert not is_publication_button({"kind": "button", "attributes": {"name": "Submit"}})
    assert not is_publication_button({"kind": "link", "attributes": {"name": "确认发布"}})
    assert not is_publication_button(None)
    assert not is_publication_button({"kind": "button", "attributes": {}})


def _raw_with_editor() -> dict[str, Any]:
    return {
        "dom": {
            "nodes": [
                {
                    "kind": "text_field",
                    "attributes": {"value_text": "正文草稿内容"},
                }
            ]
        },
        "ax": {"nodes": []},
    }


def test_bare_publish_label_still_requires_editor_evidence() -> None:
    """The conservative bar is unchanged: bare 发布 needs a document editor."""
    obj = {"kind": "button", "attributes": {"name": "确认发布"}}
    assert _is_article_publish(_raw_with_editor(), obj)
    assert not _is_article_publish({"dom": {"nodes": []}, "ax": {"nodes": []}}, obj)


def test_explicit_article_label_needs_no_editor() -> None:
    obj = {"kind": "button", "attributes": {"name": "发布文章"}}
    assert _is_article_publish({"dom": {"nodes": []}, "ax": {"nodes": []}}, obj)


def test_imported_module_is_the_patched_tree_not_a_release_snapshot() -> None:
    """Guards the PYTHONPATH trap: an unbound ``llm_loop`` silently resolves to a
    ``.releases`` snapshot, which would run the unpatched code and make every
    assertion above pass vacuously."""
    resolved = Path(perception_module.__file__).resolve()
    assert resolved.is_file(), resolved
    assert ".releases" not in resolved.parts, resolved
    assert hasattr(perception_module, "_NAME_FROM_CONTENT_TAGS"), resolved


def test_gate_sees_through_a_machine_name_attribute() -> None:
    """``<button name="commit"><span>发布</span></button>``.

    The HTML ``name`` attribute is a machine identifier, not an accessible name,
    so it must not mask the label a user actually sees.
    """
    obj = {"kind": "button", "attributes": {"name": "commit", "text": "发布"}}
    assert is_publication_button(obj)


def test_article_evidence_survives_a_machine_name_attribute() -> None:
    obj = {"kind": "button", "attributes": {"name": "commit", "text": "发布文章"}}
    assert _is_article_publish({"dom": {"nodes": []}, "ax": {"nodes": []}}, obj)


def test_table_cells_do_not_flood_the_addressing_space() -> None:
    """``td``/``th`` stay out of name-from-content: a table would contribute
    thousands of near-identical cell names."""
    assert "td" not in perception_module._NAME_FROM_CONTENT_TAGS
    assert "th" not in perception_module._NAME_FROM_CONTENT_TAGS
    assert "button" in perception_module._NAME_FROM_CONTENT_TAGS


def test_article_cue_requires_the_label_to_itself_read_as_publish() -> None:
    """``text="文章列表"`` must not supply the article cue for ``name="publish"``.

    Otherwise the sibling label would relax the editor-evidence requirement that
    the conservative bar depends on.
    """
    obj = {"kind": "button", "attributes": {"name": "publish", "text": "文章列表"}}
    assert is_publication_button(obj)
    assert not _is_article_publish({"dom": {"nodes": []}, "ax": {"nodes": []}}, obj)
    assert _is_article_publish(_raw_with_editor(), obj)


# --- Known residual (EVO-20261018 / review P2-1) -----------------------------
# Perception resolves ``name`` as ``aria-label or name-attribute or content``.
# The HTML ``name`` attribute is a machine identifier, not an accessible name, so
# ``<button name="commit"><span>发布</span></button>`` still projects
# ``name="commit"`` and no ``text`` attribute -- the projection publishes ``text``
# from a node's *direct* text only, which is empty here.  The gate therefore never
# sees "发布" end to end.  The test above exercises ``is_publication_button`` in
# isolation and must NOT be read as pipeline coverage; this one pins the current
# behaviour so the gap is visible rather than silently papered over.
def test_known_residual_machine_name_attribute_masks_the_visible_label() -> None:
    strings = ["", "HTML", "BODY", "BUTTON", "SPAN", "#text", "name", "commit", "发布"]
    node_name = [1, 2, 3, 4, 5]
    node_value = [0, 0, 0, 0, 8]
    parent_index = [-1, 0, 1, 2, 3]
    attributes = [[], [], [6, 7], [], []]
    raw = _capture(strings, node_name, node_value, parent_index, attributes)
    buttons = [
        node for node in raw["dom"]["nodes"]
        if (node.get("attributes") or {}).get("tag") == "button"
    ]
    assert len(buttons) == 1
    attrs = buttons[0]["attributes"]
    assert attrs.get("name") == "commit"          # visible label "发布" is masked
    assert "text" not in attrs                     # and no text attribute to fall back on
    assert not is_publication_button(buttons[0])   # gate miss -- OPEN, not fixed
