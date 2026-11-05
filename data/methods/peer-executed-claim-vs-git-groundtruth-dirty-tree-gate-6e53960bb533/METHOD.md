---
method_id: peer-executed-claim-vs-git-groundtruth-dirty-tree-gate-6e53960bb533
name: peer-executed-claim-vs-git-groundtruth-dirty-tree-gate
description: 并行/委派会话在事件流自报'执行完毕、闸门全绿、已登记 executed'不构成持久化证据。停手、等待或验收前，先用只读 git 三件套核对：status、HEAD 提交时间与 hash、origin ahead/behind。若自报时点之后无新提交且 tracked 仍脏，即证明闸门跑在含未提交改动的脏工作区上、'executed'登记时代码未入仓；再用单文件 diff 把缺口具体化为'只推 HEAD 会缺什么'（语义后果），把工作区 diff 导出到 /tmp 做无副作用保全，最后以'转告原写者补提交 vs 授权本会话接管'的决策分叉上报，未获用户授权不收编他人未提交工作。
aliases: 别的会话说做完了能信吗, 自报完成不等于已提交, 闸门全绿但工作区还脏, 等别人收口前先查 git, 脏树过闸不算入库
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1632:64c4d4fe0abfa013d183
evidence_refs: learning:learn:e33707fb5f23
created_at: 2026-11-04T16:28:39.201219+08:00
updated_at: 2026-11-04T16:28:39.201219+08:00
---
## Trigger
本会话任务建立在'另一会话已完成/将自行收口'的前提上（停手等待、验收、或准备按其完成状态推进），且该会话在事件流/回执中自报过完成与闸门通过。

## Discriminator
完成自报的时间戳 vs 同一时刻的 git 事实：自报之后没有任何新提交（HEAD 提交时间早于自报）、status 仍有 tracked 修改与未跟踪产物、rev-list 显示未推送。三者同时成立即判定：闸门回执只证明当时工作区状态，不证明 HEAD 已含该工作；事件流自报是声明而非持久化证据。

## Short path
- 从事件流提取对方完成自报的原文与时间戳（未知量：它声称完成了什么、何时声称）
- 只读核对 git status、HEAD hash 与提交时间、origin ahead/behind（未知量：声称时点之后仓库是否已持久化该工作）
- 不符则取关键文件的 git diff 与 HEAD 对比，把缺口具体化为'只推 HEAD 会缺什么'（未知量：缺口的实际语义后果，如消费侧白名单缺新状态值会静默跳过声明）
- 无副作用保全：git diff 导出到 /tmp 补丁并记录字节数（未知量：任何一方 clean 工作区前改动是否可恢复）
- 停止一切写操作，向用户上报缺口证据 + 二选一决策分叉（转告原写者补提交 / 授权按归属单独提交），未获授权不代提交他人未提交工作

## Stop conditions
- HEAD、工作区与自报内容一致（已提交、按需已推送）→ 前提成立，按原建议继续停手/收口，不再额外枚举
- 缺口证据（status + diff + 时间戳对比）已固定、保全补丁已落盘并上报 → 等用户在分叉间裁决，不再增加只读检查
- 用户已选定分叉 → 只执行被选分支，不混合两条路径

## Verification
- 用 git show HEAD:<关键文件> 或未提交 diff 证明 HEAD 上缺少自报所依赖的改动（例如白名单集合不含新状态值）
- 确认自报时间戳早于本次 git 核对回执时间戳，保证判定满足 knowledge-at-time
- 确认 /tmp 保全补丁存在且非零字节、内容与 git diff 一致

## Counterexamples
- 对方自报中带有具体 commit hash，且 status/rev-list 证实已提交并推送 → 前提未被证伪，直接按建议继续，无需调查
- 单会话场景、自己是唯一写者 → 自己的闸门回执加自己的提交流程已足够，不存在跨写者的声明-持久化落差
- 编排流程明确设计为先登记 executed、后由既定步骤补提交（缺口是预期中间态且有在途后续） → 不算证伪，只确认后续步骤归属
- 残留未提交内容仅为与本任务无关的文档草稿，自报结论不依赖它们 → 脏工作区不构成收口缺口
