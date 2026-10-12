from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class R8Fixture:
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


def _neutral(prefix: str, target_line: int, target: str, count: int = 236) -> str:
    rows = [f"entry {i:04d}: neutral R8 efficiency material {prefix}." for i in range(count)]
    rows.insert(target_line, target)
    return "\n".join(rows)


FIXTURES: dict[str, R8Fixture] = {
    "P1": R8Fixture(
        seed_id="P1",
        initial_content=_neutral("cobalt", 127, "R8-ALPHA-TARGET: CORAL-286"),
        current_content=_neutral("cobalt", 127, "R8-ALPHA-TARGET: CORAL-286"),
        expected_answer="CORAL-286",
        historical_answer=None,
        target_field="R8-ALPHA-TARGET",
        task="Return the value of the exact field `R8-ALPHA-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "P2": R8Fixture(
        seed_id="P2",
        initial_content=_neutral("linen", 181, "R8-BETA-TARGET: SLATE-731"),
        current_content=_neutral("linen", 181, "R8-BETA-TARGET: SLATE-731"),
        expected_answer="SLATE-731",
        historical_answer=None,
        target_field="R8-BETA-TARGET",
        task="Return the value of the exact field `R8-BETA-TARGET` from the current file.",
        preacquire_mode="none",
    ),
    "P3": R8Fixture(
        seed_id="P3",
        initial_content=_neutral("pearl", 145, "R8-CURRENT-TARGET: LIME-214"),
        current_content=_neutral("pearl", 145, "R8-CURRENT-TARGET: AZURE-683"),
        expected_answer="AZURE-683",
        historical_answer="LIME-214",
        target_field="R8-CURRENT-TARGET",
        task="Return the CURRENT value of the exact field `R8-CURRENT-TARGET`.",
        preacquire_mode="full",
        mutate_after_preacquire=True,
    ),
    "P4": R8Fixture(
        seed_id="P4",
        initial_content=_neutral("topaz", 133, "R8-GAP-TARGET: BRONZE-957"),
        current_content=_neutral("topaz", 133, "R8-GAP-TARGET: BRONZE-957"),
        expected_answer="BRONZE-957",
        historical_answer=None,
        target_field="R8-GAP-TARGET",
        task=(
            "Return the value of the exact field `R8-GAP-TARGET`. The target is known to be "
            "within source lines 104..164 (0-based); use available evidence/source coverage as needed."
        ),
        preacquire_mode="partial",
        preacquire_offset=0,
        preacquire_limit=64,
    ),
}
