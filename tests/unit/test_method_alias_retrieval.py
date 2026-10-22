"""Method alias retrieval contract (2026-10-22 method-alias-retrieval).

Aliases are author-declared synonym / colloquial spellings of *when a card
applies*. They are one extra lexical channel: ranked with name weight, folded
into the semantic candidate text and into the inventory keyword haystack, and
projected on the card only when declared. They never decide applicability, never
grant a use permission, and are unrelated to status (which is only a badge).

Equivalence guard: a card without ``aliases`` must behave exactly like it did
before the field existed; ``test_missing_and_empty_aliases_rerun_identically``
pins that for both ordering and projection.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from llm_loop.methods.store import MethodRecord, MethodStore

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


def test_alias_only_term_ranks_its_card_first(tmp_path: Path) -> None:
    root = tmp_path / "methods"
    # zzz-alias-owner matches the query *only* through its alias: neither id,
    # name, description nor body contain "zap".
    _write_card(
        root,
        "zzz-alias-owner",
        name="nightly rollup",
        description="batched aggregation job",
        body="run the scheduled job",
        extra=("aliases: zap",),
    )
    _write_card(
        root,
        "mmm-body-owner",
        name="other card",
        description="unrelated description",
        body="zap appears in the body only",
    )

    store = MethodStore(str(root))
    assert _keys(store.list("zap", limit=10)) == [
        "method:zzz-alias-owner",
        "method:mmm-body-owner",
    ]


def test_alias_weight_equals_name_weight(tmp_path: Path) -> None:
    """Alias hits weigh exactly like name hits (name weight, no new constant).

    The card projection carries no score, so equality is pinned through the
    documented tie-break: on a single-term query both cards reach the same idf
    weight and the same coverage, so the winner is decided by ``method_id``
    (descending, as in ``list()``). Flipping which side owns the lexicographically
    larger id flips the winner, which only holds while both fields weigh the same
    (an alias weight above name weight would let the alias card win both times).
    """

    def ranking(alias_id: str, name_id: str) -> list[str]:
        root = tmp_path / f"methods-{alias_id}-{name_id}"
        _write_card(root, alias_id, name="nightly rollup", extra=("aliases: zap",))
        _write_card(root, name_id, name="zap collector")
        return _keys(MethodStore(str(root)).list("zap", limit=10))

    assert ranking("aaa-alias-side", "zzz-name-side") == [
        "method:zzz-name-side",
        "method:aaa-alias-side",
    ]
    assert ranking("zzz-alias-side", "aaa-name-side") == [
        "method:zzz-alias-side",
        "method:aaa-name-side",
    ]


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
