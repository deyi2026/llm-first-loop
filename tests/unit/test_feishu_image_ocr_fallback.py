"""2026-08-20（借鉴 SYAGI）: 图片 vision 全失败 → 飞书 OCR 文字兑底（诚实标注来源）."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from llm_loop.feishu.handlers import FeishuMessage, FeishuMessageHandler


def _make_msg() -> FeishuMessage:
    return FeishuMessage(
        message_id="m-1",
        sender_id="u-1",
        chat_id="c-1",
        msg_type="image",
        file_key="k-1",
        file_name="pic.jpg",
    )


def _make_handler(
    *, ocr_lines: list[str], ocr_error: Exception | None = None
) -> tuple[FeishuMessageHandler, list]:
    h = FeishuMessageHandler.__new__(FeishuMessageHandler)
    h._engine = SimpleNamespace(settings=SimpleNamespace())
    rest = MagicMock()
    if ocr_error is not None:
        rest.ocr_image.side_effect = ocr_error
    else:
        rest.ocr_image.return_value = ocr_lines
    h._rest_client = rest
    h._audit = lambda *a, **k: None
    injected: list[str] = []
    h._inject_and_reply = lambda msg, text: injected.append(text)
    h._reply = lambda *a, **k: None
    return h, injected


def test_vision_failure_ocr_fallback_injected():
    """vision 失败 + OCR 有文字 → 注入标注 OCR 来源的文本."""
    import llm_loop.web.vision as vision_mod

    def fake_describe(*a, **k):
        raise RuntimeError("vision down")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(vision_mod, "describe_image", fake_describe)
    monkeypatch.setattr(vision_mod, "vision_enabled", lambda *a, **k: True)
    try:
        h, injected = _make_handler(ocr_lines=["第一行", "第二行"])
        h._handle_image(_make_msg(), b"\xff\xd8\xff\xe0jpg", "pic.jpg")
        assert len(injected) == 1
        assert "OCR 文字提取" in injected[0]
        assert "第一行" in injected[0]
    finally:
        monkeypatch.undo()


def test_vision_and_ocr_both_fail_honest_reply():
    """vision + OCR 都失败 → 如实回复失败（不伪造）."""
    import llm_loop.web.vision as vision_mod

    def fake_describe(*a, **k):
        raise RuntimeError("vision down")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(vision_mod, "describe_image", fake_describe)
    monkeypatch.setattr(vision_mod, "vision_enabled", lambda *a, **k: True)
    try:
        replied: list[str] = []
        h, _ = _make_handler(ocr_lines=[], ocr_error=RuntimeError("ocr denied"))
        h._reply = lambda msg, text: replied.append(text)
        h._handle_image(_make_msg(), b"jpeg-data", "pic.jpg")
        assert replied and "图片识别失败" in replied[0]
    finally:
        monkeypatch.undo()
