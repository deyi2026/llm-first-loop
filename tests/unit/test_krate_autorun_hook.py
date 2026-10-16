"""K-Rate autorun hook: settlement 后 fire-and-forget 触发 score+index.

覆盖：守卫（kill-switch / pytest / 脚本缺失）、spawn 行为、spawn 失败只 audit
不炸结算路径；autorun 脚本本身：串行锁、score exit 2 仍跑 index、日志落盘。
全部 tmp 隔离（KRATE_ROOT 指向临时树），不触碰真实 data/。
"""
from __future__ import annotations

import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

from llm_loop.introspection import registry_experience as re_mod


class _Host:
    def __init__(self) -> None:
        self.audits: list[tuple[str, dict, str]] = []

    def audit(self, name: str, payload: dict, status: str) -> None:
        self.audits.append((name, payload, status))


def _fake_tree(tmp_path: Path) -> Path:
    (tmp_path / "tools/krate").mkdir(parents=True)
    (tmp_path / "tools/krate/autorun_after_settlement.py").write_text(
        "import os\n"
        "from pathlib import Path\n"
        "Path(os.environ['KRATE_ROOT'], 'marker.txt').write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return tmp_path


def _wait_marker(tmp_path: Path, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    marker = tmp_path / "marker.txt"
    while time.monotonic() < deadline:
        if marker.exists():
            return True
        time.sleep(0.1)
    return False


def test_spawn_runs_detached_script(tmp_path, monkeypatch):
    root = _fake_tree(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)
    host = _Host()
    ret = re_mod._spawn_krate_autorun(host, repo_root=root)
    assert ret.startswith("spawned_pid="), ret
    assert _wait_marker(tmp_path), "detached script did not run within 10s"
    assert host.audits == []


def test_kill_switch_env_disables(tmp_path, monkeypatch):
    root = _fake_tree(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("LFL_KRATE_AUTORUN", "0")
    ret = re_mod._spawn_krate_autorun(_Host(), repo_root=root)
    assert ret == "disabled_env"
    time.sleep(1.0)
    assert not (tmp_path / "marker.txt").exists()


def test_pytest_env_skips(tmp_path, monkeypatch):
    root = _fake_tree(tmp_path)
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/unit/test_x::test_y")
    ret = re_mod._spawn_krate_autorun(_Host(), repo_root=root)
    assert ret == "skip_pytest"
    time.sleep(0.5)
    assert not (tmp_path / "marker.txt").exists()


def test_script_missing_skips(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)
    (tmp_path / "tools/krate").mkdir(parents=True)  # 无 autorun 脚本
    ret = re_mod._spawn_krate_autorun(_Host(), repo_root=tmp_path)
    assert ret == "script_missing"


def test_spawn_failure_audited_never_raises(tmp_path, monkeypatch):
    root = _fake_tree(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("spawn exploded")

    monkeypatch.setattr(re_mod.subprocess, "Popen", _boom)
    host = _Host()
    ret = re_mod._spawn_krate_autorun(host, repo_root=root)
    assert ret == "spawn_failed"
    assert len(host.audits) == 1
    name, payload, status = host.audits[0]
    assert name == "krate_autorun" and status == "failed"
    assert "spawn exploded" in payload["error"]


# ---------- autorun 脚本本体（真实子进程，KRATE_ROOT 隔离） ----------

_AUTORUN = Path(re_mod.__file__).resolve().parents[3] / "tools/krate/autorun_after_settlement.py"


def _stub_tree(tmp_path: Path, score_rc: int = 0) -> Path:
    krate = tmp_path / "tools/krate"
    krate.mkdir(parents=True)
    trace = tmp_path / "trace.txt"
    (krate / "krate_score.py").write_text(
        "import sys\n"
        f"open({str(trace)!r}, 'a').write('score\\n')\n"
        f"sys.exit({score_rc})\n",
        encoding="utf-8",
    )
    (krate / "krate_index.py").write_text(
        f"open({str(trace)!r}, 'a').write('index\\n')\n",
        encoding="utf-8",
    )
    return tmp_path


def _run_autorun(root: Path, wait_s: str = "5") -> subprocess.CompletedProcess:
    env = {**os.environ, "KRATE_ROOT": str(root), "KRATE_AUTORUN_WAIT_S": wait_s}
    env.pop("LFL_KRATE_AUTORUN", None)  # 防外层 kill-switch 干扰脚本级验证
    return subprocess.run(
        [sys.executable, str(_AUTORUN)],
        capture_output=True, text=True, timeout=60, env=env,
    )


def test_autorun_runs_score_then_index(tmp_path):
    root = _stub_tree(tmp_path)
    proc = _run_autorun(root)
    trace = (tmp_path / "trace.txt").read_text(encoding="utf-8").splitlines()
    assert proc.returncode == 0
    assert trace == ["score", "index"]
    log = (tmp_path / "data/knowledge_index/autorun.log").read_text(encoding="utf-8")
    assert "krate_score.py: rc=0" in log and "done in" in log


def test_autorun_score_exit2_still_runs_index(tmp_path):
    root = _stub_tree(tmp_path, score_rc=2)
    proc = _run_autorun(root)
    trace = (tmp_path / "trace.txt").read_text(encoding="utf-8").splitlines()
    assert proc.returncode == 0  # pending 状态不向结算路径报错
    assert trace == ["score", "index"]
    log = (tmp_path / "data/knowledge_index/autorun.log").read_text(encoding="utf-8")
    assert "krate_score.py: rc=2" in log


def test_autorun_lock_busy_gives_up_and_skips(tmp_path):
    root = _stub_tree(tmp_path)
    lock_path = root / "data/knowledge_index/.autorun.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a")
    fcntl.flock(fh, fcntl.LOCK_EX)  # 测试进程持锁
    try:
        started = time.monotonic()
        proc = _run_autorun(root, wait_s="1")
        elapsed = time.monotonic() - started
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()
    assert proc.returncode == 0
    assert elapsed < 15
    assert not (tmp_path / "trace.txt").exists()  # 没抢到锁就不跑
    log = (tmp_path / "data/knowledge_index/autorun.log").read_text(encoding="utf-8")
    assert "busy" in log


def test_spawn_production_path_resolves_real_repo_root(monkeypatch):
    """repo_root=None → parents[3] 真实仓库根；布局漂移在此变红，而非静默 script_missing."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("LFL_KRATE_AUTORUN", raising=False)
    recorded = {}

    class _FakeProc:
        pid = 4242

    def _record(argv, **kwargs):
        recorded["argv"] = argv
        recorded["cwd"] = kwargs.get("cwd")
        recorded["env"] = kwargs.get("env")
        return _FakeProc()

    monkeypatch.setattr(re_mod.subprocess, "Popen", _record)
    ret = re_mod._spawn_krate_autorun(_Host())
    assert ret == "spawned_pid=4242"
    repo = Path(re_mod.__file__).resolve().parents[3]
    script = repo / "tools/krate/autorun_after_settlement.py"
    assert script.exists()  # 脚本必须随仓携带（部署完整性）
    assert recorded["argv"] == [sys.executable, str(script)]
    assert recorded["cwd"] == str(repo)
    assert recorded["env"]["KRATE_ROOT"] == str(repo)
