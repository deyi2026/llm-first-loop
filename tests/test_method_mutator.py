import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import method_mutator as mm  # noqa: E402

FIXTURE = """---
method_id: fixture-card-000000000000
name: fixture
status: candidate
evidence_refs: [learning:learn:deadbeef]
---
## Trigger
需要判断某机制是否生效时。

## Discriminator
定义处 docstring 已给出当前职责边界。

## Short path
- 用符号名做一次覆盖性 grep，得到候选集
- 检查一下调用点是否存在
- 用符号名做一次覆盖性 grep，得到候选集

## Stop conditions
- 定义处已证明机制不在生效路径

## Verification
- 移除提交 message 与最终决策一致
- 当前树无活跃调用点

## Counterexamples
- 工作副本无 VCS 历史时本方法不适用
"""

# 缺 "## Counterexamples" 段的最小合法卡，用于"缺失段"缺陷路径
MINIMAL = """---
method_id: fixture-card-000000000000
name: fixture
status: candidate
evidence_refs: [learning:learn:deadbeef]
---
## Trigger
需要判断某机制是否生效时。

## Discriminator
定义处 docstring 已给出当前职责边界。

## Short path
- 用符号名做一次覆盖性 grep，得到候选集

## Stop conditions
- 定义处已证明机制不在生效路径

## Verification
- 当前树无活跃调用点
"""


def _write(tmp_path: Path) -> Path:
    d = tmp_path / "fixture-card-000000000000"
    d.mkdir()
    p = d / "METHOD.md"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


def _write_minimal(tmp_path: Path) -> Path:
    """写入缺 '## Counterexamples' 段的最小合法卡。"""
    d = tmp_path / "fixture-card-000000000000"
    d.mkdir()
    p = d / "METHOD.md"
    p.write_text(MINIMAL, encoding="utf-8")
    return p


def test_detects_duplicate_vague_and_unlinked(tmp_path):
    card = mm.parse_card(FIXTURE)
    kinds = {d.kind for d in mm.detect_defects(card)}
    assert "dup_bullet" in kinds
    assert "vague_verb" in kinds
    assert "unlinked_verification" in kinds


def test_frontmatter_is_byte_identical(tmp_path):
    p = _write(tmp_path)
    res = mm.run(p, tmp_path / "out", {"dup", "vague", "unlinked_ver"}, allow_todo=True, dry_run=False)
    assert res["changed"] is True
    out = Path(res["candidate_dir"]) / "METHOD.md"
    before = mm.parse_card(FIXTURE).frontmatter
    after = mm.parse_card(out.read_text(encoding="utf-8")).frontmatter
    assert before == after


def test_duplicate_removed_and_stop_linked(tmp_path):
    p = _write(tmp_path)
    res = mm.run(p, tmp_path / "out", {"dup", "vague", "unlinked_ver"}, allow_todo=True, dry_run=False)
    text = (Path(res["candidate_dir"]) / "METHOD.md").read_text(encoding="utf-8")
    assert text.count("用符号名做一次覆盖性 grep，得到候选集") == 1
    stop_section = text.split("## Stop conditions")[1].split("## Verification")[0]
    assert "Verification 未逐条通过前不结案" in stop_section


def test_todo_requires_explicit_flag(tmp_path):
    p = _write(tmp_path)
    try:
        mm.run(p, tmp_path / "out", {"vague"}, allow_todo=False, dry_run=False)
    except mm.MutatorError as e:
        assert "allow-todo" in str(e)
    else:
        raise AssertionError("vague 变异会引入 TODO，应被拒绝")


def test_idempotent_after_repair(tmp_path):
    p = _write(tmp_path)
    res = mm.run(p, tmp_path / "out", {"dup", "vague", "unlinked_ver"}, allow_todo=True, dry_run=False)
    repaired = Path(res["candidate_dir"]) / "METHOD.md"
    card2 = mm.parse_card(repaired.read_text(encoding="utf-8"))
    kinds2 = [d.kind for d in mm.detect_defects(card2)]
    assert "dup_bullet" not in kinds2
    assert "unlinked_verification" not in kinds2


def test_manifest_and_diff_present(tmp_path):
    p = _write(tmp_path)
    res = mm.run(p, tmp_path / "out", {"dup"}, allow_todo=False, dry_run=False)
    d = Path(res["candidate_dir"])
    man = json.loads((d / "MANIFEST.json").read_text(encoding="utf-8"))
    assert man["review_required"] is True
    assert man["status"] == "candidate"
    assert man["parent_sha256"] == res["parent_sha256"]
    diff = (d / "PATCH.diff").read_text(encoding="utf-8")
    assert diff.startswith("--- a/METHOD.md")
    assert "-" in diff and "+" in diff


def test_unknown_op_rejected(tmp_path, capsys):
    rc = mm.main(["--card", str(_write(tmp_path)), "--ops", "nope"])
    assert rc == 2


def test_missing_frontmatter_refused(tmp_path):
    p = tmp_path / "x" / "METHOD.md"
    p.parent.mkdir()
    p.write_text("## Trigger\n- x\n", encoding="utf-8")
    rc = mm.main(["--card", str(p)])
    assert rc == 3


def test_missing_section_detected_and_placeholder_added(tmp_path):
    """缺段缺陷路径：检出 missing_section，missing 算子只补占位段。"""
    p = _write_minimal(tmp_path)

    missing = [d for d in mm.detect_defects(mm.parse_card(MINIMAL)) if d.kind == "missing_section"]
    assert [d.section for d in missing] == ["Counterexamples"]

    res = mm.run(p, tmp_path / "out", {"missing"}, allow_todo=True, dry_run=False)
    assert res["changed"] is True
    out_text = (Path(res["candidate_dir"]) / "METHOD.md").read_text(encoding="utf-8")

    # 补出的段存在，且只占位不编造内容
    assert "## Counterexamples" in out_text
    assert "TODO(变异器)" in out_text

    # R1 硬约束：frontmatter 字节级不改
    assert mm.parse_card(out_text).frontmatter == mm.parse_card(MINIMAL).frontmatter

    # 幂等：同批算子重跑后缺段缺陷消失
    assert "missing_section" not in {d.kind for d in mm.detect_defects(mm.parse_card(out_text))}


def test_missing_section_needs_allow_todo(tmp_path):
    """缺段修复必然引入 TODO：未显式放行时必须拒绝产出。"""
    p = _write_minimal(tmp_path)
    with pytest.raises(mm.MutatorError) as exc:
        mm.run(p, tmp_path / "out", {"missing"}, allow_todo=False, dry_run=False)
    assert "allow-todo" in str(exc.value)
