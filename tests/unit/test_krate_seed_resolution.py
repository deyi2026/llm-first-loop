"""krate 与 release 树解耦：方法卡解析 data/methods → 仓库 tracked 种子目录 methods/。

背景（2026-11-05 第 2 步）：krate 曾从 ``.releases/*/methods/`` 兜底取 10 条种子方法，
使 .releases（189 棵 / 约 17G）无法清理。现改为直接读 tracked ``methods/``，
本测试锁定该不变量：种子卡从 methods/ 解析、runtime 副本优先、.releases 不再参与。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load(rel: str):
    path = REPO / rel
    sys.path.insert(0, str(path.parent))
    name = "krate_ut_" + path.stem + "_" + str(abs(hash(rel)) % 10000)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, name: str, extra: str = "") -> None:
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "METHOD.md").write_text(
        f"---\nname: {name}\ndescription: d-{name}\n{extra}---\n## Trigger\nhit {name}\n",
        encoding="utf-8",
    )


def _fake_repo(root: Path) -> None:
    _write(root, "data/methods/runtime-card", "runtime-card")
    _write(root, "methods/seed-card", "seed-card")
    _write(root, "data/methods/shared-card", "shared-card", "origin: runtime\n")
    _write(root, "methods/shared-card", "shared-card", "origin: seed\n")
    _write(root, ".releases/deadbeef/methods/release-only-card", "release-only-card")


def test_method_md_paths_runtime_first_then_tracked_seed(tmp_path, monkeypatch):
    _fake_repo(tmp_path)
    mod = _load("tools/krate/krate_index.py")
    monkeypatch.setattr(mod, "REPO", tmp_path)

    paths = mod.method_md_paths()
    names = [p.parent.name for p in paths]

    assert names == ["runtime-card", "shared-card", "seed-card"]
    assert paths[1].parts[-4:-2] == ("data", "methods")  # 同名卡 runtime 副本胜出
    assert not any(".releases" in p.parts for p in paths)  # release 树不再参与


def test_load_method_resolves_tracked_seed(tmp_path, monkeypatch):
    _fake_repo(tmp_path)
    mod = _load("tools/krate/krate_score.py")
    monkeypatch.setattr(mod, "REPO", tmp_path)

    seed = mod.load_method("method:seed-card")
    runtime = mod.load_method("method:runtime-card")
    assert seed and seed["name"] == "seed-card" and "hit seed-card" in seed["trigger"]
    assert runtime and runtime["name"] == "runtime-card"
    assert mod.load_method("method:release-only-card") is None  # 只在 .releases 里的卡不再可见


def test_repo_tracked_seed_dir_carries_the_ten_seeds():
    seeds = {p.parent.name for p in (REPO / "methods").glob("*/METHOD.md")}
    expected = {
        "method-ab-experiment",
        "method-candidate-relative-clock-never-state",
        "method-repo-api-discovery",
        "method-root-cause",
        "method-self-distill",
        "method-self-distill-ab",
        "method-self-distill-repo-api",
        "method-self-distill-root-cause",
        "method-semantic-operation",
        "method-web-source-diagnosis",
    }
    assert expected <= seeds
