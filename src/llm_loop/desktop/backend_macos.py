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

from llm_loop.desktop import (
    macos_actuate,
    macos_ax,
    macos_capture,
    macos_permissions,
    macos_windows,
)
from llm_loop.desktop.apps_probe import (
    build_apps,
    normalize_asn,
    parse_hidden_info,
    parse_lsappinfo_front,
    parse_lsappinfo_list,
)
from llm_loop.desktop.hid_idle import hid_idle_ms as _hid_idle_ms
from llm_loop.desktop.models import (
    AX_NODE_LIMIT_DEFAULT,
    ActOutcome,
    AppInfo,
    AxView,
    CaptureOutcome,
    DesktopErrorCode,
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


def _frontmost_pid(rows: list[dict]) -> int | None:
    """front→back 序里第一个 layer==0 且有 owner pid 的窗口所属进程。

    ``layer is None`` 视为解析失败而**跳过**，不按 0 处理：把读不到层级的窗口当成普通
    应用窗口，会让「前台是谁」在解析退化时猜错。
    """
    for row in rows:
        try:
            layer = row.get("layer")
            if layer is None or int(layer) != 0:
                continue
            pid = row.get("pid")
            if pid:
                return int(pid)
        except (TypeError, ValueError):
            continue
    return None


def _ax_readable(rows: list[dict] | None = None) -> bool:
    """AX 能力取自**实测探针**，不取 ``AXIsProcessTrusted()``。

    实测反证（2026-10-28 01:0x，同一进程内 4/4 次一致）：``AXIsProcessTrusted()=false``
    且 systemwide 探针返回 None，但 ``ax_snapshot()`` 对前台窗口照常返回
    ``available=true``、22 个节点、``root_role=AXWindow``。即授权位与 systemwide 探针
    都会给出**假阴性**，把它们当成 ``can_read_ax`` 会把可用能力报成不可用，并把用户
    赶去授权。

    因此探测顺序就是工具真正要做的那件事：先对前台 pid 读 ``AXWindows``（探针即实际
    路径）；无前台窗口时才退回 systemwide 探针；再退回授权位。
    """
    pid = _frontmost_pid(rows or [])
    if pid is not None:
        err = macos_ax.ax_readable_probe(pid)
        if err is not None:
            return err == 0
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
        rows: list[dict] = []
        can_list = False
        try:
            raw = macos_windows.list_raw_windows(False)
            if isinstance(raw, list):
                rows = raw
                can_list = True
        except Exception:  # noqa: BLE001 - 探测失败按不可用报告
            can_list = False
        return {
            "can_list_windows": can_list,
            "can_read_ax": _ax_readable(rows),
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

    def frontmost_app_bundle(self) -> str | None:
        """R5：前台 app 的 bundle_id（``lsappinfo front`` ASN → ``list`` 记录匹配）。

        复用 apps_probe 既有解析（parse_lsappinfo_front / parse_lsappinfo_list /
        normalize_asn），不另写解析器。任何取不到（lsappinfo 超时/不可执行/
        rc!=0、front 无 ASN、ASN 无匹配记录、匹配记录 bundleID=[NULL]）都返回
        None——工具层据此 fail-closed 拒绝（foreground_changed），不当成"通过"。
        子进程异常不外抛：探测本身失败 = 取不到（R5 纪律：更保守，不更宽）。
        """
        try:
            records, front_asn = self._app_records()
        except Exception:  # noqa: BLE001 - 探测失败按取不到处理（上层 fail-closed）
            return None
        if not front_asn:
            return None
        for record in records:
            if record.asn and normalize_asn(record.asn) == front_asn:
                return record.bundle_id
        return None

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

    # ── M4：D7 探测 + D5 投递（写路径；工具层门控后才可到达）───────────────
    def hid_idle_ms(self) -> int | None:
        return _hid_idle_ms()

    def ax_probe(self, pid: int) -> int | None:
        """U18 同构自检：对目标 pid 读 AXWindows 的真实错误码（0=可用）。"""
        return macos_ax.ax_readable_probe(int(pid))

    def act_press(self, window: WindowInfo, ax_ref: str) -> ActOutcome:
        """click(ax_ref)：act-time 重解析 + AXPress（主通道，已实测可投递）。"""
        el, failure = macos_actuate.resolve_element_by_axref(window, ax_ref)
        if el is None:
            return self._resolution_failure(failure)
        try:
            return macos_actuate.act_outcome_from_ax_err(
                macos_actuate.ax_press(el), "AXPress"
            )
        finally:
            el.release()

    def act_scroll_into_view(self, window: WindowInfo, ax_ref: str) -> ActOutcome:
        """scroll_into_view：act-time 重解析 + AXScrollToVisible（滚动容器把目标滚入可视区）。"""
        el, failure = macos_actuate.resolve_element_by_axref(window, ax_ref)
        if el is None:
            return self._resolution_failure(failure)
        try:
            return macos_actuate.act_outcome_from_ax_err(
                macos_actuate.ax_scroll_to_visible(el), "AXScrollToVisible"
            )
        finally:
            el.release()

    def act_set_value(self, window: WindowInfo, ax_ref: str, text: str) -> ActOutcome:
        """type：AX set-value（已实测通道）+ 写后回读校验（逐字节相等才算成）。"""
        el, failure = macos_actuate.resolve_element_by_axref(window, ax_ref)
        if el is None:
            return self._resolution_failure(failure)
        try:
            err = macos_actuate.ax_set_value(el, text)
            if err != 0:
                return macos_actuate.act_outcome_from_ax_err(err, "AXSetAttributeValue")
            readback = macos_actuate.ax_read_value_string(el)
            verified = readback == text
            if not verified:
                # S8（R1）：失败 detail 不回显键入内容（可能含敏感文本），
                # 只报长度事实与差分位置。
                first_diff = next(
                    (
                        i
                        for i, (a, b) in enumerate(zip(text, readback or "", strict=False))
                        if a != b
                    ),
                    min(len(text), len(readback or "")),
                )
                return ActOutcome(
                    ok=False,
                    error=DesktopErrorCode.BACKEND_ERROR,
                    detail=(
                        "AX 写入后回读不一致（写入已发生但结果未确认）："
                        f"expect_len={len(text)} got_len={len(readback or '')}"
                        f" first_diff_at={first_diff}（不回显键入内容）"
                    ),
                    ax_error=None,
                    verified=False,
                )
            return ActOutcome(ok=True, verified=True)
        finally:
            el.release()

    def act_click_point(self, x_pt: float, y_pt: float) -> ActOutcome:
        """click(point)：CGEvent 左键点击（全局坐标，单位=点，与 AX 同单位）。

        P2-6（R2）：cg_post_click 在事件未成对创建/补偿失败时抛 OSError——
        此处映射为确定性 backend_error 回执（detail 带固定原因文本，可审计）。
        """
        try:
            macos_actuate.cg_post_click(float(x_pt), float(y_pt))
        except Exception as exc:  # noqa: BLE001 - 投递失败确定性回执，不带栈
            return ActOutcome(
                ok=False,
                error=DesktopErrorCode.BACKEND_ERROR,
                detail=f"CGEvent 点击投递失败: {type(exc).__name__}: {exc}",
            )
        return ActOutcome(ok=True)

    def act_key(self, keycode: int, flags: int) -> ActOutcome:
        """press_key：CGEvent 命名键 down+up（闭合键集；字母通道被 IME 污染，不提供）。"""
        try:
            macos_actuate.cg_post_key(int(keycode), int(flags))
        except Exception as exc:  # noqa: BLE001
            return ActOutcome(
                ok=False,
                error=DesktopErrorCode.BACKEND_ERROR,
                detail=f"CGEvent 按键投递失败: {type(exc).__name__}: {exc}",
            )
        return ActOutcome(ok=True)

    def act_scroll(self, window: WindowInfo, signed_lines: int) -> ActOutcome:
        """scroll：滚轮事件定向投递到窗口所属 pid（不挪动用户光标）。"""
        try:
            macos_actuate.cg_post_scroll_to_pid(window.pid, int(signed_lines))
        except Exception as exc:  # noqa: BLE001
            return ActOutcome(
                ok=False,
                error=DesktopErrorCode.BACKEND_ERROR,
                detail=f"CGEvent 滚轮投递失败: {type(exc).__name__}",
            )
        return ActOutcome(ok=True)

    @staticmethod
    def _resolution_failure(failure: str | None) -> ActOutcome:
        detail = {
            "ax_ref_invalid": "ax_ref 不是合法索引路径（形如 0.2.1）",
            "ax_ref_not_found": "ax_ref 在当前 AX 树中不存在（目标已变化）",
            "ax_unavailable": "AX 通道不可用（未授权/应用不支持）",
            "ax_window_unbound": "窗口绑定未命中（窗口已移动/关闭或标题变化）",
            "window_ambiguous": "AX 侧匹配到多个候选窗口，绑定歧义",
        }.get(failure or "", f"元素解析失败: {failure}")
        return ActOutcome(
            ok=False,
            # R3：ax_ref_not_found（树在、节点不在/已变化）与 ax_window_unbound
            # （窗口解绑）分口径上报——原实现把前者并入 window_unbound，真机上
            # 掩盖了「寻址链路元素死引用」的真因（详见 dev report R3 章）。
            error=(
                DesktopErrorCode.WINDOW_AMBIGUOUS
                if failure == "window_ambiguous"
                else DesktopErrorCode.AX_REF_NOT_FOUND
                if failure == "ax_ref_not_found"
                else DesktopErrorCode.WINDOW_UNBOUND
                if failure == "ax_window_unbound"
                else DesktopErrorCode.AX_UNAVAILABLE
            ),
            detail=detail,
        )

