---
method_id: same-run-consume-perishable-review-pass-reissue-cached-on-stale-7efbae9d1be6
name: same-run-consume-perishable-review-pass-reissue-cached-on-stale
description: 准入闸签发的 PASS 资格是易耗令牌：绑定签发时刻的会话与产物摘要，使用时重验、签发后任何改动（含新增未跟踪文件，如准备用 symlink）即失效。正确姿势：发起审查前先做完所有会改工作区的准备动作；受保护命令单条提交不拼复合；拿到 PASS 后下一步立刻消费，中间不插入任何产物变更或用户轮次。若仍被拦『不存在覆盖当前产物、目标及父会话的有效独立审查资格』，不要误判为闸损坏或从头重审：立即重新发起审查（内容未变会命中缓存秒回 PASS）→ status 确认 → 同轮执行原命令。
aliases: 审查过了命令还是被拦, PASS 拿到了执行被拒, 同轮消费审查通过, 资格跨轮失效怎么绕, 审查缓存重用快速重过闸, 闸说没有有效审查资格
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8ce6aa41-bb36-4a43-9e62-65b65cd6bd74:1218:16ebdfcd75f5f4ee1973
evidence_refs: learning:learn:807bc06c9754
created_at: 2026-11-07T10:22:08.576606+08:00
updated_at: 2026-11-07T10:22:08.576606+08:00
---
## Trigger
持有准入闸 PASS 回执去执行受保护命令时被拦『不存在覆盖当前产物、目标及父会话的有效独立审查资格』；或即将凭一张写明 revalidated_on_use / 『签发后改动即失效』的 PASS 回执执行受保护动作，且 PASS 与消费之间可能插入准备命令、跨轮次或其他产物变更。

## Discriminator
PASS 回执自身的 consumable_scope 文本在使用前就已写明：资格与签发时刻会话绑定、使用时对切片外 tracked 与未跟踪文件的内容摘要重验、『签发后改动即失效』。仅凭这份在手的回执文本即可预判：PASS 与消费之间任何工作区变更（哪怕只是两个准备 symlink）或轮次边界都会使其失效，无需等失败回执倒推。

## Short path
- 发起审查前，先完成所有会改动工作区的准备动作（symlink、生成文件），使被审产物状态最终化
- 受保护命令单条提交，不与其他命令段拼成复合链（复合链会被整条拦下，白白消耗一次资格时效）
- status 拿到 PASS 后，下一个动作立刻执行受保护命令，中间不插入任何会改产物的命令或用户轮次
- 若仍被拦『无有效资格』：立即重新发起同一目标的审查——内容未变会命中缓存近乎零成本返回 PASS；查一次 status 取回执，同轮执行原命令

## Stop conditions
- 受保护命令已被闸放行并拿到执行回执（如后台 job 启动回执），且无准入阻断
- 重新发起未命中缓存（说明产物内容摘要真的变了）：转入对新内容的正式审查，不再循环重发同一目标

## Verification
- 重发回执的 candidate_sha256 与产物摘要一致，且标明复用自先前通过的子审查
- status 回执 qualification=PASS 且 consumable_scope 覆盖当前命令目标
- 受保护命令回执无准入阻断信息，进程正常启动

## Counterexamples
- 闸的资格设计为跨会话持久可复用（回执不含 revalidated_on_use 或失效条款）时，无需同轮消费，可跨轮排队执行
- 被拦的根因是内容摘要真的变了（实质代码改动）：缓存不会命中，重发循环无效，必须对新内容走完整审查
- 准备动作本身已列入被审材料范围：中途执行不会使资格失效，按审查材料清单顺序做即可，无需前置全部完成
- 重发触发的是全新非缓存审查且 deadline 很长：同轮干等可能不划算，应改为把多个受保护动作并在一张 PASS 下同轮连续消费
