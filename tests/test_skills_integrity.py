"""技能完整性清单 + 不可信来源标注测试（P1-5/S2-4，docs/安全审查与修复建议书-2026-10-25.md）.

覆盖:
- 四态判定: manifest 登记且一致=ok；正文单字节篡改=modified；新增未登记=unlisted；
  无 manifest（含损坏/版本不符 manifest）=unmanaged；默认 scan 全部返回（零回归）
- 门禁: LFL_SKILLS_REQUIRE_MANIFEST=1 时 modified/unlisted/unmanaged 拒载
  （错误含审批指引），ok 放行；未开启时加载并在回执标注 integrity=<状态> + 告警日志
- 注入: provenance banner 存在且位于正文之前
- 人工审批入口: scripts/approve_skills.py 落盘清单后原 modified 转 ok（门禁下恢复可用）
- 真实仓库目录零回归: 现有技能在无 manifest 下仍可扫描/加载（unmanaged 仅标注）
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.tools_skill_files import run_skill_load
from llm_loop.skills.loader import (
    INTEGRITY_MODIFIED,
    INTEGRITY_OK,
    INTEGRITY_UNLISTED,
    INTEGRITY_UNMANAGED,
    MANIFEST_FILENAME,
    SKILL_PROVENANCE_BANNER,
    build_manifest,
    load_manifest,
    scan_skills_dir,
    write_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_ENV = "LFL_SKILLS_REQUIRE_MANIFEST"
NON_OK_STATES = [INTEGRITY_MODIFIED, INTEGRITY_UNLISTED, INTEGRITY_UNMANAGED]


@pytest.fixture(autouse=True)
def _clean_gate_env(monkeypatch):
    """隔离宿主环境的门禁开关（测试只在受控开关状态下判定）."""
    monkeypatch.delenv(GATE_ENV, raising=False)


def _mk_skill(skills_dir: Path, name: str, body: str = "正文步骤 A。") -> Path:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "SKILL.md"
    f.write_text(
        f"---\nname: {name}\ndescription: {name} 的描述\n---\n{body}",
        encoding="utf-8",
    )
    return f


def _flip_body_byte(f: Path) -> None:
    """单字节级篡改（正文内翻转一个 ASCII 字节；UTF-8 与 frontmatter 保持完好）."""
    data = f.read_bytes()
    i = data.index(b"A")
    f.write_bytes(data[:i] + b"B" + data[i + 1 :])


def _host(skills_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(skills_dir=str(skills_dir))


def _state(metas: list, name: str):
    return next(m for m in metas if m.name == name)


def _dir_in_state(tmp_path: Path, state: str) -> tuple[Path, str]:
    """构造目标技能处于指定完整性状态的目录; 返回 (skills_dir, 待加载技能名)."""
    skills = tmp_path / f"s-{state}"
    f = _mk_skill(skills, "target")
    if state == INTEGRITY_UNMANAGED:
        return skills, "target"
    write_manifest(skills)
    if state == INTEGRITY_MODIFIED:
        _flip_body_byte(f)
        return skills, "target"
    assert state == INTEGRITY_UNLISTED
    _mk_skill(skills, "sneaky")  # 清单登记后新增 → 未登记
    return skills, "sneaky"


# ── 四态判定（loader）───────────────────────────────────────────────────────


class TestIntegrityStates:
    def test_manifest_covered_skill_is_ok(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        _mk_skill(skills, "beta")
        write_manifest(skills)
        metas = scan_skills_dir(skills)
        assert len(metas) == 2  # 零回归: 清单不改变返回集合
        assert _state(metas, "alpha").integrity == INTEGRITY_OK
        assert _state(metas, "beta").integrity == INTEGRITY_OK
        assert "sha256" in _state(metas, "alpha").integrity_detail

    def test_single_byte_change_is_modified(self, tmp_path):
        skills = tmp_path / "skills"
        f = _mk_skill(skills, "alpha")
        write_manifest(skills)
        _flip_body_byte(f)  # 改一个字节
        meta = scan_skills_dir(skills)[0]
        assert meta.integrity == INTEGRITY_MODIFIED
        assert "不一致" in meta.integrity_detail

    def test_new_skill_not_listed_is_unlisted(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        write_manifest(skills)
        _mk_skill(skills, "sneaky", body="# 后门正文")  # 新增未登记
        metas = scan_skills_dir(skills)
        assert _state(metas, "alpha").integrity == INTEGRITY_OK
        assert _state(metas, "sneaky").integrity == INTEGRITY_UNLISTED

    def test_no_manifest_is_unmanaged_and_still_returned(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        metas = scan_skills_dir(skills)
        assert len(metas) == 1  # 默认零回归: 全部返回，不因缺 manifest 阻断
        assert metas[0].integrity == INTEGRITY_UNMANAGED
        assert MANIFEST_FILENAME in metas[0].integrity_detail

    def test_corrupt_manifest_treated_as_unmanaged(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        (skills / MANIFEST_FILENAME).write_text("{ 不是 JSON", encoding="utf-8")
        assert scan_skills_dir(skills)[0].integrity == INTEGRITY_UNMANAGED

    def test_bad_manifest_version_treated_as_unmanaged(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        (skills / MANIFEST_FILENAME).write_text(
            '{"version": 99, "skills": {}}', encoding="utf-8"
        )
        assert scan_skills_dir(skills)[0].integrity == INTEGRITY_UNMANAGED

    def test_explicit_manifest_param(self, tmp_path):
        skills = tmp_path / "skills"
        f = _mk_skill(skills, "alpha")
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        metas = scan_skills_dir(
            skills, manifest={"version": 1, "skills": {"alpha": {"sha256": digest}}}
        )
        assert metas[0].integrity == INTEGRITY_OK

    def test_manifest_structure_and_roundtrip(self, tmp_path):
        skills = tmp_path / "skills"
        f = _mk_skill(skills, "alpha")
        manifest = build_manifest(skills)
        assert manifest["version"] == 1
        entry = manifest["skills"]["alpha"]
        assert entry["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
        assert entry["approved_at"]  # ISO 时间戳存在
        write_manifest(skills, manifest)
        assert load_manifest(skills) == manifest
        assert load_manifest(tmp_path / "nowhere") is None


# ── 加载门禁与注入标注（run_skill_load）────────────────────────────────────


class TestLoadGate:
    @pytest.mark.parametrize("state", NON_OK_STATES)
    def test_gate_on_rejects_non_ok(self, tmp_path, monkeypatch, state):
        monkeypatch.setenv(GATE_ENV, "1")
        skills, name = _dir_in_state(tmp_path, state)
        r = run_skill_load(_host(skills), {"name": name})
        assert r.status == ToolResultStatus.FAILURE
        assert f"integrity={state}" in r.content
        assert "运行 scripts/approve_skills.py 重新审批" in r.content
        assert SKILL_PROVENANCE_BANNER not in r.content  # 拒载时不注入正文

    def test_gate_on_allows_approved_ok_skill(self, tmp_path, monkeypatch):
        monkeypatch.setenv(GATE_ENV, "1")
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        write_manifest(skills)
        r = run_skill_load(_host(skills), {"name": "alpha"})
        assert r.status == ToolResultStatus.SUCCESS
        assert "integrity=ok" in r.content

    @pytest.mark.parametrize("state", NON_OK_STATES)
    def test_gate_off_loads_with_annotation(self, tmp_path, monkeypatch, state):
        monkeypatch.delenv(GATE_ENV, raising=False)
        skills, name = _dir_in_state(tmp_path, state)
        r = run_skill_load(_host(skills), {"name": name})
        assert r.status == ToolResultStatus.SUCCESS  # 默认零回归: 仅标注不阻断
        assert f"integrity={state}" in r.content
        assert SKILL_PROVENANCE_BANNER in r.content

    def test_gate_off_logs_warning_for_non_ok(self, tmp_path, caplog):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha")
        with caplog.at_level("WARNING"):
            r = run_skill_load(_host(skills), {"name": "alpha"})
        assert r.status == ToolResultStatus.SUCCESS
        assert any(
            INTEGRITY_UNMANAGED in rec.getMessage() for rec in caplog.records
        )

    def test_banner_precedes_body(self, tmp_path):
        skills = tmp_path / "skills"
        _mk_skill(skills, "alpha", body="正文步骤 A。")
        write_manifest(skills)
        r = run_skill_load(_host(skills), {"name": "alpha"})
        assert r.status == ToolResultStatus.SUCCESS
        banner_at = r.content.index(SKILL_PROVENANCE_BANNER)
        marker_at = r.content.index("--- SKILL.md 全文 ---")
        body_at = r.content.index("正文步骤 A。")
        assert banner_at < marker_at < body_at  # banner 在正文之前
        assert r.content.count(SKILL_PROVENANCE_BANNER) == 1


# ── 人工审批入口（scripts/approve_skills.py）────────────────────────────────


class TestApproveScript:
    def test_approve_revalidates_modified_skill(self, tmp_path, monkeypatch):
        skills = tmp_path / "skills"
        f = _mk_skill(skills, "target")
        write_manifest(skills)
        _flip_body_byte(f)  # 单字节篡改 → modified
        assert scan_skills_dir(skills)[0].integrity == INTEGRITY_MODIFIED

        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "approve_skills.py"),
                str(skills),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert "审批完成" in proc.stdout
        assert load_manifest(skills) is not None
        assert scan_skills_dir(skills)[0].integrity == INTEGRITY_OK  # 重审批转 ok

        monkeypatch.setenv(GATE_ENV, "1")
        r = run_skill_load(_host(skills), {"name": "target"})
        assert r.status == ToolResultStatus.SUCCESS  # 门禁下恢复可用
        assert "integrity=ok" in r.content

    def test_approve_script_fails_on_missing_dir(self, tmp_path):
        proc = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "approve_skills.py"),
                str(tmp_path / "nope"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 1
        assert "不存在" in proc.stderr


# ── 真实仓库目录零回归（无 manifest 时不影响现有技能可用性）─────────────────


class TestRealRepoZeroRegression:
    def test_real_skills_still_scannable_and_loadable(self, monkeypatch):
        skills = REPO_ROOT / "skills"
        metas = scan_skills_dir(skills)
        assert len(metas) >= 30  # 当前 37 个；只防"清单机制导致不可用"回归
        states = {m.integrity for m in metas}
        assert states <= {
            INTEGRITY_OK,
            INTEGRITY_MODIFIED,
            INTEGRITY_UNLISTED,
            INTEGRITY_UNMANAGED,
        }
        # 无清单时全部 unmanaged（仓库默认态；人工运行 approve 脚本后转 ok）
        if not (skills / MANIFEST_FILENAME).exists():
            assert states == {INTEGRITY_UNMANAGED}
        # 门禁关闭时真实技能仍可加载（banner + 标注）
        monkeypatch.delenv(GATE_ENV, raising=False)
        r = run_skill_load(_host(skills), {"name": "code-nav"})
        assert r.status == ToolResultStatus.SUCCESS
        assert SKILL_PROVENANCE_BANNER in r.content
        assert "integrity=" in r.content
