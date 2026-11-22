"""基础工具: read_image 图像转结构化文本证据（EVO-20260820-5d0a7b99，借鉴 DSH rc.8 工具层视觉）.

设计定位: 主模型无图像输入能力时，把用户发来的截图/流程图/界面图拆成结构化文本证据——
元信息提取（尺寸/色彩模式/格式，标准库解析文件头，零依赖）+ 内容识别（复用 web/vision
describe_image 后端链: arkcli 团队识别工具优先 → 注册表 multimodal 模型兜底）→ 交模型推理。
局限如实标注: PPT 截图/流程图/界面截图等结构化图片效果好；真实照片/复杂空间关系恢复受限。
依赖缺失/识别失败 → 如实降级（仅返回元信息）或明确报错，不伪装成功。
坐标契约（EVO-20261121-efa320ab）：回执固定给出**确定性**几何事实——原图尺寸、裁剪区域、
送检尺寸、缩放系数与换算式；模型自报 bbox 被解析为结构化坐标块并换算回原图坐标。
此前「内容识别」里的坐标来自模型自述、与元信息里的真实像素不是同一坐标系且无换算依据——
本演进把该隐式假设变成显式契约。
"""

from __future__ import annotations

import io
import json
import re
import struct
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus
from llm_loop.core.run_context import workspace_base

# 图片扩展名 → mime（与 web/routes.py 上传通道一致）
_EXT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# 图片识别默认提示（与 web/vision.py VISION_DEFAULT_PROMPT 对齐）
_DEFAULT_PROMPT = "请详细描述这张图片的内容，尽量转录图中文字。若无法识别图片，请如实说明。"

# 元信息提取单文件上限（防御: 大图只读头部，不整载）
_META_MAX_BYTES = 64 * 1024


# ── crop 解析与坐标契约（EVO-20261121-efa320ab）────────────────────────────
_BBOX_RE = re.compile(r"[\[\(]\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*[\]\)]")
_MAX_BBOX = 20


class _CropError(ValueError):
    """裁剪参数非法（类型错/缺字段/负值/零宽高）."""


def _parse_crop(raw: object) -> tuple[int, int, int, int] | None:
    """解析 crop 参数（原图像素坐标 x,y,w,h）.

    None = 未提供；非法 → 抛 :class:`_CropError`（调用方如实回执 FAILURE）。
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            raw = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise _CropError(f"crop 字符串不是合法 JSON（{exc}）") from exc
    if not isinstance(raw, dict):
        raise _CropError("crop 必须是对象 {x,y,w,h}")

    def _num(*keys: str) -> int:
        for key in keys:
            if key in raw:
                value = raw[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise _CropError(f"crop.{key} 必须是数字")
                if isinstance(value, float) and not float(value).is_integer():
                    raise _CropError(f"crop.{key} 必须是整数")
                return int(value)
        raise _CropError(f"crop 缺少字段 {'/'.join(keys)}")

    x = _num("x")
    y = _num("y")
    width = _num("w", "width")
    height = _num("h", "height")
    if x < 0 or y < 0:
        raise _CropError("crop.x/crop.y 不能为负")
    if width <= 0 or height <= 0:
        raise _CropError("crop.w/crop.h 必须大于 0")
    return (x, y, width, height)


def _crop_image_bytes(data: bytes, x: int, y: int, width: int, height: int) -> bytes | None:
    """本地裁剪（原图像素坐标）→ PNG bytes；Pillow 缺失/解码失败 → None."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow 缺失如实返回 None
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            region = im.crop((x, y, x + width, y + height))
            buf = io.BytesIO()
            region.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:  # noqa: BLE001 - 解码失败如实返回 None
        return None


def _extract_bboxes(text: str) -> list[tuple[int, int, int, int]]:
    """从识别文本抽取 bbox（四元组）——模型自报值，未经验证."""
    out: list[tuple[int, int, int, int]] = []
    for match in _BBOX_RE.finditer(text or ""):
        box = (int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4)))
        if box not in out:
            out.append(box)
        if len(out) >= _MAX_BBOX:
            break
    return out


def _format_contract(
    *,
    orig_w: int | None,
    orig_h: int | None,
    crop: tuple[int, int, int, int] | None,
    sent_w: int,
    sent_h: int,
    scale_x: float,
    scale_y: float,
) -> str:
    """确定性坐标契约行（原图/裁剪/送检/缩放/换算式）."""
    original = f"{orig_w}×{orig_h}" if orig_w and orig_h else "未知"
    crop_text = "无" if crop is None else f"({crop[0]},{crop[1]},{crop[2]},{crop[3]})"
    offset_x, offset_y = (0, 0) if crop is None else (crop[0], crop[1])
    scale_text = f"{scale_x:.3f}"
    if abs(scale_y - scale_x) > 1e-9:
        scale_text += f"×{scale_y:.3f}"
    return (
        f"[坐标契约] 原图={original} 裁剪={crop_text} 送检={sent_w}×{sent_h} 缩放={scale_text} "
        f"换算=原图坐标=(送检坐标÷缩放)+裁剪偏移({offset_x},{offset_y})"
    )


def _probe_meta(data: bytes) -> dict:
    """标准库解析图片头 → 格式/尺寸/色彩模式元信息（零依赖，失败如实跳过字段）.

    支持 PNG/JPEG/GIF/WebP/BMP；无法解析 → 仅返回格式嗅探结果。
    """
    meta: dict = {"format": "unknown"}
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 26:
            w, h, bit_depth, color_type = struct.unpack(">IIBB", data[16:26])
            ct = {
                0: "灰度", 2: "RGB", 3: "调色板", 4: "灰度+Alpha", 6: "RGBA",
            }.get(color_type, f"未知({color_type})")
            meta.update(format="PNG", width=w, height=h, bit_depth=bit_depth, color_mode=ct)
        elif data[:2] == b"\xff\xd8":
            # JPEG: 扫描 SOF0/SOF2 段取尺寸（宽高在段内偏移 5/7）
            i, w, h = 2, None, None
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    break
                seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
                i += 2 + seg_len
            meta.update(format="JPEG", width=w, height=h)
        elif data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            meta.update(format="GIF", width=w, height=h)
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X" and len(data) >= 30:
                w = 1 + (struct.unpack("<I", data[24:28])[0] & 0xFFFFFF)
                h = 1 + ((struct.unpack("<I", data[27:31])[0] >> 8) & 0xFFFFFF)
                meta.update(format="WebP", width=w, height=h)
            else:
                meta.update(format="WebP")
        elif data[:2] == b"BM" and len(data) >= 30:
            w, h = struct.unpack("<ii", data[18:26])
            bpp = struct.unpack("<H", data[28:30])[0]
            meta.update(format="BMP", width=abs(w), height=abs(h), bit_depth=bpp)
    except Exception:  # noqa: BLE001 — 头解析失败如实跳过字段（fail-open）
        pass
    return meta


def _mime_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _EXT_MIME.get(ext, "image/png")


def _fail_result(content: str) -> ToolResult:
    """FAILURE 回执（统一构造，避免 execute 过长）."""
    return ToolResult(
        status=ToolResultStatus.FAILURE,
        content=content,
        tool_call_id="",
        tool_name="read_image",
    )


def _resolve_crop(
    raw: object, orig_w: int | None, orig_h: int | None
) -> tuple[tuple[int, int, int, int] | None, str | None]:
    """解析并校验 crop（原图像素坐标）→ (crop, error_message).

    error_message 非空即 fail-closed（不进入视觉链路）。
    """
    try:
        crop = _parse_crop(raw)
    except _CropError as exc:
        return None, f"[裁剪参数错误] {exc}（crop 必须是 {{x,y,w,h}}，原图像素坐标）"
    if crop is None:
        return None, None
    x, y, width, height = crop
    if not orig_w or not orig_h:
        return None, "[裁剪参数错误] 无法解析原图尺寸，crop 不可用。"
    if x + width > orig_w or y + height > orig_h:
        return None, (
            f"[裁剪参数错误] 裁剪区域 (x={x},y={y},w={width},h={height}) "
            f"超出原图 {orig_w}×{orig_h} 边界。"
        )
    return crop, None


def _run_vision(
    send_bytes: bytes, send_mime: str, prompt: str
) -> tuple[str | None, str | None, object | None]:
    """调用视觉后端 → (text, error, geometry)；失败如实降级，不伪装成功.

    后端失败时 geometry 取自 vision 模块挂在异常上的**本地预处理事实**
    （最后一次实际送检的尺寸与缩放），而不是原图/裁剪尺寸。
    """
    try:
        from llm_loop.web.vision import describe_image_detailed

        result = describe_image_detailed(send_bytes, mime=send_mime, prompt=prompt)
    except Exception as exc:  # noqa: BLE001 — 识别失败如实降级
        geometry = getattr(exc, "vision_geometry", None)
        return None, f"{type(exc).__name__}: {exc}", geometry
    return result.text, None, result.geometry


def _meta_lines(meta: dict, orig_w: int | None, orig_h: int | None) -> list[str]:
    """元信息行（格式/尺寸/色彩模式）."""
    lines = [f"[元信息] 格式={meta.get('format')}"]
    if orig_w is not None and orig_h is not None:
        line = f"[元信息] 尺寸={orig_w}×{orig_h}"
        if meta.get("color_mode"):
            line += f"  位深={meta.get('bit_depth')}  色彩模式={meta.get('color_mode')}"
        lines.append(line)
    return lines


def _vision_block(text: str, crop: tuple[int, int, int, int] | None, scale_x: float, scale_y: float) -> list[str]:
    """[内容识别] + 模型自报 bbox 的结构化坐标块（标注未经验证）."""
    lines = ["[内容识别]", text]
    boxes = _extract_bboxes(text)
    if not boxes:
        return lines
    offset_x, offset_y = (crop[0], crop[1]) if crop else (0, 0)
    rendered = []
    for index, (bx1, by1, bx2, by2) in enumerate(boxes, start=1):
        orig_box = (
            int(round(bx1 / scale_x)) + offset_x,
            int(round(by1 / scale_y)) + offset_y,
            int(round(bx2 / scale_x)) + offset_x,
            int(round(by2 / scale_y)) + offset_y,
        )
        rendered.append(
            f"#{index} 原图=[{orig_box[0]},{orig_box[1]},{orig_box[2]},{orig_box[3]}] "
            f"送检=[{bx1},{by1},{bx2},{by2}]"
        )
    lines.append(
        "[坐标] 模型自报目标框（送检坐标→原图坐标；模型自报，未经验证）：" + "；".join(rendered)
    )
    return lines


def _degrade_lines(vision_error: str) -> list[str]:
    """识别降级说明 + 可操作指引（如实，不伪装成功）."""
    lines = [
        f"[识别降级] 视觉后端不可用/失败（{vision_error}）——仅返回元信息与坐标契约。"
    ]
    normalized = vision_error.lower().replace("_", " ")
    if "not logged in" in normalized or "api key" in normalized:
        lines.append("[指引] 请运行 `arkcli auth login volc-sso` 或 `arkcli auth apikey` 后重试。")
    else:
        lines.append("[指引] 可尝试配置视觉后端（WEB_VISION_BACKEND=arkcli/provider）后重试。")
    return lines


class ReadImageTool:
    name = "read_image"
    description = (
        "读取本地图片并转换为结构化文本证据（元信息 + 坐标契约 + 内容识别），供无视觉能力的模型推理。"
        "何时用: 用户发来截图/流程图/界面图/图片文件（本地路径），需要理解图片内容时。"
        "何时不用: 无图片路径时；纯文本任务。"
        "输出: ① 元信息（格式/尺寸/色彩模式，标准库解析）② 坐标契约（原图尺寸/裁剪区域/送检尺寸/"
        "缩放系数/换算式，确定性事实）③ 内容识别文本（视觉后端，识别来源如实标注）"
        "④ 模型自报 bbox 的结构化坐标块（已换算回原图坐标，标注为模型自报未经验证）。"
        "crop: 可选，按**原图像素坐标** {x,y,w,h} 先裁剪再识别（越界即 FAILURE）。"
        "失败对策: 文件不存在/不可读如实返回；视觉后端不可用/未认证如实降级为仅元信息与坐标契约并给出可操作指引。"
        "局限: 结构化图片（截图/流程图/界面）效果好；真实照片/复杂空间关系恢复受限；"
        "模型自报坐标未经像素级校验，只作定位线索。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "本地图片文件路径（png/jpg/jpeg/gif/webp/bmp）"},
            "prompt": {"type": "string", "description": "识别提示（可选，默认描述+转录图中文字）"},
            "crop": {
                "type": "object",
                "description": (
                    "可选裁剪区域，按**原图像素坐标** {x,y,w,h}（整数，w/h>0，区域须完全落在图内）；"
                    "裁剪后再送识别，回执的坐标契约与换算式随之更新"
                ),
                "properties": {
                    "x": {"type": "integer", "description": "左上角 x（原图像素）"},
                    "y": {"type": "integer", "description": "左上角 y（原图像素）"},
                    "w": {"type": "integer", "description": "宽度（原图像素）"},
                    "h": {"type": "integer", "description": "高度（原图像素）"},
                },
            },
        },
        "required": ["path"],
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "") or "").strip()
        prompt = str(kwargs.get("prompt", "") or "").strip() or _DEFAULT_PROMPT
        if not path:
            return _fail_result("[参数错误] 缺少必填参数 'path'（本地图片路径）")
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = Path(workspace_base()) / p
        if not p.exists() or not p.is_file():
            return _fail_result(
                f"[文件不存在] {p} 不存在或不是文件。请检查路径（可用 search_files 确认）。"
            )
        try:
            data = p.read_bytes()
        except OSError as exc:
            return ToolResult(
                status=ToolResultStatus.ERROR,
                content=f"[读取失败] {p}: {type(exc).__name__}: {exc}",
                tool_call_id="",
                tool_name=self.name,
            )
        if not data:
            return _fail_result(f"[空文件] {p} 为空，无法识别。")
        meta = _probe_meta(data[:_META_MAX_BYTES])
        orig_w = meta.get("width")
        orig_h = meta.get("height")
        crop, crop_error = _resolve_crop(kwargs.get("crop"), orig_w, orig_h)
        if crop_error:
            return _fail_result(crop_error)
        send_bytes, send_mime = data, _mime_for(path)
        if crop is not None:
            cropped = _crop_image_bytes(data, crop[0], crop[1], crop[2], crop[3])
            if cropped is None:
                return _fail_result("[裁剪失败] 本地裁剪不可用（缺 Pillow 或图片无法解码）。")
            send_bytes, send_mime = cropped, "image/png"
        vision_text, vision_error, geometry = _run_vision(send_bytes, send_mime, prompt)
        # 后端失败时 geometry 来自 vision 模块挂在异常上的**本地预处理事实**
        # （最后一次实际送检的尺寸）；此时仍需标注「非后端回报」（review P2-2）。
        estimated = geometry is None or vision_error is not None
        if geometry is not None:
            sent_w, sent_h = geometry.input_width, geometry.input_height
            scale_x, scale_y = geometry.scale_x, geometry.scale_y
        else:
            sent_w = crop[2] if crop else (orig_w or 0)
            sent_h = crop[3] if crop else (orig_h or 0)
            scale_x = scale_y = 1.0
        lines = _meta_lines(meta, orig_w, orig_h)
        contract = _format_contract(
            orig_w=orig_w,
            orig_h=orig_h,
            crop=crop,
            sent_w=sent_w,
            sent_h=sent_h,
            scale_x=scale_x,
            scale_y=scale_y,
        )
        if estimated:
            contract += "（送检尺寸取自本地预处理事实：视觉后端失败，未回报几何）"
        lines.append(contract)
        if vision_text and vision_text.strip():
            lines.extend(_vision_block(vision_text.strip(), crop, scale_x, scale_y))
        if vision_error:
            lines.extend(_degrade_lines(vision_error))
        status = (
            ToolResultStatus.SUCCESS
            if vision_text and vision_text.strip()
            else ToolResultStatus.FAILURE
        )
        return ToolResult(
            status=status,
            content="\n".join(lines),
            tool_call_id="",
            tool_name=self.name,
        )
