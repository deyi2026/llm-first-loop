"""Alias write-path contract (2026-10-23 method-alias-write-path).

Aliases used to be a manual after-the-fact backfill: the pool had 72 aliased cards
out of 1369, and new cards never carried any. This module pins the fix — aliases
are part of the write path, and every write passes a mechanical discrimination
gate (length / lifecycle-generic / duplicate / document frequency / cap) so a
noisy hint can never become durable state.

Separator characters (comma / colon / hash / newline) are refused for a second
reason: aliases are joined into one YAML scalar, so a separator would either split
into bogus aliases or forge a frontmatter key on the way back in.

The gate is not cosmetic: measured on the real pool (337 aliases), 333 had df=1
while three carried df=4/11/66 (cross-card symbols such as ``action_id``). Those
are exactly the aliases that let an unrelated card ride a query term, so the
threshold is calibrated on that distribution rather than guessed.

Equivalence guard: a write *without* aliases must remain byte-identical to the
pre-feature rendering, including key order and the absence of an empty key.
"""

from __future__ import annotations

from llm_loop.methods import store as store_module
from llm_loop.methods.reflection import validate_candidate
from llm_loop.methods.store import MethodStore, alias_df_threshold, gate_aliases


def _candidate(store: MethodStore, name: str, *, body: str = "## Trigger\n测试触发条件足够长\n", **kwargs):
    return store.save_candidate(
        name=name,
        description=f"{name} 的描述行用于区分",
        body=body,
        **kwargs,
    )


def _frontmatter(text: str) -> list[str]:
    lines = text.split("---\n")[1].strip("\n").splitlines()
    return [line.split(":", 1)[0] for line in lines]


def test_aliases_land_after_description(tmp_path):
    store = MethodStore(tmp_path)
    record = _candidate(
        store,
        "alias write probe alpha",
        aliases=["把顺序搞反了", "写入路径自检"],
    )
    text = (tmp_path / record.method_id / "METHOD.md").read_text(encoding="utf-8")
    keys = _frontmatter(text)
    assert keys.index("aliases") == keys.index("description") + 1
    assert list(record.aliases) == ["把顺序搞反了", "写入路径自检"]
    assert "aliases: 把顺序搞反了, 写入路径自检" in text


def test_no_alias_write_keeps_legacy_rendering(tmp_path):
    store = MethodStore(tmp_path)
    record = _candidate(store, "alias free probe beta")
    text = (tmp_path / record.method_id / "METHOD.md").read_text(encoding="utf-8")
    assert "aliases" not in text
    assert _frontmatter(text) == [
        "method_id",
        "name",
        "description",
        "status",
        "created_at",
        "updated_at",
    ]
    assert "\n\n\n" not in text


def test_gate_reasons_are_first_match():
    corpus = [store_module._alias_text("x" * 10)]
    kept, dropped = gate_aliases(
        ["ab", "candidate", "dup name", "dup name", "唯一的说法"],
        name="dup name",
        corpus=corpus,
        pool_size=100,
    )
    assert kept == ["唯一的说法"]
    assert [d["reason"] for d in dropped] == [
        "too_short",
        "generic",
        "duplicate",
        "duplicate",
    ]


def test_gate_drops_low_discrimination_and_respects_cap():
    corpus = [store_module._alias_text(f"card {i} action_id") for i in range(6)]
    kept, dropped = gate_aliases(
        ["action_id", "独有的说法一", "独有的说法二"],
        name="cap probe",
        corpus=corpus,
        pool_size=100,
    )
    assert kept == ["独有的说法一", "独有的说法二"]
    assert dropped[0]["reason"] == "low_discrimination"
    assert dropped[0]["df"] == 6

    kept_many, dropped_many = gate_aliases(
        [f"短语{i}号" for i in range(9)],
        name="cap probe two",
        corpus=[],
        pool_size=3,
    )
    assert len(kept_many) == store_module._ALIAS_MAX_PER_CARD
    assert {d["reason"] for d in dropped_many} == {"cap"}


def test_store_gate_uses_live_pool_frequency(tmp_path):
    store = MethodStore(tmp_path)
    for i in range(5):
        _candidate(store, f"filler card {i}", body=f"## Trigger\naction_id 出现在这张填充卡 {i} 里\n")
    drops: list[dict] = []
    record = _candidate(
        store,
        "gate live pool probe",
        aliases=["action_id", "只此一家的说法"],
        alias_drops=drops,
    )
    assert list(record.aliases) == ["只此一家的说法"]
    assert [d["reason"] for d in drops] == ["low_discrimination"]
    assert drops[0]["df"] == 5


def test_update_status_keeps_alias_and_position(tmp_path):
    store = MethodStore(tmp_path)
    record = _candidate(store, "status flip probe", aliases=["状态翻转后仍在"])
    updated = store.update_status(record.method_ref, "hold")
    text = (tmp_path / updated.method_id / "METHOD.md").read_text(encoding="utf-8")
    keys = _frontmatter(text)
    assert keys.index("aliases") == keys.index("description") + 1
    assert "aliases: 状态翻转后仍在" in text


def test_alias_is_retrievable_after_write(tmp_path):
    store = MethodStore(tmp_path)
    _candidate(store, "unrelated neighbour card", body="## Trigger\n与目标查询毫无关系的正文\n")
    record = _candidate(store, "commit ordering probe", aliases=["别把主干往回拖"])
    hits = store.list("别把主干往回拖", limit=5)
    assert hits and hits[0]["id"] == record.method_id


def test_validate_candidate_alias_shape():
    base = {
        "decision": "candidate",
        "name": "probe",
        "description": "probe description",
        "trigger": "when probe",
        "discriminator": "probe discriminator",
        "short_path": ["step"],
        "stop_conditions": ["stop"],
        "verification": ["check"],
        "counterexamples": ["bad"],
    }
    ok, errors = validate_candidate(dict(base))
    assert ok and errors == []

    ok_empty, errors_empty = validate_candidate({**base, "aliases": []})
    assert ok_empty and errors_empty == []

    ok_shape, errors_shape = validate_candidate({**base, "aliases": "not a list"})
    assert not ok_shape
    assert any("aliases must be a list" in e for e in errors_shape)

    ok_long, errors_long = validate_candidate({**base, "aliases": ["a" * 61]})
    assert not ok_long
    assert any("exceeds 60 chars" in e for e in errors_long)


def test_df_threshold_follows_the_measured_calibration():
    """The threshold is a calibration on the measured df distribution, not a guess.

    Measured 2026-10-23: 337 real aliases, 333 of them df=1, three noise symbols at
    df=4/11/66. The ladder widens with the pool but never leaves [2, 5]; pin it so a
    silent re-tuning can only change which aliases survive together with a red test.
    """
    assert alias_df_threshold(0) == 2
    assert alias_df_threshold(400) == 2
    assert alias_df_threshold(1199) == 2
    assert alias_df_threshold(1200) == 3
    assert alias_df_threshold(1600) == 4
    assert alias_df_threshold(2000) == 5
    assert alias_df_threshold(100_000) == 5


def test_df_boundary_keeps_at_threshold_and_drops_one_more():
    """df == threshold survives, df == threshold + 1 does not. The boundary is the
    whole contract: an off-by-one here silently re-admits cross-card symbols."""
    corpus = ["probe needle", "probe needle"]
    kept, dropped = gate_aliases(
        ["needle"], name="boundary probe", corpus=corpus, pool_size=800
    )
    assert kept == ["needle"]
    assert dropped == []

    kept_one_more, dropped_one_more = gate_aliases(
        ["needle"], name="boundary probe", corpus=[*corpus, "probe needle"], pool_size=800
    )
    assert kept_one_more == []
    assert [d["reason"] for d in dropped_one_more] == ["low_discrimination"]
    assert dropped_one_more[0]["df"] == 3


def test_alias_equal_to_the_card_name_is_a_duplicate():
    """An alias that merely repeats the card's own name opens no retrieval channel;
    it must not survive as a second copy of the authoritative field."""
    kept, dropped = gate_aliases(["dup name"], name="dup name", corpus=[], pool_size=100)
    assert kept == []
    assert [d["reason"] for d in dropped] == ["duplicate"]

    kept_case, dropped_case = gate_aliases(
        ["Dup Name"], name="dup name", corpus=[], pool_size=100
    )
    assert kept_case == []
    assert [d["reason"] for d in dropped_case] == ["duplicate"]


def test_duplicate_detection_is_normalization_insensitive():
    """Duplicates are judged on the normalized form, so a case or spacing variant
    cannot smuggle the same phrase into the card twice."""
    kept, dropped = gate_aliases(
        ["Foo Bar", "foo  bar"], name="norm probe", corpus=[], pool_size=100
    )
    assert kept == ["Foo Bar"]
    assert [d["reason"] for d in dropped] == ["duplicate"]


def test_blank_alias_is_absent_input_not_a_rejected_alias():
    """A blank string is absent input, not a rejected alias: it must show up neither
    in kept nor in the drop report, or every writer sees phantom rejections."""
    kept, dropped = gate_aliases(["   ", ""], name="blank probe", corpus=[], pool_size=100)
    assert kept == []
    assert dropped == []


def test_separator_aliases_never_reach_the_frontmatter(tmp_path):
    """Aliases are joined into one YAML scalar, so a comma / colon / hash / newline
    would either split into bogus aliases or forge a frontmatter key. The gate must
    drop them at write time, and the stored card must re-parse to exactly the kept
    aliases."""
    store = MethodStore(tmp_path)
    drops: list[dict] = []
    record = _candidate(
        store,
        "separator probe",
        aliases=["合法别名甲", "逗号,后截断", "换行\n伪键: 值"],
        alias_drops=drops,
    )
    text = (tmp_path / record.method_id / "METHOD.md").read_text(encoding="utf-8")
    assert list(record.aliases) == ["合法别名甲"]
    assert [d["reason"] for d in drops] == ["unsafe_chars", "unsafe_chars"]
    assert store.get(record.method_ref).aliases == ("合法别名甲",)
    assert _frontmatter(text) == [
        "method_id",
        "name",
        "description",
        "aliases",
        "status",
        "created_at",
        "updated_at",
    ]
    assert "逗号" not in text
    assert "伪键" not in text
