---
method_id: ff-ancestry-before-conflict-surface-bbca6df4f924
name: ff-ancestry-before-conflict-surface
description: 把分支落回主线/运行线前，先用一次廉价结构判定（merge-base --is-ancestor）区分快进与真合并：若目标线 head 是分支 tip 的祖先，合并不可能冲突，应跳过全部文件级 diff/overlap 冲突面分析，验证前提后直接移动 ref。本集先做了 diff+comm 重叠计算（还在 /bin/sh 下因 <() 进程替换失败一次），事后查拓扑才发现是纯快进，前置的冲突面分析整体多余；结构判定本身应用可移植命令表达。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:010fcc8e-3ba8-4948-9ae5-66a30cc8ea6e:741:7c65ad4f146fcce67e1a
evidence_refs: learning:learn:73c434cea336
created_at: 2026-09-17T15:16:57.610414+00:00
updated_at: 2026-09-17T15:16:57.610414+00:00
---
## Trigger
已同时拿到分支 tip 与目标线（或主线）head 的具体 commit id，且正准备按'需要真合并'的默认假设去计算合并冲突面/文件重叠时

## Discriminator
两个端点 id 在动手前已由权威记录给出（部署/运行状态给线头，分支查询给 tip）；祖先关系是一次命令即可判定的二值事实，若成立则冲突面问题被结构性消除——应先解这个最便宜的未知量，再决定是否需要内容级分析

## Short path
- 明确首要未知量：这次落线是快进还是真合并？两端 id 已知，一次可移植的 is-ancestor 判定即可回答
- 判定为 YES（线头是 tip 的祖先）→ 冲突面分析整体取消，不产生任何 diff/overlap 调用
- 对其他需要锚定的 ref（如 main）重复同一判定，确认可一并快进
- 验证 FF 前提后移动 ref：纯 ref 移动、零树变更、不影响 serving 运行时
- 复核旧 head 已包含于新 ref、部署代数与 head 未变，停止

## Stop conditions
- 祖先关系已判定，ref 已按判定结果移动且验证包含旧 head
- 判定为 NO（真实分叉）时本方法结束，转入常规冲突面/rebase 评估
- 用户目标只是审查分支 delta 而非落线时，不走本路径

## Verification
- 移动 ref 前先对 旧head 与 新tip 跑 is-ancestor 并确认成功退出码，移动后再复核包含关系
- FF 路径的最终决策依据中不应出现任何 diff/overlap 输出；若依赖了它，说明结构判定被跳过
- 纯锚 ref 操作后 serving 部署记录（generation/head）应保持不变

## Counterexamples
- 分支与目标线已真实分叉（is-ancestor 为 NO）：必须做内容级冲突评估，本方法不适用
- 任务目标本身就是审查分支改动了哪些文件：文件级 diff 是目标而非手段，不能跳过
- 仓库策略要求 --no-ff 保留合并历史，或环境无 git 元数据可用：FF 判定不决定行动
