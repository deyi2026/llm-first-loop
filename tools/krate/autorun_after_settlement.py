#!/usr/bin/env python3
"""K-Rate autorun: score + index, spawned by the settlement_submit hook.

Serialization : flock on <root>/data/knowledge_index/.autorun.lock
                - free  -> run immediately
                - busy  -> poll up to KRATE_AUTORUN_WAIT_S (default 300s), then give up
                  (score/index are idempotent; next trigger or a manual run covers the rest)
Exit code     : always 0, even on internal failure (hook 侧 stderr=DEVNULL，非零退出
                = 零痕迹静默死亡)。scorer-unreachable (krate_score exit 2) is a
                *pending* state, not an error; trace goes to autorun.log.
Env           : KRATE_ROOT overrides the repo root (tests / relocation);
                LFL_KRATE_AUTORUN=0 disables (belt-and-braces; hook also checks).
"""
import fcntl
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(os.environ.get("KRATE_ROOT") or Path(__file__).resolve().parents[2])
LOG = REPO / "data/knowledge_index/autorun.log"
LOCK = REPO / "data/knowledge_index/.autorun.lock"
_STEP_TIMEOUT_S = 1800


def _log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} [autorun] {msg}\n")
        if LOG.stat().st_size > 2_000_000:
            data = LOG.read_bytes()
            with LOG.open("wb") as f:
                f.write(data[-256_000:])
    except Exception:  # noqa: BLE001 — 日志永不致命
        pass


def _parse_wait_s() -> float:
    try:
        return float(os.environ.get("KRATE_AUTORUN_WAIT_S", "300"))
    except ValueError:
        return 300.0


def _acquire_lock(wait_s: float):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = LOCK.open("a")
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.monotonic() >= deadline:
                fh.close()
                return None
            time.sleep(2)


def main() -> int:  # 永不向调用方报错：一切内部失败 best-effort 落日志后 exit 0
    try:
        if os.environ.get("LFL_KRATE_AUTORUN") == "0":
            return 0
        wait_s = _parse_wait_s()
        fh = _acquire_lock(wait_s)
        if fh is None:
            _log(f"lock busy >{wait_s:.0f}s, giving up (idempotent; next trigger covers)")
            return 0
        started = time.monotonic()
        _log("start: krate_score -> krate_index")
        for script in ("krate_score.py", "krate_index.py"):
            try:
                proc = subprocess.run(
                    [sys.executable, str(REPO / "tools/krate" / script)],
                    cwd=str(REPO), capture_output=True, text=True,
                    timeout=_STEP_TIMEOUT_S,
                )
                _log(f"{script}: rc={proc.returncode} "
                     f"out={proc.stdout.strip()[:400]!r} err={proc.stderr.strip()[:400]!r}")
            except subprocess.TimeoutExpired as exc:
                _log(f"{script}: TIMEOUT after {_STEP_TIMEOUT_S}s ({exc})")
            except Exception as exc:  # noqa: BLE001 — autorun 永不向结算路径报错
                _log(f"{script}: SPAWN_ERROR {exc!r}")
        fh.close()
        _log(f"done in {time.monotonic() - started:.1f}s")
    except Exception as exc:  # noqa: BLE001 — 承载"恒 exit 0"不变量（含锁文件 IO 失败）
        _log(f"FATAL {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
