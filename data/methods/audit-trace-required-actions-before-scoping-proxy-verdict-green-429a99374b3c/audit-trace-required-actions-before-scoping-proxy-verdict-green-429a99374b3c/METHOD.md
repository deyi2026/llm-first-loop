---
method_id: audit-trace-required-actions-before-scoping-proxy-verdict-green-429a99374b3c
name: audit-trace-required-actions-before-scoping-proxy-verdict-green
description: 代理/本地判分器返回绿（local_verdict.ok=true、terminated_by=*verified_locally*）时，绿只覆盖其证据字段机械编码的判据，不等于目标语义完成。报告口径前先做一次轨迹-语义核对：把决策轨迹与目标必需的终止动作模式（如 grasp 后必须有 release 才算 place 完成）机械比对。必需动作缺失⇒按范围限定口径如实报告（几何通过≠放下语义），并把判据缺口登记为下轮候选修复，冻结期不改源码。防止把代理判据的绿当完整成功推进错误里程碑，也避免到 Oracle/复验阶段才发现放置不完整而返工重跑。
aliases: 抓了没松手就算放好了吗, 判绿但动作链不完整, 回放决策序列找漏掉的必做步骤, 判分器口径比目标窄怎么办
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:588:12d49f093fabd5d60a74
evidence_refs: learning:learn:098fd0a45111
created_at: 2026-11-19T15:31:00.590109+08:00
updated_at: 2026-11-19T15:31:00.590109+08:00
---
## Trigger
带 prereg 预算的 agent 行为评测回合以本地判定绿终止（terminated_by 形如 place_verified_locally_*、local_verdict.ok=true），而判分器证据字段只是几何/代理量（位置/高度/速度），目标语义还要求未出现在任何判据中的动作（如 place 前必须 release）。

## Discriminator
当时可见两事实任一即触发细看：① 判定证据键清单机械地不含任何'脱离持握/已释放'类字段（只有 inside_tray_xy/height_ok/speed 类几何键），而目标语义含该动作；② 终态显著快于既有基线（本集 10.6s 终态 vs episode_006 120.1s）。同文件决策轨迹显示 grasp 后无 release、终止动作是 move_to——'判据未覆盖必需动作'在采信绿之前即可确认。

## Short path
- 回合终态后一次性取回判定回执+决策轨迹（同文件），不先入'绿=成功'口径
- 机械比对：证据键清单 ↔ 目标语义必需终止动作模式（如每个 grasp 须有后继 release 才允许 place 终止）；快于基线的终态作为加倍细看提示
- 必需动作缺失 ⇒ 报告改用范围限定口径：写明哪些判据通过、语义上缺什么；checkpoint 如实记录判据缺口为下轮候选，遵守冻结指令不改源码
- 报告与 checkpoint 落盘即停；Oracle 侧保持 PENDING，不自签补判

## Stop conditions
- 轨迹包含全部语义必需动作且判定绿 → 按完整本地成功报告（oracle 状态照实保留）
- 必需动作缺失 → 范围限定报告 + 判据缺口登记完成即停
- 判定红 → 退出本方法，转失败路径排查

## Verification
- 对目标每个必需终止动作，在证据键或轨迹事件中逐条找到映射；缺一即不得报完整成功
- terminated_by 是判分器自述；报告结论以轨迹核对结果为准，不反向引用自述当证据

## Counterexamples
- 判分证据已直接编码脱离条件（存在 grasp_active/released 类键且值正确）→ 绿可信，无需轨迹取证
- 判定来自覆盖完整语义的权威签名 Oracle → 只核签发者身份，不做本地代理口径限定
- 任务无动作序列语义（纯测量/纯报告/单点查询）→ 轨迹模式比对不适用
- 完成快本身不是缺陷结论：合法少步路径也会早终；速度只作细看提示，不得单独作为重跑理由
