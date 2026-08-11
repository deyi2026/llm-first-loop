"""系统交互封装（EVO-20260810-86e777d1 演进: 通知型 → 授权确认型）.

- 通知型 notify(): osascript display notification（无交互，仅提醒）
- 授权型 confirm(): osascript display dialog（带按钮，返回用户选择 确认/拒绝）
- 失败 fail-open（返回 False，调用方降级，不阻断循环）
- 零依赖（osascript 系统自带）
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)


def _osascript_available() -> bool:
    return shutil.which("osascript") is not None


def notify(title: str, message: str) -> bool:
    """弹 macOS 系统通知（无交互，仅提醒）；不可用/失败 → False."""
    if not _osascript_available():
        return False
    try:
        safe_title = str(title).replace('"', '\\"')
        safe_msg = str(message).replace('"', '\\"')
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{safe_msg}" with title "{safe_title}"'],
            capture_output=True, text=True, timeout=5,
        )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("系统通知失败（fail-open）", exc_info=True)
        return False


def confirm(
    title: str,
    message: str,
    *,
    confirm_label: str = "确认",
    cancel_label: str = "拒绝",
    timeout_s: float = 120.0,
) -> bool:
    """授权确认弹窗（display dialog 带按钮，阻塞等待用户选择）.

    Returns:
        True = 用户点确认；False = 拒绝 / osascript 不可用 / 超时 / 异常。
    """
    if not _osascript_available():
        logger.debug("osascript 不可用，授权弹窗降级为拒绝")
        return False
    try:
        safe_title = str(title).replace('"', '\\"')
        safe_msg = str(message).replace('"', '\\"')
        safe_ok = str(confirm_label).replace('"', '\\"')
        safe_cancel = str(cancel_label).replace('"', '\\"')
        script = (
            f'display dialog "{safe_msg}" buttons {{"{safe_cancel}", "{safe_ok}"}} '
            f'default button "{safe_ok}" with title "{safe_title}"'
        )
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout_s,
        )
        # 用户点确认 → stdout 含 "button returned:确认"；点拒绝 → 退出码非0
        return "button returned:" in proc.stdout and safe_ok in proc.stdout
    except Exception:  # noqa: BLE001 — 授权失败降级为拒绝（安全默认）
        logger.warning("授权弹窗失败（fail-open → 拒绝）", exc_info=True)
        return False
