"""scripts/check_evo_refs.py 的单测：引用提取、真值源比对、退出码约定。

样例编号一律用 2099 年的假日期 + 全 a/b 哈希，避免与真实演进记录撞号。
全部测试自建 tmp_path 真值源，不读真实 data/、不触网。
"""

import json

import pytest

from scripts.check_evo_refs import (
    Baseline,
    LedgerFormatError,
    baseline_violations,
    collect_text_files,
    extract_refs,
    history_refs_from_text,
    known_ids_from_jsonl,
    load_baseline,
    load_baseline_table,
    main,
    normalize_known_id,
    unknown_refs,
)

FAKE_KNOWN = "EVO-20991231-aaaaaaaa"
FAKE_UNKNOWN = "EVO-20991231-bbbbbbbb"
# 过去日期的"历史欠账"形状：可被豁免表登记（对照未来日期哨兵永远不被豁免）。
LEGACY_ID = "EVO-20200101-abcdef01"
LEGACY_ID_2 = "EVO-20200102-abcdef02"


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


# ---- 2026-11-02：窗口外真编号回溯 + 豁免表（append-only baseline）----


def test_history_refs_from_text_extracts_ids_from_commit_body():
    blob = f"feat: x\n\nEVO-20260814-39a10097 与 {FAKE_KNOWN}\n"
    assert history_refs_from_text(blob) == {"EVO-20260814-39a10097", FAKE_KNOWN}


def test_load_baseline_missing_file_is_empty_not_blanket_exempt(tmp_path):
    assert load_baseline(tmp_path / "absent.json") == set()


def test_load_baseline_malformed_warns_and_stays_empty(tmp_path, capsys):
    broken = tmp_path / "baseline.json"
    broken.write_text("{ 不是 JSON", encoding="utf-8")
    assert load_baseline(broken) == set()
    assert "按空表处理" in capsys.readouterr().err


def test_load_baseline_keeps_case_so_entries_actually_match(tmp_path):
    """曾经把条目 upper() 过：extract_refs 产出小写后缀 → 豁免表 100% 不命中."""
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps({"exempt": ["EVO-20260814-39a10097"]}), encoding="utf-8")
    assert "EVO-20260814-39a10097" in load_baseline(path)


def test_cli_baseline_exempts_legacy_but_still_blocks_new_fabrication(tmp_path, capsys):
    legacy = LEGACY_ID
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"旧引用 {legacy} 新编造 {FAKE_UNKNOWN}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"exempt": [legacy]}), encoding="utf-8")
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", str(target)]
    assert main(argv) == 1
    out = capsys.readouterr().out
    assert FAKE_UNKNOWN in out
    assert legacy not in out


def test_cli_regen_baseline_denies_unattested_ids(tmp_path, capsys):
    """重登记不再"一次性洗白"：无出处的编号不写入，豁免表原样不动（2026-11-02 复盘）."""
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN} 欠账 {LEGACY_ID}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"quota": 0, "frozen": [], "exempt": []}), encoding="utf-8"
    )
    before = baseline.read_text(encoding="utf-8")
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", "--regen-baseline"]
    assert main([*argv, str(target)]) == 1
    assert "BLOCK UNATTESTED" in capsys.readouterr().out
    assert baseline.read_text(encoding="utf-8") == before, "被拒时不得留下半张豁免表"


def test_cli_regen_baseline_refuses_future_dated_ids(tmp_path, capsys):
    """未来日期不可能是历史欠账：登记时跳过，之后仍被拦（防"一次 regen 洗白编造"）."""
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_UNKNOWN}")
    baseline = tmp_path / "baseline.json"
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", "--regen-baseline"]
    assert main([*argv, str(target)]) == 0
    assert "跳过 1 个未来日期编号" in capsys.readouterr().err
    assert json.loads(baseline.read_text(encoding="utf-8"))["exempt"] == []


def test_cli_no_history_skips_git_probe(tmp_path, monkeypatch):
    def _boom(_root):
        raise AssertionError("--no-history 时不得探测 git 历史")

    monkeypatch.setattr("scripts.check_evo_refs.git_history_refs", _boom)
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_KNOWN}")
    assert main(["--ledger", str(ledger), "--no-history", str(target)]) == 0


# ---- 2026-11-02：豁免表只许减不许增（quota / frozen / 出处三判据）----


def test_load_baseline_table_reads_quota_and_frozen(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(
        json.dumps({"quota": 2, "frozen": [LEGACY_ID], "exempt": [LEGACY_ID, LEGACY_ID_2]}),
        encoding="utf-8",
    )
    table = load_baseline_table(path)
    assert table.quota == 2
    assert table.frozen == {LEGACY_ID}
    assert table.exempt == {LEGACY_ID, LEGACY_ID_2}


def test_load_baseline_table_v1_has_no_frozen_or_quota(tmp_path):
    """v1 缺 frozen/quota 时必须如实为 None/空，不得假装满足判据."""
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"exempt": [LEGACY_ID]}), encoding="utf-8")
    table = load_baseline_table(path)
    assert table.quota is None and table.frozen == frozenset()
    assert table.exempt == {LEGACY_ID}


def test_baseline_violations_flags_future_dated_entry():
    table = Baseline(exempt=frozenset({FAKE_UNKNOWN}), frozen=frozenset({FAKE_UNKNOWN}), quota=1)
    assert any("未来日期" in p for p in baseline_violations(table, set()))


def test_baseline_violations_flags_quota_growth():
    table = Baseline(
        exempt=frozenset({LEGACY_ID, LEGACY_ID_2}), frozen=frozenset({LEGACY_ID}), quota=1
    )
    assert any("超配额" in p for p in baseline_violations(table, set()))


def test_baseline_violations_flags_addition_without_provenance():
    table = Baseline(exempt=frozenset({LEGACY_ID}), frozen=frozenset(), quota=1)
    assert any("无出处" in p for p in baseline_violations(table, set()))
    # 能回溯到提交信息就不算违规（出处=git 历史里的编号）
    assert baseline_violations(table, {LEGACY_ID}) == []
    # 读不到历史时不做该判定（无从判断≠合规，CLI 另行降级告警）
    assert baseline_violations(table, None) == []


def test_cli_denies_future_dated_baseline_entry(tmp_path, capsys):
    """历史欠账不可能是未来日期：手改豁免表把它塞进来也必须被拦."""
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {FAKE_UNKNOWN}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"quota": 1, "frozen": [FAKE_UNKNOWN], "exempt": [FAKE_UNKNOWN]}),
        encoding="utf-8",
    )
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", str(target)]
    assert main(argv) == 1
    assert "未来日期豁免" in capsys.readouterr().err


def test_cli_denies_baseline_quota_growth(tmp_path, capsys):
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {LEGACY_ID} {LEGACY_ID_2}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"quota": 1, "frozen": [LEGACY_ID], "exempt": [LEGACY_ID, LEGACY_ID_2]}
        ),
        encoding="utf-8",
    )
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", str(target)]
    assert main(argv) == 1
    assert "超配额" in capsys.readouterr().err


def test_cli_denies_baseline_entry_without_provenance(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("scripts.check_evo_refs.git_history_refs", lambda _root: set())
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {LEGACY_ID}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"quota": 1, "frozen": [], "exempt": [LEGACY_ID]}), encoding="utf-8"
    )
    # 不传 --no-history：history=set() 参与判定，豁免条目必须能在提交信息里找到
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), str(target)]
    assert main(argv) == 1
    assert "无出处豁免" in capsys.readouterr().err


def test_cli_adopt_legacy_baseline_upgrades_to_v2(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"exempt": [LEGACY_ID_2, LEGACY_ID]}), encoding="utf-8")
    assert main(["--baseline", str(baseline), "--adopt-legacy-baseline"]) == 0
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["quota"] == 2
    assert payload["frozen"] == payload["exempt"] == [LEGACY_ID, LEGACY_ID_2]
    # 已是 v2：重复迁移必须确定性拒绝，不静默重冻结（否则冻结基线可被无限后移）
    assert main(["--baseline", str(baseline), "--adopt-legacy-baseline"]) == 2
    assert "拒绝重复迁移" in capsys.readouterr().err


def test_cli_regen_keeps_frozen_and_ratchets_quota_down(tmp_path, capsys):
    """只许减不许增：树上已消失的旧豁免退场，quota 随实际条数下调."""
    ledger = _ledger(tmp_path, [{"id": FAKE_KNOWN}])
    target = _text(tmp_path, "note.md", f"引用 {LEGACY_ID}")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"quota": 5, "frozen": [LEGACY_ID, LEGACY_ID_2], "exempt": [LEGACY_ID, LEGACY_ID_2]}
        ),
        encoding="utf-8",
    )
    argv = ["--ledger", str(ledger), "--baseline", str(baseline), "--no-history", "--regen-baseline"]
    assert main([*argv, str(target)]) == 0
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert payload["exempt"] == [LEGACY_ID]
    assert payload["quota"] == 1, "quota 必须随条目收紧，不得保留旧上限"
