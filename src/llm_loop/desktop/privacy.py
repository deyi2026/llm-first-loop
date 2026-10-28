"""D8 privacy redaction + U14 see-allowlist (M3 desktop).

The core bundle-id substring list is HARDCODED (password managers / keychain /
loginwindow).  Configuration can only APPEND entries — there is deliberately
no parameter that removes or replaces core items, and the ``SeeAllowlist`` is
a separate, weaker gate that never weakens the core list:

- privacy hit  → ``windows`` redacts the title; ``snapshot`` → privacy_blocked
- allowlist miss (list non-empty) → apps marked ``allowed:false``; windows
  title redacted; snapshot → app_not_allowed
- priority: privacy_blocked (core) > app_not_allowed (config), always.
"""

from __future__ import annotations

# 核心拦截名单（子串匹配，比较前统一小写；只能追加，不能删改）
CORE_PRIVACY_BUNDLE_SUBSTRINGS: tuple[str, ...] = (
    "1password",
    "bitwarden",
    "lastpass",
    "dashlane",
    "keychain",
    "com.apple.securityagent",
    "com.apple.passwords",
    "com.apple.loginwindow",
)


def _normalize(raw: str) -> str:
    return str(raw or "").strip().lower()


class PrivacyPolicy:
    """核心名单（不可变）+ 追加名单（只增）。"""

    def __init__(self, extra_substrings: tuple[str, ...] = ()) -> None:
        self._core = CORE_PRIVACY_BUNDLE_SUBSTRINGS
        extras: list[str] = []
        for item in extra_substrings:
            normalized = _normalize(item)
            if normalized and normalized not in extras:
                extras.append(normalized)
        self._extras = tuple(extras)

    @property
    def core_items(self) -> tuple[str, ...]:
        return self._core

    @property
    def extra_items(self) -> tuple[str, ...]:
        return self._extras

    def is_sensitive(self, bundle_id: str | None) -> bool:
        candidate = _normalize(bundle_id or "")
        if not candidate:
            return False
        return any(needle and needle in candidate for needle in (*self._core, *self._extras))


class SeeAllowlist:
    """U14 see 层可见范围（bundle_id 精确匹配；默认空 = 全部允许，不默认拒绝）。"""

    def __init__(self, entries: tuple[str, ...] = ()) -> None:
        normalized = {_normalize(entry) for entry in entries if _normalize(entry)}
        self._entries = frozenset(normalized)

    @property
    def is_empty(self) -> bool:
        return not self._entries

    def is_allowed(self, bundle_id: str | None) -> bool:
        if self.is_empty:
            return True
        return _normalize(bundle_id or "") in self._entries


def split_bundle_config(raw: str | None) -> tuple[str, ...]:
    """逗号分隔配置串 → 规范化元组（空串 → ()；供 env 配置解析）。"""
    if not raw:
        return ()
    parts = [part.strip() for part in str(raw).split(",")]
    return tuple(part for part in parts if part)

