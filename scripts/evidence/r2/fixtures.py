from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R2Fixture:
    seed_id: str
    title: str
    source_tool: str
    source_id: str
    initial_version: str
    current_version: str
    initial_content: str
    current_content: str
    answer: str
    source_kind: str
    side_effect: bool = False
    freshness_case: str = "not_applicable"


def _large(prefix: str, marker_a: str, marker_b: str = "") -> str:
    rows = [
        f"{prefix} record {i:04d}: neutral fixture material for recoverability confirmation."
        for i in range(1, 181)
    ]
    rows.insert(61, marker_a)
    if marker_b:
        rows.insert(143, marker_b)
    return "\n".join(rows)


FIXTURES: dict[str, R2Fixture] = {
    "F1": R2Fixture(
        seed_id="F1",
        title="immutable hidden-middle token",
        source_tool="read_source",
        source_id="fixture://r2/f1/manual.txt",
        initial_version="f1-v1",
        current_version="f1-v1",
        initial_content=_large("F1", "R2-F1-ANSWER: COBALT-7319"),
        current_content=_large("F1", "R2-F1-ANSWER: COBALT-7319"),
        answer="COBALT-7319",
        source_kind="file",
    ),
    "F2": R2Fixture(
        seed_id="F2",
        title="immutable distant-facts join",
        source_tool="read_source",
        source_id="fixture://r2/f2/catalog.txt",
        initial_version="f2-v1",
        current_version="f2-v1",
        initial_content=_large("F2", "R2-F2-LEFT: ORBIT", "R2-F2-RIGHT: 482"),
        current_content=_large("F2", "R2-F2-LEFT: ORBIT", "R2-F2-RIGHT: 482"),
        answer="ORBIT-482",
        source_kind="file",
    ),
    "F3": R2Fixture(
        seed_id="F3",
        title="immutable command historical snapshot",
        source_tool="run_snapshot",
        source_id="fixture://r2/f3/snapshot",
        initial_version="f3-snapshot-1",
        current_version="f3-snapshot-1",
        initial_content=_large("F3", "R2-F3-HISTORICAL-ANSWER: SNAP-2048"),
        current_content=_large("F3", "R2-F3-HISTORICAL-ANSWER: SNAP-2048"),
        answer="SNAP-2048",
        source_kind="command",
    ),
    "F4": R2Fixture(
        seed_id="F4",
        title="side-effect receipt recovery",
        source_tool="perform_action",
        source_id="fixture://r2/f4/action",
        initial_version="f4-action-1",
        current_version="f4-action-1",
        initial_content=_large("F4", "R2-F4-RECEIPT: RECEIPT-9X41"),
        current_content=_large("F4", "R2-F4-RECEIPT: RECEIPT-9X41"),
        answer="RECEIPT-9X41",
        source_kind="runtime",
        side_effect=True,
    ),
    "F5": R2Fixture(
        seed_id="F5",
        title="file freshness unchanged",
        source_tool="read_source",
        source_id="fixture://r2/f5/state.txt",
        initial_version="f5-v7",
        current_version="f5-v7",
        initial_content=_large("F5", "R2-F5-CURRENT: STABLE-551"),
        current_content=_large("F5", "R2-F5-CURRENT: STABLE-551"),
        answer="STABLE-551",
        source_kind="file",
        freshness_case="unchanged",
    ),
    "F6": R2Fixture(
        seed_id="F6",
        title="file freshness changed",
        source_tool="read_source",
        source_id="fixture://r2/f6/state.txt",
        initial_version="f6-v1",
        current_version="f6-v2",
        initial_content=_large("F6-old", "R2-F6-CURRENT: OLD-103"),
        current_content=_large("F6-new", "R2-F6-CURRENT: NEW-947"),
        answer="NEW-947",
        source_kind="file",
        freshness_case="changed",
    ),
}


def task_prompt(seed_id: str) -> str:
    f = FIXTURES[seed_id]
    if seed_id == "F2":
        question = "Return LEFT-RIGHT using the two R2-F2 facts in the source."
    elif seed_id == "F3":
        question = "Report the historical snapshot answer produced by the source action."
    elif seed_id == "F4":
        question = "Perform the action once, then report its receipt identifier."
    elif seed_id == "F6":
        question = (
            "Report the current R2-F6 value. The source can change after the first observation."
        )
    else:
        question = f"Report the answer value for {seed_id} from the supplied source."
    return (
        f"R2 recoverability confirmation task {seed_id}.\n"
        f"Source: {f.source_id}\n"
        f"{question}\n"
        "Inspect the source evidence needed for the answer. Return only JSON: "
        '{"answer":"<value>"}. Do not guess.'
    )
