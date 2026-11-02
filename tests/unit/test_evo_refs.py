"""scripts/check_evo_refs.py 的单测：引用提取、真值源比对、退出码约定。

样例编号一律用 2099 年的假日期 + 全 a/b 哈希，避免与真实演进记录撞号。
全部测试自建 tmp_path 真值源，不读真实 data/、不触网。
"""

import json

import pytest

from scripts.check_evo_refs import (
    LedgerFormatError,
    collect_text_files,
    extract_refs,
    known_ids_from_jsonl,
    main,
    normalize_known_id,
    unknown_refs,
)

FAKE_KNOWN = "EVO-20991231-aaaaaaaa"
FAKE_UNKNOWN = "EVO-20991231-bbbbbbbb"


def _ledger(tmp_path, rows):
    path = tmp_path / "ledger.jsonl"
    lines = [row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _text(tmp_path, name, body):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_extract_refs_finds_and_dedupes():
    texts = [f"见 {FAKE_KNOWN} 与 {FAKE_UNKNOWN}", f"再次 {FAKE_KNOWN}"]
    assert extract_refs(texts) == {FAKE_KNOWN, FAKE_UNKNOWN}


def test_extract_refs_ignores_non_matching_shapes():
    loose = ["EVO-2099-12-31-aaaaaaaa", "EVO-20991231-AAAAAAA", "EVO-E2E-SMOKE-TEST-001"]
    assert extract_refs(loose) == set()


def test_normalize_known_id_folds_dashed_date():
    assert normalize_known_id("EVO-2099-12-31-aaaaaaaa") == FAKE_KNOWN
    assert normalize_known_id(f"  {FAKE_KNOWN}  ") == FAKE_KNOWN


def test_known_ids_reads_both_id_fields_and_skips_blank(tmp_path):
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}, {"suggestion_id": "EVO-2099-12-31-bbbbbbbb"}, ""])
    assert known_ids_from_jsonl(ledger) == {FAKE_KNOWN, FAKE_UNKNOWN}


def test_known_ids_rejects_malformed_line(tmp_path):
    ledger = _ledger(tmp_path, ["{ 不是 JSON"])
    with pytest.raises(LedgerFormatError):
        known_ids_from_jsonl(ledger)


def test_known_ids_rejects_non_object_line(tmp_path):
    ledger = _ledger(tmp_path, ["[1, 2, 3]"])
    with pytest.raises(LedgerFormatError):
        known_ids_from_jsonl(ledger)


def test_unknown_refs_only_reports_failing_sources():
    sources = {"ok.md": f"只有已知 {FAKE_KNOWN}", "bad.md": f"混了 {FAKE_UNKNOWN}"}
    assert unknown_refs(sources, {FAKE_KNOWN}) == {"bad.md": {FAKE_UNKNOWN}}


def test_collect_text_files_recurses_whitelist_and_skips_hidden(tmp_path):
    _text(tmp_path, "docs/a.md", "x")
    _text(tmp_path, "docs/b.bin", "x")
    _text(tmp_path, "docs/.hidden/c.md", "x")
    found = [path.name for path in collect_text_files([tmp_path / "docs"])]
    assert found == ["a.md"]


def test_cli_passes_when_all_refs_known(tmp_path, capsys):
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN}")
    assert main(["--ledger", str(ledger), str(target)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_fails_on_unknown_ref_with_file_and_id(tmp_path, capsys):
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"编造 {FAKE_UNKNOWN}")
    assert main(["--ledger", str(ledger), str(target)]) == 1
    out = capsys.readouterr().out
    assert "BLOCK UNKNOWN" in out
    assert FAKE_UNKNOWN in out
    assert "note.md" in out


def test_cli_missing_ledger_is_undecidable_exit_2(tmp_path, capsys):
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN}")
    code = main(["--ledger", str(tmp_path / "absent.jsonl"), str(target)])
    assert code == 2
    assert "无法判定" in capsys.readouterr().err


def test_cli_missing_ledger_with_allow_missing_degrades_to_zero(tmp_path, capsys):
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN}")
    code = main(["--ledger", str(tmp_path / "absent.jsonl"), "--allow-missing", str(target)])
    assert code == 0


def test_cli_missing_input_path_is_undecidable_exit_2(tmp_path, capsys):
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    assert main(["--ledger", str(ledger), str(tmp_path / "ghost.md")]) == 2
    assert "不存在" in capsys.readouterr().err


def test_cli_malformed_ledger_is_undecidable_exit_2(tmp_path, capsys):
    ledger = _ledger(tmp_path, ["{ 不是 JSON"])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN}")
    assert main(["--ledger", str(ledger), str(target)]) == 2
    assert "无法判定" in capsys.readouterr().err
