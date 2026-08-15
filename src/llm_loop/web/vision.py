"""图片识别模块（M39，借鉴 本地既有实现 vision.py 算法思路，引用非改写）.

httpx 直调 MiniMax OpenAI 兼容多模态端点（/v1/chat/completions + image_url data URI），
2026-08-15 修复：旧 Anthropic 兼容端点 /v1/messages 已被 MiniMax 下线（404）——
新端点 image 内容走 content parts（type=image_url）。无 key 如实降级（不伪装识别成功）；
失败如实反馈；独立于核心 LLM 主链路（不修改 LoopEngine/prompt）。
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
    """MiniMax OpenAI 兼容端点 base（/v1/chat/completions 由本模块拼接）."""
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
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                    {"type": "text", "text": prompt.strip() or VISION_DEFAULT_PROMPT},
                ],
            }
        ],
    }
    resp = httpx.post(
        f"{_vision_base_url()}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_vision_timeout(),
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"视觉识别响应结构异常（{type(exc).__name__}）") from exc
    if not text:
        raise RuntimeError("视觉识别返回空结果")
    return text.strip()
