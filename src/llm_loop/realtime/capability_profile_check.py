"""能力档案完整性与观察项校验（门禁 T25，`T-GATE-6`）。

对应需求：`RTM-CAP-11/12/13/14`、`RTM-SEC-08`、`RTM-AUD-01`、`RTM-TOL-16`、`RTM-PLY-07`。

- 能力档案必须含**本地栈版本 / 接口 / 模型 / 许可**；缺项**显式报错**（不静默降级为「可用」）；
- 转写会话边界必须标注「仅转写、无音频、无工具回环」；
- 观察项（如全双工 VoiceChat）必须 `first_release=False` 且带证伪证据/退出条件。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from llm_loop.realtime.provider_adapter import LocalStackProfile, RecoveryMode

REQUIRED_PROFILE_FIELDS: tuple[str, ...] = (
    "local_stack_version",
    "streaming_asr_model",
    "final_asr_model",
    "tts_model",
    "vad_model",
)

TRANSCRIPTION_SESSION_BOUNDARY = (
    "仅转写：无 response.create、不产出音频、无工具回环（CAP-12）"
)


class CapabilityProfileIncompleteError(RuntimeError):
    """能力档案缺项：显式报错，**不得**静默当作可用。"""


def missing_profile_fields(profile: LocalStackProfile) -> tuple[str, ...]:
    missing: list[str] = [name for name in REQUIRED_PROFILE_FIELDS if not getattr(profile, name, "")]
    if not profile.licenses:
        missing.append("licenses")
    return tuple(missing)


def validate_capability_profile(profile: LocalStackProfile) -> None:
    """完整性校验；缺项抛 `CapabilityProfileIncompleteError`。"""
    missing = missing_profile_fields(profile)
    if missing:
        raise CapabilityProfileIncompleteError(
            "local stack capability profile incomplete: " + ", ".join(missing)
        )
    if profile.recovery_mode is not RecoveryMode.LOCAL_REBUILD_ONLY:
        raise CapabilityProfileIncompleteError("first release supports local_rebuild_only recovery")


def transcription_session_boundaries() -> dict[str, bool | str]:
    """转写会话能力边界（供界面/能力档案标注）。"""
    return {
        "transcribes_only": True,
        "produces_audio": False,
        "has_tool_loopback": False,
        "requires_response_create": False,
        "note": TRANSCRIPTION_SESSION_BOUNDARY,
    }


@dataclass(frozen=True)
class ObservationItem:
    """观察项：**不上线**（`first_release=False`），但保留证据与退出条件。"""

    name: str
    falsification_evidence: tuple[str, ...] = field(default_factory=tuple)
    root_cause_candidates: tuple[str, ...] = field(default_factory=tuple)
    exit_conditions: tuple[str, ...] = field(default_factory=tuple)
    first_release: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("observation name is required")
        if self.first_release:
            raise ValueError("observation items must not ship in the first release")

    def is_released(self) -> bool:
        return self.first_release

    def is_auditable(self) -> bool:
        return bool(self.falsification_evidence and self.exit_conditions)
