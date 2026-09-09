"""ERC Phase2 shadow recorder.

The recorder is opt-in and fail-open when installed on ToolRegistry.  It dual-writes a
pre-projection Tool Observation to the new Evidence store while the legacy ToolResult
content/archive/prompt path remains unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

from llm_loop.core.message import ToolCall, ToolResult
from llm_loop.memory.evidence import (
    Coverage,
    EvidenceCapture,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    make_capture_request,
)


class EvidenceShadowRecorder:
    def __init__(
        self,
        capture: EvidenceCapture,
        *,
        owner_resolver: Callable[[], OwnerScope],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.capture = capture
        self.owner_resolver = owner_resolver
        self.clock = clock or (lambda: datetime.now(UTC))

    def __call__(self, call: ToolCall, result: ToolResult) -> None:
        raw = result.raw_observation if result.raw_observation is not None else result.content
        source, coverage = source_for_call(call, result)
        request = make_capture_request(
            owner=self.owner_resolver(),
            stable_capture_id=call.id,
            raw_observation=raw,
            acquired_at=self.clock(),
            tool_name=call.name,
            tool_call_id=call.id,
            source=source,
            coverage=coverage,
            provenance=Provenance(
                producer="tool_registry_shadow",
                authority="tool_observation",
                scope=result.status.value,
            ),
        )
        self.capture.capture(request)


def source_for_call(
    call: ToolCall, result: ToolResult | None = None
) -> tuple[SourceIdentity, Coverage]:
    args = call.arguments if isinstance(call.arguments, dict) else {}
    if call.name == "read_file":
        locator = str(args.get("path", "<unknown-file>"))
        from llm_loop.workspace.artifacts import ARTIFACT_SCHEME

        start = max(0, int(args.get("offset", 0) or 0))
        limit = args.get("limit")
        end = None if limit is None else start + max(0, int(limit))
        return (
            SourceIdentity(
                kind=SourceKind.FILE,
                locator=locator,
                version_policy=(
                    SourceVersionPolicy.VERSIONED
                    if locator.startswith(ARTIFACT_SCHEME)
                    else SourceVersionPolicy.PROBEABLE
                ),
                version_token=(None if result is None else result.evidence_source_version_token),
            ),
            Coverage(
                unit="source_line",
                start=start,
                end_exclusive=end,
                source_complete=start == 0 and limit is None,
            ),
        )
    if call.name == "edit_file":
        return (
            SourceIdentity(
                kind=SourceKind.FILE,
                locator=str(args.get("path", "<unknown-file>")),
                version_policy=SourceVersionPolicy.PROBEABLE,
                version_token=None if result is None else result.evidence_source_version_token,
            ),
            Coverage(unit="diff", start=0, end_exclusive=None, source_complete=False),
        )
    if call.name == "execute_command":
        return (
            SourceIdentity(
                kind=SourceKind.COMMAND,
                locator=str(args.get("command", "<unknown-command>")),
                version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
            ),
            Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
        )
    if call.name == "web_fetch":
        start = max(0, int(args.get("start", 0) or 0))
        count = int(args.get("count", 0) or args.get("max_chars", 100000) or 100000)
        return (
            SourceIdentity(
                kind=SourceKind.WEB,
                locator=str(args.get("url", "<unknown-url>")),
                version_policy=SourceVersionPolicy.VOLATILE,
            ),
            Coverage(
                unit="text_char",
                start=start,
                end_exclusive=None if start == 0 else start + max(0, count),
                source_complete=False,
            ),
        )
    if call.name == "web_search":
        query = args.get("query")
        queries = args.get("queries")
        locator = (
            str(query) if query else json.dumps(queries or [], ensure_ascii=False, sort_keys=True)
        )
        return (
            SourceIdentity(
                kind=SourceKind.WEB,
                locator=locator or "<unknown-web-query>",
                version_policy=SourceVersionPolicy.VOLATILE,
            ),
            Coverage(unit="result_set", start=0, end_exclusive=None, source_complete=False),
        )
    return (
        SourceIdentity(
            kind=SourceKind.RUNTIME_SNAPSHOT,
            locator=f"tool:{call.name}",
            version_policy=SourceVersionPolicy.VERSIONED,
            version_token=None,
        ),
        Coverage(unit="observation", start=0, end_exclusive=None, source_complete=True),
    )
