"""图片识别模块（M39，借鉴 本地既有实现 vision.py 算法思路，引用非改写）.

httpx 直调 MiniMax 多模态端点（Anthropic 兼容 /v1/messages），base64 image block。
无 key 如实降级（不伪装识别成功）；失败如实反馈；独立于核心 LLM 主链路（不修改 LoopEngine/prompt）。
"""

import base64
import os

import httpx

VISION_DEFAULT_PROMPT = "请详细描述这张图片的内容，尽量转录图中文字。若无法识别图片，请如实说明。"


def vision_enabled() -> bool:
    """图片识别是否可用（MINIMAX_API_KEY 已配置）."""
    return bool(os.environ.get("MINIMAX_API_KEY", "").strip())


def _vision_timeout() -> float:
    try:
        return max(10.0, float(os.environ.get("WEB_VISION_TIMEOUT", "60")))
    except ValueError:
        return 60.0


def _vision_base_url() -> str:
    """MiniMax 多模态端点（base 部分，/v1/messages 由本模块拼接）."""
    return os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.chat").rstrip("/")


def _vision_model() -> str:
    return os.environ.get("WEB_VISION_MODEL", "MiniMax-M3").strip() or "MiniMax-M3"


def describe_image(image_bytes: bytes, mime: str = "image/png", prompt: str = "") -> str:
    """调用 LLM 视觉能力描述图片，返回描述文本.

    Args:
        image_bytes: 图片二进制内容.
        mime: 图片 MIME 类型.
        prompt: 自定义提示词，空则用默认（描述+转录）.

    Returns:
        图片描述文本（非空）.

    Raises:
        RuntimeError: key 未配置 / HTTP 错误 / API 返回错误 / 空结果.
        httpx.RequestError: 网络错误（调用方如实降级）.
    """
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY 未配置，无法使用视觉识别")
    if not image_bytes:
        raise RuntimeError("图片内容为空")

    model = _vision_model()
    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": model,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    },
                    {"type": "text", "text": prompt.strip() or VISION_DEFAULT_PROMPT},
                ],
            }
        ],
    }
    resp = httpx.post(
        f"{_vision_base_url()}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_vision_timeout(),
    )
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
    if not text.strip():
        raise RuntimeError("视觉识别返回空结果")
    return text.strip()
