"""守卫代码时效测试（cmd gate / safety 层"改了没重启"专用对照）.

背景：2026-11-01 命令闸修复已提交，但运行中的进程仍执行启动时载入的旧字节码；
既有 HEAD 对照看不见未提交改动，check_self_stale 虽有实现却全仓无调用方（死代码）。
本文件钉住：指纹口径、stale 判据（只对已 import 的模块成立）、未知不伪造、
以及"信息项不并入动作项（restart_required）"的分层口径。
"""

import json
import sys
import types
from pathlib import Path

import pytest

from llm_loop.core import guard_code as gcd
from llm_loop.introspection import proc_version
from llm_loop.introspection.proc_version import (
    GUARD_MODULES,
    get_process_versions,
    guard_code_drift,
    guard_code_fingerprint,
    guard_code_note,
)
from llm_loop.runtime.manifest import _guard_code_block
from llm_loop.runtime.service_control import _guard_code_drift_view


@pytest.fixture(autouse=True)
def _isolate_explicit_source_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LFL_WORKSPACE_ROOT", raising=False)


def _fake_source_tree(tmp_path, override: dict[str, str] | None = None):
    """在 tmp_path/src/llm_loop 下铺出全部声明的守卫模块文件."""
    pkg = tmp_path / "src" / "llm_loop"
    for rel in GUARD_MODULES:
        path = pkg / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((override or {}).get(rel, f"# {rel}\n"), encoding="utf-8")
    return pkg


def _bind_source(monkeypatch, pkg, snapshot: dict[str, str]) -> None:
    monkeypatch.setattr(proc_version, "_source_root", lambda: pkg)
    monkeypatch.setattr(proc_version, "_GUARD_SNAPSHOT", dict(snapshot))


def test_every_declared_guard_module_exists():
    """声明即契约：改名/搬迁后不静默失配（否则指纹恒 missing、stale 永不触发）."""
    root = proc_version._package_root()
    missing = [rel for rel in GUARD_MODULES if not (root / rel).is_file()]
    assert missing == []


def test_fingerprint_deterministic_and_scoped(tmp_path):
    pkg = _fake_source_tree(tmp_path)
    before = guard_code_fingerprint(pkg)
    assert before == guard_code_fingerprint(pkg)  # 同内容同指纹
    assert set(before) == set(GUARD_MODULES)

    target = GUARD_MODULES[0]
    (pkg / target).write_text("# changed\n", encoding="utf-8")
    after = guard_code_fingerprint(pkg)
    assert after[target] != before[target]
    assert all(after[rel] == before[rel] for rel in GUARD_MODULES[1:])


def test_fingerprint_missing_file_marked_not_fabricated(tmp_path):
    pkg = _fake_source_tree(tmp_path)
    (pkg / GUARD_MODULES[1]).unlink()
    fp = guard_code_fingerprint(pkg)
    assert fp[GUARD_MODULES[1]] == "missing"
    assert all(fp[rel] != "missing" for rel in GUARD_MODULES if rel != GUARD_MODULES[1])


def test_drift_clean_when_source_matches_snapshot(tmp_path, monkeypatch):
    pkg = _fake_source_tree(tmp_path)
    snapshot = guard_code_fingerprint(pkg)
    _bind_source(monkeypatch, pkg, snapshot)

    drift = guard_code_drift()
    assert drift["stale"] is False
    assert drift["changed"] == []
    assert guard_code_note() == ""


def test_drift_stale_only_for_loaded_modules(tmp_path, monkeypatch):
    """磁盘已变 + 本进程已 import → stale；未 import → 只记 changed_unloaded."""
    pkg = _fake_source_tree(tmp_path)
    snapshot = guard_code_fingerprint(pkg)
    _bind_source(monkeypatch, pkg, snapshot)
    (pkg / GUARD_MODULES[0]).write_text("# v2\n", encoding="utf-8")

    loaded_name = proc_version._module_name(GUARD_MODULES[0])
    monkeypatch.setitem(sys.modules, loaded_name, types.ModuleType(loaded_name))
    drift = guard_code_drift()
    assert drift["stale"] is True
    assert drift["changed_loaded"] == [GUARD_MODULES[0]]

    monkeypatch.delitem(sys.modules, loaded_name, raising=False)
    drift = guard_code_drift()
    assert drift["stale"] is False
    assert drift["changed"] == [GUARD_MODULES[0]]
    assert drift["changed_unloaded"] == [GUARD_MODULES[0]]


def test_guard_note_names_module_and_restart(tmp_path, monkeypatch):
    pkg = _fake_source_tree(tmp_path)
    snapshot = guard_code_fingerprint(pkg)
    _bind_source(monkeypatch, pkg, snapshot)
    (pkg / GUARD_MODULES[0]).write_text("# v2\n", encoding="utf-8")
    name = proc_version._module_name(GUARD_MODULES[0])
    monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    note = guard_code_note()
    assert "守卫代码时效提示" in note
    assert GUARD_MODULES[0] in note
    assert "重启" in note

    # check_self_stale 优先返回守卫口径（比"工作区 dirty"更具体）
    monkeypatch.setattr(proc_version, "git_head", lambda: "deadbee")
    monkeypatch.setattr(proc_version, "workspace_dirty", lambda: True)
    assert proc_version.check_self_stale() == note


def test_drift_fail_open_records_error(tmp_path, monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(proc_version, "_source_root", _boom)
    drift = guard_code_drift()
    assert drift["stale"] is False
    assert "boom" in drift["error"]


def test_record_process_start_includes_guard_code(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    proc_version.record_process_start("guard-svc")
    rows = [
        json.loads(line)
        for line in (tmp_path / "audit" / "proc_versions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[-1]["guard_code"] == proc_version._GUARD_SNAPSHOT


def test_process_versions_flags_guard_drift(tmp_path, monkeypatch):
    """记录里的守卫指纹与源码树不同 → guard_code_current=False + 守卫口径 note."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    pkg = _fake_source_tree(tmp_path / "ws")
    _bind_source(monkeypatch, pkg, guard_code_fingerprint(pkg))
    # 记录来自另一份守卫代码
    stale_record = {rel: "0" * 16 for rel in GUARD_MODULES}
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "proc_versions.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-11-01T00:00:00+08:00",
                "pid": 4242,
                "service": "web",
                "git_head": proc_version.git_head(),
                "workspace_dirty": False,
                "guard_code": stale_record,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    info = get_process_versions()
    svc = [s for s in info["services"] if s["service"] == "web"][0]
    assert svc["guard_code_current"] is False
    assert set(svc["guard_code_changed"]) == set(GUARD_MODULES)
    assert "守卫模块" in svc["note"]
    assert info["guard_code_now"] == guard_code_fingerprint(pkg)
    assert "stale" in info["guard_code_self"]


def test_process_versions_old_record_has_unknown_guard_state(tmp_path, monkeypatch):
    """旧记录没有 guard_code → 未知(null)，不得当作"一致(True)"."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "proc_versions.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:00+08:00", "pid": 1, "service": "feishu",
                    "git_head": proc_version.git_head(), "workspace_dirty": False},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    svc = [s for s in get_process_versions()["services"] if s["service"] == "feishu"][0]
    assert svc["guard_code_current"] is None
    assert svc["guard_code_changed"] == []


def test_manifest_block_carries_all_declared_modules():
    block = _guard_code_block()
    assert set(block) == set(GUARD_MODULES)


def test_service_control_view_stale_and_layered(tmp_path, monkeypatch):
    """status 视图：stale/current/unknown 三态；stale 只作信息项（不并入动作项）."""
    pkg = _fake_source_tree(tmp_path)
    monkeypatch.setattr(gcd, "repo_source_root", lambda: pkg)
    recorded = guard_code_fingerprint(pkg)

    assert _guard_code_drift_view(recorded)["status"] == "current"
    assert _guard_code_drift_view(None)["status"] == "unknown"
    assert _guard_code_drift_view({})["reason"] == "manifest_missing_guard_code"

    (pkg / GUARD_MODULES[0]).write_text("# v2\n", encoding="utf-8")
    stale = _guard_code_drift_view(recorded)
    assert stale["status"] == "stale"
    assert stale["changed"] == [GUARD_MODULES[0]]
    assert "restart_required" in stale["note"]  # 说明不改动作项口径，而不是伪装成动作项


def test_drift_undetermined_when_workspace_is_not_this_package(tmp_path, monkeypatch):
    """源码树里没有本包（如 LFL_WORKSPACE_ROOT 指向别的工作区）→ 不可判定，不误报 stale."""
    foreign = tmp_path / "unrelated-workspace"
    foreign.mkdir()
    monkeypatch.setattr(proc_version, "_source_root", lambda: foreign)

    drift = guard_code_drift()
    assert drift["stale"] is False
    assert drift["changed"] == []
    assert drift["undetermined"] == "source_root_has_no_llm_loop_package"
    assert guard_code_note() == ""


def test_process_versions_guard_state_null_when_source_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    foreign = tmp_path / "unrelated-workspace"
    foreign.mkdir()
    monkeypatch.setattr(proc_version, "_source_root", lambda: foreign)
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    (audit / "proc_versions.jsonl").write_text(
        json.dumps({"ts": "2026-11-01T00:00:00+08:00", "pid": 7, "service": "web",
                    "git_head": proc_version.git_head(), "workspace_dirty": False,
                    "guard_code": {rel: "0" * 16 for rel in GUARD_MODULES}},
                   ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    info = get_process_versions()
    assert info["guard_code_now"] is None
    svc = [s for s in info["services"] if s["service"] == "web"][0]
    assert svc["guard_code_current"] is None  # 不可判定 ≠ 一致
    assert svc["guard_code_changed"] == []


def test_service_control_view_unknown_when_source_root_undeterminable(tmp_path, monkeypatch):
    monkeypatch.setattr(gcd, "repo_source_root", lambda: None)
    view = _guard_code_drift_view({rel: "0" * 16 for rel in GUARD_MODULES})
    assert view["status"] == "unknown"
    assert view["reason"] == "source_root_has_no_llm_loop_package"


def test_repo_root_from_release_layout():
    """真实部署形态：加载路径在 .releases/<sha>/ 下 → 反推回源码仓根.

    manifest 的 workspace_root 在 release 部署下就是 release 目录本身（实测
    ce205a4 全部 4 个服务如此），拿它当基准恒判"一致"——正是要防的静默误判。
    """
    repo = Path("/tmp/repo")
    loaded = repo / ".releases" / "ce205a4" / "src" / "llm_loop"
    assert proc_version._repo_root_from(loaded) == repo
    assert proc_version._repo_root_from(repo / "src" / "llm_loop") is None


def test_compose_guard_code_freshness_per_service(tmp_path, monkeypatch):
    """status 小节：按服务读 manifest 指纹，三分态 + 不可读如实标注."""
    from llm_loop.runtime.service_control import (
        _MANAGED_SERVICES,
        compose_guard_code_freshness,
    )

    class _StubStore:
        def __init__(self, runtime_dir):
            self.runtime_dir = runtime_dir

    pkg = _fake_source_tree(tmp_path / "ws")
    monkeypatch.setattr(gcd, "repo_source_root", lambda: pkg)
    recorded = guard_code_fingerprint(pkg)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    services = list(_MANAGED_SERVICES)
    # 第 1 个：指纹一致 → current；第 2 个：旧指纹 → stale；其余：manifest 缺失
    for idx, svc in enumerate(services[:2]):
        payload = recorded if idx == 0 else {rel: "0" * 16 for rel in GUARD_MODULES}
        (runtime_dir / f"runtime_manifest.{svc}.json").write_text(
            json.dumps({"pid": 1, "guard_code": payload}, ensure_ascii=False),
            encoding="utf-8",
        )

    freshness = compose_guard_code_freshness(_StubStore(runtime_dir))
    assert freshness[services[0]]["status"] == "current"
    assert freshness[services[1]]["status"] == "stale"
    for svc in services[2:]:
        assert freshness[svc]["status"] == "unknown"
        assert freshness[svc]["reason"] == "manifest_unreadable"
