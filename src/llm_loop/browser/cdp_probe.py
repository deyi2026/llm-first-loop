"""CDP 端点可达性探针（EVO-20261121-efa320ab）。

为什么需要（本机实测，2026-11-21）：Chrome 已登录但未开远程调试端口时，
"CDP 端点存在吗"这一事实**没有任何工具能回答**——只能盲写坐标脚本反复试错。
本模块提供**只读**探针：发现候选端点 → 探测可达性 → 如实回报元信息。

边界（刻意收紧，不得放宽）：
- 只探 loopback（127.0.0.1 / localhost / ::1）；非 loopback 目标直接拒绝。
- 只取 /json/version 与 /json/list 的**元信息**（浏览器版本、协议版本、目标计数）；
  **不回传**页面标题/URL 等页面内容。
- 不改任何配置、不启动浏览器、不放宽既有 browser 工具的显式 opt-in 门禁。
- 额外输入有上界：额外端口/目录各至多 MAX_EXTRA_* 个，候选端点至多 MAX_CANDIDATES 个
  （review P2：无界输入会让总耗时随参数线性膨胀）。
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_PROBE_PORTS: tuple[int, ...] = (9222, 9223, 9229)
DEFAULT_TIMEOUT_S = 2.0
ACTIVE_PORT_FILENAME = "DevToolsActivePort"

# 上界（review P2-1/P2-2）：额外端口/目录各至多 MAX_EXTRA_* 个，
# 候选端点合计至多 MAX_CANDIDATES 个。
MAX_EXTRA_PORTS = 8
MAX_EXTRA_USER_DATA_DIRS = 8
MAX_CANDIDATES = 32

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


def merged_probe_ports(extra: Sequence[int] | None = None) -> list[int]:
    """缺省端口 + 额外端口（去重保序；额外项至多 MAX_EXTRA_PORTS 个）.

    契约：``extra`` 是**额外**端口，与缺省端口**合并**而不是替换——工具描述写的是
    「额外」，此前实现却是替换（review P2-1），此处以合并为准并由测试锁定。
    """
    merged: list[int] = list(DEFAULT_PROBE_PORTS)
    for port in list(extra or [])[:MAX_EXTRA_PORTS]:
        try:
            value = int(port)
        except (TypeError, ValueError):
            continue
        if value not in merged:
            merged.append(value)
    return merged


def merged_user_data_dirs(extra: Sequence[str] | None = None) -> list[str]:
    """缺省用户数据目录 + 额外目录（去重保序；额外项至多 MAX_EXTRA_USER_DATA_DIRS 个）."""
    merged: list[str] = list(LINUX_PROFILE_DIRS)
    for directory in list(extra or [])[:MAX_EXTRA_USER_DATA_DIRS]:
        text = str(directory).strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def discover_cdp_candidates(
    *,
    env_url: str | None = None,
    ports: tuple[int, ...] | list[int] | None = None,
    user_data_dirs: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """候选 CDP base url 列表（去重、保序、最多 MAX_CANDIDATES 个）.

    来源：① 已配置的 LFL_BROWSER_PERCEPTION_CDP_URL ② 常见调试端口（+ 额外端口）
    ③ Chrome 用户数据目录下的 DevToolsActivePort（+ 额外目录）。

    ``ports`` / ``user_data_dirs`` 语义是**额外**输入（与缺省合并，不是替换）。
    """
    out: list[str] = []

    def _add(candidate: str) -> None:
        base = _normalize_base(candidate)
        if not base or base in out:
            return
        if len(out) >= MAX_CANDIDATES:
            return
        out.append(base)

    configured = env_url if env_url is not None else os.environ.get(
        "LFL_BROWSER_PERCEPTION_CDP_URL", ""
    )
    _add(configured)
    for port in merged_probe_ports(ports):
        try:
            _add(f"http://127.0.0.1:{int(port)}")
        except (TypeError, ValueError):
            continue
    for directory in merged_user_data_dirs(user_data_dirs):
        found = read_devtools_active_port(directory)
        if found:
            _add(found)
    return out


def _bounded_timeout(request_timeout: float, deadline: float | None) -> float | None:
    """单次请求的超时预算：受整体时限约束；时限已到 → None（不再发起请求）."""
    import time

    if deadline is None:
        return request_timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return max(0.2, min(request_timeout, remaining))


def probe_cdp_endpoint(
    base_url: str, timeout_s: float = DEFAULT_TIMEOUT_S, deadline: float | None = None
) -> dict[str, Any]:
    """探测单个 CDP 端点（只读元信息）.

    ``deadline`` 是整体探测时限的绝对时刻（``time.monotonic()`` 时基）。给定后，
    端点内的两次请求**共享**这一预算：预算用尽后第二次请求不再发出
    （review P2-2：单请求超时不是整体上界）。

    Returns:
        dict: url / reachable / browser / protocol_version / target_count / error。
        不可达时 reachable=False 且 error 非空（**不伪报可达**）。
        可达但目标计数未取到时附带 note（如实说明原因）。
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
    request_timeout = max(0.2, float(timeout_s))
    try:
        with httpx.Client(
            timeout=request_timeout, trust_env=False, follow_redirects=False
        ) as client:
            first_timeout = _bounded_timeout(request_timeout, deadline)
            if first_timeout is None:
                report["error"] = "已达整体探测时限，未发起请求"
                return report
            response = client.get(
                f"{base}/json/version", timeout=httpx.Timeout(first_timeout)
            )
            if response.status_code >= 400:
                report["error"] = f"HTTP {response.status_code}"
                return report
            payload = response.json()
            if not isinstance(payload, dict):
                report["error"] = "/json/version 响应不是 JSON 对象"
                return report
            report["browser"] = str(payload.get("Browser") or "") or None
            report["protocol_version"] = str(payload.get("Protocol-Version") or "") or None
            second_timeout = _bounded_timeout(request_timeout, deadline)
            if second_timeout is None:
                report["note"] = "已达整体探测时限，目标计数未读取"
            else:
                try:
                    targets = client.get(
                        f"{base}/json/list", timeout=httpx.Timeout(second_timeout)
                    )
                    if targets.status_code < 400:
                        listed = targets.json()
                        report["target_count"] = len(listed) if isinstance(listed, list) else None
                except Exception:  # noqa: BLE001 - 目标计数失败不影响可达性判定
                    report["target_count"] = None
                    report["note"] = "目标计数读取失败（目标数未知）"
            report["reachable"] = True
            return report
    except Exception as exc:  # noqa: BLE001 - 连接失败如实回报
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
