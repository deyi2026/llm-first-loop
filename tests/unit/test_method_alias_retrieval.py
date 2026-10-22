"""Method alias retrieval contract (2026-10-22 method-alias-retrieval).

Aliases are author-declared synonym / colloquial spellings of *when a card
applies*. They are a weak retrieval hint and nothing more: an alias hit adds
``_ALIAS_WEIGHT`` (=3) to the lexical score — strictly below ``desc`` (4), the
weakest authoritative field — and never enters ``term_hits`` / ``coverage``. A
card that merely carries the word as an alias therefore cannot pull the term
away from a card whose id/name/desc/body really covers it. Aliases are also
folded into the semantic candidate text and into the inventory keyword haystack,
and are projected on the card only when declared. They never decide
applicability, never grant a use permission, and are unrelated to status (which
is only a badge).

Equivalence guard: a card without ``aliases`` must behave exactly like it did
before the field existed; ``test_missing_and_empty_aliases_rerun_identically``
pins that for both ordering and projection.
"""

from __future__ import annotations

import math
import sys
from dataclasses import fields
from pathlib import Path

import pytest

import llm_loop.methods.store as store_module
from llm_loop.methods.store import (
    _ALIAS_WEIGHT,
    _FIELD_WEIGHTS,
    MethodRecord,
    MethodStore,
)

_FRONT = "---\n{front}\n---\n{body}\n"


def _write_card(
    root: Path,
    method_id: str,
    *,
    name: str,
    description: str = "",
    body: str = "",
    status: str = "candidate",
    extra: tuple[str, ...] = (),
) -> Path:
    directory = root / method_id
    directory.mkdir(parents=True, exist_ok=True)
    front = [
        f"method_id: {method_id}",
        f"name: {name}",
        f"description: {description}",
        f"status: {status}",
    ]
    front.extend(extra)
    path = directory / "METHOD.md"
    path.write_text(_FRONT.format(front="\n".join(front), body=body), encoding="utf-8")
    return path


def _keys(cards: list[dict]) -> list[str]:
    return [card["key"] for card in cards]


def _projection(cards: list[dict]) -> list[dict]:
    # Two exclusions, both structural rather than semantic:
    # - "file" is an absolute temp path;
    # - "content_hash" hashes the raw front matter, and the empty-alias corpus
    #   carries one extra `aliases:` line on purpose.
    # Every other projected field must be identical.
    drop = {"file", "content_hash"}
    return [{k: v for k, v in card.items() if k not in drop} for card in cards]


def test_aliases_parsed_whitespace_and_default_empty(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _write_card(root, "card-listed", name="listed", extra=("aliases: a,b , c",))
    _write_card(root, "card-missing", name="missing")
    _write_card(root, "card-blank", name="blank", extra=("aliases:",))

    store = MethodStore(str(root))
    listed = store.get("method:card-listed")
    missing = store.get("method:card-missing")
    blank = store.get("method:card-blank")
    assert listed is not None and missing is not None and blank is not None
    assert listed.aliases == ("a", "b", "c")
    assert missing.aliases == ()
    assert blank.aliases == ()
    # aliases is the last dataclass field, so every pre-existing positional
    # construction keeps its meaning.
    assert [f.name for f in fields(MethodRecord)][-1] == "aliases"
    assert MethodRecord.__dataclass_fields__["aliases"].default == ()


def test_card_projects_aliases_only_when_declared(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _write_card(root, "card-listed", name="listed", extra=("aliases: a,b , c",))
    _write_card(root, "card-missing", name="missing")

    store = MethodStore(str(root))
    listed = store.get("method:card-listed")
    missing = store.get("method:card-missing")
    assert listed is not None and missing is not None
    assert listed.card()["aliases"] == ["a", "b", "c"]
    # Empty aliases must not grow every card in the pool with a dead key.
    assert "aliases" not in missing.card()


class _ScoreSpy:
    """Capture the scores ``list()`` computes without changing what it returns.

    ``list()`` rounds exactly twice per ranked record: once on the 4dp lexical sum
    and once on the final score. Wrapping the store module's ``round`` therefore
    exposes the documented score formula through the real call surface instead of
    re-deriving it inside the test.

    Keys are the ``record.method_id`` that ``list()`` is scoring right now, read off
    the caller frame, so the mapping survives any ranking order: pairing by call
    order instead would silently label scores with the wrong card whenever the
    scores are not tied (that is exactly the situation these tests measure).
    """

    def __init__(self) -> None:
        self.values: dict[str, float] = {}

    def __call__(self, value: float, ndigits: int | None = None) -> float:
        if ndigits is not None:
            # Identify the record being scored by its type, never by the local's name:
            # the seam has to survive a rename of the loop variable inside list().
            frame = sys._getframe(1)
            record = next(
                (item for item in frame.f_locals.values() if isinstance(item, MethodRecord)),
                None,
            )
            if record is not None:
                # Inner lexical round then outer total: the total is the larger one.
                previous = self.values.get(record.method_id)
                self.values[record.method_id] = (
                    value if previous is None else max(previous, value)
                )
        return round(value, ndigits) if ndigits is not None else round(value)


def _scores(
    store: MethodStore, query: str, monkeypatch: pytest.MonkeyPatch
) -> dict[str, float]:
    """Final ``list()`` score per card key — the value the ranking sorts on."""
    spy = _ScoreSpy()
    with monkeypatch.context() as patch:
        patch.setattr(store_module, "round", spy, raising=False)
        cards = store.list(query, limit=50)
    assert set(spy.values) == {card["key"].split(":", 1)[1] for card in cards}
    return {f"method:{method_id}": score for method_id, score in spy.values.items()}


def test_alias_weight_is_literal_three_below_every_authoritative_field() -> None:
    """The weight is a reviewed contract, so it is pinned as a literal.

    ``_ALIAS_WEIGHT == _FIELD_WEIGHTS["name"]`` — the assertion this replaces —
    restated the constant instead of checking it, and stayed green through the very
    edit that broke retrieval. What matters can be stated without reading the code:
    an alias weighs 3, and 3 is strictly below the weakest authoritative field
    (desc, 4), so an id/name/desc/body hit on a term always out-scores an alias hit
    on that same term.
    """
    assert _ALIAS_WEIGHT == 3
    assert _FIELD_WEIGHTS["desc"] == 4
    assert all(_ALIAS_WEIGHT < weight for weight in _FIELD_WEIGHTS.values())


def test_alias_hit_surfaces_its_card_but_never_outranks_an_authoritative_hit(
    tmp_path: Path,
) -> None:
    """An alias is a hint: it finds its card, it does not win the term.

    ``zap`` is authoritative on exactly one card (its body) and appears only as an
    alias on the other, so the alias card has to come second while still being
    returned at all — the hint keeps working, it just does not take the term.
    """
    cards = (
        (
            "zzz-alias-owner",
            dict(
                name="nightly rollup",
                description="batched aggregation job",
                body="run the scheduled job",
            ),
            ("aliases: zap",),
        ),
        (
            "mmm-body-owner",
            dict(
                name="other card",
                description="unrelated description",
                body="zap appears in the body only",
            ),
            (),
        ),
    )
    aliased = tmp_path / "aliased"
    bare = tmp_path / "bare"
    for root, keep_alias in ((aliased, True), (bare, False)):
        for method_id, fields_, extra in cards:
            # The alias line is dropped for the control corpus only.
            _write_card(root, method_id, extra=(extra if keep_alias else ()), **fields_)

    assert _keys(MethodStore(str(aliased)).list("zap", limit=10)) == [
        "method:mmm-body-owner",
        "method:zzz-alias-owner",
    ]
    # Control corpus (same cards, no alias line): the term no longer reaches the
    # alias card at all, which is what shows the alias is still doing retrieval work.
    assert _keys(MethodStore(str(bare)).list("zap", limit=10)) == ["method:mmm-body-owner"]


@pytest.mark.parametrize(
    ("alias_id", "name_id"),
    [("aaa-alias-side", "zzz-name-side"), ("zzz-alias-side", "aaa-name-side")],
)
def test_name_hit_outranks_alias_hit_whichever_method_id_sorts_last(
    tmp_path: Path, alias_id: str, name_id: str
) -> None:
    """Negative guard for the alias-scoring regression.

    Both cards reach the single query term ``zap`` — one through its name, one only
    through an alias. While the alias channel weighed like ``name`` the two cards
    scored identically and the winner fell through to the ``method_id`` tie-break,
    so the alias card won whenever its id sorted last. Weight or coverage leaking
    back into the alias channel is the only thing that can put it first here, and
    the two parametrizations remove id order as an alibi.
    """
    root = tmp_path / f"methods-{alias_id}-{name_id}"
    _write_card(root, alias_id, name="nightly rollup", extra=("aliases: zap",))
    _write_card(root, name_id, name="zap collector")
    assert _keys(MethodStore(str(root)).list("zap", limit=10)) == [
        f"method:{name_id}",
        f"method:{alias_id}",
    ]


def test_alias_hit_adds_only_alias_weight_and_never_moves_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alias hits pay ``_ALIAS_WEIGHT*10`` in lexical and nothing in coverage.

    Both cards carry byte-identical authoritative text, so they hold identical
    authoritative hits, identical df/idf for the shared term and identical coverage;
    one of them only gains an alias. The query's second term ``omega`` exists nowhere
    but in that alias, so the observed delta isolates the alias channel: exactly
    ``_ALIAS_WEIGHT * 10 * idf(omega)`` with ``idf`` read off df(omega) = 0 — i.e. the
    alias-only term never entered ``term_hits`` (nor df) either. A coverage credit
    for the alias would have moved the +50 band instead, and the band moves in
    integer steps (25 here, for 1 of 2 terms), so exact equality against the pure
    lexical credit is what rules it out.
    """
    query = "alpha omega"
    core = dict(name="nightly rollup", description="alpha shared core")
    plain = tmp_path / "plain"
    aliased = tmp_path / "aliased"
    for root, extra in ((plain, ()), (aliased, ("aliases: omega",))):
        # Only card-b differs between the two corpora: same core text, one alias line.
        _write_card(root, "card-a", **core)
        _write_card(root, "card-b", extra=extra, **core)

    off = _scores(MethodStore(str(plain)), query, monkeypatch)
    on = _scores(MethodStore(str(aliased)), query, monkeypatch)

    # Adding an alias to card-b must not disturb card-a either: shared terms keep
    # their df, so idf is untouched by the alias channel.
    assert off["method:card-a"] == off["method:card-b"] == on["method:card-a"]
    idf_omega = math.log((2 + 1) / (0 + 1)) + 1.0
    alias_credit = on["method:card-b"] - on["method:card-a"]
    assert alias_credit == pytest.approx(_ALIAS_WEIGHT * 10 * idf_omega, abs=1e-3)
    # Same hit in the weakest authoritative field would have paid strictly more,
    # which is the ordering guarantee the weight exists for.
    assert alias_credit < _FIELD_WEIGHTS["desc"] * 10 * idf_omega


def test_missing_and_empty_aliases_rerun_identically(tmp_path: Path) -> None:
    plain = tmp_path / "plain" / "methods"
    blank = tmp_path / "blank" / "methods"
    corpus = [
        ("card-one", "nightly rollup", "batched aggregation job", "run the scheduled job"),
        ("card-two", "ingest pipeline", "stream into the warehouse", "retry with backoff"),
        ("card-three", "trace topology", "ancestry of spans", "walk the parent chain"),
    ]
    for root, extra in ((plain, ()), (blank, ("aliases:",))):
        for method_id, name, description, body in corpus:
            _write_card(root, method_id, name=name, description=description, body=body, extra=extra)

    plain_store = MethodStore(str(plain))
    blank_store = MethodStore(str(blank))

    # A query that hits nothing is included on purpose: an empty alias channel
    # must not change zero-hit ordering either.
    for query in ("rollup", "ingest pipeline", "walk the parent chain", "zzz-no-such-term"):
        plain_cards = plain_store.list(query, limit=10)
        blank_cards = blank_store.list(query, limit=10)
        assert _keys(plain_cards) == _keys(blank_cards), query
        assert _projection(plain_cards) == _projection(blank_cards), query


def test_update_status_preserves_alias_line_and_other_keys(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    path = _write_card(
        root,
        "card-listed",
        name="listed",
        description="desc kept",
        extra=("aliases: a,b , c", "owner_note: keep-me", "custom_tag: xyz"),
    )

    store = MethodStore(str(root))
    # candidate -> active is a legal one-step transition; status is only a badge.
    updated = store.update_status("method:card-listed", "active")
    assert updated.status == "active"
    assert updated.aliases == ("a", "b", "c")

    raw = path.read_text(encoding="utf-8")
    assert "aliases: a,b , c" in raw
    assert "owner_note: keep-me" in raw
    assert "custom_tag: xyz" in raw
    assert "description: desc kept" in raw
    assert "method_id: card-listed" in raw

    reloaded = store.get("method:card-listed")
    assert reloaded is not None
    assert reloaded.status == "active"
    assert reloaded.aliases == ("a", "b", "c")
    assert reloaded.card()["aliases"] == ["a", "b", "c"]


def test_semantic_candidate_carries_alias_without_extra_spaces(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _write_card(
        root,
        "card-listed",
        name="nightly rollup",
        description="batched aggregation job",
        body="run the scheduled job",
        extra=("aliases: zap, rolling up",),
    )
    _write_card(
        root,
        "card-missing",
        name="other card",
        description="unrelated description",
        body="body text",
    )

    store = MethodStore(str(root))
    listed = store.get("method:card-listed")
    missing = store.get("method:card-missing")
    assert listed is not None and missing is not None

    content = MethodStore.semantic_candidate(listed)["content"]
    assert content == (
        "card-listed nightly rollup zap rolling up batched aggregation job run the scheduled job"
    )
    assert "  " not in content
    # No aliases -> content is byte-identical to the projection before this field.
    assert MethodStore.semantic_candidate(missing)["content"] == (
        "card-missing other card unrelated description body text"
    )


def test_inventory_keyword_matches_alias(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    _write_card(
        root,
        "card-listed",
        name="nightly rollup",
        description="batched aggregation job",
        extra=("aliases: zap",),
    )
    _write_card(root, "card-missing", name="other card", description="unrelated description")

    store = MethodStore(str(root))
    matched = store.inventory("zap")
    assert _keys(matched["records"]) == ["method:card-listed"]
    # counts are pool-wide status totals (query-independent), records are matches.
    assert matched["counts"] == {"candidate": 2}
    assert store.inventory("zzz-no-such-term")["records"] == []
