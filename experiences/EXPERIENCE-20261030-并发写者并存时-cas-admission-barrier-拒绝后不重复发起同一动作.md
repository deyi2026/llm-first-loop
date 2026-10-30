---
title: 并发写者并存时，CAS/admission-barrier 拒绝后不重复发起同一动作
scenario: Goal 上线期同一工作区有并发写者会话：我的 publish 被 CAS 拒绝（current=345，已有他人 desired），我对 wecom 发起的 restart 被 `admission barrier conflict … svc-828b16db…` 确定性拒绝。
root_cause: 控制面的 CAS 与 admission barrier 就是并发下的仲裁器；重复发起同一动作会抢闸、生成多余代（进而让在飞的重启因 generation 复核失效），属于净损失。
solution: 把拒绝回执当当前事实：① 不重复 publish，避免制造 gen+1；② 不重复 restart，先查 action 台账/读 live manifest 判断他人是否已达成目标；③ 若确需自己发起，先用 status(action_id) 确认无在飞同服务动作再发；④ 被 barrier 挡回时改走只读确认路径（本次 wecom 最终由会话 fd308b28 的动作完成 confirmed_ok）。
evidence: "evidence://v1/c9799ec77e6eeb4778f4eb67861f7037090d44eb2efc432d6a1e03ae2aaf1b22（wecom barrier 拒绝；同一动作随后 succeeded，verify=confirmed_ok wecom[ok pid=7401 head=913f2945a314]）；publish 侧 CAS 拒绝记录见本会话 service_control 回执，desired 仍停在 gen 345 未被抬到 346"
tags: [service_control, concurrency, deployment]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-30T23:39:20.390454+08:00"
updated_at: "2026-10-30T23:39:20.390454+08:00"
---