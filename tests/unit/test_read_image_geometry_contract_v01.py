"""read_image 坐标契约与 crop 参数回归（EVO-20261121-efa320ab；RULE-AI-24 RED→GREEN）。

背景（本机实测，2026-11-21）：read_image 回执里的「内容识别」文本来自视觉模型自述坐标，
与回执元信息里的 PNG 真实像素**不是同一坐标系**，两者无固定比例、工具也不回传缩放系数——
「点错按钮」是坐标契约缺失的机制性根因，不是偶发手误。本文件锁定三项契约：

1) crop 参数按**原图像素坐标**裁剪；越界/非法即 FAILURE 并给出明确提示；
2) 回执固定给出**确定性**坐标契约（原图尺寸/裁剪偏移/送检尺寸/缩放系数/换算式）；
3) 模型自报 bbox 被解析为结构化坐标块并换算回原图坐标（明确标注模型自报未经验证）。
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.read_image import ReadImageTool
from llm_loop.web import vision as vision_mod


def _png_bytes(width: int, height: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _install_fake_vision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "识别文本",
    geometry: vision_mod.VisionGeometry | None = None,
    raise_error: bool = False,
) -> dict:
    """替换视觉后端；返回捕获调用参数的字典。"""

    captured: dict = {}

    def _fake(image_bytes: bytes, mime: str = "", prompt: str = "", settings=None):
        captured["bytes"] = image_bytes
        captured["mime"] = mime
        captured["prompt"] = prompt
        if raise_error:
            raise RuntimeError("视觉后端不可用（测试注入）")
        if geometry is not None:
            return vision_mod.VisionResult(text=text, geometry=geometry, backend="fake")
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            width, height = im.size
        geom = vision_mod.VisionGeometry(
            source_width=width,
            source_height=height,
            input_width=width,
            input_height=height,
            max_side=vision_mod.vision_max_side(),
            downsampled=False,
        )
        return vision_mod.VisionResult(text=text, geometry=geom, backend="fake")

    monkeypatch.setattr(vision_mod, "describe_image_detailed", _fake)
    return captured


def _write_png(tmp_path: Path, width: int = 400, height: int = 300) -> Path:
    path = tmp_path / "shot.png"
    path.write_bytes(_png_bytes(width, height))
    return path


def test_crop_region_is_applied_in_original_pixel_space(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(
        path=str(path), crop={"x": 10, "y": 20, "w": 100, "h": 50}
    )

    assert result.status is ToolResultStatus.SUCCESS
    from PIL import Image

    with Image.open(io.BytesIO(captured["bytes"])) as sent:
        assert sent.size == (100, 50)
    assert "原图=400×300" in result.content
    assert "裁剪=(10,20,100,50)" in result.content
    assert "送检=100×50" in result.content
    assert "缩放=1.000" in result.content


def test_crop_out_of_bounds_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(
        path=str(path), crop={"x": 380, "y": 0, "w": 100, "h": 50}
    )

    assert result.status is ToolResultStatus.FAILURE
    assert "裁剪" in result.content


def test_receipt_without_crop_reports_full_image_geometry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(path=str(path))

    assert result.status is ToolResultStatus.SUCCESS
    assert "原图=400×300" in result.content
    assert "裁剪=无" in result.content
    assert "送检=400×300" in result.content


def test_model_bbox_is_mapped_back_to_original_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    geometry = vision_mod.VisionGeometry(
        source_width=100,
        source_height=50,
        input_width=50,
        input_height=25,
        max_side=1568,
        downsampled=True,
    )
    _install_fake_vision(monkeypatch, text="目标元素 bbox=[10,20,30,40]", geometry=geometry)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(
        path=str(path), crop={"x": 10, "y": 20, "w": 100, "h": 50}
    )

    assert result.status is ToolResultStatus.SUCCESS
    assert "缩放=0.500" in result.content
    # 原图坐标 = 送检坐标 / 缩放 + 裁剪偏移 → [30,60,70,100]
    assert "[30,60,70,100]" in result.content
    assert "模型自报" in result.content


def test_geometry_contract_survives_vision_backend_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_vision(monkeypatch, raise_error=True)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(
        path=str(path), crop={"x": 0, "y": 0, "w": 200, "h": 100}
    )

    assert result.status is ToolResultStatus.FAILURE
    assert "原图=400×300" in result.content
    assert "送检=200×100" in result.content
    assert "[识别降级]" in result.content


def test_failure_path_reports_actual_preprocessed_send_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """后端失败时回报的是**实际送检尺寸**（本地降采样后），不是原图尺寸（review P2-2）."""
    monkeypatch.setenv("WEB_VISION_MAX_SIDE", "1568")

    def _boom(image_bytes: bytes, mime: str = "", prompt: str = "", settings=None):
        raise RuntimeError("视觉后端不可用（测试注入）")

    monkeypatch.setattr(vision_mod, "_describe_minimax", _boom)
    monkeypatch.setattr(vision_mod, "_describe_provider", _boom)
    path = _write_png(tmp_path, width=4000, height=3000)

    result = ReadImageTool().execute(path=str(path))

    assert result.status is ToolResultStatus.FAILURE
    assert "原图=4000×3000" in result.content
    # 实际送检尺寸是本地降采样（并兜底再降采样一半）后的尺寸，不是 4000×3000
    assert "送检=4000×3000" not in result.content
    assert "送检=784×588" in result.content
    assert "缩放=0.196" in result.content


@pytest.mark.parametrize(
    "bad",
    [
        {"x": -1, "y": 0, "w": 10, "h": 10},
        {"x": 0, "y": 0, "w": 0, "h": 10},
        {"x": 0, "y": 0, "h": 10},
        {"x": "a", "y": 0, "w": 10, "h": 10},
        "not-json",
    ],
)
def test_invalid_crop_parameters_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)

    result = ReadImageTool().execute(path=str(path), crop=bad)

    assert result.status is ToolResultStatus.FAILURE
    assert "裁剪" in result.content


def test_crop_without_pillow_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """本地裁剪不可用（缺 Pillow）→ 如实 FAILURE，不静默忽略 crop。"""
    import builtins

    _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)
    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name.startswith("PIL"):
            raise ImportError("PIL blocked (测试注入)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)

    result = ReadImageTool().execute(path=str(path), crop={"x": 0, "y": 0, "w": 10, "h": 10})

    assert result.status is ToolResultStatus.FAILURE
    assert "裁剪" in result.content


def test_prompt_is_passed_through_to_vision_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _install_fake_vision(monkeypatch)
    path = _write_png(tmp_path)

    ReadImageTool().execute(path=str(path), prompt="只找发布按钮", crop={"x": 10, "y": 20, "w": 100, "h": 50})

    assert "只找发布按钮" in captured["prompt"]
