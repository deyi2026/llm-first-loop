"""2026-08-20（借鉴 SYAGI P1）: 图片 MIME magic-bytes 嗅探 + describe_image 空 mime 自动嗅探."""

from __future__ import annotations

import pytest

from llm_loop.web.vision import _sniff_mime, describe_image


def test_sniff_mime_by_magic_bytes():
    assert _sniff_mime(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert _sniff_mime(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert _sniff_mime(b"GIF89a...") == "image/gif"
    assert _sniff_mime(b"RIFFxxxxWEBP...") == "image/webp"
    assert _sniff_mime(b"BMxxxx") == "image/bmp"
    assert _sniff_mime(b"unknown") == "image/png"  # 兜底


def test_describe_image_sniffs_mime_when_not_provided(monkeypatch: pytest.MonkeyPatch):
    """describe_image 不传 mime → 按字节嗅探（jpg 不再按 png 声明）."""
    captured: dict = {}

    def fake_provider(image_bytes: bytes, mime: str, prompt: str, settings) -> str:
        captured["mime"] = mime
        return "ok"

    monkeypatch.setattr("llm_loop.web.vision._vision_backend", lambda: "provider")
    monkeypatch.setattr("llm_loop.web.vision._describe_provider", fake_provider)
    text = describe_image(b"\xff\xd8\xff\xe0jpeg-bytes", settings=object())
    assert text == "ok"
    assert captured["mime"] == "image/jpeg"
