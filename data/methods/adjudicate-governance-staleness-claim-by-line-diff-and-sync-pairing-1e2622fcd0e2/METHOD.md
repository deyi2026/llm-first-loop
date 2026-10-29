---
method_id: adjudicate-governance-staleness-claim-by-line-diff-and-sync-pairing-1e2622fcd0e2
name: adjudicate-governance-staleness-claim-by-line-diff-and-sync-pairing
description: 用户以『最近更新很多、结合 main 的情况』推断既有规则/方法卡/经验卡需要批量修改时，先把断言转成两项可机械核查的事实：治理文件与权威线的内容同一性（git diff 权威线 -- 规则/技能/方法文件），以及历史上每次语义变更是否伴随规则同步提交的配对关系。只对结论依赖运行态的资产做当前代码实测，并用 git cat-file -e 判断修正是否滞留在未合并分支。产出不是修订方案，而是分类残差（滞留的 superseded 修正 / 新机制采用缺口 / 规则到执行清单的传导缺口）与逐类处置建议，不启动全量逐卡审计，并显式声明核查边界。
aliases: 更新很多规则方法要不要跟着改, 怎么核实规则是不是真的落后main, 经验卡结论过期没过期怎么判断, 批量修订治理文档前先diff证伪, 规则没跟上更新怎么查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:3e24aff2-8af5-497f-882a-a249bcc66acd:411:2005a599ab392c6f02d8
evidence_refs: learning:learn:cbec8eb11897
created_at: 2026-10-29T10:51:34.691008+08:00
updated_at: 2026-10-29T10:51:34.691008+08:00
---
## Trigger
用户基于『最近更新很多/结合 main 的情况』断言既有规则、方法、经验需要相应修改完善，且治理文件（规则文档、skills、方法卡）与代码同仓、随 git 版本化

## Discriminator
分支与权威线对治理文件的 git diff 是否为空，以及历史上每次语义变更是否都有对应规则同步提交——两条均为当时即可查询的事实，能把『大面积过期』的假设缩为少数可枚举残差

## Short path
- 定位权威仓与权威线：用 receipts 文件名/目录名/remote URL 身份线回答『main 指哪个仓』，不在 docs 跟踪仓里回答代码仓问题
- git diff <权威线> -- 规则/技能/方法文件，回答『治理文件是否落后』
- git log 交叉配对：每次语义变更 ↔ 规则同步提交，回答『同步纪律是否断裂』
- 仅对结论依赖运行态的资产（如经验卡断言 CLI 子命令存在性）用当前代码实测，并用 git cat-file -e <权威线>:<path> 判修正是否滞留在未合并分支
- 把残差分类为滞留 superseded / 机制采用缺口 / 规则→清单传导缺口，逐类给处置，并声明未逐条比对的核查边界

## Stop conditions
- 治理文件与权威线 diff 为空且同步配对完整 ⇒ 『规则落后』假设证伪，停止修订规划，转入残差定位
- 每类残差都有确定性证据（scoped diff / cat-file 存在性 / grep 计数）⇒ 停止枚举，输出分类处置

## Verification
- 复跑 git diff <权威线> -- 治理文件目录确认逐字节为空
- 对滞留修正逐文件 git cat-file -e <权威线>:<path> 双向确认 main 上不存在
- 传导缺口用受影响清单文件的关键词 grep 命中数复核（如 0 命中）

## Counterexamples
- diff 非空（治理文件确实落后权威线）⇒『多数不成立』结论翻转，转入逐块合并/移植处置
- 治理资产不在同一 git 仓（外部 wiki/工单库）⇒线内同一性检查不适用，需资产库自身版本化手段
- 用户明确批准预算、点名要求全量逐卡审计 ⇒ 不以成本效益为由自行缩范围
