"""Typed tool recovery policy for deterministic next-step guidance.

R8.7 starts with web_fetch as the reference implementation.  The policy is deliberately
small: unsupported failures fall back to the pre-existing generic guidance rather than
pretending we know the correct recovery path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from llm_loop.core.message import ToolResult, ToolResultStatus


@dataclass(frozen=True)
class ToolRecoveryAdvice:
    failure_class: str
    retry_same_tool: str
    preferred_next: tuple[str, ...] = ()
    preferred_skill: str | None = None
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "failure_class": self.failure_class,
            "retry_same_tool": self.retry_same_tool,
            "preferred_next": list(self.preferred_next),
            "preferred_skill": self.preferred_skill,
            "reason": self.reason,
        }

    def render(self) -> str:
        next_text = ", ".join(self.preferred_next) if self.preferred_next else "none"
        skill = f"; skill={self.preferred_skill}" if self.preferred_skill else ""
        reason = f"\n[恢复说明] {self.reason}" if self.reason else ""
        return (
            f"[恢复策略] class={self.failure_class}; retry_same_tool={self.retry_same_tool}; "
            f"next={next_text}{skill}{reason}"
        )


_KNOWN_ANTI_BOT_SUFFIXES = ("toutiao.com",)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def web_fetch_preflight(url: str) -> ToolRecoveryAdvice | None:
    host = _host(url)
    if not host:
        return None
    if any(host == suffix or host.endswith("." + suffix) for suffix in _KNOWN_ANTI_BOT_SUFFIXES):
        # Site adapters run inside WebFetchTool and preserve the same SSRF/redirect/curl
        # safety boundary.  Do not route supported article URLs away before the tool
        # gets a chance to execute its deterministic adapter.  Keep the legacy R8.7
        # route only for Toutiao URL shapes that the adapter cannot handle.
        from llm_loop.tools.builtin.web_fetch import _toutiao_article_id

        if _toutiao_article_id(url) is not None:
            return None
        return ToolRecoveryAdvice(
            failure_class="known_domain_anti_bot",
            retry_same_tool="no",
            preferred_next=("skill_load:web-fetch-fast",),
            preferred_skill="web-fetch-fast",
            reason="direct web_fetch has no deterministic adapter for this URL shape; no network request was executed",
        )
    return None


def health_quarantine_advice(
    tool_name: str, reason_code: str, preferred_next: tuple[str, ...]
) -> ToolRecoveryAdvice:
    return ToolRecoveryAdvice(
        failure_class="environment_prerequisite_missing",
        retry_same_tool="after_fix",
        preferred_next=preferred_next,
        reason=f"{tool_name} runtime health is quarantined: {reason_code}",
    )


def classify_tool_recovery(result: ToolResult) -> ToolRecoveryAdvice | None:
    if result.tool_name != "web_fetch":
        return None
    content = result.content or ""
    if result.status == ToolResultStatus.BLOCKED:
        return ToolRecoveryAdvice(
            failure_class="security_policy_block",
            retry_same_tool="no",
            reason="stop at the security boundary; do not weaken private-target/SSRF protection as routine recovery",
        )
    if result.status == ToolResultStatus.SUCCESS:
        return None
    if "JS 壳" in content or "js_shell" in content.lower():
        return ToolRecoveryAdvice(
            failure_class="javascript_shell_or_anti_bot",
            retry_same_tool="no",
            preferred_next=("skill_load:web-fetch-fast",),
            preferred_skill="web-fetch-fast",
            reason="web_fetch already exhausted its generic HTTP/curl path; use the site-specific extraction skill",
        )
    match = re.search(r"HTTP\s+(\d{3})", content, re.IGNORECASE)
    code = int(match.group(1)) if match else None
    if code in {403, 418}:
        return ToolRecoveryAdvice(
            failure_class="anti_bot_or_access_reject",
            retry_same_tool="no",
            preferred_next=("skill_load:web-fetch-fast", "web_search"),
            preferred_skill="web-fetch-fast",
            reason="UA rotation is already exhausted inside web_fetch; repeating the same path is low value",
        )
    if code == 404:
        return ToolRecoveryAdvice(
            failure_class="url_not_found",
            retry_same_tool="no",
            preferred_next=("web_search",),
            reason="find the canonical/current URL before fetching again",
        )
    if code == 429:
        return ToolRecoveryAdvice(
            failure_class="rate_limited",
            retry_same_tool="later",
            preferred_next=("web_search",),
            reason="use an alternate source now; retry the same origin only after meaningful backoff",
        )
    if result.status == ToolResultStatus.TIMEOUT or (code is not None and 500 <= code <= 599):
        return ToolRecoveryAdvice(
            failure_class="transient_transport_or_server",
            retry_same_tool="once",
            preferred_next=("retry_tool", "web_search"),
            reason="one bounded retry is allowed; after a repeat failure switch source/path",
        )
    return None
