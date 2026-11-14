---
title: "验证软告警前先隔离硬门：同 goal 第二条 main lane 会被 1:1 硬拒，测不到 paths 重叠告警"
scenario: 测试「某维度只告警不阻断」时，用同一唯一性维度（如同一 goal 开第二条 main lane）构造输入，被硬裁决先拦，导致软告警路径完全未被覆盖
root_cause: ""
solution: 先枚举入口的所有硬门，逐项喂合法值，只保留被测维度为违规；本次改为第二条 lane 用不同 goal_id，仅 paths 交叉，82 passed
evidence: "tests/unit/test_lane_precheck.py::test_overlap_warning_does_not_block 首版 1 failed（_assert_unique 硬拒，回执无 overlap_warning）；改 goal_id=goal-10 后 lane 相关 5 个测试文件 82 passed；同一提交 9b88107a4 已过 ci_gate exit=0 与两轮独立审查 PASS"
tags: []
source:
  goal_id: GOAL-20261114-5dd32a6d
  lane_id: lane-a0ac0f0b
  commit: 9b88107a4
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T13:09:42.079021+08:00"
updated_at: "2026-11-14T13:09:42.079021+08:00"
---

## 场景
为 lane 开门验证「paths 重叠只告警不阻断」（同类还有：任何"软告警 vs 硬裁决"并存的入口），写测试时用同一 goal_id 连开两条 main lane 来制造路径重叠。

## 现象
测试首跑失败：第二条 lane 被 `LaneStore._assert_unique` 以「同 goal 至多一条在途 main lane」直接拒绝，回执里根本没有 overlap_warning。测到的是 1:1 硬裁决，不是软告警路径。

## 根因
同一入口上叠加了两个门：goal 1:1 硬拦（branch/worktree/goal 唯一性）与 paths 重叠软告警。构造软告警的输入时复用了会被硬拦的维度，于是硬门先命中，软门永远测不到。

## 正确做法
隔离被测门：验证软告警时，把硬拦维度全部置为合法值。
- 第二条 lane 用不同 goal_id（或 lane_role=sub，若该路径允许）
- 保留唯一的重叠维度：paths 交叉
- 修正后 82 passed

## 推广判据
测试「A 只告警不阻断」前，先列清该入口的所有硬门（唯一性/权限/状态迁移），逐项喂合法值，只留被测维度为违规。否则拿到的"通过"或"失败"都可能来自另一个门。

## 反例
若直接放宽断言（改成接受 FAILURE），会把"1:1 硬拦生效"误记成"告警逻辑正确"，两处逻辑都失去覆盖。