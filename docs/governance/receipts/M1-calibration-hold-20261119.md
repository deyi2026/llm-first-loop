# M1 Calibration HOLD — 2026-11-19 (TASK-008 close-out)

> **Current status (TASK-009, 2026-11-19):** Local physics calibration
> `M1-baseline-v1.6.2` is **LOCAL_PHYSICS_BASELINE_PASS (10/10)**.
> Independent Oracle uid463 remains **PENDING_ORACLE / HOLD**. The historical
> TASK-008 failure analysis below is retained as an audit trail and is superseded
> by the subsequent independent QA correction and TASK-009 results.

## Verdict
M1-baseline 标定 **BASELINE_FAIL 维持**（安全硬门：全轨迹无非预期腕杆-cube 接触）。
scene.py 已恢复至已验收基线几何（rod axial z[0.14,0.18] r0.004，
scene_xml_sha256=f64d0cb0ea84843b0412a6913c8bd3798d19e4b8f98c6385af63457ecea79df7）。
修复尝试按 QA 时间盒执行一轮后停止调参，历史回执全部冻结保留。

## Evidence ledger (immutable, sha256 sidecars)
- M1-baseline-v1-initial-fail.json        5/10 PASS（旧判据，move_to_tray 13mm 贴边超时 ×5）sha f0ff6c63…9dcf
- M1-baseline-v1.1-pre-safety-gate.json   5/10（仪器化重跑，判据未变）sha b6a50160…125c
- M1-baseline-v1.2.json                   0/10（安全硬门生效：rod↔cube 全轨迹接触）sha d8b27eb5…6cd3
- M1-baseline-v1.3-fail-rod-rear.json     0/10（rod 后移 z[0.18,0.22]：approach_down 回归 46.7mm）sha b5b0f4f2…76aa
- M1-baseline-v1.4.json                   0/10（侧向双杆 y=±0.03 r0.003：grasp 全败同形态）sha b7fe3972…365

## Root-cause chain (measured, not assumed)
1. v1.2 首触：approach_down 中 rod（轴向，腕后）擦过 cube 后上沿，penetration 0.58–0.81mm，weld_active=false。
2. weld 在该位形建立后 rod–cube 成为恒定刚性相对几何 → 搬运全程持续接触（1200–3600 步）。
3. 关键发现：v1.2 的 approach_down「done（12mm）」与 grasp 接触**依赖 rod 的物理阻挡**（rod 顶住 cube 形成无意背撑）。
4. 移除阻挡（v1.3/v1.4）后暴露真实缺陷：approach_down 目标 z=cube+0.010 在肘/肩限位位形下**伺服不可达**
   （残差 46.7mm；v1.2 的 12mm 是挡块造成的偶然物理停止，恰好落入容差——非真实可达性证据）。
5. 下压过程推滑 cube → 指尖闭合扑空（v1.3/v1.4 grasp 全败一致形态）。

## Next-stage minimal design options (for independent QA to choose; NOT implemented)
- A 轨迹层：两段式下压——先在 cube 正上方 0.07 悬停对准，再以更低位形限速纯竖直接近；不动场景几何。
- B 场景层：腕部结构重设计（ rod 移出 cube 扫掠带且不充当背撑），需连带重校下压位形的 IK 可达性。
- C 控制层：move_to 分段中途重解 IK（避免单一限位位形），并对 move_to_tray 13mm 贴边同因处理。
- 任何方案落地 = 新 experiment_id（v1.5+）+ before/after 双回执 + 独立 QA 复核；不得放宽 13mm/Oracle 判据。

## Dependencies / holds
- 独立 Oracle（uid463 跨 UID）仍 PENDING_ORACLE / HOLD，未接 sudoers/NOPASSWD。
- BASELINE 未 PASS 前不启动 GLM 新一轮真实 A/B（Gate D），不申请 merge/CI/部署。
- 沙箱内 git index 写 EPERM：本轮 scene.py 恢复用内容级 sed 完成（与 HEAD 5598fdb2 的 scene.py 内容一致），
  受管 commit 由 Host 执行。

## Independent QA correction (2026-11-19, Host measurement) — supersedes prior root-cause wording

The earlier "IK/joint-limit unreachable" claim in this file was an **inference error** and is
hereby corrected by independent Host measurements (isolated MuJoCo 4.0.1, seed 7, descent
target xyz=(0.18000369, 0.00089624, 0.031)):

| Variant | tool err after 600 steps | rod↔cube steps | rod↔floor steps |
|---|---|---|---|
| original rod + cube present | 0.008494 m | 808 | 462 |
| original rod + cube temporarily removed (diagnostic only) | 0.008344 m | 0 | 512 |
| rear rod (v1.3) + cube present | 0.045564 m | 38 | 581 |
| rear rod + cube temporarily removed (diagnostic only) | 0.045543 m | 0 | 581 |

Corrected statement: the approach_down target is **kinematically reachable** (pure-IK
residual ≈ 2.7–3.0 mm; reproduced locally by scripts/embodied/m1_kinematic_probe.py).
The v1.3 46 mm servo stall is a **dynamic obstruction by wrist_rod↔floor contact**
(581 steps with/without cube — identical, proving the cube is not the cause).
The original scene also exhibits heavy rod↔floor contact (462–512 steps). The cube
relocation rows are a pure diagnostic control (NOT task execution, NOT success).

Calibration hard-gate P1 gap fixed in M1-baseline-v1.5: TrajectoryRecorder now
hard-gates ALL unexpected contacts (including wrist_rod↔floor and any arm↔floor)
with per-stage attribution; the previous cube-only filter missed the decisive pair.
Local read-only probe (m1_kinematic_probe.py) reproduces the Host numbers:
rod↔floor 460 steps vs Host 462; FK residual 2.99 mm vs Host 2.75 mm.


## TASK-009 current local physics result (2026-11-19)

- Frozen candidate: `M1-baseline-v1.6.2.json`, SHA-256
  `9ae1b7eeed11cde8e6039492e7a36725051ea00671001fbf53ccaa17bede6ff2`;
  the corresponding `.json.sha256` is retained.
- Collision-enabled geometry: `l3` capsule end z=0.11 instead of 0.12;
  `wrist_rod` z=[0.12,0.13] instead of [0.14,0.18]. No collision disable,
  no 13 mm tolerance relaxation, and no Oracle threshold relaxation.
- The `move_to` budget is 750 rather than 600 physics steps (2 ms per step);
  the 20-step settle criterion and 180-second episode budget remain unchanged.
- 10/10 fixed engineering seeds passed in-process physics grasp/lift/place.
  The collision hard gate now instruments **all 100 cold-start settle steps**
  as well as the remaining trajectory. No unexpected contacts in those seeds.
  The sole non-cube structural whitelist `base_geom/l1` is checked against
  actual MuJoCo body/geom/joint ownership; failure is a verdict blocker.
- Empty grasp and off-target placement were rejected, and same-seed
  determinism passed. These are **local** checks, not independent uid463
  Oracle acceptance and not a real GLM autonomous episode.
- Host verification: `tests/embodied_m1` **49 passed** before the final
  evidence-hash pinning test additions; Ruff PASS and Pyright 0 errors.
  A subsequent final test run is required after those additions.

### Evidence-integrity incident and correction

During this QA cycle, an early local `v1.6.1` run was repeated before the
exclusive-create guard was added. The original pre-rerun JSON SHA-256 was
`84043c4adf0a9bc294e744025f16d6e02e1d06aaa3cbb470e859fed0a0130a1c`;
the current re-run JSON SHA-256 is
`167c63560d346f74067381341e20427822350f0e4dcbb814575b4667d760590d`.
The original bytes were not recovered. This is an **acknowledged pre-freeze
evidence overwrite**, not an unchanged historical record. No other historical
receipt changed in the before/after audit. The `v1.6.2` generator now
refuses to reuse any existing JSON or SHA-sidecar version, creates files
exclusively, and tests pin fixed expected hashes (not merely JSON/sidecar
self-consistency). Older `v1.6` pre-metadata-fix receipts remain preserved.

### Remaining gates

Independent Oracle uid463 cross-UID Host acceptance is still on HOLD pending
a separately authorized, least-privilege Host installation. No GLM autonomous
B1/B2 evaluation, independent Reviewer PASS, full R9, remote CI, protected
main merge, or unified deployment has been claimed for this M1 candidate.
