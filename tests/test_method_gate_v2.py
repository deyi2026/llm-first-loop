"""v2 判据的确定性校验测试：判定与校验分离，校验部分必须可回归。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import method_gate_v2 as gv  # noqa: E402
from scripts import method_mutator as mm  # noqa: E402

CARD = """---
method_id: fixture-v2
source_refs:
  - fixture
---

## Steps

- 逐步执行

## Verification

- 观察 A：直接读取退出码
- 观察 B：记录耗时用于归档

## Stop conditions

- Verification 未逐条通过前不结案
- 观察 A 已读取且退出码为 0 ⇒ 闭环
"""


def _row(card_text, labels):
    card = mm.parse_card(card_text)
    items = gv.verification_items(card)
    return {
        "pair_id": "P00",
        "card_sha": gv.card_sha(card_text),
        "items": [
            {
                "i": i + 1,
                "text_sha": gv.item_sha(t),
                "text": t,
                "label": labels[i][0],
                "witness_stop": labels[i][1] if len(labels[i]) > 1 else None,
                "inherited": False,
                "note": "",
            }
            for i, t in enumerate(items)
        ],
    }


def test_gate_rule_cannot_back_a_covered_item():
    row = _row(CARD, [("covered", 1), ("covered", 2)])
    errs = gv.validate_row(row, CARD, mm.parse_card(CARD))
    assert any("通用门禁句" in e for e in errs), errs
    assert not any("V2" in e for e in errs), errs  # 第二条 witness STOP2 是具体观察


def test_stale_card_is_rejected():
    row = _row(CARD, [("covered", 2), ("auxiliary",)])
    edited = CARD.replace("记录耗时用于归档", "记录耗时并归档")
    errs = gv.validate_row(row, edited, mm.parse_card(edited))
    assert any("stale" in e or "哈希不匹配" in e for e in errs), errs


def test_open_item_becomes_a_defect_aux_does_not(tmp_path):
    card_dir = tmp_path / "cards"
    card_dir.mkdir()
    card_path = card_dir / "METHOD.md"
    card_path.write_text(CARD, encoding="utf-8")
    cards = tmp_path / "cards.jsonl"
    cards.write_text(
        json.dumps({"pair_id": "P00", "family": "F1", "path": str(card_path)}) + "\n",
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "cards": {
                    "P00": {
                        "1": {"label": "open", "note": "无停止条件要求退出码"},
                        "2": {"label": "auxiliary", "note": "归档规范"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    res = gv.scan(cards, spec)
    assert res["summary"]["true_gap"] == 1
    assert res["summary"]["open_items_total"] == 1
    assert [it["i"] for it in res["results"][0]["open_items"]] == [1]


def test_repair_must_name_observable_and_not_be_gate_rule(tmp_path):
    card_path = tmp_path / "METHOD.md"
    card_path.write_text(CARD, encoding="utf-8")
    cards = tmp_path / "cards.jsonl"
    cards.write_text(
        json.dumps({"pair_id": "P00", "path": str(card_path)}) + "\n", encoding="utf-8"
    )
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"repairs": {"P00": {"observable_terms": ["退出码"], "bullets": ["验证通过即可"]}}}),
        encoding="utf-8",
    )
    with pytest.raises(gv.GateError):
        gv.apply_repairs(bad, cards, tmp_path / "out")

    gate = tmp_path / "gate.json"
    gate.write_text(
        json.dumps(
            {"repairs": {"P00": {"observable_terms": ["Verification"], "bullets": ["Verification 未逐条通过前不结案"]}}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(gv.GateError):
        gv.apply_repairs(gate, cards, tmp_path / "out")


def test_repair_only_appends_to_stop_conditions(tmp_path):
    card_path = tmp_path / "METHOD.md"
    card_path.write_text(CARD, encoding="utf-8")
    cards = tmp_path / "cards.jsonl"
    cards.write_text(
        json.dumps({"pair_id": "P00", "path": str(card_path)}) + "\n", encoding="utf-8"
    )
    rep = tmp_path / "rep.json"
    bullet = "退出码未经直接读取时不得宣布通过"
    rep.write_text(
        json.dumps({"repairs": {"P00": {"observable_terms": ["退出码"], "bullets": [bullet]}}}),
        encoding="utf-8",
    )
    res = gv.apply_repairs(rep, cards, tmp_path / "out")
    new_text = (tmp_path / "out" / "P00" / "METHOD.md").read_text(encoding="utf-8")
    old, new = mm.parse_card(CARD), mm.parse_card(new_text)
    assert old.frontmatter == new.frontmatter
    assert gv.verification_items(old) == gv.verification_items(new)
    assert gv.stop_items(new)[: len(gv.stop_items(old))] == gv.stop_items(old)
    assert bullet in gv.stop_items(new)
    assert not mm.GATE_RULE.search(bullet)
    assert res["applied"][0]["pair_id"] == "P00"
