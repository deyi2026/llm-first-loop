"""EVO-20260820-5d0a7b99（借鉴 DSH rc.8 工具层视觉）: read_image 图像转结构化文本证据测试.

验证:
- 元信息提取（标准库解析 PNG/JPEG 头 → 格式/尺寸/色彩模式，零依赖）
- 内容识别: describe_image 后端成功 → SUCCESS 含元信息 + 识别文本
- 识别失败/后端不可用 → 如实降级为仅元信息（不伪装成功）
- 文件不存在/空文件/缺参数 → 如实失败
"""

from __future__ import annotations

import struct
from unittest import mock

from llm_loop.core.message import ToolResultStatus
from llm_loop.tools.builtin.read_image import ReadImageTool, _probe_meta


def _png_bytes(width: int = 64, height: int = 48) -> bytes:
    """构造最小合法 PNG 头（签名 + IHDR 尺寸段，足够元信息解析）."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBB", width, height, 8, 2)  # w, h, bit_depth=8, color_type=2(RGB)
    return sig + b"\x00\x00\x00\x0dIHDR" + ihdr + b"\x00\x00\x00\x00"


def _jpeg_bytes(width: int = 320, height: int = 240) -> bytes:
    """构造最小 JPEG（SOI + SOF0 段含尺寸）."""
    sof0 = (
        b"\xff\xd8"
        + b"\xff\xc0"
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">HH", height, width)
        + b"\x03"
    )
    return sof0


def test_meta_probe_png():
    meta = _probe_meta(_png_bytes(64, 48))
    assert meta["format"] == "PNG"
    assert meta["width"] == 64 and meta["height"] == 48
    assert meta["bit_depth"] == 8 and meta["color_mode"] == "RGB"


def test_meta_probe_jpeg():
    meta = _probe_meta(_jpeg_bytes(320, 240))
    assert meta["format"] == "JPEG"
    assert meta["width"] == 320 and meta["height"] == 240


def test_meta_probe_unknown():
    meta = _probe_meta(b"\x00\x01\x02\x03 not an image")
    assert meta["format"] == "unknown"


def test_read_image_success_with_vision(tmp_path, monkeypatch):
    """后端识别成功 → SUCCESS 含元信息 + 识别文本."""
    p = tmp_path / "shot.png"
    p.write_bytes(_png_bytes(64, 48))
    with mock.patch(
        "llm_loop.web.vision.describe_image", return_value="界面截图：顶部导航栏 + 内容区"
    ):
        r = ReadImageTool().execute(path=str(p))
    assert r.status == ToolResultStatus.SUCCESS
    assert "格式=PNG" in r.content
    assert "64×48" in r.content
    assert "界面截图" in r.content


def test_read_image_vision_fails_degrades(tmp_path, monkeypatch):
    """后端失败 → 如实降级仅元信息（FAILURE + 降级标注 + 指引）."""
    p = tmp_path / "shot.png"
    p.write_bytes(_png_bytes(10, 10))
    with mock.patch(
        "llm_loop.web.vision.describe_image",
        side_effect=RuntimeError("not logged in: 请先登录"),
    ):
        r = ReadImageTool().execute(path=str(p))
    assert r.status == ToolResultStatus.FAILURE  # 无识别文本 → 如实失败（不伪装成功）
    assert "格式=PNG" in r.content  # 元信息仍返回
    assert "[识别降级]" in r.content
    assert "arkcli auth login" in r.content  # 可操作指引


def test_read_image_missing_path():
    r = ReadImageTool().execute(path="/nonexistent/nope.png")
    assert r.status == ToolResultStatus.FAILURE
    assert "不存在" in r.content


def test_read_image_empty_file(tmp_path):
    p = tmp_path / "empty.png"
    p.write_bytes(b"")
    r = ReadImageTool().execute(path=str(p))
    assert r.status == ToolResultStatus.FAILURE
    assert "空文件" in r.content


def test_read_image_missing_param():
    r = ReadImageTool().execute()
    assert r.status == ToolResultStatus.FAILURE
    assert "path" in r.content
