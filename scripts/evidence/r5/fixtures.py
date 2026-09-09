from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R5Fixture:
    seed_id: str
    source_kind: str
    initial_content: str
    current_content: str
    expected_answer: str
    historical_answer: str | None
    current_answer: str
    target_field: str
    task: str
    mutate_after_preacquire: bool


def _neutral(prefix: str, target_line: int, target: str, count: int = 225) -> str:
    rows = [
        f"record {i:04d}: neutral evidence holdout material {prefix}." for i in range(1, count + 1)
    ]
    rows.insert(target_line, target)
    return "\n".join(rows)


FIXTURES: dict[str, R5Fixture] = {
    "J1": R5Fixture(
        seed_id="J1",
        source_kind="file",
        initial_content=_neutral("alpha", 131, "R5-CURRENT-TARGET: SILVER-208"),
        current_content=_neutral("alpha", 131, "R5-CURRENT-TARGET: CEDAR-741"),
        expected_answer="CEDAR-741",
        historical_answer="SILVER-208",
        current_answer="CEDAR-741",
        target_field="R5-CURRENT-TARGET",
        task="Return the CURRENT value of the exact field `R5-CURRENT-TARGET`.",
        mutate_after_preacquire=True,
    ),
    "J2": R5Fixture(
        seed_id="J2",
        source_kind="file",
        initial_content=_neutral("bravo", 137, "R5-HISTORICAL-TARGET: OPAL-335"),
        current_content=_neutral("bravo", 137, "R5-HISTORICAL-TARGET: GRAPHITE-881"),
        expected_answer="OPAL-335",
        historical_answer="OPAL-335",
        current_answer="GRAPHITE-881",
        target_field="R5-HISTORICAL-TARGET",
        task=(
            "Using the PRE-CHANGE HISTORICAL EVIDENCE that was acquired before this task, "
            "return the historical value of the exact field `R5-HISTORICAL-TARGET`."
        ),
        mutate_after_preacquire=True,
    ),
    "J3": R5Fixture(
        seed_id="J3",
        source_kind="file",
        initial_content=_neutral("charlie", 143, "R5-ACTIVE-ROUTE: SOUTH-147"),
        current_content=_neutral("charlie", 143, "R5-ACTIVE-ROUTE: NORTH-624"),
        expected_answer="NORTH-624",
        historical_answer="SOUTH-147",
        current_answer="NORTH-624",
        target_field="R5-ACTIVE-ROUTE",
        task="Return the CURRENT value of the exact field `R5-ACTIVE-ROUTE`.",
        mutate_after_preacquire=True,
    ),
    "J4": R5Fixture(
        seed_id="J4",
        source_kind="snapshot",
        initial_content=_neutral("delta", 139, "R5-SNAPSHOT-TARGET: CRANE-509"),
        current_content=_neutral("delta", 139, "R5-SNAPSHOT-TARGET: CRANE-509"),
        expected_answer="CRANE-509",
        historical_answer=None,
        current_answer="CRANE-509",
        target_field="R5-SNAPSHOT-TARGET",
        task="Return the value of the exact field `R5-SNAPSHOT-TARGET` from the already acquired runtime snapshot Evidence.",
        mutate_after_preacquire=False,
    ),
}
