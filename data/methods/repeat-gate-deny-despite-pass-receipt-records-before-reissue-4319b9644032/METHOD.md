---
method_id: repeat-gate-deny-despite-pass-receipt-records-before-reissue-4319b9644032
name: repeat-gate-deny-despite-pass-receipt-records-before-reissue
description: 命名准入/审查闸（独立 review_admission 类）放行的保护动作被同一命名错误反复拒绝时：若已按拒绝文案自述协议核验一轮（status=PASS、candidate_sha256 与 start 回执一致、命令逐字单条复用）仍被拒，则失配维度不在可调参数里——多为执行时重算的产物/快照指纹漂移，其语义是 host 私有知识，换参重试或重跑闸回合大概率同因复败。此时立即用闸名+拒绝原文检索经验库并水合 verified 卡（含其引用的 superseded 卡），按卡内有序 solution 执行。本集第二次同名拒绝后才检索，0d 卡龄即命中同型卡，直接给出『先核远端是否已含目标提交→隔离 worktree 绑 upstream→PASS 后零中间操作立即推送』。修复机制（稳定快照/隔离 worktree/复核远端）由命中卡承担，本卡只锁升级时机：第二次同名拒绝 = 参数空间穷尽信号。
aliases: 审查PASS了推送还是被拦, 同样的闸拒绝第二次直接查经验库, 推送被资格闸反复拒, PASS回执不管用怎么办, 准入闸重试失败先搜记录再重跑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:95500c09-6f2a-4a06-babc-88afd527db4d:102:f676b8e0c60774ff0a04
evidence_refs: learning:learn:0d3577388cbc
created_at: 2026-10-31T14:36:03.873242+08:00
updated_at: 2026-10-31T14:36:03.873242+08:00
---
## Trigger
保护动作（push/发布/全量测试）已拿到准入审查 PASS 回执，却被同一闸再次以同一命名错误拒绝；或同一阻断错误在按文案修正参数（拆复合命令、补 workdir）后第二次原样出现

## Discriminator
回执仍 PASS 且 candidate_sha256/parent/kind 未变、重试命令与 start 目标逐字一致、仍被同样拒绝 ⇒ 可调参数空间已穷尽，失配只能在执行时重算的指纹维度（如主工作树被后台写者持续漂移）；闸的指纹语义无法从回执推出，但该失败类在经验库中是高复发模式（本集命中 0d 卡龄 verified 卡）

## Short path
- 首次被拒：按拒绝文案自述修复（如拆分复合命令）+ 回执参数逐字重试一次；未知量：是否参数层失误
- 仍被同一命名错误拒绝且 status 核验仍 PASS、sha 一致：判定参数空间穷尽 → 停止换参重试，禁止在主工作树重跑昂贵闸回合（同因必复败）
- search_records 用闸名+拒绝原文检索；命中 verified 卡则水合全文，连带读取其引用的 superseded/操作细节卡
- 按卡内有序 solution 执行（本集：fetch 先核远端是否已含目标提交 → 隔离 worktree 检出目标提交并绑 upstream → 审查 PASS → 零中间操作立即推送）
- 推送后用 fetch/ls-remote 复核远端权威真值，清理临时 worktree 与分支

## Stop conditions
- 水合卡方案执行成功且远端/权威面独立复核一致（fetch、ls-remote）
- 检索确认无同型卡且闸实现源码在当前仓库可读 → 降级为直读闸实现或最小复现实验定位指纹维度
- 拒绝文案显示缺的是用户授权而非技术资格（『审查不替代用户授权』）→ 停止技术重试，转请求授权

## Verification
- 检索动作发生在第二次同名拒绝之后、任何第二次闸回合（重新 start）之前
- 实际执行步序与水合卡 solution 一致；最终动作回执成功且远端真值独立复核通过
- 复盘：若检索未命中且事后证明是新颖机制，把新根因写回经验库（本卡不应替代该闭环）

## Counterexamples
- 首次拒绝且文案已给出机械修复（复合命令拆分、命名缺失字段）→ 直接按文案修一次即可，先检索属过度
- 瞬态错误（网络超时/5xx/限流）→ 退避重试更便宜，且拒绝文案不会是资格语义类
- 任务本身在开发该闸、闸源码即当前改动对象且经验库无同型卡 → 读实现比查记录更快
- 回执与重试命令实际存在未察觉差异（workdir/refspec/kind 漏配）→ 先逐字段 diff 回执 vs 命令，确认真的一致才升级
