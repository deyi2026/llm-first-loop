"""L2 window capture: screencapture argv subprocess + honesty guards (M3).

Hard rules implemented here (M3 contract rule 1/3):

- ``CGPreflightScreenCaptureAccess()`` is checked FIRST.  When ungranted the
  subprocess is never spawned — ungranted ``screencapture`` exits 0 with a
  black/wallpaper image (D0 §5.4), so the only honest move is to refuse with
  ``capture_unavailable`` before touching the executable.
- Geometry is dual-unit: bounds are points, the PNG is pixels; the receipt
  carries ``scale`` and the |px - pt*scale| <= 2px assertion (U19).  A
  violation degrades the receipt (``capture_size_mismatch``), never fails it.
- Only argv-list subprocess calls (no shell), timeout 10s → capture_timeout.
"""

from __future__ import annotations

import hashlib
import struct
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from llm_loop.desktop import macos_permissions
from llm_loop.desktop.models import (
    CAPTURE_SIZE_TOLERANCE_PX,
    BoundsPt,
    CaptureOutcome,
    DesktopErrorCode,
    ImageInfo,
    WindowInfo,
)

CAPTURE_TIMEOUT_S = 10.0
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    """读 PNG IHDR 宽高（纯函数；非 PNG → None；不引入 Pillow）。"""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def check_capture_size(
    width: int,
    height: int,
    bounds: BoundsPt,
    scale: float,
    tolerance: float = CAPTURE_SIZE_TOLERANCE_PX,
) -> list[str]:
    """U19 断言：|width - w*scale| 与 |height - h*scale| ≤ 2px；超差记 degraded。"""
    if scale <= 0:
        return ["capture_size_mismatch"]
    mismatches: list[str] = []
    if abs(width - bounds.w * scale) > tolerance or abs(height - bounds.h * scale) > tolerance:
        mismatches.append("capture_size_mismatch")
    return mismatches


def capture_window(
    window: WindowInfo,
    out_dir: Path,
    scale_hint: float | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] | None = None,
    preflight: Callable[[], bool] | None = None,
) -> CaptureOutcome:
    """窗口级截图（-x 无声 -o 无阴影 -l 窗口 id）。前置预检不过不调可执行文件。"""
    preflight_fn = preflight or macos_permissions.screen_capture_granted
    if not preflight_fn():
        return CaptureOutcome(
            image=None,
            error=DesktopErrorCode.CAPTURE_UNAVAILABLE,
            detail="屏幕录制授权未授予；已拒绝调用 screencapture（无授权会静默产出黑图/壁纸）",
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%f")
    path = out_dir / f"win-{window.window_id}-{stamp}.png"
    run = runner or subprocess.run
    try:
        proc = run(
            ["screencapture", "-x", "-o", "-l", str(window.window_id), str(path)],
            capture_output=True,
            timeout=CAPTURE_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        path.unlink(missing_ok=True)  # 不留半截/黑图文件冒充证据
        return CaptureOutcome(
            image=None,
            error=DesktopErrorCode.CAPTURE_TIMEOUT,
            detail=f"screencapture 超过 {CAPTURE_TIMEOUT_S:.0f}s 未返回",
        )
    if proc.returncode != 0:
        path.unlink(missing_ok=True)  # 同上：失败产物必须清出 artifact 目录
        stderr = (proc.stderr or b"").decode("utf-8", "replace")[-160:]
        return CaptureOutcome(
            image=None,
            error=DesktopErrorCode.CAPTURE_UNAVAILABLE,
            detail=f"screencapture rc={proc.returncode}: {stderr}".strip(),
        )
    data = path.read_bytes()
    dims = png_dimensions(data)
    if dims is None:
        path.unlink(missing_ok=True)
        return CaptureOutcome(
            image=None,
            error=DesktopErrorCode.CAPTURE_UNAVAILABLE,
            detail="screencapture 产物不是有效 PNG（可能为黑图/空文件）",
        )
    width, height = dims
    scale = float(scale_hint if scale_hint and scale_hint > 0 else 1.0)
    degraded = tuple(check_capture_size(width, height, window.bounds_pt, scale))
    digest = hashlib.sha256(data).hexdigest()
    image = ImageInfo(
        ref=f"vision://desktop/v0.1/{digest}",
        path=str(path),
        sha256=digest,
        width=width,
        height=height,
        scale=scale,
        bounds_pt=window.bounds_pt,
        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
        bytes=len(data),
    )
    return CaptureOutcome(image=image, error=None, degraded=degraded)

