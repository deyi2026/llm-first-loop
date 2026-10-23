"""annotate_aliases: the in-band channel for cards that predate aliases.

save_candidate is idempotent and never rewrites, so 1316 of 1372 cards had no way
to gain retrieval hints except hand-editing frontmatter (which bypasses the gate).
This pins the one-key RMW: body byte-identical, aliases gated, merge appends,
replace overwrites, and a fully-dropped request is a no-op instead of a churn.
"""

from __future__ import annotations

import pytest

from llm_loop.methods.store import MethodStore


def _card(store: MethodStore, name: str, body: str = "## Trigger\n持久正文不应被改动\n") -> str:
    record = store.save_candidate(
        name=name, description=f"{name} 的描述行", body=body
    )
    return record.method_ref


def test_merge_appends_and_keeps_body(tmp_path):
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate alpha probe")
    before = (tmp_path / ref.removeprefix("method:") / "METHOD.md").read_text(encoding="utf-8")
    record, dropped = store.annotate_aliases(ref, ["顺序搞反了", "写入路径"], mode="merge")
    after = (tmp_path / ref.removeprefix("method:") / "METHOD.md").read_text(encoding="utf-8")
    assert list(record.aliases) == ["顺序搞反了", "写入路径"]
    assert dropped == []
    assert before.split("---\n", 2)[2] == after.split("---\n", 2)[2], "body must stay byte-identical"


def test_merge_preserves_existing_then_appends(tmp_path):
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate beta probe")
    store.annotate_aliases(ref, ["已有的别名"], mode="merge")
    record, _ = store.annotate_aliases(ref, ["新增的别名"], mode="merge")
    assert list(record.aliases) == ["已有的别名", "新增的别名"]


def test_replace_overwrites(tmp_path):
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate gamma probe")
    store.annotate_aliases(ref, ["旧的别名"], mode="merge")
    record, _ = store.annotate_aliases(ref, ["新的别名"], mode="replace")
    assert list(record.aliases) == ["新的别名"]


def test_all_dropped_is_a_noop_not_a_churn(tmp_path):
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate delta probe")
    _, first = store.annotate_aliases(ref, ["有效别名一", "有效别名二"], mode="merge")
    path = tmp_path / ref.removeprefix("method:") / "METHOD.md"
    stamp = path.stat().st_mtime_ns
    record, dropped = store.annotate_aliases(ref, ["method", "ab"], mode="merge")
    assert list(record.aliases) == ["有效别名一", "有效别名二"]
    assert {d["reason"] for d in dropped} == {"generic", "too_short"}
    assert path.stat().st_mtime_ns == stamp, "a fully-dropped write must not touch the file"


def test_unknown_card_raises(tmp_path):
    store = MethodStore(tmp_path)
    with pytest.raises(ValueError):
        store.annotate_aliases("method:nope-000000000000", ["别名三字"], mode="merge")


def test_bad_mode_raises(tmp_path):
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate epsilon probe")
    with pytest.raises(ValueError):
        store.annotate_aliases(ref, ["别名三字"], mode="append")


def test_replace_with_nothing_kept_refuses_instead_of_wiping(tmp_path):
    """Review P1 (2nd round): an all-dropped replace must not silently empty the card.

    `aliases: ` round-trips as an empty string, so the round-trip guard cannot see the
    difference between "no aliases requested" and "every alias was rejected".
    """
    store = MethodStore(tmp_path)
    ref = _card(store, "annotate zeta probe")
    store.annotate_aliases(ref, ["保留的别名"], mode="merge")
    with pytest.raises(ValueError, match="refusing to replace"):
        store.annotate_aliases(ref, ["ab"], mode="replace")
    record = store.get(ref)
    assert list(record.aliases) == ["保留的别名"], "existing aliases must survive the refusal"
