from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R7Fixture:
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


def _neutral(prefix: str, target_line: int, target: str, count: int = 230) -> str:
    rows = [f"record {i:04d}: neutral R7 holdout material {prefix}." for i in range(count)]
    rows.insert(target_line, target)
    return "\n".join(rows)


FIXTURES: dict[str, R7Fixture] = {
    "Q1": R7Fixture(
        seed_id="Q1",
        initial_content=_neutral("quartz", 131, "R7-PRIMARY-TARGET: AMBER-612"),
        current_content=_neutral("quartz", 131, "R7-PRIMARY-TARGET: AMBER-612"),
        expected_answer="AMBER-612",
        historical_answer=None,
        target_field="R7-PRIMARY-TARGET",
        task="Return the value of the exact field `R7-PRIMARY-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "Q2": R7Fixture(
        seed_id="Q2",
        initial_content=_neutral("saffron", 177, "R7-SECONDARY-TARGET: IVORY-374"),
        current_content=_neutral("saffron", 177, "R7-SECONDARY-TARGET: IVORY-374"),
        expected_answer="IVORY-374",
        historical_answer=None,
        target_field="R7-SECONDARY-TARGET",
        task="Return the value of the exact field `R7-SECONDARY-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "Q3": R7Fixture(
        seed_id="Q3",
        initial_content=_neutral("umber", 139, "R7-CURRENT-TARGET: MINT-105"),
        current_content=_neutral("umber", 139, "R7-CURRENT-TARGET: PLUM-842"),
        expected_answer="PLUM-842",
        historical_answer="MINT-105",
        target_field="R7-CURRENT-TARGET",
        task="Return the CURRENT value of the exact field `R7-CURRENT-TARGET`.",
        preacquire_mode="full",
        mutate_after_preacquire=True,
    ),
    "Q4": R7Fixture(
        seed_id="Q4",
        initial_content=_neutral("violet", 129, "R7-GAP-TARGET: ONYX-913"),
        current_content=_neutral("violet", 129, "R7-GAP-TARGET: ONYX-913"),
        expected_answer="ONYX-913",
        historical_answer=None,
        target_field="R7-GAP-TARGET",
        task=(
            "Return the value of the exact field `R7-GAP-TARGET`. The target is known to be "
            "within source lines 100..160 (0-based); use available evidence/source coverage as needed."
        ),
        preacquire_mode="partial",
        preacquire_offset=0,
        preacquire_limit=60,
    ),
}
