"""视觉链路大图本地降采样兜底回归（EVO-20261121-efa320ab；RULE-AI-24 RED→GREEN）。

背景（本机实测，2026-11-21）：3000×200 / 2400×200 / 3120×1990 三张图内容识别**全部降级**
（仅返回元信息），1560 宽及以下可成功——大图失败率显著更高。本文件锁定：

1) WEB_VISION_MAX_SIDE 生效时，超阈值大图在**本地**降采样后再送检；
2) 结果结构化报告送检尺寸与缩放系数（供坐标换算）；
3) 识别失败时按「再降采样一半」兜底重试一次，如实报告 fallback_used；
4) WEB_VISION_MAX_SIDE=0 时禁用降采样与兜底（行为与旧版一致）。
"""

from __future__ import annotations

import io

import pytest

from llm_loop.web import vision as vision_mod


def _png_bytes(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (7, 8, 9)).save(buf, format="PNG")
    return buf.getvalue()


def _install_backend(monkeypatch: pytest.MonkeyPatch, *, fail_first: bool = False) -> list:
    calls: list[tuple[int, int]] = []

    def _fake(image_bytes: bytes, mime: str, prompt: str) -> str:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            calls.append(im.size)
        if fail_first and len(calls) == 1:
            raise RuntimeError("视觉模型返回 HTTP 500（测试注入）")
        return "识别文本"

    monkeypatch.setattr(vision_mod, "_describe_minimax", _fake)
    return calls


def test_large_image_is_downsampled_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")
    calls = _install_backend(monkeypatch)

    result = vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")

    assert calls == [(100, 75)]
    assert result.geometry.source_width == 400
    assert result.geometry.source_height == 300
    assert result.geometry.input_width == 100
    assert result.geometry.input_height == 75
    assert result.geometry.downsampled is True
    assert result.geometry.scale_x == pytest.approx(0.25)
    assert result.fallback_used is False


def test_max_side_zero_disables_downsampling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "0")
    calls = _install_backend(monkeypatch)

    result = vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")

    assert calls == [(400, 300)]
    assert result.geometry.downsampled is False


def test_failed_recognition_retries_once_with_further_downsample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")
    calls = _install_backend(monkeypatch, fail_first=True)

    result = vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")

    assert len(calls) == 2
    assert calls[1][0] < calls[0][0]
    assert result.fallback_used is True
    assert result.text


def test_fallback_updates_reported_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """兜底重试成功后，几何必须反映**实际送检尺寸**（source 仍为送检前尺寸）。"""
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")
    calls = _install_backend(monkeypatch, fail_first=True)

    result = vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")

    assert result.geometry.source_width == 400
    assert result.geometry.source_height == 300
    assert result.geometry.input_width == calls[1][0]
    assert result.geometry.input_height == calls[1][1]
    assert result.geometry.downsampled is True


def test_total_failure_raises_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")

    def _always_fail(image_bytes: bytes, mime: str, prompt: str) -> str:
        raise RuntimeError("视觉模型返回 HTTP 500（测试注入）")

    monkeypatch.setattr(vision_mod, "_describe_minimax", _always_fail)

    with pytest.raises(RuntimeError):
        vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")


def test_backend_prompt_declares_sent_pixel_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    """送检尺寸必须写进提示词——模型自报坐标必须落在该尺寸内（坐标契约的前提）。"""
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")
    prompts: list[str] = []

    def _fake(image_bytes: bytes, mime: str, prompt: str) -> str:
        prompts.append(prompt)
        return "识别文本"

    monkeypatch.setattr(vision_mod, "_describe_minimax", _fake)

    vision_mod.describe_image_detailed(_png_bytes(400, 300), mime="image/png")

    assert prompts
    assert "100×75" in prompts[0]
    assert "400×300" in prompts[0]


def test_describe_image_wrapper_keeps_string_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_VISION_BACKEND", "minimax")
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "100")
    _install_backend(monkeypatch)

    text = vision_mod.describe_image(_png_bytes(400, 300), mime="image/png")

    assert isinstance(text, str)
    assert text.strip()
