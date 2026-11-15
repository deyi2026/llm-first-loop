"""Explicit four-service source-checkout rollout over existing managed actions.

The historical ``target=all`` deliberately excludes the long-lived WeCom
connection. This coordinator does not change that contract: it publishes once,
waits for a verified ``all`` action, then admits one separate WeCom action.
Both action receipts remain the authoritative execution evidence.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm_loop.runtime import service_control as sc

_RELEASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_SERVICES = ("web", "feishu", "learning", "wecom")


class ReleaseAlreadyRunningError(RuntimeError):
    """The global managed-release coordinator lock is already held."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _paths(data_dir: Path, release_id: str) -> tuple[Path, Path, Path]:
    if not _RELEASE_ID.fullmatch(release_id):
        raise ValueError("release-id must be 1..64 ASCII letters, digits, _ or -")
    folder = data_dir / "runtime" / "unified-releases"
    return folder / f"{release_id}.json", folder / "coordinator.lock", folder / f"{release_id}.log"


def _read(path: Path) -> dict[str, Any]:
    # Check the opened inode, not a prior is_symlink probe (TOCTOU).
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1_000_000:
            raise ValueError("unified release journal is not a bounded regular file")
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("unified release journal schema mismatch")
    return data


def _save(path: Path, state: dict[str, Any], **updates: Any) -> None:
    state.update(updates)
    state["updated_at"] = _now()
    sc.atomic_write_bytes_file(
        path, (json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n").encode(), mode=0o600
    )


def _same_deployment(current: Any, candidate: Any) -> bool:
    return (
        current is not None
        and current.generation == candidate.generation
        and current.deployment_id == candidate.deployment_id
        and current.git_head == candidate.git_head
        and current.code_root == candidate.code_root
        and current.runtime_root == candidate.runtime_root
        and current.webui_artifact_sha256 == candidate.webui_artifact_sha256
    )


def _assert_desired(store: sc.ManagedServiceDeploymentStore, candidate: Any) -> None:
    if not _same_deployment(store.read(), candidate):
        raise RuntimeError("desired deployment changed; refusing cross-generation continuation")


def _find_action(
    store: sc.ManagedServiceDeploymentStore, *, state: dict[str, Any], stage: str, target: str, candidate: Any
) -> Any | None:
    matches = [
        a for a in sc.read_all_actions(store)
        if a.requester_session_id == state["requester"]
        and a.origin == f"unified-release:{state['release_id']}:{stage}"
        and a.target == target
        and a.deployment_generation == candidate.generation
        and a.deployment_id == candidate.deployment_id
    ]
    if len(matches) > 1:
        raise RuntimeError(f"multiple {target} actions for one release; operator review required")
    return matches[0] if matches else None


def _start_or_recover_action(
    store: sc.ManagedServiceDeploymentStore,
    candidate: Any,
    state: dict[str, Any],
    journal: Path,
    *,
    stage: str,
    target: str,
) -> Any:
    key = f"{stage}_action_id"
    action = _find_action(
        store, state=state, stage=stage, target=target, candidate=candidate
    )
    recorded = state.get(key)
    if recorded and (action is None or action.action_id != recorded):
        raise RuntimeError(f"{stage} action identity mismatch; refusing replay")
    if action is None:
        _assert_desired(store, candidate)
        action = store.accept_restart(
            target=target,
            expected_generation=candidate.generation,
            requester_session_id=state["requester"],
            origin=f"unified-release:{state['release_id']}:{stage}",
        )
    if not recorded:
        _save(journal, state, **{key: action.action_id})

    # A restart is never replayed. If the process died after the spawn intent,
    # the action receipt/worker PID must prove progress; otherwise stop.
    if action.status == "accepted" and not state.get(f"{stage}_spawn_intent"):
        if action.worker_pid > 0:
            # A concurrent controller already owns this accepted action.
            # Never launch another worker for the same physical restart.
            _save(journal, state, **{f"{stage}_spawn_intent": True, f"{stage}_spawned": True})
        else:
            _save(journal, state, **{f"{stage}_spawn_intent": True})
            sc.spawn_service_control_worker(store, action.action_id)
            _save(journal, state, **{f"{stage}_spawned": True})
    elif action.status == "accepted" and not state.get(f"{stage}_spawned"):
        if action.worker_pid <= 0:
            raise RuntimeError(f"{stage} spawn outcome unknown; no automatic second spawn")
        _save(journal, state, **{f"{stage}_spawned": True})
    return action


def _await_action(
    store: sc.ManagedServiceDeploymentStore,
    candidate: Any,
    action_id: str,
    *,
    timeout_s: float,
    poll_s: float,
) -> Any:
    deadline = time.monotonic() + timeout_s
    while True:
        _assert_desired(store, candidate)
        action = store.read_action(action_id)
        if (
            action is None or action.deployment_id != candidate.deployment_id
            or action.deployment_generation != candidate.generation
        ):
            raise RuntimeError("action disappeared or deployment identity changed")
        if action.status == "succeeded":
            if action.verify_verdict != "confirmed_ok":
                raise RuntimeError("succeeded action lacks confirmed_ok verification")
            return action
        if action.status == "failed":
            raise RuntimeError(f"action {action_id} failed; no automatic retry")
        # verify_evidence_ready is nonterminal: a separate reviewer may still
        # acknowledge the evidence. Never treat it as succeeded or retry it.
        if time.monotonic() >= deadline:
            raise TimeoutError(f"action {action_id} still {action.status}; resume after checking")
        time.sleep(poll_s)


def _verify_live(store: sc.ManagedServiceDeploymentStore, candidate: Any, names: tuple[str, ...]) -> None:
    _assert_desired(store, candidate)
    view = sc.compose_service_identity_view(store)
    rows = view.get("services")
    if not isinstance(rows, dict):
        raise RuntimeError("service identity view missing services")
    for name in names:
        row = rows.get(name)
        if not isinstance(row, dict) or not isinstance(row.get("live"), dict):
            raise RuntimeError(f"service identity view missing {name}")
        live = row["live"]
        if (
            not live.get("pid_alive")
            or not live.get("matches_desired_generation")
            or row.get("restart_required")
            or row.get("admission_barrier")
        ):
            raise RuntimeError(f"{name} not verified live at target generation")
    if names == _SERVICES and view.get("admission_barriers"):
        raise RuntimeError("admission barriers remain after four-service rollout")


def _adopt_wecom(store: sc.ManagedServiceDeploymentStore, candidate: Any) -> Any | None:
    """Avoid a second WeCom reconnect when another managed action already proved it."""
    matches = [
        a for a in sc.read_all_actions(store)
        if a.target == "wecom"
        and a.deployment_id == candidate.deployment_id
        and a.deployment_generation == candidate.generation
    ]
    if not matches:
        return None
    # A managed WeCom restart in progress must not race a second reconnect.
    # Persist its exact action ID and wait for its own verified completion.
    pending = [a for a in matches if a.status not in {"succeeded", "failed"}]
    if len(pending) > 1:
        raise RuntimeError("multiple in-flight WeCom restarts; operator review required")
    if pending:
        return pending[0]
    verified = [a for a in matches if a.status == "succeeded" and a.verify_verdict == "confirmed_ok"]
    if verified:
        _verify_live(store, candidate, ("wecom",))
        return sorted(verified, key=lambda a: (a.updated_at, a.action_id))[-1]
    raise RuntimeError("prior unverified WeCom action; refusing automatic reconnect")


def _run_locked(store: sc.ManagedServiceDeploymentStore, journal: Path, state: dict[str, Any], *, timeout_s: float, poll_s: float) -> dict[str, Any]:
    if state["status"] == "succeeded":
        return state
    _save(journal, state, status="running", worker_pid=os.getpid(), last_error="")
    try:
        expected = int(state["expected_generation"])
        candidate_raw = state.get("candidate")
        if candidate_raw is None:
            current = store.read()
            if current is not None and current.generation != expected:
                raise RuntimeError("generation changed before candidate preparation")
            candidate = sc.build_deployment(
                code_root=state["code_root"],
                runtime_root=state["runtime_root"],
                generation=expected + 1,
            )
            _save(journal, state, candidate=candidate.to_dict())
        else:
            candidate = sc.ManagedServiceDeployment.from_dict(candidate_raw)
        if candidate.git_head != state["expected_sha"]:
            raise RuntimeError("candidate SHA does not match explicitly reviewed SHA")
        current = store.read()
        if current is None or current.generation == expected:
            store.compare_and_swap(candidate, expected_generation=expected)
        else:
            _assert_desired(store, candidate)
        _save(journal, state, status="published", generation=candidate.generation, git_head=candidate.git_head)

        first = _start_or_recover_action(store, candidate, state, journal, stage="phase1", target="all")
        _await_action(store, candidate, first.action_id, timeout_s=timeout_s, poll_s=poll_s)
        _verify_live(store, candidate, ("web", "feishu", "learning"))
        _save(journal, state, status="phase1_verified")

        if state.get("phase2_adopted"):
            # An externally owned verified WeCom action has a different origin
            # and requester. Resume must use its recorded immutable action ID,
            # never look for it among this coordinator's own actions.
            adopted_id = state.get("phase2_action_id")
            second = store.read_action(adopted_id) if adopted_id else None
            if (
                second is None or second.action_id != adopted_id
                or second.target != "wecom"
                or second.deployment_id != candidate.deployment_id
                or second.deployment_generation != candidate.generation
                or (second.status == "succeeded" and second.verify_verdict != "confirmed_ok")
            ):
                raise RuntimeError("adopted WeCom receipt missing or invalid; no restart replay")
        else:
            # If accept_restart committed but journaling the action ID did not,
            # _start_or_recover_action must record and resume that same action.
            # Never skip it by treating a found action as fully recovered.
            own = _find_action(
                store, state=state, stage="phase2", target="wecom", candidate=candidate
            )
            second = None
            if own is None and not state.get("phase2_action_id"):
                second = _adopt_wecom(store, candidate)
                if second is not None:
                    _save(journal, state, phase2_action_id=second.action_id, phase2_adopted=True)
            if second is None:
                second = _start_or_recover_action(store, candidate, state, journal, stage="phase2", target="wecom")
        if state.get("phase2_action_id") != second.action_id:
            raise RuntimeError("phase2 action identity mismatch")
        _await_action(store, candidate, second.action_id, timeout_s=timeout_s, poll_s=poll_s)
        _verify_live(store, candidate, _SERVICES)
        _save(journal, state, status="succeeded", completed_at=_now(), worker_pid=0)
    except (OSError, ValueError, RuntimeError, TimeoutError, KeyError) as exc:
        _save(journal, state, status="blocked", last_error=str(exc), worker_pid=0)
        raise
    return state


def run_release(
    store: sc.ManagedServiceDeploymentStore,
    release_id: str,
    *,
    timeout_s: float = 3600,
    poll_s: float = 2,
    lock_wait_s: float = 0,
) -> dict[str, Any]:
    journal, lock, _ = _paths(store.data_dir, release_id)
    if journal.is_symlink() or lock.is_symlink():
        raise ValueError("unified release journal/lock must not be a symlink")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + lock_wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise ReleaseAlreadyRunningError("unified release already running") from exc
                time.sleep(0.1)
        state = _read(journal)
        return _run_locked(store, journal, state, timeout_s=timeout_s, poll_s=poll_s)
    finally:
        os.close(fd)


def _launch_worker(state: dict[str, Any], journal: Path, log: Path, *, wait: bool) -> int:
    store = sc.ManagedServiceDeploymentStore(state["data_dir"])
    if wait:
        try:
            result = run_release(store, state["release_id"])
        except ReleaseAlreadyRunningError:
            print(json.dumps({"ok": False, "status": "already_running", "journal": str(journal)}))
            return 12
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            print(json.dumps({"ok": False, "error": str(exc), "journal": str(journal)}))
            return 1
        print(json.dumps({"ok": result["status"] == "succeeded", "status": result["status"], "journal": str(journal)}))
        return 0 if result["status"] == "succeeded" else 1

    # Hold the global coordinator lock through Popen + journal PID write.
    # The child waits briefly for the parent to release it. A second caller
    # sees already_running instead of launching a duplicate worker.
    _, lock, _ = _paths(store.data_dir, state["release_id"])
    if lock.is_symlink():
        raise ValueError("unified release lock must not be a symlink")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"ok": False, "status": "already_running", "journal": str(journal)}))
            return 12
        current = _read(journal)
        if current["status"] == "succeeded":
            print(json.dumps({"ok": True, "status": "succeeded", "journal": str(journal)}))
            return 0
        # Acquiring the global flock proves no coordinator currently owns it.
        # A journal PID may have been reused by an unrelated process; the
        # durable per-action spawn intent, not PID liveness, guards replay.
        argv = [sys.executable, "-m", "llm_loop.runtime.unified_release", "--release-id", state["release_id"], "--data-dir", state["data_dir"], "--worker"]
        env = sc._control_subprocess_env(
            code_root=state["code_root"],
            runtime_root=state["runtime_root"],
            python_src=Path(__file__).resolve().parents[2],
        )
        if log.is_symlink():
            raise ValueError("unified release log must not be a symlink")
        log_fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(log_fd, "a", encoding="utf-8") as stream:
            proc = subprocess.Popen(  # noqa: S603 - fixed argv, validated journal, no shell
                argv, cwd=state["runtime_root"], env=env,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
            )
        _save(journal, current, status="dispatching", worker_pid=proc.pid)
    finally:
        os.close(fd)
    # Exit 0 acknowledges durable dispatch, NOT successful deployment.
    print(json.dumps({"accepted": True, "completed": False, "detached": True, "status": "dispatching", "release_id": state["release_id"], "journal": str(journal)}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Independent operator entry; service_control's legacy CLI stays untouched."""
    four = argparse.ArgumentParser(prog="llm_loop.runtime.unified_release")
    four.add_argument("--release-id", required=True)
    four.add_argument("--data-dir", required=True)
    four.add_argument("--code-root")
    four.add_argument("--runtime-root")
    four.add_argument("--expected-generation", type=int)
    four.add_argument("--expected-sha", help="exact 40-character reviewed Git SHA")
    four.add_argument("--requester", help="actual initiating LFL session ID, or CLI operator identity")
    four.add_argument("--reason", default="unified four-service release")
    four.add_argument("--wait", action="store_true", help="foreground wait (can take hours); default detached")
    four.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    four.add_argument("--status-only", action="store_true")
    return four


def main(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).expanduser().resolve()
    journal, _, log = _paths(data_dir, args.release_id)
    if args.status_only:
        # Status is a pure observation; do not create directories or lock files.
        print(json.dumps(_read(journal), ensure_ascii=False, sort_keys=True))
        return 0
    journal.parent.mkdir(parents=True, exist_ok=True)
    if journal.is_symlink():
        raise ValueError("unified release journal must not be a symlink")
    if args.worker:
        try:
            result = run_release(sc.ManagedServiceDeploymentStore(data_dir), args.release_id, lock_wait_s=5)
            return 0 if result["status"] == "succeeded" else 1
        except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
            print(f"unified release blocked: {exc}", file=sys.stderr)
            return 1
    if not journal.exists():
        if args.expected_generation is None or not args.code_root or not args.runtime_root:
            raise ValueError("new release requires code-root, runtime-root, expected-generation")
        if not args.requester:
            raise ValueError("new release requires real requester identity (session ID for Web)")
        if not args.expected_sha or not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
            raise ValueError("new release requires exact reviewed --expected-sha")
        state: dict[str, Any] = {
            "schema": 1,
            "release_id": args.release_id,
            "code_root": str(Path(args.code_root).expanduser().resolve()),
            "runtime_root": str(Path(args.runtime_root).expanduser().resolve()),
            "data_dir": str(data_dir),
            "expected_generation": args.expected_generation,
            "expected_sha": args.expected_sha,
            "requester": args.requester,
            "reason": args.reason,
            "created_at": _now(),
            "status": "planned",
        }
        fd = os.open(journal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(state, out, ensure_ascii=False, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        # The initial directory entry must survive a power loss as well.
        dir_fd = os.open(journal.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    state = _read(journal)
    if state["release_id"] != args.release_id or state["data_dir"] != str(data_dir):
        raise ValueError("journal identity mismatch")
    if args.code_root and str(Path(args.code_root).expanduser().resolve()) != state["code_root"]:
        raise ValueError("code-root does not match durable release request")
    if args.runtime_root and str(Path(args.runtime_root).expanduser().resolve()) != state["runtime_root"]:
        raise ValueError("runtime-root does not match durable release request")
    if args.expected_generation is not None and args.expected_generation != state["expected_generation"]:
        raise ValueError("expected-generation does not match durable release request")
    if args.expected_sha is not None and args.expected_sha != state["expected_sha"]:
        raise ValueError("expected-sha does not match durable release request")
    if args.requester is not None and args.requester != state["requester"]:
        raise ValueError("requester does not match durable release request")
    if state["status"] == "succeeded":
        print(json.dumps({"ok": True, "status": "succeeded", "journal": str(journal)}))
        return 0
    return _launch_worker(state, journal, log, wait=args.wait)


def cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return main(args)
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
