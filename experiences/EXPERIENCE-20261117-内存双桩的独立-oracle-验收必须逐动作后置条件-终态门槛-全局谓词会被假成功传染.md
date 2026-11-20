---
title: 内存双桩的独立 Oracle 验收必须逐动作后置条件+终态门槛，全局谓词会被假成功传染
scenario: "具身智能 M0-A 内存双桩合同测试（DESIGN-20261116 embodied v2.3 §11.1.1）：模拟\"执行端宣称成功但独立 Oracle 验收\"场景时，第一版 StubOracle.verify() 用全局目标谓词且不查动作终态。"
root_cause: "假成功通道的共同根因：验收层与执行层共用状态且谓词粒度错配（全局谓词+无终态门槛+效果判定未绑定已知目标集合），使\"宣称成功\"能沿真值传染。"
solution: 独立 Oracle 验收必须逐动作化：按 action_id 记录该动作效果（world_changed 绑定已知目标/托盘集合）、verify_effect 只读本动作记录+隐藏世界状态、验收前强制终态门槛（未定态 Denied）、UNKNOWN 冻结做成机械副作用、零副作用证据加拦截能力自证。测试断言拒绝码+动作计数。
evidence: "两轮独立 Reviewer（deepseek-v4-flash，只读）回执：Reviewer#1 对候选v2 给 REVISE+4条P0/P1 精确定位；修补后 Reviewer#2 复审独立探针确认前四条真修复，同时抓出残留 P0（place 未知托盘 VERIFIED 通道）佐证第3条；pytest tests/embodied 6 passed exit=0（/tmp/embodied-m0a-pytest-final-v3.log）；候选 SHA：stubs=dc7bd60f…24b3、test=4b4a6088…8e3c。"
tags: [embodied, oracle-verification, fail-closed, dual-stub, m0-a, per-action-postcondition]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-17T00:17:36.140840+08:00"
updated_at: "2026-11-17T00:17:36.140840+08:00"
---

M0-A 具身双桩审查两轮独立确认的语义缺陷模式：1) 验收谓词若为全局目标判定（如"目标已入托盘"），任何先前真动作的真值会传染给后续假动作——执行端对假动作宣称成功+claim 后仍可获 VERIFIED。修复：Oracle 按 action_id 记录每动作效果（world_changed 等），verify_effect(action_id) 只读该动作记录+隐藏世界态。2) 验收前必须设终态门槛：RUNNING/UNKNOWN/INTERRUPTED 一律拒收验收（返回 Denied 而非写 VERIFIED）。3) 效果记录的 world_changed 判定必须绑定已知目标集合（place 到未知托盘 world_changed=True 仍是假成功通道——第二轮 REVISE 抓到）。4) UNKNOWN 冻结必须是双桩机械行为（返回 UNKNOWN receipt 前自动写 holds），不能依赖调用方显式登记。5) 零副作用断言需要"拦截能力自证"（触发被替换的 socket 构造必抛错+计数，再清零）才有真实证据链，恒零计数是空转断言。审查判据：断言拒绝码+动作计数，不用错误消息字符串。
当前性验证（2026-11-16 候选 v3，SHA stubs=dc7bd60f…24b3）：cd <repo>/.worktrees/embodied-m0a-tests-20261116 && <repo>/.venv/bin/python -m pytest tests/embodied -q 应得 6 passed exit0；python -c 传染复现：真 pick cube-red→VERIFIED 后假 pick cube-ghost+claim→verify_with_oracle 应返回 EXECUTED_UNVERIFIED（第1条已修复的直接证据）；残留缺陷复现：pick cube-red 后 place tray_id=tray-ghost → verify_with_oracle 应返回 VERIFIED（第3条残留 P0-新1，M1 前必须修——若该命令已返回 EXECUTED_UNVERIFIED 则说明该缺陷已被后续修补关闭，本条对应子项过时）。