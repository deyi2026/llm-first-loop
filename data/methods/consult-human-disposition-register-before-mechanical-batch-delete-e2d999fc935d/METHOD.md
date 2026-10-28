---
method_id: consult-human-disposition-register-before-mechanical-batch-delete-e2d999fc935d
name: consult-human-disposition-register-before-mechanical-batch-delete
description: 对『已合并⇒可删』类批量清理，机械判据（--merged/patch-id/worktree 状态）只证内容等价，不证处置意图。治理化仓库常维护按对象点名的人工登记（governance/triage/ADR 文档）：删除前用一次廉价查询提取『保留』名单并从可删集扣除。零成本旁证：待删集中卡龄远超同期、跨越多次历史清理仍存活的长命对象（experiment/poc/design 类）。流程：机械分类 → 查人工登记求差 → 归档 bundle+verify → 删 → 快照差分验证。登记与机械结论冲突时上报或按登记新旧复核，不静默以机械结论覆盖登记；删错后靠 bundle 恢复兜底应视为 gate 失败而非成功。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1486:51d49a099b6ef3a65565
evidence_refs: learning:learn:8bf1538e6830
created_at: 2026-10-21T21:44:55.707926+08:00
updated_at: 2026-10-21T21:44:55.707926+08:00
---
## Trigger
批量删除可由机械等价判据（拓扑 merged / patch-id）定罪的对象集合（分支、worktree、快照），且所在仓库/系统可能存在人工处置登记层。可见信号：治理类经验卡命中、docs/governance 类文档惯例、待删集中含跨越多次历史清理仍存活的长命对象（dated 命名卡龄远超同期分支）。

## Discriminator
删除动作发生前，『人工处置意图』是否已作为独立未知量被消解。机械分类只回答内容等价；当卡龄异常（同期分支皆被处理而它独活多次 triage）或仓库有治理文档惯例时，人工保留先验升高。一条登记查询（ls docs/governance、git log -- docs/governance、按名 grep 保留标记）即可把候选集从『全部机械可删』缩为『机械可删且未被登记保留』。

## Short path
- 机械分类生成候选可删集（拓扑 + patch-id），并完成 worktree 占用/脏状态副作用审计——这只消解『内容是否已等价落库』
- 删除前插入登记查询步：定位仓库自身 triage/governance/ADR 登记，提取按名点『保留/暂缓』名单；未知量：哪些机械可删对象带人工保留意图
- 可删集 = 机械可删 ∖ 登记保留；登记与机械结论冲突时按登记新旧与当前 main 活动复核或上报，不静默取机械侧
- 删除前打可验证归档（git bundle + verify）作为可逆底座
- 删除后用前后全量 branch/ls-remote 快照差分核对恰好等于预期集；任何登记点名『保留』的对象出现在差分中即从归档恢复并记为 gate 失败

## Stop conditions
- 可删集已完成与人工登记的求差，且归档 bundle 已通过 verify
- 登记查询确证仓库不存在人工处置登记层
- 用户显式指令声明忽略登记层

## Verification
- 删除前后全量分支/远端 ref 快照差分恰好等于预期可删集，无多余对象
- 保留集逐名回对登记文档：登记点名『保留』的对象仍存在
- git fsck 无 missing/corrupt；归档 bundle verify 通过，误删可逆

## Counterexamples
- 无治理文档的个人/临时仓库：登记查询零收益，机械分类 + 归档即足够，不应强加此 gate
- 登记是脚本自动生成的机械清单而非人工决策：不携带新意图信息，不能作为 gate 依据
- 用户显式说『merged 的全删，登记不用管』：显式指令优先于内部登记
- 登记严重过时且『保留』对象已被后续工作替代：登记是线索非圣旨，冲突上报而非机械执行任一侧
