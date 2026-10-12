from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R10Fixture:
    seed_id: str
    initial_content: str
    current_content: str
    expected_answer: str
    historical_answer: str | None
    target_field: str
    task: str
    preacquire_mode: str
    preacquire_offset: int = 0
    preacquire_limit: int | None = None
    mutate_after_preacquire: bool = False


def _neutral(prefix: str, target_line: int, target: str, count: int = 242) -> str:
    rows = [f"item {i:04d}: neutral R10 source-resolution material {prefix}." for i in range(count)]
    rows.insert(target_line, target)
    return "\n".join(rows)


FIXTURES: dict[str, R10Fixture] = {
    "T1": R10Fixture(
        seed_id="T1",
        initial_content=_neutral("basalt", 136, "R10-ALPHA-TARGET: GARNET-324"),
        current_content=_neutral("basalt", 136, "R10-ALPHA-TARGET: GARNET-324"),
        expected_answer="GARNET-324",
        historical_answer=None,
        target_field="R10-ALPHA-TARGET",
        task="Return the value of the exact field `R10-ALPHA-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "T2": R10Fixture(
        seed_id="T2",
        initial_content=_neutral("jasper", 188, "R10-BETA-TARGET: MOSS-781"),
        current_content=_neutral("jasper", 188, "R10-BETA-TARGET: MOSS-781"),
        expected_answer="MOSS-781",
        historical_answer=None,
        target_field="R10-BETA-TARGET",
        task="Return the value of the exact field `R10-BETA-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "T3": R10Fixture(
        seed_id="T3",
        initial_content=_neutral("granite", 151, "R10-CURRENT-TARGET: KHAKI-127"),
        current_content=_neutral("granite", 151, "R10-CURRENT-TARGET: MAROON-968"),
        expected_answer="MAROON-968",
        historical_answer="KHAKI-127",
        target_field="R10-CURRENT-TARGET",
        task="Return the CURRENT value of the exact field `R10-CURRENT-TARGET`.",
        preacquire_mode="full",
        mutate_after_preacquire=True,
    ),
    "T4": R10Fixture(
        seed_id="T4",
        initial_content=_neutral("quartzite", 141, "R10-GAP-TARGET: TURQUOISE-654"),
        current_content=_neutral("quartzite", 141, "R10-GAP-TARGET: TURQUOISE-654"),
        expected_answer="TURQUOISE-654",
        historical_answer=None,
        target_field="R10-GAP-TARGET",
        task=(
            "Return the value of the exact field `R10-GAP-TARGET`. The target is known to be "
            "within source lines 112..172 (0-based); use current Evidence/source coverage as needed."
        ),
        preacquire_mode="partial",
        preacquire_offset=0,
        preacquire_limit=68,
    ),
}
