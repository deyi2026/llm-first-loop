"""CDP 端点可达性探针（EVO-20261121-efa320ab）。

为什么需要（本机实测，2026-11-21）：Chrome 已登录但未开远程调试端口时，
"CDP 端点存在吗"这一事实**没有任何工具能回答**——只能盲写坐标脚本反复试错。
本模块提供**只读**探针：发现候选端点 → 探测可达性 → 如实回报元信息。

边界（刻意收紧，不得放宽）：
- 只探 loopback（127.0.0.1 / localhost / ::1）；非 loopback 目标直接拒绝。
- 只取 /json/version 与 /json/list 的**元信息**（浏览器版本、协议版本、目标计数）；
  **不回传**页面标题/URL 等页面内容。
- 不改任何配置、不启动浏览器、不放宽既有 browser 工具的显式 opt-in 门禁。
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_PROBE_PORTS: tuple[int, ...] = (9222, 9223, 9229)
DEFAULT_TIMEOUT_S = 2.0
ACTIVE_PORT_FILENAME = "DevToolsActivePort"

# Linux 常见 Chrome/Chromium/Edge 用户数据目录（DevToolsActivePort 落盘位置）
LINUX_PROFILE_DIRS: tuple[str, ...] = (
    "~/.config/google-chrome",
    "~/.config/google-chrome-beta",
    "~/.config/google-chrome-unstable",
    "~/.config/chromium",
    "~/.config/chromium-browser",
    "~/.config/microsoft-edge",
    "~/.config/brave",
)


def _normalize_base(url: str) -> str:
    """规范化 base url（补 scheme、去尾斜杠）."""
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    return text


def _is_loopback(url: str) -> bool:
    """目标是否为 loopback（探针只允许本机端点）."""
    host = (urlparse(url).hostname or "").strip()
    if not host:
        return False
    if host.lower() in {"localhost", "ip6-localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_devtools_active_port(user_data_dir: str | Path) -> str | None:
    """读 DevToolsActivePort（Chrome 开远程调试端口时的落盘事实）→ base url.

    文件首行是端口、次行是浏览器 ws 路径；只取端口构造 loopback base url。
    """
    try:
        candidate = Path(user_data_dir).expanduser() / ACTIVE_PORT_FILENAME
        if not candidate.is_file():
            return None
        first_line = candidate.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
        if not first_line:
            return None
        port_text = first_line[0].strip()
        if not port_text.isdigit():
            return None
        port = int(port_text)
        if not 0 < port < 65536:
            return None
        return f"http://127.0.0.1:{port}"
    except OSError:
        return None


def discover_cdp_candidates(
    *,
    env_url: str | None = None,
    ports: tuple[int, ...] | list[int] | None = None,
    user_data_dirs: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """候选 CDP base url 列表（去重、保序）.

    来源：① 已配置的 LFL_BROWSER_PERCEPTION_CDP_URL ② 常见调试端口
    ③ Chrome 用户数据目录下的 DevToolsActivePort。
    """
    out: list[str] = []

    def _add(candidate: str) -> None:
        base = _normalize_base(candidate)
        if base and base not in out:
            out.append(base)

    configured = env_url if env_url is not None else os.environ.get(
        "LFL_BROWSER_PERCEPTION_CDP_URL", ""
    )
    _add(configured)
    for port in ports if ports is not None else DEFAULT_PROBE_PORTS:
        try:
            _add(f"http://127.0.0.1:{int(port)}")
        except (TypeError, ValueError):
            continue
    dirs = list(user_data_dirs) if user_data_dirs is not None else list(LINUX_PROFILE_DIRS)
    for directory in dirs:
        found = read_devtools_active_port(directory)
        if found:
            _add(found)
    return out


def probe_cdp_endpoint(base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """探测单个 CDP 端点（只读元信息）.

    Returns:
        dict: url / reachable / browser / protocol_version / target_count / error。
        不可达时 reachable=False 且 error 非空（**不伪报可达**）。
    """
    base = _normalize_base(base_url)
    report: dict[str, Any] = {
        "url": base,
        "reachable": False,
        "browser": None,
        "protocol_version": None,
        "target_count": None,
        "error": None,
    }
    if not base:
        report["error"] = "空端点"
        return report
    if not _is_loopback(base):
        report["error"] = "仅允许 loopback 端点（探针不探测非本机目标）"
        return report
    try:
        with httpx.Client(
            timeout=max(0.2, float(timeout_s)), trust_env=False, follow_redirects=False
        ) as client:
            response = client.get(f"{base}/json/version")
            if response.status_code >= 400:
                report["error"] = f"HTTP {response.status_code}"
                return report
            payload = response.json()
            if not isinstance(payload, dict):
                report["error"] = "/json/version 响应不是 JSON 对象"
                return report
            report["browser"] = str(payload.get("Browser") or "") or None
            report["protocol_version"] = str(payload.get("Protocol-Version") or "") or None
            try:
                targets = client.get(f"{base}/json/list")
                if targets.status_code < 400:
                    listed = targets.json()
                    report["target_count"] = len(listed) if isinstance(listed, list) else None
            except Exception:  # noqa: BLE001 - 目标计数失败不影响可达性判定
                report["target_count"] = None
            report["reachable"] = True
            return report
    except Exception as exc:  # noqa: BLE001 - 连接失败如实回报
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
