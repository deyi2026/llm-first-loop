---
method_id: terminal-gate-receipt-is-contract-no-idempotent-repoll-8eafbd82d2d8
name: terminal-gate-receipt-is-contract-no-idempotent-repoll
description: 门禁/审查子代理的 status 回执一旦进入终态（qualification=PASS/FAIL，非 pending），它就是签发合同快照：对同一 child_id 重调 status 是幂等只读，缺失的字段（如任务点名的显式 P0/P1 计数）不会因复读出现。正确做法是把验收项逐条映射到回执显式字段或签发语义（PASS 签发即 P0/P1 闸通过），全部可解就立即消费资格进入下一步，并在最终报告如实标注哪些是显式核验、哪些由语义推得。
aliases: PASS了还要再查一遍status吗, 终态回执别复读, 回执没有P0P1计数怎么办, 审查过了直接跑CI别再确认, 资格签发即过闸, 幂等状态查询重复调用
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ec1f3ab3-b3b9-4c2a-8810-f67f133c40ad:0:7e805a6e1bfa226c820b
evidence_refs: learning:learn:998134cf56f3
created_at: 2026-11-08T21:38:11.529020+08:00
updated_at: 2026-11-08T21:38:11.529020+08:00
---
## Trigger
任务书规定『真实 completed + qualification PASS + P0=0/P1=0』后才可消费资格；review_admission(status) 已返回终态回执（qualification=PASS、artifact_reviewed、SHA/scope 绑定齐全），但回执 schema 不含任务点名的显式严重级计数字段。

## Discriminator
终态回执与 pending 回执的形态差异：无 review_still_running、有 qualification 终值与签发语义（如『签发后改动即失效』）。终态下同一 child_id 的 status 是幂等只读快照，缺失字段不会因再查一次出现；此时剩余未知量是『验收语义映射』，不是『再查一次』。

## Short path
- 收到终态 qualification 回执后，在同一回执内核对 candidate_sha256/scope 与 precheck 是否一致；
- 把验收项逐条映射：显式字段直接采信；缺失项用签发语义裁决（PASS 签发即 P0/P1 闸通过），一次完成，不重调 status；
- 全部可解→立即执行被授权的消费动作（如后台启动 ci_gate）；
- 最终报告如实标注各验收项口径来源：显式字段核验 vs 签发语义推导。

## Stop conditions
- 终态回执 + SHA/scope 绑定与 precheck 一致 + 每条验收项均被显式字段或签发语义覆盖；
- 消费动作已被接受并进入执行（后台 job 成功启动）。

## Verification
- 回执 candidate_sha256 与 precheck 一致、scope 覆盖全部声明路径且 paths_ignored=false；
- 消费动作未被 fail-closed 拒绝，证明资格真实有效；
- 报告中的闸计数注明来源（显式/语义），不虚构回执里不存在的字段值。

## Counterexamples
- 回执仍 pending/running：按任务书继续 wait+status 轮询是必需动作，重调不算零信息复读（属 repeat-guard 前件审计法管辖区）；
- 存在独立结果通道（如 job_output、findings 详情端点）可能携带显式计数：对它做一次有界读取合理，反模式仅指重复读取同一终态快照；
- 终态回执与 precheck 绑定矛盾（SHA 不匹配）：不得消费资格，走停止/上报路径而非复读 status。
