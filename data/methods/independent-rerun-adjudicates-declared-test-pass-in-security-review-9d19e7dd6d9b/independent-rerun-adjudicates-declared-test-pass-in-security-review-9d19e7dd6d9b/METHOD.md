---
method_id: independent-rerun-adjudicates-declared-test-pass-in-security-review-9d19e7dd6d9b
name: independent-rerun-adjudicates-declared-test-pass-in-security-review
description: 独立审查中，发起方声明的测试结论（如"N targeted PASS"）是被审断言而非事实：当任务书明文要求裁决该声明（"声明与真实变更一致"类义务）或它构成验收证据核心时，用项目权威解释器对声明所指套件做一次定点重跑——重跑本身就是判别器。红→P0"声明不可复现"坐实，失败 traceback 指向的 require/断言行直接给出根因段（本集：硬编码期望 gid 致 tmp_path 环境必红）；绿→声明可信，转入代码级清单核验，不再重复跑。终判必须区分"本run独立复现"与"仅转述发起方"，不得混写。
aliases: 发起方说测试全过要不要信, 独立复审要不要重跑测试, 复跑结果与声明数对不上, 验收声明先跑一遍再签, 安全门禁测试声明核实
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d96460e0-9d3f-47db-9e33-2f70ead9bf86:0:4669e93a18dbab1bb746
evidence_refs: learning:learn:f6fbdd309d01
created_at: 2026-11-17T02:05:15.296243+08:00
updated_at: 2026-11-17T02:05:15.296243+08:00
---
## Trigger
独立安全/准入审查任务把发起方声明的测试结果列为被审对象，且预算尚允许1-2次执行类调用时。判别背景：该声明既是任务点名的裁决义务，又是终判拟引用的关键证据。

## Discriminator
两个当时已知事实同时成立即触发：①任务书/验收义务点名要核对发起方声明（声明=待审断言，不是背景信息）；②存在当前环境可复现的 targeted 套件与项目权威运行环境。此时一次重跑把"声明真伪"这个未知量直接缩成红/绿终态，无需靠读代码推断。

## Short path
- 先自证冻结锚点（HEAD==任务SHA）并核对声明对应物（如 diff --stat 对路径清单），同时定位声明所指测试文件与剩余预算
- 用项目权威解释器（venv/冻结运行时，而非环境默认解释器）重跑该 targeted 套件一次——避免依赖级失败白耗硬预算
- 红→把失败用例+file:line 记为 P0"声明不可复现"；沿 traceback 指向的 require/断言行直读根因段，产出最小修复建议
- 绿→声明可信，停止执行类调用，把剩余预算全部用于清单项代码级核验

## Stop conditions
- 重跑结果与声明一致（全绿且数量吻合）→ 声明裁决完毕，不重复执行测试
- 套件依赖当前环境结构性不可达的状态（特权 UID、未完成的部署/安装态）→ 该项降级为"未验证事项"，不得当作红/绿证据，也不据此翻转 HOLD
- 预算已不允许任何执行调用 → 终判中显式声明"该声明未经独立复核"，禁止把它当 PASS 依据

## Verification
- 终判中每条 PASS/FAIL 断言都能指出证据来源是"本run独立复现回执"还是"转述发起方声明"，两者分开标注
- 失败根因已按 traceback 指向的 file:line 直读确认（而非仅凭失败用例名推断），并验证根因与环境参数（如 gid/uid 来源）的因果一致

## Counterexamples
- 修复复审场景：上一轮 P0/P1 修复点逐项核对、发起方刚复跑过全量、预算紧张 → 不重跑，走清单词族行号图+聚簇 span 的代码级审查
- 测试需要不存在的特权安装态（如独立 UID 部署验收）→ 重跑必然结构性失败，把环境不可达当"测试红"会制造假 P0；应维持 HOLD 并如实列未验证项
- 声明是静态可机械核对的（路径清单、SHA、diff --stat）→ 零成本核对即可，不值得消耗执行调用
- 发起方进入审查前的守卫预飞（守卫红会改候选 SHA、该轮审查注定作废）→ 属 gate 前止损决策，不是审查中的声明裁决，别混用
