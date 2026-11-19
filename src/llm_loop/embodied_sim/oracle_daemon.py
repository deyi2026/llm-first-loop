"""Host-owned oracle daemon for M1 (deployed by Host as a separate process).

Owns the live MuJoCoScene and the Ed25519 private key. Clients can only send
STRICTLY WHITELISTED action commands over Host-managed file queues; the daemon
executes them on ITS OWN scene (real mj_step physics), takes its own privileged
snapshot, judges locally, and returns an Ed25519-signed receipt binding
run_id/scene_epoch/action_seq/nonce/snapshot_hash/uid.

This process never accepts snapshots, file paths, stdin JSON, or arbitrary
scripts from callers. In the current sandbox no such daemon runs (no root);
attestation requests therefore fail closed with AttestationUnavailable.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from llm_loop.embodied_sim import MuJoCoScene
from llm_loop.embodied_sim.attestation import (
    ATTEST_UID,
    _trusted_host_file,
    canonical,
    snapshot_hash,
    validate_command,
)
from llm_loop.embodied_sim.oracle import judge_grasp, judge_place
from llm_loop.embodied_sim.skills import EmbodiedInterface
from llm_loop.embodied_sim.trial import EXPERIMENT_ID, validate_trial


class DaemonUnavailableError(Exception):
    fail_closed = True


PROD_PRIVATE_KEY_PATH = "/usr/local/etc/lfl-m1-oracle-ed25519.key"


def load_private_key(path: str) -> Ed25519PrivateKey:
    raw = bytes.fromhex(Path(path).read_text().strip())
    return Ed25519PrivateKey.from_private_bytes(raw)


class OracleDaemon:
    """One daemon binds one live scene/interface and one private key."""

    def __init__(
        self, iface, run_id: str, private_key_path: str,
        experiment_id: str = "M1-SIM-001", trial: dict[str, Any] | None = None,
    ):
        self.iface = iface
        self.scene = iface.scene
        self.run_id = str(run_id)
        if (trial is None and experiment_id != "M1-SIM-001") or (
            trial is not None and experiment_id != EXPERIMENT_ID
        ):
            raise ValueError("trial binding and experiment identity disagree")
        self.trial = validate_trial(trial) if trial is not None else None
        self.experiment_id = experiment_id
        self._key_path = str(private_key_path)
        self._action_seq = 0
        self._seen_nonces: set[str] = set()
        try:
            self._key = load_private_key(private_key_path)
        except (OSError, ValueError) as e:
            raise DaemonUnavailableError(f"private key unavailable: {e}") from None
        self._pub_hex = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()

    @property
    def public_key_hex(self) -> str:
        return self._pub_hex

    def handle_command(
        self, command: dict[str, Any], run_id: str, action_seq: int, nonce: str
    ) -> dict[str, Any]:
        """Execute one whitelisted command on the owned scene, sign the result."""
        core: dict[str, Any]
        try:
            skill = validate_command(command)
            if str(run_id) != self.run_id:
                raise ValueError("run_id mismatch: daemon bound to another run")
            if not isinstance(nonce, str) or re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
                raise ValueError("invalid nonce")
            if nonce in self._seen_nonces:
                raise ValueError("replayed nonce")
            is_action = skill in ("move_to", "grasp", "release")
            expected_seq = self._action_seq + int(is_action)
            if type(action_seq) is not int or action_seq != expected_seq:
                raise ValueError("out-of-order action_seq")
            self._seen_nonces.add(nonce)
            if skill == "observe":
                result = {
                    "oracle_execution": "observation_only",
                    "observation": self.scene.observe(),
                    "run_id": self.run_id,
                    "action_seq": self._action_seq,
                }
                if self.trial is not None:
                    result["trial"] = self.trial
                return result
            if is_action:
                result = self.iface.execute_skill(
                    skill,
                    command.get("params") or {},
                    intent_key=f"daemon-{nonce}",
                    grant_version=1,
                )
                if "action_id" not in result:
                    raise ValueError(f"skill rejected: {result.get('error', result)}")
                aid = result["action_id"]
                status = result
                while self.iface.get_action_status(aid)["state"] == "running":
                    self.iface.advance(60)
                    status = self.iface.get_action_status(aid)
                if status["state"] not in ("done", "failed"):
                    raise ValueError(f"action did not reach terminal state: {status['state']}")
                self._action_seq = action_seq
                result = {
                    "oracle_execution": "action_only",
                    "run_id": self.run_id,
                    "action_seq": self._action_seq,
                    "action_status": status,
                }
                if self.trial is not None:
                    result["trial"] = self.trial
                return result
            # Only an explicit, separate physical Oracle check may be signed.
            # A successful move/observe is NOT proof of grasp or placement.
            if os.getuid() != ATTEST_UID:
                raise ValueError("Host UID463 identity required for signing")
            if self._key_path != PROD_PRIVATE_KEY_PATH or not _trusted_host_file(
                self._key_path, owner=ATTEST_UID, private_key=True
            ):
                raise ValueError("Host-installed private key required for signing")
            # A completed arm command does not mean the cube is stationary.
            # Observe a bounded, passive settling interval inside the
            # independent Host scene before the physical Oracle snapshot.
            # No client-selected wait duration or actuation is accepted.
            settle_steps = 30 if skill == "verify_grasp" else 150
            self.scene.step(settle_steps)
            snapshot = self.scene.oracle_snapshot()
            if skill == "verify_grasp":
                ok, ev = judge_grasp(snapshot)
                claim_kind = "grasp"
            elif skill == "verify_place":
                ok, ev = judge_place(snapshot, self.scene.observe()["tray_pos"])
                claim_kind = "place"
            else:
                raise ValueError("unrecognized Oracle claim")
            ev = {**ev, "oracle_settle_steps": settle_steps}
            core = {
                "claim_kind": claim_kind,
                "run_id": str(run_id),
                "scene_epoch": int(self.scene.scene_epoch),
                "action_seq": int(action_seq),
                "nonce": str(nonce),
                "snapshot_hash": snapshot_hash(snapshot),
                "oracle_execution": "host_uid463_managed",
                "verdict": "success" if ok else "failure",
                "uid": int(os.getuid()),
                "experiment_id": self.experiment_id,
                "evidence": ev,
                "oracle_impl": "embodied-m1-oracle-daemon-v0",
            }
            if self.trial is not None:
                core["trial"] = self.trial
            signature = self._key.sign(canonical(core)).hex()
            return {**core, "signature": signature, "daemon_public_key": self._pub_hex}
        except Exception as e:
            return {
                "oracle_execution": "daemon_fail_closed",
                "verdict": "failure",
                "error": f"{type(e).__name__}: {e}",
            }

    def process_pending(self, jobs_dir: str, receipts_dir: str) -> int:
        """Consume all pending job files; write one signed receipt per job."""
        count = 0
        for job_path in sorted(Path(jobs_dir).glob("*.job")):
            try:
                nonce = job_path.stem
                if re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
                    continue
                flags = os.O_RDONLY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                fd = os.open(job_path, flags)
                with os.fdopen(fd, "rb") as inp:
                    info = os.fstat(inp.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
                        continue
                    payload = json.loads(inp.read(16385).decode("utf-8"))
                if not isinstance(payload, dict):
                    continue
                if payload.get("nonce") != nonce or set(payload) != {
                    "command",
                    "run_id",
                    "action_seq",
                    "nonce",
                }:
                    continue
                seq = payload.get("action_seq")
                if type(seq) is not int:
                    continue
                receipt = self.handle_command(
                    payload.get("command") or {}, payload.get("run_id", ""), seq, nonce
                )
                dest = Path(receipts_dir) / f"{nonce}.receipt.json"
                temp = Path(receipts_dir) / f".{nonce}.{os.getpid()}.tmp"
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                # Publish only complete receipts: a client must never read
                # a partially written final filename under concurrent xdist.
                try:
                    fd = os.open(temp, flags, 0o644)
                    with os.fdopen(fd, "w", encoding="utf-8") as out:
                        os.fchmod(out.fileno(), 0o644)
                        out.write(json.dumps(receipt, sort_keys=True) + "\n")
                        out.flush()
                        os.fsync(out.fileno())
                    os.link(temp, dest)  # atomic create-if-absent; no overwrite
                finally:
                    with contextlib.suppress(FileNotFoundError):
                        temp.unlink()
                count += 1
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # Malformed/untrusted job cannot terminate the Host daemon.
                pass
            finally:
                with contextlib.suppress(OSError):
                    job_path.unlink()
        return count

    def serve_forever(
        self, jobs_dir: str, receipts_dir: str, poll_interval_s: float = 0.5
    ) -> None:  # pragma: no cover - Host deployment
        if os.getuid() != ATTEST_UID:
            raise DaemonUnavailableError("Host UID463 required")
        while True:
            self.process_pending(jobs_dir, receipts_dir)
            time.sleep(poll_interval_s)


def build_daemon_from_scene_seed(
    seed: int, run_id: str, private_key_path: str,
    trial: dict[str, Any] | None = None,
) -> OracleDaemon:
    """Host-side bootstrap helper: the daemon constructs its OWN interface.

    In production the Host process builds this from its managed live scene;
    tests may call it directly to exercise the protocol (same-process tests
    validate the protocol, NOT the process boundary - the boundary is Host
    deployment's responsibility and is never claimed by client code).
    """
    if trial is not None and validate_trial(trial)["seed"] != seed:
        raise ValueError("Host scene seed differs from signed trial identity")
    scene = MuJoCoScene(seed=seed)
    scene.step(100)
    iface = EmbodiedInterface(scene)
    return OracleDaemon(
        iface, run_id=run_id, private_key_path=private_key_path,
        experiment_id=EXPERIMENT_ID if trial is not None else "M1-SIM-001",
        trial=trial,
    )
