---
method_id: posthoc-audit-query-recorded-verdict-for-exact-artifact-first-c679ff649be7
name: posthoc-audit-query-recorded-verdict-for-exact-artifact-first
description: 对已落主干的历史提交/产物做事后审查时，第一未知量是权威流水线对该确切 sha 记录的裁决，而不是先例回执考古或内容本身。一条按 sha 寻址的查询（如 gh run list/view）即可取得进入时刻的 conclusion 与失败具名单元，并直接重分类审查问题：红→红是否真实、是否被后续提交修复、闸是否 fail-closed；绿→覆盖面是否包含本次 delta。之后才冻结补丁做独立内容审查。本集先花了约 6 步全库找回执/先例（含一次 60s 超时、全根目录 ls、加宽 grep、search_docs miss），而最重要的头部事实『该提交进入 main 时 CI 是红的』本是一条查询即可得到。
aliases: 复盘已合入提交先查它的run结论, 事后审查先看进主时CI红绿, 审计落地提交从流水线记录下手, 别先翻回执先问门禁怎么判的, 查那次push的CI结果再写复盘
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:3608:50fb6732259f8f134059
evidence_refs: learning:learn:a344c7161a6d
created_at: 2026-11-11T13:39:53.465408+08:00
updated_at: 2026-11-11T13:39:53.465408+08:00
---
## Trigger
用户要求对已合入主干/已生效的历史提交或产物做事后审查、合规复盘或『当时是否被门禁拦住』类核查（含以『按建议执行』续接的此类任务），且存在按产物 id（commit sha / run id / 部署批次）寻址的权威记录面（CI runs、审计日志、部署记录）可查询

## Discriminator
动手前 diffstat 或提交信息已显示目标产物落在门禁/流水线面上（如该提交自身修改了 CI workflow），且 git 历史已确认它在主干祖先中——即『存在一条按 sha 寻址的进入时刻裁决』这一事实已在手，足以把『仓库里有没有先例/回执、内容好不好』的宽搜索缩成一次定向裁决查询

## Short path
- 锚定真实工作区（pwd / rev-parse），确认目标 sha 在主干历史中并取 diffstat
- 一条定向查询取该 sha 的权威裁决：conclusion、失败具名单元、进入时间
- 按裁决重分类问题：红→验证红是否真实、被哪个后续提交修复、闸是否按 fail-closed 工作；绿→核查该 run 覆盖面是否包含本次 delta
- 冻结 基线..目标 delta 为带哈希补丁，交有界只读审查者；其每条 finding 用真实 run 日志/源码逐条裁决，不照单接受
- 落盘回执并显式声明边界（内容审查 ≠ 推送方执行环境一致性），停止

## Stop conditions
- 权威裁决已取到且其失败/通过单元已被解释：真实红且已修复、无关红、或覆盖不足已定性
- 内容 finding 已逐条对到真值来源（真实日志、定义面源码），回执已落盘

## Verification
- 查询返回的 run 确以目标 sha 为 head，防止误取相邻 run 的结论
- 失败具名单元与后续修复提交的 diffstat 能对上（红确实被修复而非自愈）
- 冻结补丁的哈希与审查者所见产物一致

## Counterexamples
- 离线 mirror 或无远端 CI 的仓库：不存在按 sha 的裁决记录，权威面退化为本地闸脚本日志，不能硬套远端 run 查询
- 审查问题纯粹关于内容质量、红绿不改变问题清单：CI 核查可并行甚至后置，不必串行先行
- CI 失败是 runner 基础设施 flake、与 delta 无交集：裁决需要重新解读而非照单接受
- 产物尚未落地（PR 或本地候选）：没有『进入时刻裁决』可查，应走前置门禁而非事后审计
