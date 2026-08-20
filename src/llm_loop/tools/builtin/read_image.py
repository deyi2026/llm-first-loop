"""基础工具: read_image 图像转结构化文本证据（EVO-20260820-5d0a7b99，借鉴 DSH rc.8 工具层视觉）.

设计定位: 主模型无图像输入能力时，把用户发来的截图/流程图/界面图拆成结构化文本证据——
元信息提取（尺寸/色彩模式/格式，标准库解析文件头，零依赖）+ 内容识别（复用 web/vision
describe_image 后端链: arkcli 团队识别工具优先 → 注册表 multimodal 模型兜底）→ 交模型推理。
局限如实标注: PPT 截图/流程图/界面截图等结构化图片效果好；真实照片/复杂空间关系恢复受限。
依赖缺失/识别失败 → 如实降级（仅返回元信息）或明确报错，不伪装成功。
"""

from __future__ import annotations

import struct
from pathlib import Path

from llm_loop.core.message import ToolResult, ToolResultStatus

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


class ReadImageTool:
    name = "read_image"
    description = (
        "读取本地图片并转换为结构化文本证据（元信息 + 内容识别），供无视觉能力的模型推理。"
        "何时用: 用户发来截图/流程图/界面图/图片文件（本地路径），需要理解图片内容时。"
        "何时不用: 无图片路径时；纯文本任务。"
        "输出: ① 元信息（格式/尺寸/色彩模式，标准库解析）② 内容识别文本（arkcli 团队识别工具优先，"
        "注册表视觉模型兜底；识别来源如实标注）。"
        "失败对策: 文件不存在/不可读如实返回；视觉后端不可用/未认证如实降级为仅元信息并给出可操作指引。"
        "局限: 结构化图片（截图/流程图/界面）效果好；真实照片/复杂空间关系恢复受限。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "本地图片文件路径（png/jpg/jpeg/gif/webp/bmp）"},
            "prompt": {"type": "string", "description": "识别提示（可选，默认描述+转录图中文字）"},
        },
        "required": ["path"],
    }

    def execute(self, **kwargs) -> ToolResult:
        path = str(kwargs.get("path", "") or "").strip()
        prompt = str(kwargs.get("prompt", "") or "").strip() or _DEFAULT_PROMPT
        if not path:
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content="[参数错误] 缺少必填参数 'path'（本地图片路径）",
                tool_call_id="",
                tool_name=self.name,
            )
        p = Path(path).expanduser()
        if not p.is_absolute():
            from llm_loop.core.run_context import workspace_base

            p = Path(workspace_base()) / p
        if not p.exists() or not p.is_file():
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[文件不存在] {p} 不存在或不是文件。请检查路径（可用 search_files 确认）。",
                tool_call_id="",
                tool_name=self.name,
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
            return ToolResult(
                status=ToolResultStatus.FAILURE,
                content=f"[空文件] {p} 为空，无法识别。",
                tool_call_id="",
                tool_name=self.name,
            )
        meta = _probe_meta(data[:_META_MAX_BYTES])
        meta_lines = [f"[元信息] 格式={meta.get('format')}"]
        if meta.get("width") is not None:
            line = f"[元信息] 尺寸={meta['width']}×{meta['height']}"
            if meta.get("color_mode"):
                line += f"  位深={meta.get('bit_depth')}  色彩模式={meta.get('color_mode')}"
            meta_lines.append(line)
        # 内容识别（复用 web/vision 后端链，fail-open 降级为仅元信息）
        vision_text: str | None = None
        vision_error: str | None = None
        try:
            from llm_loop.web.vision import describe_image

            vision_text = describe_image(data, mime=_mime_for(path), prompt=prompt)
        except Exception as exc:  # noqa: BLE001 — 识别失败如实降级（不伪装成功）
            vision_error = f"{type(exc).__name__}: {exc}"
        lines = list(meta_lines)
        if vision_text and vision_text.strip():
            lines.append("[内容识别]")
            lines.append(vision_text.strip())
        if vision_error:
            lines.append(f"[识别降级] 视觉后端不可用/失败（{vision_error}）——仅返回元信息。")
            if "not logged in" in vision_error.lower() or "API Key" in vision_error:
                lines.append("[指引] 请运行 `arkcli auth login volc-sso` 或 `arkcli auth apikey` 后重试。")
            else:
                lines.append("[指引] 可尝试配置视觉后端（WEB_VISION_BACKEND=arkcli/provider）后重试。")
        content = "\n".join(lines)
        status = (
            ToolResultStatus.SUCCESS
            if vision_text and vision_text.strip()
            else ToolResultStatus.FAILURE
        )
        return ToolResult(
            status=status,
            content=content,
            tool_call_id="",
            tool_name=self.name,
        )
