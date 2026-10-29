---
method_id: premise-check-before-procedure-research-on-inherited-todos-b906c0c8b0ee
name: premise-check-before-procedure-research-on-inherited-todos
description: 遗留待办（清 barrier、版本同步等）本质是对过去状态的断言：后台 reaper 自愈或上一轮误读（不同短 hash 不等于分叉）都可能让前提已失效。动手研究或执行变更流程前，先把每个待办改写成可检验前提，用一次只读权威查询（状态视图、两机实际 HEAD + merge-base --is-ancestor）判定是否仍成立；为假则记 no-op 收档，为真才投入子命令语法、闸与回滚研究。本集两个遗留项均因此免执行，省去机制 grep 与两轮 CLI 枚举。
aliases: 遗留项先查还要不要做, 清障碍前先看还在不在, 旧会话待办先验前提再做, git pull 前先核实版本真的不一致, 后台自愈可能让待办失效, 版本分叉先查祖先关系
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1589:0f0057887ec1da8bfb8a
evidence_refs: learning:learn:8dc3a0d6583d
created_at: 2026-10-29T20:41:40.289768+08:00
updated_at: 2026-10-29T20:41:40.289768+08:00
---
## Trigger
用户交办源自上一会话结论的遗留项（『走一次清除』『需要 git pull 保持同版本』之类），且所断言的系统状态存在只读查询面（状态视图子命令、git lineage 查询）

## Discriminator
研究机制时手上已有的证据本身就表明前提可廉价证伪：目标状态是可只读查询的视图且空态合法（如 orphan_barrier 出现在 status to_dict、单测断言其可为空列表）；版本分歧主张仅凭两个不同短 hash，未经实际 HEAD 对比与祖先关系检查。即『是否仍需要做』可以先于『怎么做』被一步回答。

## Short path
- 把每个遗留项改写为可检验前提：『障碍列表现在非空』『两机 HEAD 现在不同』
- 由运行进程 env/标准路径推出 data-dir，跑只读状态视图 → 回执为空列表 → 该项 no-op，跳过全部变更子命令研究
- 两机各取实际 HEAD，并用 merge-base --is-ancestor 检查旧结论引用的 hash 是否只是当前 HEAD 的祖先 → 版本本就一致 → 免 pull 免重启
- 只有前提为真的项（如本集的部署 bge 边车）才投入变更流程研究与执行
- no-op 结论附只读回执入档，不触碰任何变更通道，避免再留挂起 action/orphan barrier

## Stop conditions
- 每个遗留项的前提均已被一次只读权威查询证实或证伪
- 前提为假：记录 no-op 与证据后立即移到下一项，不再研究其变更语法
- 前提为真：变更已按核验过的前提执行并取得回执

## Verification
- no-op 判定引用的是活状态回执（状态视图当前输出、两机实际 HEAD 相等），而非上一会话结论或本地缓存
- 全程未对已失效前提调用任何变更通道（不新增挂起 action、不制造新的孤儿 barrier）

## Counterexamples
- 用户明确要求演练清除/同步流程本身（目的在流程而非最终状态）时，前提已失效也不应取消执行
- 只读视图自身是陈旧缓存（如 remote tracking ref）时，该查询不具权威性，须先打活源头再下前提结论
- 前提核验比直接执行更贵或更有风险（外部系统、重认证）且目标动作幂等时，可直接执行并以动作结果为验
