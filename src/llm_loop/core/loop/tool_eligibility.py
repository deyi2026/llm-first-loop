"""R8.7 prompt-facing Tool Eligibility integration mixin."""

# pyright: reportAttributeAccessIssue=false, reportGeneralTypeIssues=false
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from llm_loop.tools.eligibility import project_tool_schemas

if TYPE_CHECKING:
    from llm_loop.core.loop.engine import LoopEngine

logger = logging.getLogger(__name__)


class _ToolEligibilityMixin:
    def _project_tool_schemas_for_round(
        self: LoopEngine,
        tool_schemas: list[dict],
        *,
        planned_label: str,
        user_text: str,
        session_messages: list[Any],
    ) -> list[dict]:
        """Apply R8.7 projection or preserve legacy behavior in shadow/off modes."""
        mode = getattr(self.settings, "tool_eligibility_mode", "enforce")
        if mode == "enforce":
            projection = project_tool_schemas(
                tool_schemas,
                user_text=user_text,
                session_messages=session_messages,
                mode="enforce",
            )
            effective = list(projection.schemas)
        elif mode == "shadow":
            projection = project_tool_schemas(
                tool_schemas,
                user_text=user_text,
                session_messages=session_messages,
                mode="enforce",
            )
            effective = self._filter_local_tools(tool_schemas, planned_label)
        else:
            self._last_tool_eligibility = {
                "configured_mode": "off",
                "applied": False,
                "original_count": len(tool_schemas),
                "visible_count": len(tool_schemas),
            }
            return self._filter_local_tools(tool_schemas, planned_label)

        info = projection.as_dict()
        info["configured_mode"] = mode
        info["applied"] = mode == "enforce"
        self._last_tool_eligibility = info
        try:
            self._record_action(
                "tool.eligibility",
                mode,
                (
                    f"model={planned_label};original={projection.original_count};"
                    f"candidate={len(projection.visible_names)};"
                    f"quarantined={len(projection.quarantined_names)};"
                    f"applied={int(mode == 'enforce')}"
                ),
            )
        except Exception:  # noqa: BLE001 — observability must not block the run
            logger.debug("tool eligibility telemetry failed (fail-open)", exc_info=True)
        return effective
