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
    rows = [f"record {i:04d}: neutral R7 v2 holdout material {prefix}." for i in range(count)]
    rows.insert(target_line, target)
    return "\n".join(rows)


FIXTURES: dict[str, R7Fixture] = {
    "Q1": R7Fixture(
        seed_id="Q1",
        initial_content=_neutral("cedar", 131, "R7V2-PRIMARY-TARGET: LARCH-527"),
        current_content=_neutral("cedar", 131, "R7V2-PRIMARY-TARGET: LARCH-527"),
        expected_answer="LARCH-527",
        historical_answer=None,
        target_field="R7V2-PRIMARY-TARGET",
        task="Return the value of the exact field `R7V2-PRIMARY-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "Q2": R7Fixture(
        seed_id="Q2",
        initial_content=_neutral("linen", 177, "R7V2-SECONDARY-TARGET: PEARL-681"),
        current_content=_neutral("linen", 177, "R7V2-SECONDARY-TARGET: PEARL-681"),
        expected_answer="PEARL-681",
        historical_answer=None,
        target_field="R7V2-SECONDARY-TARGET",
        task="Return the value of the exact field `R7V2-SECONDARY-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "Q3": R7Fixture(
        seed_id="Q3",
        initial_content=_neutral("moss", 139, "R7V2-CURRENT-TARGET: CLOVE-214"),
        current_content=_neutral("moss", 139, "R7V2-CURRENT-TARGET: ASPEN-763"),
        expected_answer="ASPEN-763",
        historical_answer="CLOVE-214",
        target_field="R7V2-CURRENT-TARGET",
        task="Return the CURRENT value of the exact field `R7V2-CURRENT-TARGET`.",
        preacquire_mode="full",
        mutate_after_preacquire=True,
    ),
    "Q4": R7Fixture(
        seed_id="Q4",
        initial_content=_neutral("slate", 129, "R7V2-GAP-TARGET: TOPAZ-438"),
        current_content=_neutral("slate", 129, "R7V2-GAP-TARGET: TOPAZ-438"),
        expected_answer="TOPAZ-438",
        historical_answer=None,
        target_field="R7V2-GAP-TARGET",
        task=(
            "Return the value of the exact field `R7V2-GAP-TARGET`. The target is known to be "
            "within source lines 100..160 (0-based); use available evidence/source coverage as needed."
        ),
        preacquire_mode="partial",
        preacquire_offset=0,
        preacquire_limit=60,
    ),
}
