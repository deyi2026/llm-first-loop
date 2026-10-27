"""macOS DesktopBackend implementation (D0 分支 A′：进程内 ctypes，零新依赖).

Assembled from the macos_* modules; every method is read-only.  ``lsappinfo``
runs as an argv-list subprocess (no shell, no network).  This class is only
meaningful on darwin — the factory constructs it under ``sys.platform ==
"darwin"`` and the tool maps everything else to ``unsupported_platform``.
"""

from __future__ import annotations

import os
import platform as _platform
import subprocess
import sys
from pathlib import Path

from llm_loop.desktop import macos_ax, macos_capture, macos_permissions, macos_windows
from llm_loop.desktop.apps_probe import (
    build_apps,
    parse_hidden_info,
    parse_lsappinfo_front,
    parse_lsappinfo_list,
)
from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    AppInfo,
    AxView,
    CaptureOutcome,
    DisplayInfo,
    PermissionSnapshot,
    PlatformInfo,
    SessionSnapshot,
    WindowInfo,
)

LSAPPINFO_BIN = "/usr/bin/lsappinfo"
LSAPPINFO_TIMEOUT_S = 5.0
DEFAULT_CAPTURE_DIR = Path.home() / "Library" / "Caches" / "lfl" / "desktop_perceive"


class DesktopBackendError(RuntimeError):
    """后端确定性失败（lsappinfo 不可用等）；工具层映射为 backend_error 回执。"""


def _ax_readable() -> bool:
    """AX 能力取自**实测探针**，不取 ``AXIsProcessTrusted()``。

    实测反证（2026-10-27 同一条父进程链路）：00:0x 时 ``ax_trusted=false``、
    ``AXWindows`` 返回 -25211；00:5x 时同一 API 返回 true，而 AX 属性读取在两次测量
    里都可用。即该 API 会给出**假阴性**，把它当成 ``can_read_ax`` 会把可用能力报成
    不可用，并把用户赶去授权。因此：探针成功就以 ``ax_error == 0`` 为准；探针本身
    失败（None）才回退授权字段。
    """
    err = macos_permissions.ax_error_probe()
    if err is None:
        return macos_permissions.ax_trusted()
    return err == 0


def backend_for_platform(platform_str: str, capture_dir: Path | str | None = None):
    """平台判定：darwin → macOS 后端；其余 → None（工具回 unsupported_platform）。

    独立成函数便于离线测试非 darwin 分支（不加载任何框架）。
    """
    if str(platform_str) == "darwin":
        return MacOSDesktopBackend(capture_dir=capture_dir)
    return None


class MacOSDesktopBackend:
    supported = True

    def __init__(self, capture_dir: Path | str | None = None) -> None:
        self._capture_dir = Path(capture_dir) if capture_dir else DEFAULT_CAPTURE_DIR

    # ── 自检 ──────────────────────────────────────────────────────────────
    def platform_info(self) -> PlatformInfo:
        return macos_permissions.platform_info()

    def session_snapshot(self) -> SessionSnapshot:
        return macos_permissions.session_snapshot()

    def permission_snapshot(self) -> PermissionSnapshot:
        return macos_permissions.permission_snapshot()

    def capability_snapshot(self) -> dict[str, bool]:
        can_list = False
        try:
            can_list = isinstance(macos_windows.list_raw_windows(False), list)
        except Exception:  # noqa: BLE001 - 探测失败按不可用报告
            can_list = False
        return {
            "can_list_windows": can_list,
            "can_read_ax": _ax_readable(),
            "can_capture": macos_permissions.screen_capture_granted(),
        }

    def list_displays(self) -> list[DisplayInfo]:
        return macos_windows.list_displays()

    def process_info(self) -> dict[str, object]:
        return {
            "pid": os.getpid(),
            "executable": sys.executable or "",
            "python": _platform.python_version(),
        }

    # ── L0-lite / L0 ─────────────────────────────────────────────────────
    def _run_lsappinfo(self, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                [LSAPPINFO_BIN, *args],
                capture_output=True,
                timeout=LSAPPINFO_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"lsappinfo {' '.join(args)} 超时"
            raise DesktopBackendError(msg) from exc
        except OSError as exc:
            msg = f"lsappinfo 不可执行: {exc}"
            raise DesktopBackendError(msg) from exc
        if proc.returncode != 0:
            stderr = (proc.stderr or b"").decode("utf-8", "replace")[-120:]
            msg = f"lsappinfo {' '.join(args)} rc={proc.returncode}: {stderr}".strip()
            raise DesktopBackendError(msg)
        return proc.stdout.decode("utf-8", "replace")

    def _app_records(self) -> tuple[list, str | None]:
        records = parse_lsappinfo_list(self._run_lsappinfo(["list"]))
        front_asn = parse_lsappinfo_front(self._run_lsappinfo(["front"]))
        return records, front_asn

    def list_apps(self) -> list[AppInfo]:
        records, front_asn = self._app_records()
        hidden_map: dict[str, bool | None] = {}
        for record in records:
            if record.app_type == "Foreground" and record.pid is not None:
                hidden_map[record.name] = parse_hidden_info(
                    self._run_lsappinfo(["info", "-only", "hidden", record.name])
                )
        return build_apps(
            records,
            front_asn=front_asn,
            hidden_lookup=lambda name: hidden_map.get(name),
        )

    def _pid_bundle_map(self) -> dict[int, str]:
        records, _ = self._app_records()
        return {
            record.pid: record.bundle_id
            for record in records
            if record.pid is not None and record.bundle_id
        }

    def list_windows(self, include_offscreen: bool = False) -> list[WindowInfo]:
        rows = macos_windows.list_raw_windows(include_offscreen=include_offscreen)
        return macos_windows.window_infos_from_raw(
            rows,
            self._pid_bundle_map(),
            on_screen_default=not include_offscreen,
        )

    def get_window(self, window_id: int) -> WindowInfo | None:
        for window in self.list_windows(include_offscreen=True):
            if window.window_id == int(window_id):
                return window
        return None

    # ── L1 / L2 ──────────────────────────────────────────────────────────
    def ax_snapshot(
        self,
        window: WindowInfo,
        depth: int,
        node_limit: int = AX_NODE_LIMIT_DEFAULT,
    ) -> AxView:
        return macos_ax.ax_windows_view(window, depth, node_limit)

    def capture_window(self, window: WindowInfo) -> CaptureOutcome:
        scale = macos_windows.display_scale_for_bounds(
            self.list_displays(), window.bounds_pt
        )
        return macos_capture.capture_window(
            window,
            self._capture_dir,
            scale_hint=scale,
        )

