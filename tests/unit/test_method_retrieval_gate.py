"""Admission-gate guards for method discovery (P1-1①) and its tie-break (P1-1③).

Before the gate every card hit by a single query term entered the ranking pool, so
`list(q, 200)` came back full (200) for 5 of 6 sampled queries — at ~1370 cards one
shared bigram was enough to crowd out the right card. These tests lock the three
admission routes (name hit / two authoritative terms / one in-pool-rare term), the
rejection of a single common-term hit, the status tie-break, and the untouched
lifecycle behaviour of exact hydration and inventory().
"""
from __future__ import annotations

from pathlib import Path

from llm_loop.methods.store import MethodStore


def _write_card(
    root: Path,
    method_id: str,
    *,
    name: str = "Plain Card",
    description: str = "plain card",
    body: str = "# Body\nnothing here",
    status: str = "candidate",
) -> None:
    card = root / method_id
    card.mkdir(parents=True)
    front = [
        "---",
        f"method_id: {method_id}",
        f"name: {name}",
        f"description: {description}",
        f"status: {status}",
        "---",
    ]
    (card / "METHOD.md").write_text("\n".join(front) + "\n" + body.strip() + "\n", encoding="utf-8")


def _store(root: Path) -> MethodStore:
    root.mkdir(parents=True, exist_ok=True)
    return MethodStore(str(root), workspace_root=str(root))


def _ids(cards: list[dict]) -> list[str]:
    return [card["id"] for card in cards]


def test_name_hit_admits_even_when_the_term_is_common(tmp_path: Path) -> None:
    """Route ①: the author-written name is evidence on its own; body-only noise is not."""
    corpus = tmp_path / "methods"
    for index in range(6):
        _write_card(corpus, f"filler-body-{index}", body="quantum filler text")
    _write_card(corpus, "named-quantum-rollup", name="quantum rollup", body="batched job")

    stats: dict = {}
    # limit=1 keeps the page below the backfill floor, so this asserts the *gate* alone.
    cards = _store(corpus).list("quantum", 1, stats=stats)

    assert _ids(cards) == ["named-quantum-rollup"]
    assert stats["pool_before"] == 7
    assert stats["admitted"] == 1
    assert stats["dropped_by_gate"] == 6
    assert stats["backfilled"] == 0
    assert stats["dropped_terms"]["quantum"] == 6


def test_two_distinct_authoritative_terms_admit_a_body_only_card(tmp_path: Path) -> None:
    """Route ②: corroboration across two query terms beats a single common one."""
    corpus = tmp_path / "methods"
    for index in range(5):
        _write_card(corpus, f"alpha-only-{index}", body="alpha channel notes")
        _write_card(corpus, f"beta-only-{index}", body="beta gateway notes")
    _write_card(corpus, "alpha-beta-owner", body="alpha beta combined handling")

    cards = _store(corpus).list("alpha beta", 1)

    assert _ids(cards) == ["alpha-beta-owner"]


def test_rare_single_term_is_itself_enough(tmp_path: Path) -> None:
    """Route ③: df <= 3 inside the pool makes one term discriminative on its own."""
    corpus = tmp_path / "methods"
    for index in range(5):
        _write_card(corpus, f"ordinary-{index}", body="ordinary notes")
    _write_card(corpus, "zebra-handler", body="zebra appears only here")

    stats: dict = {}
    cards = _store(corpus).list("zebra", 50, stats=stats)

    assert _ids(cards) == ["zebra-handler"]
    assert stats["dropped_by_gate"] == 0


def test_common_single_term_hit_is_dropped_and_counted(tmp_path: Path) -> None:
    """The noise case the gate exists for: one ubiquitous term buys nothing.

    With limit=1 the page would otherwise be empty, so the single backfill slot is
    used — that is the documented safety net (a narrow question never returns less than
    the pre-gate call). The assertion therefore moves to the counters: the gate admitted
    nobody, and the caller can see it was a backfill rather than a match.
    """
    corpus = tmp_path / "methods"
    for index in range(5):
        _write_card(corpus, f"gamma-body-{index}", body="gamma metric pipeline")
    store = _store(corpus)

    stats: dict = {}
    cards = store.list("gamma", 1, stats=stats)
    assert len(cards) == 1
    assert stats == {
        "pool_before": 5,
        "admitted": 0,
        "dropped_by_gate": 5,
        "backfilled": 1,
        "returned": 1,
        "dropped_terms": {"gamma": 5},
    }
    # limit=0 asks for nothing, so nothing (not even a backfill) may be returned.
    assert store.list("gamma", 0, stats={}) == []


def test_score_ties_keep_id_descending_regardless_of_status(tmp_path: Path) -> None:
    """Review P1-1: status must NOT be a sort key.

    The gate already changed *which* cards enter the page; using status to re-order
    equal-score ties would additionally rewrite the order existing callers had pinned
    (method_id descending). This pins the pre-gate ordering: four cards scoring the
    same come back by id, descending, whatever their status.
    """
    corpus = tmp_path / "methods"
    plan = (
        ("zzz-active-side", "active"),
        ("nnn-hold-side", "hold"),
        ("mmm-qualified-side", "qualified"),
        ("aaa-candidate-side", "candidate"),
    )
    for method_id, status in plan:
        _write_card(corpus, method_id, name="lambda probe", status=status)

    cards = _store(corpus).list("lambda", 50)

    assert _ids(cards) == [
        "zzz-active-side",
        "nnn-hold-side",
        "mmm-qualified-side",
        "aaa-candidate-side",
    ]


def test_dispositioned_cards_stay_out_of_discovery_but_hydrate_and_inventory(tmp_path: Path) -> None:
    """The gate must not resurrect retired/invalidated cards, nor hide them from admin."""
    corpus = tmp_path / "methods"
    _write_card(corpus, "omega-live", name="omega keeper", status="candidate")
    _write_card(corpus, "omega-retired", name="omega keeper", status="retired")
    _write_card(corpus, "omega-invalidated", name="omega keeper", status="invalidated")

    store = _store(corpus)
    stats: dict = {}
    assert _ids(store.list("omega", 50, stats=stats)) == ["omega-live"]
    assert stats["pool_before"] == 1

    hydrated = store.get("method:omega-retired")
    assert hydrated is not None and hydrated.status == "retired"
    inventory = store.inventory("omega", 50)
    assert {row["id"] for row in inventory["records"]} == {
        "omega-live",
        "omega-retired",
        "omega-invalidated",
    }
