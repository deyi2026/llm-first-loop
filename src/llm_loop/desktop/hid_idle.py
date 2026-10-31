"""D7 HID idle probe (M4 desktop_operate).

Reads ``HIDIdleTime`` from the ``IOHIDSystem`` IORegistry service — the
nanoseconds since the last keyboard/mouse/trackpad event.  This is the
user-presence signal for §6.2/D7: idle < 60s ⇒ a mutate would race a human.

Implementation notes (A-level, probed 2026-10-31 in-session):

- The classic ``IOHIDGetIdleTime()`` export is GONE from the IOKit framework
  on this macOS build (dlsym: symbol not found).  The working path is
  ``IOServiceGetMatchingService(0, IOServiceMatching("IOHIDSystem"))`` →
  ``IORegistryEntryCreateCFProperties`` → dictionary key ``HIDIdleTime``
  (uint64 nanoseconds).  Cross-checked against ``ioreg -c IOHIDSystem -r``
  which prints the same value (51816300083 vs 51834244375 ns, both ≈51.8s,
  read seconds apart).
- Every failure degrades to ``None`` — and the CALLER treats ``None`` as
  "user present" (fail-closed): a probe we cannot run must never license a
  mutation that could race the user (§6.1 T7).

Pure ctypes, lazy framework loads, no subprocess, no network.
"""

from __future__ import annotations

import ctypes

from llm_loop.desktop.macos_cf import cf_dict_get, cf_release, cf_to_int, load_framework

USER_PRESENT_WINDOW_MS = 60_000  # D7：HID idle < 60s 视为用户在场

_IOKIT_READY = False


def _iokit() -> ctypes.CDLL:
    global _IOKIT_READY
    lib = load_framework("IOKit")
    if not _IOKIT_READY:
        lib.IOServiceGetMatchingService.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        lib.IOServiceGetMatchingService.restype = ctypes.c_uint32
        lib.IOServiceMatching.argtypes = [ctypes.c_char_p]
        lib.IOServiceMatching.restype = ctypes.c_void_p
        lib.IORegistryEntryCreateCFProperties.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        lib.IORegistryEntryCreateCFProperties.restype = ctypes.c_int
        lib.IOObjectRelease.argtypes = [ctypes.c_uint32]
        lib.IOObjectRelease.restype = ctypes.c_int
        _IOKIT_READY = True
    return lib


def hid_idle_ms() -> int | None:
    """距上次 HID 事件的毫秒数；探针任何环节失败 → None（调用方按在场处理）。"""
    try:
        lib = _iokit()
        service = int(
            lib.IOServiceGetMatchingService(0, lib.IOServiceMatching(b"IOHIDSystem"))
        )
        if not service:
            return None
        try:
            props = ctypes.c_void_p()
            if lib.IORegistryEntryCreateCFProperties(service, ctypes.byref(props), None, 0) != 0:
                return None
            if not props.value:
                return None
            try:
                value = cf_dict_get(props.value, "HIDIdleTime")
                as_int = cf_to_int(value)
                if as_int is None or as_int < 0:
                    return None
                return int(as_int // 1_000_000)
            finally:
                cf_release(props.value)
        finally:
            lib.IOObjectRelease(ctypes.c_uint32(service))
    except Exception:  # noqa: BLE001 - 探针失败必须读到 None，绝不读到成功
        return None
