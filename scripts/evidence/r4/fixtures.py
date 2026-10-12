from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R4Fixture:
    seed_id: str
    title: str
    source_kind: str
    initial_content: str
    current_content: str
    answer: str
    initial_answer: str
    current_answer: str
    task: str
    mutate_after_first: bool = False
    historical_answer: bool = False
    side_effect: bool = False


def _rows(prefix: str, count: int = 225) -> list[str]:
    return [
        f"{prefix} row {i:04d}: neutral holdout material for production evidence consumption."
        for i in range(1, count + 1)
    ]


def _join(rows: list[str]) -> str:
    return "\n".join(rows)


def _k1() -> str:
    rows = _rows("K1")
    rows.insert(38, "== R4 BREAK ==")
    rows.insert(98, "== R4 BREAK ==")
    rows.insert(162, "== R4 BREAK ==")
    rows.insert(163, "third-break-value: LUMEN-5831")
    return _join(rows)


def _k2() -> str:
    rows = _rows("K2")
    rows.insert(55, "R4-K2-LEFT: VEGA")
    rows.insert(174, "R4-K2-RIGHT: 731")
    return _join(rows)


def _large_with_marker(prefix: str, at: int, marker: str) -> str:
    rows = _rows(prefix)
    rows.insert(at, marker)
    return _join(rows)


FIXTURES: dict[str, R4Fixture] = {
    "K1": R4Fixture(
        seed_id="K1",
        title="multi-page third separator",
        source_kind="file",
        initial_content=_k1(),
        current_content=_k1(),
        answer="LUMEN-5831",
        initial_answer="LUMEN-5831",
        current_answer="LUMEN-5831",
        task=(
            "Inspect the supplied source. Return the value immediately after the THIRD occurrence "
            "of the exact separator `== R4 BREAK ==`. The same separator occurs multiple times."
        ),
    ),
    "K2": R4Fixture(
        seed_id="K2",
        title="distant search join",
        source_kind="file",
        initial_content=_k2(),
        current_content=_k2(),
        answer="VEGA-731",
        initial_answer="VEGA-731",
        current_answer="VEGA-731",
        task="Return LEFT-RIGHT using the distant facts labeled R4-K2-LEFT and R4-K2-RIGHT.",
    ),
    "K3": R4Fixture(
        seed_id="K3",
        title="side effect receipt transport separation",
        source_kind="action",
        initial_content=_large_with_marker("K3", 132, "ACTION BUSINESS RECEIPT: RCPT-M8V2"),
        current_content=_large_with_marker("K3", 132, "ACTION BUSINESS RECEIPT: RCPT-M8V2"),
        answer="RCPT-M8V2",
        initial_answer="RCPT-M8V2",
        current_answer="RCPT-M8V2",
        task="Perform the supplied action exactly as needed and return its BUSINESS RECEIPT identifier.",
        side_effect=True,
    ),
    "K4": R4Fixture(
        seed_id="K4",
        title="current value after probeable file change",
        source_kind="file",
        initial_content=_large_with_marker("K4-old", 128, "R4-K4-CURRENT-VALUE: AMBER-214"),
        current_content=_large_with_marker("K4-new", 128, "R4-K4-CURRENT-VALUE: TEAL-908"),
        answer="TEAL-908",
        initial_answer="AMBER-214",
        current_answer="TEAL-908",
        task=(
            "Return the CURRENT R4-K4 value. The file is allowed to change after the first observation."
        ),
        mutate_after_first=True,
    ),
    "K5": R4Fixture(
        seed_id="K5",
        title="explicit historical stale access",
        source_kind="file",
        initial_content=_large_with_marker("K5-old", 127, "R4-K5-FIRST-OBSERVATION: IVORY-337"),
        current_content=_large_with_marker("K5-new", 127, "R4-K5-CURRENT: BLACK-920"),
        answer="IVORY-337",
        initial_answer="IVORY-337",
        current_answer="BLACK-920",
        task=(
            "Return the value from the FIRST observation of this file, even if the file later "
            "changes. This is explicitly a historical/audit question, not a current-state query."
        ),
        mutate_after_first=True,
        historical_answer=True,
    ),
    "K6": R4Fixture(
        seed_id="K6",
        title="unverified immutable runtime snapshot",
        source_kind="snapshot",
        initial_content=_large_with_marker("K6", 129, "R4-K6-SNAPSHOT-VALUE: QUARTZ-662"),
        current_content=_large_with_marker("K6", 129, "R4-K6-SNAPSHOT-VALUE: QUARTZ-662"),
        answer="QUARTZ-662",
        initial_answer="QUARTZ-662",
        current_answer="QUARTZ-662",
        task="Acquire the runtime snapshot and report its snapshot value. It is historical evidence, not a live-current claim.",
    ),
}
