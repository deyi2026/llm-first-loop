---
method_id: zero-push-delta-skips-gate-after-shared-remote-truth-refresh-75d52a96c06f
name: zero-push-delta-skips-gate-after-shared-remote-truth-refresh
description: 多克隆共享同一远端（常为可直接读的本地镜像）的工作区里收到『走闸推 main』类指令时，第一个未知量是权威远端当前真值，不是回执文件或各克隆分支形态。先用 git remote -v 钉住共享远端，直读镜像 tip 并 fetch 刷新；若上次基线之后远端已前进、且每个待推提交都是远端 main 祖先（并发外部会话已推完），推送退化为 no-op：跳过昂贵的审查闸，按 SHA 逐项给出祖先证据后报告，不为空推送做门禁表演。
aliases: 空推送不用过闸, 推送前先查镜像 main 真值, 别的会话是不是已经推过了, 多克隆工作区先钉共享远端, 审查闸前先算推送增量
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:62423b4e-2e2c-44f3-82e5-45126a6bce95:252:09ad611ee11ab815032b
evidence_refs: learning:learn:8f394944bbdc
created_at: 2026-10-26T17:47:03.425727+08:00
updated_at: 2026-10-26T17:47:03.425727+08:00
---
## Trigger
带审查闸/高成本前置流程的推送指令（如『走闸推 main』），且工作区内存在多个共享同一远端的兄弟克隆；推送意图引用的是上一会话观察到的远端状态，本地 tracking ref 可能已过期

## Discriminator
各克隆 git remote -v 指向同一远端 URL/路径，即唯一推送目标；本地镜像可直接 git -C 读取真值。fetch 回执出现 old..new 的 main 前进（自上次观察之后）即提示并发会话可能已完成推送——此时『待推增量是否为零』成为开闸前唯一决定性未知量，可用 merge-base --is-ancestor 逐项闭合

## Short path
- cwd 非仓库 → 一次有界 find .git 列出候选克隆，不先猎回执文件或逐仓枚举分支
- 对候选逐个 git remote -v + rev-parse main/HEAD：钉住共享权威远端与各克隆位置
- 远端是本地镜像则直接读其 main tip，并在本会话 fetch 刷新，与上次基线比较
- 对每个意图提交跑 merge-base --is-ancestor <sha> <remote-main>，逐项判定是否已在
- 全部为祖先 → 增量为零：不开闸，输出逐 SHA 证据与 no-op 结论；可再做一次仅统计 ahead 计数的有界全工作区扫描防漏报
- 存在任一非祖先或本地真领先 → 才是实内容，按正常闸流程继续

## Stop conditions
- 全部意图提交均已验证为刷新后远端 main 的祖先（或 push --dry-run 报 Everything up-to-date）→ 停止，不开闸
- 用户改口推送目标为其他 ref/分支 → 按该 ref 增量重算，main 结论不迁移
- 远端不可直读（网络远端）→ 退化为 fetch 刷新加零增量残余 ref 量化，不直接判无事可做

## Verification
- git push --dry-run 应报 Everything up-to-date，与祖先判定互证
- 每个意图 SHA 的 merge-base --is-ancestor 判定结果留痕（在哪个远端 tip 上判的）
- 领先/落后计数只取自 fetch 刷新后的镜像 tip，不取自陈旧 tracking 快照

## Counterexamples
- 远端 main 未包含意图提交，或本地真领先/分叉 → 有实内容，必须照常过闸，不得以『可能有人推过』为由跳过
- 推送目标是特性分支等非 main ref：main 已最新不代表该 ref 增量为零，须按目标 ref 单独计算
- 治理规程要求对 no-op 决策本身留审查/登记记录的合规场景：可省完整审查但须按规程登记决策，不能静默消失
- 远端不可直读且用户明确预期有内容待推：零增量应转入残余 ref 量化与用户拍板，而非直接判无事可做
