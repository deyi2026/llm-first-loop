"""EVO-20260918-c69527a1 + EVO-20260918-f2310800.

c69527a1: snapshot projection surface - model-declared kinds/cursor window with
verbatim matched_total/returned/truncated/next_cursor receipts (zero policy).
f2310800: vision phase 1 - optional fixed-parameter screenshot persisted as an
evidence-layer artifact; never feeds objects/grounding/version paths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class _Backend:
    def __init__(self, *, vision: bytes | None = None, vision_error: Exception | None = None) -> None:
        self.vision = vision
        self.vision_error = vision_error

    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(FIXTURES["base"]))

    def capture_vision_evidence(self) -> bytes:
        if self.vision_error is not None:
            raise self.vision_error
        assert self.vision is not None
        return self.vision


def _adapter(tmp_path: Path) -> BrowserPerceptionAdapter:
    return BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))


def _tool(backend: _Backend, adapter: BrowserPerceptionAdapter) -> BrowserPerceiveTool:
    return BrowserPerceiveTool(adapter=adapter, backend=backend, session_id_getter=lambda: "s1")


def test_projection_kinds_filter_with_verbatim_totals(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", FIXTURES["base"], projection_kinds=["button"])
    proj = result["objects_projection"]
    assert proj["matched_total"] == 2
    assert proj["returned"] == 2
    assert proj["truncated"] is False
    assert proj["next_cursor"] is None
    assert proj["complete"] is True
    assert {obj.get("kind") for obj in result["objects"]} == {"button"}


def test_projection_cursor_pagination(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    page1 = adapter.snapshot(
        "s1", FIXTURES["base"], projection_limit=1, projection_kinds=["button"], projection_cursor=0
    )
    p1 = page1["objects_projection"]
    assert p1["returned"] == 1 and p1["truncated"] is True and p1["next_cursor"] == 1
    page2 = adapter.snapshot(
        "s1", FIXTURES["base"], projection_limit=1, projection_kinds=["button"], projection_cursor=p1["next_cursor"]
    )
    p2 = page2["objects_projection"]
    assert p2["returned"] == 1 and p2["truncated"] is False and p2["next_cursor"] is None
    assert page1["objects"][0]["id"] != page2["objects"][0]["id"]


def test_projection_defaults_preserve_legacy_receipt(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", FIXTURES["base"])
    proj = result["objects_projection"]
    assert proj["returned"] == proj["matched_total"] == proj["total"]
    assert proj["cursor"] == 0
    assert proj["complete"] is True
    assert proj["kinds"] is None


def test_tool_rejects_malformed_projection_params(tmp_path: Path) -> None:
    tool = _tool(_Backend(), _adapter(tmp_path))
    bad = tool.execute(action="snapshot", projection_kinds="button")
    assert bad.status.value == "failure"
    assert "projection_kinds" in bad.content
    bad_cursor = tool.execute(action="snapshot", projection_cursor=-1)
    assert bad_cursor.status.value == "failure"
    bad_vision = tool.execute(action="snapshot", vision="full")
    assert bad_vision.status.value == "failure"


def test_tool_vision_evidence_is_persisted_with_ref_and_sha(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    tool = _tool(_Backend(vision=_PNG), adapter)
    result = tool.execute(action="snapshot", vision="evidence")
    payload = json.loads(result.content)
    vision = payload["vision"]
    assert vision["status"] == "ok"
    assert vision["mime"] == "image/png"
    assert vision["bytes"] == len(_PNG)
    assert vision["sha256"] == hashlib.sha256(_PNG).hexdigest()
    assert vision["ref"].startswith("vision://browser/v0.1/")
    stored = Path(vision["path"]).read_bytes()
    assert stored == _PNG
    # Evidence-layer invariant: the main snapshot receipts are unchanged by vision.
    assert payload["objects_projection"]["returned"] >= 1
    assert "vision" not in payload["snapshot"]


def test_tool_vision_unavailable_and_failure_never_mask_snapshot(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    class _PlainBackend:
        def capture(self) -> dict[str, Any]:
            return json.loads(json.dumps(FIXTURES["base"]))

    plain = BrowserPerceiveTool(adapter=adapter, backend=_PlainBackend(), session_id_getter=lambda: "s1")
    payload = json.loads(plain.execute(action="snapshot", vision="evidence").content)
    assert payload["vision"] == {"status": "unavailable"}

    failing = _tool(_Backend(vision_error=RuntimeError("screenshot denied")), adapter)
    payload = json.loads(failing.execute(action="snapshot", vision="evidence").content)
    assert payload["vision"]["status"] == "failed"
    assert payload["vision"]["error_type"] == "RuntimeError"
    assert payload["objects_projection"]["returned"] >= 1
