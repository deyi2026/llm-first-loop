# M1 Calibration HOLD — 2026-11-19 (TASK-008 close-out)

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
