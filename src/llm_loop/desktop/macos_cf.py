"""Shared lazy CoreFoundation/CoreGraphics ctypes shims (M3 desktop).

All framework loads are function-local and cached: importing this module (or
the whole ``llm_loop.desktop`` package) never triggers ``ctypes.CDLL``, so the
package imports safely on non-darwin platforms.  Prototypes are set exactly
once per process.  Nothing here talks to the network, spawns processes, or
mutates system state.
"""

from __future__ import annotations

import ctypes

CFIndex = ctypes.c_long
CFTypeRef = ctypes.c_void_p
K_CF_STRING_ENCODING_UTF8 = 0x08000100

K_CFTYPE_STRING = "string"
K_CFTYPE_NUMBER = "number"
K_CFTYPE_BOOLEAN = "boolean"
K_CFTYPE_ARRAY = "array"

_FRAMEWORK_ROOT = "/System/Library/Frameworks"
_FRAMEWORKS: dict[str, ctypes.CDLL] = {}
_PROTO_READY: set[str] = set()


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class CGRect(ctypes.Structure):
    _fields_ = [("origin", CGPoint), ("size", CGSize)]


def load_framework(name: str) -> ctypes.CDLL:
    """Lazily dlopen a system framework and cache the handle (darwin only)."""
    key = f"{_FRAMEWORK_ROOT}/{name}.framework/{name}"
    lib = _FRAMEWORKS.get(key)
    if lib is None:
        lib = ctypes.CDLL(key)
        _FRAMEWORKS[key] = lib
    return lib


def _cf() -> ctypes.CDLL:
    lib = load_framework("CoreFoundation")
    if "cf" not in _PROTO_READY:
        lib.CFStringCreateWithCString.argtypes = [CFTypeRef, ctypes.c_char_p, ctypes.c_uint32]
        lib.CFStringCreateWithCString.restype = CFTypeRef
        lib.CFStringGetCString.argtypes = [CFTypeRef, ctypes.c_char_p, CFIndex, ctypes.c_uint32]
        lib.CFStringGetCString.restype = ctypes.c_bool
        lib.CFArrayGetCount.argtypes = [CFTypeRef]
        lib.CFArrayGetCount.restype = CFIndex
        lib.CFArrayGetValueAtIndex.argtypes = [CFTypeRef, CFIndex]
        lib.CFArrayGetValueAtIndex.restype = CFTypeRef
        lib.CFDictionaryGetValue.argtypes = [CFTypeRef, CFTypeRef]
        lib.CFDictionaryGetValue.restype = CFTypeRef
        lib.CFNumberGetValue.argtypes = [CFTypeRef, ctypes.c_int, ctypes.c_void_p]
        lib.CFNumberGetValue.restype = ctypes.c_bool
        lib.CFGetTypeID.argtypes = [CFTypeRef]
        lib.CFGetTypeID.restype = ctypes.c_ulong
        lib.CFStringGetTypeID.restype = ctypes.c_ulong
        lib.CFNumberGetTypeID.restype = ctypes.c_ulong
        lib.CFBooleanGetTypeID.restype = ctypes.c_ulong
        lib.CFArrayGetTypeID.restype = ctypes.c_ulong
        lib.CFRelease.argtypes = [CFTypeRef]
        _PROTO_READY.add("cf")
    return lib


def make_cfstr(text: str) -> int:
    """Create a transient CFString; callers own (and should release) it."""
    ref = _cf().CFStringCreateWithCString(None, text.encode("utf-8"), K_CF_STRING_ENCODING_UTF8)
    return int(ref or 0)


def cf_release(ref: int | None) -> None:
    if ref:
        lib = _cf()
        lib.CFRelease(ctypes.c_void_p(ref))


def cf_retain(ref: int | None) -> int:
    """CFRetain：从容器（如 CFArray）取出子引用后、释放容器前必须 retain，
    否则子引用悬垂（use-after-free，实测会造成 Trace/BPT trap）。"""
    if ref:
        lib = _cf()
        lib.CFRetain(ctypes.c_void_p(ref))
    return int(ref or 0)


def cf_type_kind(ref: int | None) -> str | None:
    """Classify a CFTypeRef into string/number/boolean/array or None."""
    if not ref:
        return None
    lib = _cf()
    tid = lib.CFGetTypeID(ctypes.c_void_p(ref))
    if tid == lib.CFStringGetTypeID():
        return K_CFTYPE_STRING
    if tid == lib.CFNumberGetTypeID():
        return K_CFTYPE_NUMBER
    if tid == lib.CFBooleanGetTypeID():
        return K_CFTYPE_BOOLEAN
    if tid == lib.CFArrayGetTypeID():
        return K_CFTYPE_ARRAY
    return None


def cf_to_str(ref: int | None, max_bytes: int = 8192) -> str | None:
    if cf_type_kind(ref) != K_CFTYPE_STRING:
        return None
    buf = ctypes.create_string_buffer(max_bytes)
    ok = _cf().CFStringGetCString(
        ctypes.c_void_p(ref), buf, CFIndex(max_bytes), K_CF_STRING_ENCODING_UTF8
    )
    return buf.value.decode("utf-8", "replace") if ok else None


def cf_to_bool(ref: int | None) -> bool | None:
    if cf_type_kind(ref) != K_CFTYPE_BOOLEAN:
        return None
    lib = _cf()
    lib.CFBooleanGetValue.argtypes = [CFTypeRef]
    lib.CFBooleanGetValue.restype = ctypes.c_bool
    return bool(lib.CFBooleanGetValue(ctypes.c_void_p(ref)))


def cf_to_float(ref: int | None) -> float | None:
    if cf_type_kind(ref) != K_CFTYPE_NUMBER:
        return None
    out = ctypes.c_double()
    ok = _cf().CFNumberGetValue(
        ctypes.c_void_p(ref), 13, ctypes.byref(out)
    )  # 13 = kCFNumberFloat64Type
    return float(out.value) if ok else None


def cf_to_int(ref: int | None) -> int | None:
    if cf_type_kind(ref) != K_CFTYPE_NUMBER:
        return None
    out = ctypes.c_int64()
    ok = _cf().CFNumberGetValue(
        ctypes.c_void_p(ref), 4, ctypes.byref(out)
    )  # 4 = kCFNumberSInt64Type
    return int(out.value) if ok else None


def cf_array_count(ref: int | None) -> int:
    if cf_type_kind(ref) != K_CFTYPE_ARRAY:
        return 0
    return int(_cf().CFArrayGetCount(ctypes.c_void_p(ref)))


def cf_array_item(ref: int | None, index: int) -> int:
    return int(_cf().CFArrayGetValueAtIndex(ctypes.c_void_p(ref), CFIndex(index)) or 0)


def cf_dict_get(dict_ref: int | None, key: str) -> int:
    """CFDictionaryGetValue(dict, key) → value ref（0 表示无值）。"""
    if not dict_ref:
        return 0
    key_ref = make_cfstr(key)
    try:
        return int(_cf().CFDictionaryGetValue(ctypes.c_void_p(dict_ref), ctypes.c_void_p(key_ref)) or 0)
    finally:
        cf_release(key_ref)

