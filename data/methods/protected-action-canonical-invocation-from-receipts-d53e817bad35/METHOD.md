---
method_id: protected-action-canonical-invocation-from-receipts-d53e817bad35
name: protected-action-canonical-invocation-from-receipts
description: 带命令闸的环境里，受保护动作（全量门禁脚本、git push/merge、写受保护目录）的调用形态本身是被校验对象：cd && 链、管道、tail 截断等组合包装会被判为规避而整条阻断。提交前先从本 run 状态卡或早前回执找出该动作最近一次成功调用的逐字命令串并原样复用（同 cwd、单条、不包装）；只读探查命令不受此限、可自由组合提效。被拦时按回执指名的差异做最小修改重发，不换动作不换措辞。与『拒因即合同差分重发』互为防/治两端。
aliases: 门禁命令别拼管道tail, cd套门禁被拦, 受保护命令照抄成功回执的写法, 命令闸形态拦截, 门禁怎么发命令不被拦
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:2272:16fe3e528e232caf8590
evidence_refs: learning:learn:3ca8ef87c30d
created_at: 2026-11-10T23:04:19.670503+08:00
updated_at: 2026-11-10T23:04:19.670503+08:00
---
## Trigger
执行环境存在命令闸/受保护动作管控（本 run 状态或早前回执已见过其拦截行为：单步提交要求、路径写白名单、参数预检），且下一步要执行受保护动作（全量 CI 门禁、push、merge、写治理目录）；尤其当出于便利想给命令加 cd 切换、管道、tail 截断等包装时

## Discriminator
该受保护动作在本环境的既有成功调用回执就是闸认可的规范形态（如单条 `bash scripts/ci_gate.sh`、`git -C <主仓根> …`），全部不含组合包装；组合命令串不在任何成功先例中——这是提交前即可对照的事实，不需等被拦后才知道

## Short path
- 判别拟执行命令类别：受保护动作（门禁/push/merge/写受保护目录）vs 只读探查；后者直接组合提效
- 对受保护动作，从状态卡或早前回执取该动作最近一次成功调用的原样命令串
- 原样复用该形态提交：同 cwd、单条命令、不带 &&/管道/tail；需要截断输出时依赖工具自身输出上限或事后读日志
- 若仍被拦：把拦截回执指名的形态差异与拟命令做一次最小差分，只改该点重发；动作与语义目标不变

## Stop conditions
- 受保护动作以与既有成功调用一致的形态提交并被受理
- 闸回执显式给出的允许形态已满足（如允许的 git -C 用法）

## Verification
- 提交前将拟命令与既有成功调用串逐字对照（参数值除外），确认无新增组合结构
- 重发前确认只修改了拦截回执指名的差异点，未顺带改动其他部分

## Counterexamples
- git log/grep/awk 等只读探查无保护语义，机械拆成单条反而浪费轮次
- 该动作无历史成功回执可抄时（首次执行），应从闸/脚本自身文档推导允许形态，而非默认裸命令
- 闸显式允许的包装形式（指定 wrapper、git -C 主仓根）优先于『绝不组合』的教条，应采用点名形式
