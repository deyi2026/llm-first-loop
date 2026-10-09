"""EVO-20261009-9d116efa：restart 管道硬化单测。

G1 runtime.toml schema 兼容预检（resolver check-only CLI）；
G2 停机级失败的单次 known-good 自动回滚（候选选择与放弃分支）；
G3 task_budget admin-once 发放前置校验（字段注册谓词）。
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

import llm_loop.runtime.service_control as sc
from llm_loop.runtime.resolver import TOML_SCHEMA, check_runtime_toml

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------- G1: check_runtime_toml ----------

def test_g1_check_passes_for_current_repo_runtime_toml():
    ok, msg = check_runtime_toml(REPO_ROOT / "runtime.toml", ["web", "feishu", "learning"])
    assert ok, msg
    assert "校验通过" in msg


def test_g1_check_rejects_unregistered_field(tmp_path):
    bad = tmp_path / "runtime.toml"
    bad.write_text('[web]\nhost = "127.0.0.1"\nnonexistent_future_field = "x"\n', encoding="utf-8")
    ok, msg = check_runtime_toml(bad, ["web"])
    assert not ok
    assert "web.nonexistent_future_field" in msg


def test_g1_check_missing_file_is_skip_ok(tmp_path):
    ok, msg = check_runtime_toml(tmp_path / "absent.toml", ["web"])
    assert ok and "跳过" in msg


def test_g1_check_service_scoped_unknown_field(tmp_path):
    bad = tmp_path / "runtime.toml"
    bad.write_text(
        '[web]\nhost = "127.0.0.1"\n[semantic.web]\nfuture_scope_field = 1\n', encoding="utf-8"
    )
    ok, msg = check_runtime_toml(bad, ["web"])
    assert not ok


def test_g1_cli_exit_codes(tmp_path):
    bad = tmp_path / "runtime.toml"
    bad.write_text('[web]\nhost = "127.0.0.1"\nghost_field = "x"\n', encoding="utf-8")
    env = {"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"}
    r_bad = subprocess.run(
        [sys.executable, "-m", "llm_loop.runtime.resolver", "--check-toml", str(bad), "web"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert r_bad.returncode == 1
    assert "web.ghost_field" in r_bad.stdout
    r_ok = subprocess.run(
        [sys.executable, "-m", "llm_loop.runtime.resolver", "--check-toml",
         str(REPO_ROOT / "runtime.toml"), "web"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT,
    )
    assert r_ok.returncode == 0
    assert "校验通过" in r_ok.stdout


# ---------- G2: known-good 候选选择 ----------

def _receipt_line(runtime_root: Path, *, sha: str, rc: int, authority: str = "service_control") -> str:
    return json.dumps({
        "created_at": "2026-10-09T14:00:00+08:00",
        "git_head_full": sha,
        "rc": rc,
        "authority": authority,
        "stage_fact": "started",
    }, ensure_ascii=False)


def _sha(ch: str) -> str:
    return ch * 40


def _fixture_receipt_log(tmp_path: Path, lines: list[str]) -> Path:
    log = tmp_path / "data" / "restart-receipt.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def _make_release(tmp_path: Path, sha: str) -> Path:
    rel = tmp_path / ".releases" / sha
    (rel / "scripts").mkdir(parents=True, exist_ok=True)
    (rel / "scripts" / "restart_mirror.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    return rel


def test_g2_picks_latest_known_good_excluding_failing_generation(tmp_path):
    _make_release(tmp_path, _sha("a"))
    _make_release(tmp_path, _sha("b"))
    _fixture_receipt_log(tmp_path, [
        _receipt_line(tmp_path, sha=_sha("f"), rc=1),        # 13:55 事故：失败代
        _receipt_line(tmp_path, sha=_sha("b"), rc=0),        # 14:08 人工恢复
        _receipt_line(tmp_path, sha=_sha("a"), rc=0, authority="manual"),  # 非权威，跳过
    ])
    found = sc._find_known_good_release(tmp_path, exclude_git_head=_sha("f"))
    assert found is not None
    sha, rel_dir = found
    assert sha == _sha("b") and rel_dir.name == _sha("b")


def test_g2_skips_rc_nonzero_and_missing_release_dir(tmp_path):
    _make_release(tmp_path, _sha("c"))
    _fixture_receipt_log(tmp_path, [
        _receipt_line(tmp_path, sha=_sha("d"), rc=0),   # rc=0 但 .releases 目录缺失
        _receipt_line(tmp_path, sha=_sha("e"), rc=1),   # 失败
        _receipt_line(tmp_path, sha=_sha("c"), rc=0),   # 命中
    ])
    found = sc._find_known_good_release(tmp_path, exclude_git_head=_sha("f"))
    assert found is not None and found[0] == _sha("c")


def test_g2_no_log_returns_none(tmp_path):
    assert sc._find_known_good_release(tmp_path, exclude_git_head=_sha("f")) is None


def test_g2_rollback_aborts_without_known_good(tmp_path, monkeypatch):
    store = sc.ManagedServiceDeploymentStore(str(tmp_path / "managed.json"))
    failing = sc.ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id="deploy-1",
        generation=1,
        git_head=_sha("f"),
        code_root=str(tmp_path),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="0" * 64,
    )
    ok, note, rolled = sc._publish_rollback_desired(store, failing)
    assert ok is False and rolled is None and "known-good" in note


def test_g2_rollback_surfaces_build_failure(tmp_path, monkeypatch):
    _make_release(tmp_path, _sha("b"))
    _fixture_receipt_log(tmp_path, [_receipt_line(tmp_path, sha=_sha("b"), rc=0)])
    monkeypatch.setattr(
        sc, "build_deployment",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("materialize boom")),
    )
    store = sc.ManagedServiceDeploymentStore(str(tmp_path / "managed.json"))
    failing = sc.ManagedServiceDeployment(
        schema="managed-service-deployment/v1",
        deployment_id="deploy-1",
        generation=1,
        git_head=_sha("f"),
        code_root=str(tmp_path),
        runtime_root=str(tmp_path),
        webui_artifact_sha256="0" * 64,
    )
    ok, note, rolled = sc._publish_rollback_desired(store, failing)
    assert ok is False and rolled is None and "重新发布失败" in note


# ---------- G3: 发放前置谓词 ----------

def test_g3_canary_field_registered_in_schema():
    """r9 字段必须在注册态：被误删时本测试红——发放脚本会同步拒发。"""
    assert ("web", "task_budget_canary_config") in TOML_SCHEMA
