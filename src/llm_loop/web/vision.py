"""图片识别模块（M39 + 2026-08-15 重构：走自家 provider 注册表，视觉模型可配）.

后端策略（env WEB_VISION_BACKEND）:
- provider（默认）：从 provider 注册表（data/providers.json）选择**支持多模态的模型**
  （ModelSpec.multimodal=True，如 Kimi k3/k3-256k——2026-08-15 实测 kimi 视觉可用，
  正确识别纯色图；MiniMax M3/M2.x 实测均无真实视觉，M2.x 返回凭空猜测属伪成功幻觉，
  故不作为默认）。调用方式为 OpenAI 兼容 chat/completions + image_url data URI。
  模型选择：WEB_VISION_MODEL 显式 "provider/model" → 优先；否则扫描注册表首个
  multimodal 模型。api_key 从注册表 api_key_env 对应环境变量读取（与 LLM 主链路一致）。
- arkcli（团队自研多模态工具）：`arkcli +understand image-caption`（豆包视觉）。
  数据面鉴权失败时如实报错并给修复指引（`arkcli auth login volc-sso` / `arkcli auth apikey`）。
- minimax（旧路径 opt-in）：httpx 直调 MiniMax 端点（仅显式开启；见上实测结论）。

独立于核心 LLM 主链路（不修改 LoopEngine/prompt）；失败如实反馈。
"""

import base64
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

import httpx

VISION_DEFAULT_PROMPT = "请详细描述这张图片的内容，尽量转录图中文字。若无法识别图片，请如实说明。"

_AUTH_HINT = (
    "请先运行 `arkcli auth login volc-sso` 刷新登录，或 `arkcli auth apikey` 选择 API Key"
    "（数据面调用需 ARK API Key）；当前账户无法完成图片识别。"
)


def _vision_backend() -> str:
    """识别后端：provider（默认，注册表 multimodal 模型）/ arkcli / minimax."""
    return os.environ.get("WEB_VISION_BACKEND", "provider").strip().lower() or "provider"


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
    return _pick_provider_model(reg, os.environ.get("WEB_VISION_MODEL", "")) is not None


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
    """旧路径：MiniMax OpenAI 兼容端点（仅显式 opt-in；见模块 docstring 实测结论）."""
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY 未配置，无法使用视觉识别")
    model = _vision_model() or "MiniMax-M3"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    base_url = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.chat").rstrip("/")
    payload = {
        "model": model,
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
    resp = httpx.post(
        f"{base_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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


def describe_image(image_bytes: bytes, mime: str = "image/png", prompt: str = "", settings: Any = None) -> str:
    """调用图片识别能力描述图片，返回描述文本（非空）.

    Args:
        settings: 引擎设置（provider 后端注册表来源）；None = 全局配置。

    Raises:
        RuntimeError: 工具不可用 / 调用失败 / 空结果（含可操作指引）.
    """
    if not image_bytes:
        raise RuntimeError("图片内容为空")
    backend = _vision_backend()
    if backend == "minimax":
        return _describe_minimax(image_bytes, mime, prompt)
    if backend == "arkcli":
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
    # provider 后端（默认）
    return _describe_provider(image_bytes, mime, prompt, settings)
