"""L0-lite app inventory parsing for ``lsappinfo`` (pure functions, M3).

Sample-anchored against the real macOS 15 output (A 级实测 2026-10-27):

::

     1) "loginwindow" ASN:0x0-0x3003:
        bundleID="com.apple.loginwindow"
        bundle path="/System/Library/CoreServices/loginwindow.app"
        executable path="/System/Library/CoreServices/loginwindow.app/..."
        pid = 424 type="UIElement" flavor=3 Version="3085.5.3" ... Arch=ARM64
        coalition: 394
        checkin time = 2026/08/30 07:31:28 ( ... )

``bundleID=[ NULL ]`` is a real state (background daemons) → None, not "".
Foreground comes from ``type="Foreground"``; ``lsappinfo front`` echoes an ASN
used as cross-check.  Hidden state needs a separate per-app probe
(``lsappinfo info -only hidden <app>`` → ``"Hidden"=false``) and is therefore
injected as a lookup so tests stay offline.  No permission required (F15).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from llm_loop.desktop.models import AppInfo

_ENTRY_HEAD_RE = re.compile(r'^\s*\d+\)\s+"(?P<name>[^"]*)"\s+(?P<asn>ASN:0x[0-9a-fA-FxX\-]+:?)')
_BUNDLE_ID_RE = re.compile(r'^\s*bundleID="(?P<bundle>[^"]*)"\s*$')
_BUNDLE_NULL_RE = re.compile(r"^\s*bundleID=\[\s*NULL\s*\]\s*$")
_EXECUTABLE_RE = re.compile(r'^\s*executable path="(?P<path>[^"]*)"\s*$')
_PID_TYPE_RE = re.compile(r"^\s*pid\s*=\s*(?P<pid>\d+)\b(?P<rest>.*)$")
_TYPE_RE = re.compile(r'\btype="(?P<type>[^"]*)"')
_FRONT_ASN_RE = re.compile(r"(?P<asn>ASN:0x[0-9a-fA-FxX\-]+)")
_HIDDEN_RE = re.compile(r'^\s*"Hidden"\s*=\s*(?P<hidden>true|false)\s*$', re.IGNORECASE)

APP_TYPE_FOREGROUND = "Foreground"


@dataclass(frozen=True)
class RawAppRecord:
    name: str
    asn: str | None
    bundle_id: str | None
    executable: str | None
    pid: int | None
    app_type: str | None


def normalize_asn(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().rstrip(":").lower()


def parse_lsappinfo_list(text: str) -> list[RawAppRecord]:
    """逐条解析 ``lsappinfo list``（宽容：未知行跳过，不抛异常）。"""
    records: list[RawAppRecord] = []
    current: dict | None = None
    for line in text.splitlines():
        head = _ENTRY_HEAD_RE.match(line)
        if head:
            if current is not None:
                records.append(_finish_record(current))
            current = {
                "name": head.group("name"),
                "asn": head.group("asn"),
                "bundle_id": None,
                "executable": None,
                "pid": None,
                "app_type": None,
            }
            continue
        if current is None:
            continue
        bundle = _BUNDLE_ID_RE.match(line)
        if bundle:
            current["bundle_id"] = bundle.group("bundle")
            continue
        if _BUNDLE_NULL_RE.match(line):
            current["bundle_id"] = None
            continue
        executable = _EXECUTABLE_RE.match(line)
        if executable:
            current["executable"] = executable.group("path")
            continue
        pid_type = _PID_TYPE_RE.match(line)
        if pid_type:
            current["pid"] = int(pid_type.group("pid"))
            type_match = _TYPE_RE.search(pid_type.group("rest") or "")
            if type_match:
                current["app_type"] = type_match.group("type")
    if current is not None:
        records.append(_finish_record(current))
    return records


def _finish_record(current: dict) -> RawAppRecord:
    return RawAppRecord(
        name=str(current.get("name") or ""),
        asn=current.get("asn"),
        bundle_id=current.get("bundle_id"),
        executable=current.get("executable"),
        pid=current.get("pid"),
        app_type=current.get("app_type"),
    )


def parse_lsappinfo_front(text: str) -> str | None:
    """``lsappinfo front`` → 前台 app 的 ASN（无则 None）。"""
    match = _FRONT_ASN_RE.search(text or "")
    return normalize_asn(match.group("asn")) if match else None


def parse_hidden_info(text: str) -> bool | None:
    """``lsappinfo info -only hidden <app>`` → bool（不可解析 → None）。"""
    match = _HIDDEN_RE.match((text or "").strip())
    if not match:
        return None
    return match.group("hidden").lower() == "true"


def build_apps(
    records: list[RawAppRecord],
    front_asn: str | None = None,
    hidden_lookup=None,
    allowlist=None,
) -> list[AppInfo]:
    """记录 → AppInfo 契约对象（前台判定 type=Foreground 优先，ASN 交叉核对）。

    hidden_lookup: Callable[[str], bool|None]（按 app 名查询）；allowlist:
    SeeAllowlist（U14；空名单=全部 allowed，不过滤、只标记）。
    """
    apps: list[AppInfo] = []
    for record in records:
        is_foreground = record.app_type == APP_TYPE_FOREGROUND
        if not is_foreground and front_asn and record.asn:
            is_foreground = normalize_asn(record.asn) == normalize_asn(front_asn)
        hidden = False
        if hidden_lookup is not None and record.pid is not None:
            probe = hidden_lookup(record.name)
            hidden = bool(probe) if probe is not None else False
        apps.append(
            AppInfo(
                bundle_id=record.bundle_id,
                name=record.name,
                pid=record.pid,
                is_foreground=is_foreground,
                is_hidden=hidden,
                allowed=allowlist.is_allowed(record.bundle_id) if allowlist else True,
            )
        )
    return apps

