#!/usr/bin/env python
"""M1 baseline calibration runner (M1-baseline-v1).

Deterministic, model-free, network-free, hardware-free. Reuses the frozen
scene/thin-interface/oracle stack and the Gate-B-proven two-stage approach,
contact-confirmed grasp, lift, move-to-tray, release sequence.

Grasp mechanism disclosure: contact_confirmed_weld - finger closure is real
position-actuator physics gated on a real fingertip-cube contact, after which
the predefined weld equality carries the cube through the constraint solver.
This is NOT claimed to be a friction-only unconstrained grasp.

Exit 0 only when all 10 seeds pass the Gate-B tolerances and both negative
checks fail closed; otherwise writes BASELINE_FAIL with reproducible causes.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import mujoco as _mujoco_impl  # noqa: E402

mujoco: Any = _mujoco_impl  # C-extension boundary facade (local, explicit)

from llm_loop.embodied_sim import MuJoCoScene  # noqa: E402
from llm_loop.embodied_sim.oracle import (  # noqa: E402
    judge_grasp,
    judge_place,
    make_receipt,
)
from llm_loop.embodied_sim.scene import SCENE_CONSTANTS, build_scene_xml  # noqa: E402
from llm_loop.embodied_sim.skills import GRASP_MECHANISM, EmbodiedInterface  # noqa: E402

OUT_DIR = ROOT / "experiments" / "embodied" / "m1" / "calibration"
BASELINE_VERSION = "M1-baseline-v1.8"
CALIBRATION_SEEDS = list(range(10))  # engineering baseline seeds; prereg paired seeds (20261117+) remain Gate D
LIFT_SETTLE_STEPS = 30
PLACE_SETTLE_STEPS = 150
EXPECTED_CUBE_PARTNERS = {"fingertip_left", "fingertip_right", "palm", "tray_floor", "floor"}

# v1.5 (TASK-009 QA correction): hard gate now covers ALL unexpected contacts,
# not only cube-involving pairs. The independent Host QA measurement proved the
# v1.3 46mm servo stall was wrist_rod<->floor dynamic obstruction (rod-floor:
# 581 contact steps with cube removed, vs 808 rod-cube + 462 rod-floor steps in
# the original scene) - the old cube-only filter missed exactly that.
_EXPECTED_PAIRS = {
    frozenset(("floor", "cube_geom")),
    frozenset(("floor", "tray_floor")),
    frozenset(("floor", "tray_wall_n")),
    frozenset(("floor", "tray_wall_s")),
    frozenset(("floor", "tray_wall_w")),
    frozenset(("cube_geom", "fingertip_left")),
    frozenset(("cube_geom", "fingertip_right")),
    frozenset(("cube_geom", "palm")),
    frozenset(("cube_geom", "tray_floor")),
    frozenset(("cube_geom", "tray_wall_n")),
    frozenset(("cube_geom", "tray_wall_s")),
    frozenset(("cube_geom", "tray_wall_w")),
    # TASK-009: the ONLY whitelisted non-cube pair - adjacent-joint shoulder
    # assembly (base cylinder + link1 capsule share the shoulder_pan geometry).
    # Runtime-verified each run in main(): link1.parent_body == arm_base.
    frozenset(("base_geom", "l1")),
}


def is_unexpected_contact(g1: str, g2: str) -> bool:
    return frozenset((g1, g2)) not in _EXPECTED_PAIRS


def _run(iface, name, params, key):
    r = iface.execute_skill(name, params, key, 1)
    if "action_id" not in r:
        return r
    aid = r["action_id"]
    while iface.get_action_status(aid)["state"] == "running":
        iface.advance(60)
    return iface.get_action_status(aid)


def _max_cube_step_displacement(scene, steps):
    """Max single mj_step cube displacement over the next `steps` physics steps."""
    import numpy as np

    max_d = 0.0
    for _ in range(steps):
        a = scene.data.qpos[scene._cube_qadr:scene._cube_qadr + 3].copy()
        scene.step(1)
        b = scene.data.qpos[scene._cube_qadr:scene._cube_qadr + 3]
        max_d = max(max_d, float(np.linalg.norm(b - a)))
    return max_d


class TrajectoryRecorder:
    """Instance-level step instrumentation: samples EVERY mj_step for max single
    cube displacement and the union of unexpected contact pairs. Measurement
    only; physics semantics untouched."""

    def __init__(self, scene):
        import numpy as np
        self._np = np
        self.scene = scene
        self.max_step_d = 0.0
        self.stage = "cold_start_settle"
        self.by_stage: dict[str, dict[tuple[str, ...], int]] = {}
        self.unexpected_steps: dict[tuple[str, ...], int] = {}
        self.stage_steps: dict[str, int] = {}
        self.first_contact_geometry: dict[str, Any] | None = None
        self._orig_step = scene.step
        scene.step = self._step  # measurement hook

    def mark(self, stage: str):
        self.stage = stage

    def _step(self, n: int = 1):
        scene = self.scene
        np = self._np
        for _ in range(int(n)):
            self.stage_steps[self.stage] = self.stage_steps.get(self.stage, 0) + 1
            a = scene.data.qpos[scene._cube_qadr:scene._cube_qadr + 3].copy()
            self._orig_step(1)
            b = scene.data.qpos[scene._cube_qadr:scene._cube_qadr + 3]
            self.max_step_d = max(self.max_step_d, float(np.linalg.norm(b - a)))
            for i in range(scene.data.ncon):
                c = scene.data.contact[i]
                g1 = mujoco.mj_id2name(scene.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom1))
                g2 = mujoco.mj_id2name(scene.model, mujoco.mjtObj.mjOBJ_GEOM, int(c.geom2))
                if is_unexpected_contact(str(g1), str(g2)):
                    key = tuple(sorted((str(g1), str(g2))))
                    self.unexpected_steps[key] = self.unexpected_steps.get(key, 0) + 1
                    per = self.by_stage.setdefault(self.stage, {})
                    per[key] = per.get(key, 0) + 1
                    if self.first_contact_geometry is None:
                        o = scene.observe()
                        self.first_contact_geometry = {
                            "stage": self.stage, "t": round(float(o["t"]), 4),
                            "tool_pos": [round(v, 4) for v in o["tool_pos"]],
                            "cube_pos": [round(v, 4) for v in o["cube"]["pos"]],
                            "arm_qpos": [round(v, 4) for v in o["arm_qpos"]],
                            "weld_active": scene.weld_active(),
                            "pair": [g1, g2], "penetration_m": round(float(c.dist), 5)}

    def detach(self):
        self.scene.step = self._orig_step


def run_calibrated_episode(seed: int) -> dict[str, Any]:
    """Cold-start one seed through the Gate-B-proven sequence; measure everything."""
    t_wall0 = time.monotonic()
    scene = MuJoCoScene(seed=seed)
    recorder = TrajectoryRecorder(scene)
    scene.step(100)  # cold-start settle (gravity), now inside the contact gate
    iface = EmbodiedInterface(scene)
    obs = iface.observe()["observation"]
    cube = obs["cube"]["pos"]
    tray = obs["tray_pos"]
    init_q = [round(v, 6) for v in obs["arm_qpos"]]

    stages: list[dict[str, Any]] = []
    snap: dict[str, Any] | None = None
    measured = {
        "seed": seed,
        "mujoco_version": mujoco.__version__,
        "grasp_mechanism": f"{GRASP_MECHANISM} (disclosed simplification; NOT friction-only unconstrained grasp)",
        "stages": stages,
        "unexpected_collisions": [],
        "failure_stage": None,
        "failure_reason": None,
    }

    def stage(name, runner):
        recorder.mark(name)
        st = runner()
        stages.append({"stage": name, "state": st.get("state"),
                       "steps": st.get("steps"), "err_m": st.get("last_err_m"),
                       "reason": st.get("reason"), "mechanism": st.get("grasp_mechanism")})
        if st.get("state") not in ("done", True):
            measured["failure_stage"] = name
            measured["failure_reason"] = st.get("reason") or st.get("error")
        return st

    stage("approach_above", lambda: _run(iface, "move_to",
                                         {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "c1"))
    stage("approach_down", lambda: _run(iface, "move_to",
                                        {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "c2"))
    stage("grasp", lambda: _run(iface, "grasp", {}, "c3"))
    if measured["failure_stage"] is None:
        stage("lift", lambda: _run(iface, "move_to",
                                   {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "c4"))
        scene.step(LIFT_SETTLE_STEPS)
        snap = scene.oracle_snapshot()
        ok_g, ev_g = judge_grasp(snap)
        measured["grasp_local_oracle"] = {"ok": ok_g, "evidence": ev_g,
                                          "verification": "PENDING_ORACLE (in-process; uid463 channel HOLD)"}
        contacts = [(a, b) for a, b, _ in snap["contact_pairs"]]
        measured["finger_contacts"] = [c for c in contacts
                                       if "cube_geom" in c and ("fingertip_left" in c or "fingertip_right" in c)]
        stage("move_to_tray", lambda: _run(iface, "move_to",
                                           {"x": tray[0], "y": tray[1], "z": cube[2] + 0.15}, "c5"))
        if measured["failure_stage"] == "move_to_tray":
            measured["steady_state_probe"] = probe_steady_state(scene, iface,
                                                                [tray[0], tray[1], cube[2] + 0.15])
        stage("release", lambda: _run(iface, "release", {}, "c6"))
        scene.step(PLACE_SETTLE_STEPS)

    final = iface.observe()["observation"]
    final_q = [round(v, 6) for v in final["arm_qvel"]]
    tool_target = [tray[0], tray[1], cube[2] + 0.15]
    measured.update({
        "initial_arm_qpos": init_q,
        "final_arm_qvel": final_q,
        "final_tool_pos": [round(v, 6) for v in final["tool_pos"]],
        "final_tool_target": [round(v, 6) for v in tool_target],
        "final_tool_error_m": round(sum((a - b) ** 2 for a, b in
                                        zip(final["tool_pos"], tool_target, strict=True)) ** 0.5, 6),
        "final_cube_pos": [round(v, 6) for v in final["cube"]["pos"]],
        "final_cube_speed": round(float(sum(v * v for v in final["cube"]["vel"])) ** 0.5, 6),
        "in_tray_stable": bool(abs(final["cube"]["pos"][0] - tray[0]) < 0.055
                               and abs(final["cube"]["pos"][1] - tray[1]) < 0.055
                               and 0.015 <= final["cube"]["pos"][2] <= 0.09
                               and float(sum(v * v for v in final["cube"]["vel"])) ** 0.5 < 0.01),
        "max_single_step_cube_displacement_m_full_trajectory": round(recorder.max_step_d, 6),
        "instrumented_steps_by_stage": dict(recorder.stage_steps),
        "unexpected_collisions_full_trajectory": [
            {"geoms": list(k), "steps_present": v} for k, v in recorder.unexpected_steps.items()],
        "unexpected_collisions_final_snapshot_only": (
            [
                [a, b] for a, b, _ in snap["contact_pairs"]
                if is_unexpected_contact(str(a), str(b))
            ] if snap is not None else None),
        "physics_time_s": round(float(scene.data.time), 3),
        "wall_s": round(time.monotonic() - t_wall0, 3),
        "final_state_digest": scene.state_digest(),
    })
    recorder.detach()
    snap = scene.oracle_snapshot()
    ok_p, ev_p = judge_place(snap, tray)
    measured["place_local_oracle"] = {"ok": ok_p, "evidence": ev_p,
                                      "verification": "PENDING_ORACLE (in-process; uid463 channel HOLD)"}
    measured["unexpected_contacts_by_stage"] = {
        stage_name: {"/".join(k): v for k, v in per.items()}
        for stage_name, per in recorder.by_stage.items()}
    measured["first_unexpected_contact_geometry"] = recorder.first_contact_geometry
    measured["no_unexpected_contacts"] = len(recorder.unexpected_steps) == 0
    measured["passed"] = (measured["failure_stage"] is None
                          and measured.get("grasp_local_oracle", {}).get("ok") is True
                          and ok_p and measured["in_tray_stable"]
                          and measured["no_unexpected_contacts"])
    return measured


def probe_steady_state(scene, iface, target, max_steps=1200, sample_every=100):
    """Measurement-only residual decay curve after a move_to timeout.

    Servo targets stay as-is; we only keep integrating physics and record the
    tool->target residual. No tolerance or contract value is touched. Purpose:
    give the independent controller-calibration QA real steady-state numbers.
    """
    import numpy as np
    residuals = []
    for i in range(max_steps):
        scene.step(1)
        if (i + 1) % sample_every == 0:
            tool = iface.observe()["observation"]["tool_pos"]
            residuals.append({"step": i + 1,
                              "err_m": round(float(np.linalg.norm(
                                  np.asarray(tool) - np.asarray(target))), 6)})
    return {"target": [round(v, 6) for v in target],
            "residual_by_steps": residuals,
            "note": "measurement only; move_to_tray stage result unchanged (still failed at Gate-B tolerance)"}


def run_determinism_check(seed: int = 7) -> dict[str, Any]:
    a = run_calibrated_episode(seed)
    b = run_calibrated_episode(seed)
    def stage_sig(r: dict[str, Any]) -> list[tuple[str, Any, Any]]:
        return [(st["stage"], st["state"], st["steps"]) for st in r["stages"]]

    return {"seed": seed,
            "digest_equal": a["final_state_digest"] == b["final_state_digest"],
            "stage_trace_equal": stage_sig(a) == stage_sig(b),
            "deterministic": a["final_state_digest"] == b["final_state_digest"]
            and stage_sig(a) == stage_sig(b)}


def run_negative_checks() -> dict[str, Any]:
    out: dict[str, Any] = {}
    # N1: grasp at an empty offset point must fail honestly, weld stays off
    scene = MuJoCoScene(seed=7)
    scene.step(100)
    iface = EmbodiedInterface(scene)
    cube = iface.observe()["observation"]["cube"]["pos"]
    _run(iface, "move_to", {"x": cube[0] + 0.03, "y": cube[1] + 0.06, "z": cube[2] + 0.06}, "n0")
    g = _run(iface, "grasp", {}, "n1")
    out["grasp_empty"] = {"state": g["state"], "reason": g.get("reason"),
                          "weld_active": scene.weld_active(),
                          "rejected": g["state"] == "failed" and not scene.weld_active()}
    # N2: full sequence then release off-target -> place oracle must refuse
    ok_seq = True
    for name, params, key in (
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.07}, "n2"),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.010}, "n3"),
        ("grasp", {}, "n4"),
        ("move_to", {"x": cube[0], "y": cube[1], "z": cube[2] + 0.13}, "n5"),
        ("move_to", {"x": tray_of(scene)[0] + 0.15, "y": tray_of(scene)[1], "z": cube[2] + 0.15}, "n6"),
        ("release", {}, "n7"),
    ):
        st = _run(iface, name, params, key)
        ok_seq = ok_seq and st.get("state") == "done"
        if st.get("state") != "done":
            out["place_off_target_sequence_broken"] = {"stage": name, "status": st}
            break
    scene.step(PLACE_SETTLE_STEPS)
    tray = tray_of(scene)
    ok_p, ev_p = judge_place(scene.oracle_snapshot(), tray)
    receipt = make_receipt(scene.oracle_snapshot(), "place", ok_p, ev_p, "M1-baseline-v1-neg", scene.scene_epoch)
    out["place_off_target"] = {
        "sequence_completed": ok_seq,
        "local_place_ok": ok_p,
        "receipt_verdict": receipt["verdict"],
        "fake_success_rejected": (not ok_p) and receipt["verdict"] == "failure",
        "evidence": ev_p,
    }
    return out


def tray_of(scene):
    return [float(v) for v in scene.data.xpos[mujoco.mj_name2id(
        scene.model, mujoco.mjtObj.mjOBJ_BODY, "tray_a")]]


def code_shas() -> dict[str, str]:
    shas = {}
    rel = ["scripts/embodied/m1_calibrate.py", "src/llm_loop/embodied_sim/scene.py",
           "src/llm_loop/embodied_sim/sim.py", "src/llm_loop/embodied_sim/skills.py",
           "src/llm_loop/embodied_sim/oracle.py", "src/llm_loop/embodied_sim/contract.py",
           "src/llm_loop/embodied_sim/policy.py", "src/llm_loop/embodied_sim/episode.py",
           "src/llm_loop/embodied_sim/goal_binding.py"]
    for r in rel:
        p = ROOT / r
        if p.exists():
            shas[r] = hashlib.sha256(p.read_bytes()).hexdigest()
    return shas


def main() -> int:
    # Fail closed: once a receipt exists, only a NEW version may run.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{BASELINE_VERSION}.json"
    sidecar_path = OUT_DIR / f"{BASELINE_VERSION}.json.sha256"
    if out_path.exists() or sidecar_path.exists():
        raise FileExistsError(f"immutable calibration receipt exists: {BASELINE_VERSION}")
    t0 = time.monotonic()
    evidence: dict[str, Any] = {
        "baseline_version": BASELINE_VERSION,
        "scene_xml_sha256": hashlib.sha256(build_scene_xml().encode()).hexdigest(),
        "scene_revision_reason": ("v1.6.2 approved geometry (collision ENABLED on both changed "
                                  "geoms): l3 capsule end z0.12->0.11 and wrist_rod "
                                  "z[0.14,0.18]->z[0.12,0.13]; move_to physics-step budget "
                                  "600->750 (same 2ms timestep); _MOVE_TOL_M 13mm, 20-step "
                                  "settle, oracle thresholds and 180s episode budget unchanged. "
                                  "IK reachability is kinematically fine - the prior blockers "
                                  "were DYNAMIC CONTACTS (rod-cube scuffing then rod-floor "
                                  "obstruction), not pose unreachability. Failed candidates "
                                  "preserved: M1-baseline-v1.3-fail-rod-rear.json (0/10, "
                                  "approach_down 46.7mm), M1-baseline-v1.4.json (0/10, grasp "
                                  "miss), M1-baseline-v1.6-pre-metadata-fix.json (10/10 physics "
                                  "PASS but stale v1.2-era metadata, corrected here). "
                                  "M2 (issue #79, M1-baseline-v1.7): episode.py now re-observes "
                                  "the target and scene epoch after every action and at goal "
                                  "verification, and binds each claim to that goal digest "
                                  "(goal_binding.py, oracle/contract goal checks); POLICIES AND "
                                  "PHYSICS UNCHANGED - no tolerance, budget, geometry or step "
                                  "count moved, which is why the same 10 engineering seeds must "
                                  "reproduce exactly. Moving-target behaviour is covered by "
                                  "tests/embodied_m2/, not by this receipt. "
                                  "M2 review fix (M1-baseline-v1.8): episode.py's rebind now "
                                  "returns REPLAN at every re-observation point, voided actions "
                                  "stay attributed to the goal they ran against, and "
                                  "tool_action trace events keep t_s; POLICIES AND PHYSICS STILL "
                                  "UNCHANGED - only episode.py's digest moved."),
        "legacy_note_v13": ("TASK-008 approved minimal geometry fix: wrist_rod relocated "
                                  "from link3 z[0.14,0.18] (overlapping tool作用区 z~0.123..0.163 "
                                  "incl. tool_site 0.143) to wrist-rear conduit z[0.18,0.22]; "
                                  "collision remains enabled; v1.2 BASELINE_FAIL 0/10 root cause "
                                  "was rod scuffing cube in approach_down then welded into a "
                                  "constant rigid contact"),
        "hard_gate_scope": ("v1.5+: ALL unexpected contacts are hard-gated (including "
                            "wrist_rod<->floor and any arm-body floor contact), per-stage "
                            "attribution and first-contact geometry retained; cube-only filter "
                            "was a P1 calibration gap identified by independent Host QA"),
        "cold_start_scope_note": ("v1.6.2-v1.6.5 include all 100 initial gravity-settle steps "
                                  "in the full-trajectory contact gate; earlier receipts start after settle. "
                                  "v1.6.3 revalidated Gate C progress feedback; v1.6.4 hardened "
                                  "place and grasp truth; v1.6.5 revalidates public release hint "
                                  "after episode_008 empty finish=length. Physics unchanged."),
        "metadata_correction_disclosure": ("v1.6 (pre-metadata-fix) contained stale v1.2-era "
                                           "scene_revision_reason text; QA read it before this "
                                           "correction, so the original bytes are preserved as "
                                           "M1-baseline-v1.6-pre-metadata-fix.json and the "
                                           "corrected receipt is issued as v1.6.1."),
        "revision_note": ("v1.2: unexpected non-gripper cube contacts promoted to a HARD verdict "
                          "gate (no_unexpected_contacts); per-stage attribution and first-contact "
                          "geometry added. Tolerances and oracle thresholds remain UNCHANGED. "
                          "v1 initial-fail preserved as M1-baseline-v1-initial-fail.json; "
                          "v1.1 (pre-safety-gate) preserved as M1-baseline-v1.1-pre-safety-gate.json"),
        "mujoco_version": mujoco.__version__,
        "scene_constants_digest": hashlib.sha256(
            json.dumps(SCENE_CONSTANTS, sort_keys=True).encode()).hexdigest(),
        "calibration_seeds": CALIBRATION_SEEDS,
        "prereg_note": ("engineering baseline seeds 0..9; prereg paired_seed_start=20261117 "
                        "is reserved for the Gate D B1/B2 comparison and untouched"),
        "code_sha256": code_shas(),
    }
    seeds = [run_calibrated_episode(s) for s in CALIBRATION_SEEDS]
    evidence["seed_results"] = seeds
    evidence["determinism_check"] = run_determinism_check(7)
    evidence["negative_checks"] = run_negative_checks()
    all_pass = all(r["passed"] for r in seeds)
    neg_ok = (evidence["negative_checks"]["grasp_empty"]["rejected"]
              and evidence["negative_checks"]["place_off_target"]["fake_success_rejected"])
    det_ok = evidence["determinism_check"]["deterministic"]
    # runtime structural verification for the only whitelisted non-cube pair
    _probe = MuJoCoScene(seed=0).model
    _bid = mujoco.mj_name2id(_probe, mujoco.mjtObj.mjOBJ_BODY, "link1")
    _parent = mujoco.mj_id2name(_probe, mujoco.mjtObj.mjOBJ_BODY, int(_probe.body_parentid[_bid]))
    _base_geom = mujoco.mj_name2id(_probe, mujoco.mjtObj.mjOBJ_GEOM, "base_geom")
    _l1_geom = mujoco.mj_name2id(_probe, mujoco.mjtObj.mjOBJ_GEOM, "l1")
    _shoulder = mujoco.mj_name2id(_probe, mujoco.mjtObj.mjOBJ_JOINT, "shoulder_pan")
    _base_body = mujoco.mj_name2id(_probe, mujoco.mjtObj.mjOBJ_BODY, "arm_base")
    structural_ok = (_parent == "arm_base"
                     and int(_probe.geom_bodyid[_base_geom]) == _base_body
                     and int(_probe.geom_bodyid[_l1_geom]) == _bid
                     and int(_probe.jnt_bodyid[_shoulder]) == _bid)
    evidence["structural_whitelist_verification"] = {
        "pair": ["base_geom", "l1"],
        "link1_parent_body": _parent,
        "shared_joint": "shoulder_pan",
        "adjacent_assembly_confirmed": structural_ok,
    }
    evidence["cold_start_contact_gate"] = {
        "expected_steps": 100,
        "all_seeds_instrumented": all(
            r["instrumented_steps_by_stage"].get("cold_start_settle") == 100
            for r in seeds),
    }
    evidence["independent_oracle"] = "PENDING_ORACLE (uid463 Host Worker accepted; trusted signer NOT_INSTALLED)"
    if (all_pass and neg_ok and det_ok and structural_ok
            and evidence["cold_start_contact_gate"]["all_seeds_instrumented"]):
        evidence["verdict"] = "LOCAL_PHYSICS_BASELINE_PASS"
    else:
        evidence["verdict"] = "BASELINE_FAIL"
    evidence["failures"] = [ {"seed": r["seed"], "stage": r["failure_stage"],
                              "reason": r["failure_reason"]}
                             for r in seeds if not r["passed"] ]
    evidence["wall_total_s"] = round(time.monotonic() - t0, 3)
    blob = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    with out_path.open("x", encoding="utf-8") as f:
        f.write(blob)
    sha = hashlib.sha256(blob.encode()).hexdigest()
    with sidecar_path.open("x", encoding="utf-8") as f:
        f.write(sha + "\n")
    print(json.dumps({"verdict": evidence["verdict"],
                      "seeds_passed": sum(1 for r in seeds if r["passed"]),
                      "deterministic": det_ok, "negatives_fail_closed": neg_ok,
                      "failures": evidence["failures"],
                      "evidence_sha256": sha}, indent=2))
    return 0 if evidence["verdict"] == "LOCAL_PHYSICS_BASELINE_PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
