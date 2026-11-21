"""图片识别模块（M39 + 2026-08-15 重构）.

设计定位（团队确认）：识别工具本身把图片/文档**转换为文字**，输出文本给
**无视觉能力的主模型**使用——本模块产出的 result_text 由调用方注入对话上下文。

后端策略（env WEB_VISION_BACKEND，默认 auto 自动链）:
- auto（默认）：MiniMax **Anthropic 兼容端点**（真实视觉，MINIMAX_API_KEY 已配置）
  → provider（注册表 multimodal 模型）→ 明确报错。识别来源在结果 detail 中如实标注。
  （2026-08-20 调整：arkcli 未认证且非本机默认工具，不再占 auto 链首位——需要时
  显式 WEB_VISION_BACKEND=arkcli。）
- arkcli：仅显式 opt-in（`WEB_VISION_BACKEND=arkcli`），失败即报错（含
  `arkcli auth login volc-sso` / `arkcli auth apikey` 指引）。
- provider：仅注册表视觉模型（OpenAI 兼容 chat/completions + image_url；WEB_VISION_MODEL
  显式 "provider/model" 优先，否则扫描注册表首个 multimodal 模型；api_key 走 api_key_env）。
- minimax（opt-in）：MiniMax **Anthropic 兼容端点**（/anthropic/v1/messages +
  image base64 block，2026-08-20 修正：旧 OpenAI 兼容端点实测无真实视觉；
  Anthropic 端点经 SYAGI 实测真实可用，失败如实报错不编造）。

独立于核心 LLM 主链路（不修改 LoopEngine/prompt）；失败如实反馈。
"""

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

import httpx

VISION_DEFAULT_PROMPT = "请详细描述这张图片的内容，尽量转录图中文字。若无法识别图片，请如实说明。"

# 2026-08-20（借鉴 SYAGI P1 修复）: 飞书图片消息不带扩展名, 此前 mime 恒 image/png,
# jpg/gif/webp 错报致部分识别失败。按文件头 magic bytes 嗅探; 嗅探失败按 png 兜底。
def _sniff_mime(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes[:2] == b"BM":
        return "image/bmp"
    return "image/png"

_AUTH_HINT = (
    "请先运行 `arkcli auth login volc-sso` 刷新登录，或 `arkcli auth apikey` 选择 API Key"
    "（数据面调用需 ARK API Key）；当前账户无法完成图片识别。"
)


def _vision_backend() -> str:
    """识别后端：auto（默认，MiniMax 优先 + provider 兜底）/ arkcli / provider / minimax."""
    return os.environ.get("WEB_VISION_BACKEND", "auto").strip().lower() or "auto"


def _vision_timeout() -> float:
    try:
        return max(10.0, float(os.environ.get("WEB_VISION_TIMEOUT", "60")))
    except ValueError:
        return 60.0


def _vision_model() -> str:
    return os.environ.get("WEB_VISION_MODEL", "").strip()


def _registry(settings: Any) -> Any:
    """provider 注册表（懒加载；settings 缺省走全局配置）."""
    from llm_loop.config import load_settings
    from llm_loop.llm.providers import load_registry

    if settings is None:
        settings = load_settings()
    return load_registry(settings)


def vision_enabled(settings: Any = None) -> bool:
    """图片识别是否可用（按后端判定；provider 后端：注册表存在可用视觉模型）."""
    backend = _vision_backend()
    if backend == "minimax":
        return bool(os.environ.get("MINIMAX_API_KEY", "").strip())
    if backend == "arkcli":
        return shutil.which("arkcli") is not None
    # provider 后端
    try:
        reg = _registry(settings)
    except Exception:  # noqa: BLE001 — 注册表不可读按不可用
        return False
    has_provider = _pick_provider_model(reg, os.environ.get("WEB_VISION_MODEL", "")) is not None
    if backend == "provider":
        return has_provider
    # auto：MiniMax（Anthropic 端点真实可用）或注册表视觉模型任一可用即可
    return has_provider or bool(os.environ.get("MINIMAX_API_KEY", "").strip())


def _pick_provider_model(reg: Any, explicit: str) -> tuple[str, str] | None:
    """选择视觉模型：显式 "provider/model" 优先；否则扫描注册表首个 multimodal 模型.

    Returns:
        (provider_id, model_id)；无可用 → None（api_key_env 缺失的候选跳过——与
        pool.fallback_candidates 同语义：无 key 的 provider 不可用）。
    """
    if explicit and "/" in explicit:
        pid, mid = explicit.split("/", 1)
        spec = reg.providers.get(pid)
        if spec is not None and mid in spec.models and spec.models[mid].multimodal:
            if spec.api_key_env and not os.environ.get(spec.api_key_env, "").strip():
                return None  # 显式指定但缺 key → 不可用
            return (pid, mid)
        return None
    for pid, spec in reg.providers.items():
        if spec.api_key_env and not os.environ.get(spec.api_key_env, "").strip():
            continue  # 缺 key 的 provider 跳过（不尝试）
        for mid, mspec in spec.models.items():
            if getattr(mspec, "multimodal", False):
                return (pid, mid)
    return None


def _describe_provider(image_bytes: bytes, mime: str, prompt: str, settings: Any) -> str:
    """注册表视觉模型（OpenAI 兼容 chat/completions + image_url data URI）."""
    reg = _registry(settings)
    pick = _pick_provider_model(reg, _vision_model())
    if pick is None:
        hint = _vision_model() or "注册表无 multimodal 模型"
        raise RuntimeError(
            f"未找到可用视觉模型（{hint}）——请确认 provider 注册表中存在 multimodal=True 的模型"
            "（如 kimi k3），或在 WEB_VISION_MODEL 指定 provider/model。"
        )
    pid, mid = pick
    spec = reg.providers[pid]
    api_key = os.environ.get(spec.api_key_env, "").strip() if spec.api_key_env else ""
    if not api_key:
        raise RuntimeError(f"视觉模型 {pid}/{mid} 的 api_key（{spec.api_key_env}）未配置。")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload = {
        "model": mid,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt.strip() or VISION_DEFAULT_PROMPT},
                ],
            }
        ],
    }
    url = f"{spec.base_url.rstrip('/')}/chat/completions"
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_vision_timeout(),
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"视觉模型 {pid}/{mid} 请求失败（{type(exc).__name__}）") from exc
    if resp.status_code >= 400:
        body = resp.text[:300]
        raise RuntimeError(
            f"视觉模型 {pid}/{mid} 返回 HTTP {resp.status_code}（{body}）——"
            "若模型不支持图片输入，请在注册表改选 multimodal 模型或设 WEB_VISION_MODEL。"
        )
    data = resp.json()
    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"视觉模型 {pid}/{mid} 响应结构异常（{type(exc).__name__}）") from exc
    if not text:
        raise RuntimeError("视觉识别返回空结果")
    return text


def _describe_arkcli(image_bytes: bytes, mime: str, prompt: str) -> str:
    """arkcli +understand image-caption（豆包视觉）：扁平 schema {content, ...}."""
    ext = {  # mime → 文件扩展名（arkcli 按扩展名推断模态）
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(mime, ".png")
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        tmp.write(image_bytes)
    try:
        cmd = [
            "arkcli",
            "+understand",
            "image-caption",
            "--input",
            f"@{tmp_path}",
            prompt.strip() or VISION_DEFAULT_PROMPT,
            "--no-progress",
            "--format",
            "json",
        ]
        model = _vision_model()
        if model and "/" in model:
            cmd += ["--model", model.split("/", 1)[1]]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_vision_timeout(),
            check=False,
        )
        for out in (proc.stdout, proc.stderr):
            if not out.strip():
                continue
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("content"):
                return str(data["content"]).strip()
            if isinstance(data, dict) and data.get("ok") is False:
                msg = str(data.get("error", {}).get("message", ""))
                raise RuntimeError(f"arkcli 调用失败: {msg}")
        if proc.returncode != 0:
            raise RuntimeError(f"arkcli 非零退出（{proc.returncode}）: {(proc.stderr or '')[:300]}")
        raise RuntimeError("arkcli 未返回可解析结果")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"arkcli 图片识别超时（{_vision_timeout():.0f}s）") from exc
    finally:
        import contextlib

        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def _describe_minimax(image_bytes: bytes, mime: str, prompt: str) -> str:
    """MiniMax Anthropic 兼容端点（2026-08-20 修正，借鉴 SYAGI 可用视觉实现）.

    旧实现走 OpenAI 兼容端点（/v1/chat/completions + image_url），实测 M3/M2.x 均无
    真实视觉（M2.x 返回凭空猜测属伪成功幻觉）。MiniMax 的真实多模态视觉走 Anthropic
    兼容端点（/anthropic/v1/messages + image base64 block），SYAGI 实测可用。
    失败如实抛错（HTTP/API 错误/空结果），不编造描述。
    """
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY 未配置，无法使用视觉识别")
    if not image_bytes:
        raise RuntimeError("图片内容为空")
    model = _vision_model() or "MiniMax-M3"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    base_url = os.environ.get(
        "MINIMAX_ANTHROPIC_BASE_URL", "https://api.minimax.chat/anthropic"
    ).rstrip("/")
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
        f"{base_url}/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=_vision_timeout(),
    )
    if resp.status_code != 200:
        raise RuntimeError(f"vision API HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("type") == "error" or data.get("error"):
        raise RuntimeError(f"vision API error: {str(data.get('error'))[:300]}")
    texts = [
        block.get("text", "")
        for block in (data.get("content") or [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    result = "\n".join(t for t in texts if t).strip()
    if not result:
        raise RuntimeError("vision API 返回空描述 (模型可能不支持图片输入)")
    return result


# ── 大图本地降采样与坐标几何（EVO-20261121-efa320ab）────────────────────────
# 实测依据（2026-11-21 本机）：3000×200 / 2400×200 / 3120×1990 三张图内容识别全部降级
# （仅返回元信息），1560 宽及以下可成功——大图失败率显著更高。故按长边阈值在**本地**
# 降采样后再送检，并把「送检尺寸 / 缩放系数」作为结构化事实回报给调用方（坐标换算依据）。
VISION_MAX_SIDE_ENV = "WEB_VISION_MAX_SIDE"
DEFAULT_VISION_MAX_SIDE = 1568
_FALLBACK_MIN_SIDE = 32


def vision_max_side() -> int:
    """大图本地降采样阈值（长边像素上限）；<=0 表示关闭降采样与兜底重试.

    环境变量 ``WEB_VISION_MAX_SIDE``：留空取默认 1568；0=禁用（行为与本演进前一致）。
    """
    raw = os.environ.get(VISION_MAX_SIDE_ENV, "").strip()
    if not raw:
        return DEFAULT_VISION_MAX_SIDE
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_VISION_MAX_SIDE


@dataclass(frozen=True)
class VisionGeometry:
    """送检几何：source=送检前尺寸，input=实际送检尺寸（降采样后）."""

    source_width: int
    source_height: int
    input_width: int
    input_height: int
    max_side: int
    downsampled: bool

    @property
    def scale_x(self) -> float:
        """送检坐标 → 送检前坐标 的比例因子（input/source）."""
        if not self.source_width:
            return 1.0
        return self.input_width / self.source_width

    @property
    def scale_y(self) -> float:
        if not self.source_height:
            return 1.0
        return self.input_height / self.source_height


@dataclass(frozen=True)
class VisionResult:
    """识别结果 + 几何事实（坐标换算的唯一依据）."""

    text: str
    geometry: VisionGeometry
    backend: str = ""
    fallback_used: bool = False
    error: str | None = None


@dataclass(frozen=True)
class PreparedImage:
    """本地预处理后的待送检图片（降采样后）."""

    data: bytes
    width: int
    height: int
    mime: str


def image_size(image_bytes: bytes) -> tuple[int, int] | None:
    """图片像素尺寸（Pillow）；无法解析时返回 None（不伪报尺寸）."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow 缺失时如实降级
        return None
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001 - 解码失败如实降级
        return None


def prepare_image(image_bytes: bytes, mime: str, max_side: int) -> PreparedImage:
    """按长边阈值本地降采样（只缩小、不放大、不改原文件）.

    超出阈值才重编码（JPEG 保持 JPEG，其余转 PNG）；降采样失败如实退回原图。
    """
    size = image_size(image_bytes)
    fallback_mime = mime or _sniff_mime(image_bytes)
    if size is None or max_side <= 0 or max(size) <= max_side:
        width, height = size or (0, 0)
        return PreparedImage(image_bytes, width, height, fallback_mime)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 - Pillow 缺失时如实退回原图
        return PreparedImage(image_bytes, size[0], size[1], fallback_mime)
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            im.load()
            ratio = max_side / float(max(size))
            new_w = max(1, int(round(size[0] * ratio)))
            new_h = max(1, int(round(size[1] * ratio)))
            resized = im.resize((new_w, new_h))
            buf = io.BytesIO()
            if (im.format or "").upper() == "JPEG":
                resized.convert("RGB").save(buf, format="JPEG", quality=90)
                out_mime = "image/jpeg"
            else:
                resized.save(buf, format="PNG")
                out_mime = "image/png"
            return PreparedImage(buf.getvalue(), new_w, new_h, out_mime)
    except Exception:  # noqa: BLE001 - 降采样失败如实退回原图
        return PreparedImage(image_bytes, size[0], size[1], fallback_mime)


def _geometry_prompt(prompt: str, geometry: VisionGeometry) -> str:
    """给视觉模型的坐标契约（送检像素尺寸 + 原点约定 + bbox 格式）.

    模型自报坐标必须落在**送检尺寸**内；调用方据此换算回原图坐标。
    """
    base = (prompt or "").strip() or VISION_DEFAULT_PROMPT
    return (
        f"{base}\n\n"
        "（坐标契约）本图送检像素尺寸 = "
        f"{geometry.input_width}×{geometry.input_height}"
        f"（送检前尺寸 = {geometry.source_width}×{geometry.source_height}；"
        "左上角为原点，x 向右、y 向下）。"
        "若给出目标元素边界框，请用 [x1,y1,x2,y2] 像素坐标表示（基于送检尺寸），"
        "数值须落在送检尺寸范围内。"
    )


def _dispatch_vision(image_bytes: bytes, mime: str, prompt: str, settings: Any) -> str:
    """按后端策略调用识别能力（auto/minimax/arkcli/provider），失败如实抛错."""
    backend = _vision_backend()
    if backend == "minimax":
        return _describe_minimax(image_bytes, mime, prompt)
    if backend == "arkcli":
        return _describe_arkcli_with_hint(image_bytes, mime, prompt)
    if backend == "provider":
        return _describe_provider(image_bytes, mime, prompt, settings)
    # auto（2026-08-20 调整）：MiniMax Anthropic 端点（真实可用，key 已配置）优先
    # → 注册表视觉模型 → 明确报错。arkcli 未认证/非默认工具, 不再占链首（显式 opt-in）。
    try:
        return _describe_minimax(image_bytes, mime, prompt)
    except RuntimeError as mm_exc:
        try:
            return _describe_provider(image_bytes, mime, prompt, settings)
        except RuntimeError as prov_exc:
            raise RuntimeError(
                f"MiniMax 失败（{mm_exc}）且注册表视觉模型亦失败（{prov_exc}）。{_AUTH_HINT}"
            ) from prov_exc


def describe_image_detailed(
    image_bytes: bytes, mime: str = "", prompt: str = "", settings: Any = None
) -> VisionResult:
    """识别图片并回报几何事实（原图尺寸/送检尺寸/缩放系数/是否兜底重试）.

    大图（长边 > WEB_VISION_MAX_SIDE）先在**本地**降采样再送检；识别失败时按
    「再降采样一半」兜底重试一次；两次都失败则如实抛错（不伪装成功）。
    """
    if not image_bytes:
        raise RuntimeError("图片内容为空")
    if not mime:
        mime = _sniff_mime(image_bytes)
    max_side = vision_max_side()
    source = image_size(image_bytes)
    prepared = prepare_image(image_bytes, mime, max_side)
    fallback_used = False
    try:
        geometry = VisionGeometry(
            source_width=source[0] if source else prepared.width,
            source_height=source[1] if source else prepared.height,
            input_width=prepared.width,
            input_height=prepared.height,
            max_side=max_side,
            downsampled=bool(source) and (prepared.width, prepared.height) != source,
        )
        text = _dispatch_vision(
            prepared.data, prepared.mime, _geometry_prompt(prompt, geometry), settings
        )
    except RuntimeError:
        if max_side <= 0 or source is None:
            raise
        retry = prepare_image(
            prepared.data, prepared.mime, max(_FALLBACK_MIN_SIDE, max_side // 2)
        )
        if (retry.width, retry.height) == (prepared.width, prepared.height):
            raise
        retry_geometry = VisionGeometry(
            source_width=source[0],
            source_height=source[1],
            input_width=retry.width,
            input_height=retry.height,
            max_side=max_side,
            downsampled=True,
        )
        text = _dispatch_vision(
            retry.data, retry.mime, _geometry_prompt(prompt, retry_geometry), settings
        )
        prepared = retry
        geometry = retry_geometry
        fallback_used = True
    return VisionResult(
        text=(text or "").strip(),
        geometry=geometry,
        backend=_vision_backend(),
        fallback_used=fallback_used,
    )


def describe_image(image_bytes: bytes, mime: str = "", prompt: str = "", settings: Any = None) -> str:
    """调用图片识别能力描述图片，返回描述文本（非空）.

    识别结果即**文本**（供无视觉能力的主模型使用），调用方注入对话上下文。
    几何事实（送检尺寸/缩放系数）经 :func:`describe_image_detailed` 暴露。

    Args:
        settings: 引擎设置（provider 后端注册表来源）；None = 全局配置。

    Raises:
        RuntimeError: 工具不可用 / 调用失败 / 空结果（含可操作指引）.
    """
    return describe_image_detailed(image_bytes, mime=mime, prompt=prompt, settings=settings).text


def _describe_arkcli_with_hint(image_bytes: bytes, mime: str, prompt: str) -> str:
    """arkcli 后端（含未安装/未认证的可操作指引）."""
    if shutil.which("arkcli") is None:
        raise RuntimeError(f"arkcli 未安装（PATH 中找不到），无法调用图片识别工具。{_AUTH_HINT}")
    try:
        text = _describe_arkcli(image_bytes, mime, prompt)
    except RuntimeError as exc:
        msg = str(exc)
        if any(k in msg for k in ("not logged in", "API Key is required", "AccessDenied", "SSO")):
            raise RuntimeError(f"{msg}。{_AUTH_HINT}") from exc
        raise
    if not text.strip():
        raise RuntimeError("图片识别返回空结果")
    return text
