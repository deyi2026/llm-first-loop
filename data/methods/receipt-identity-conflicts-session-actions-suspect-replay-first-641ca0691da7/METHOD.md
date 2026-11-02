---
method_id: receipt-identity-conflicts-session-actions-suspect-replay-first-641ca0691da7
name: receipt-identity-conflicts-session-actions-suspect-replay-first
description: 命令回执复用旧 stdout 时，回执里的身份类字段（git HEAD、部署 generation、记录 id）会与本会话自己刚产生并确认过的身份事实冲突。此时不要拿回执当真值去重建基线或部署代：会话自己的动作产物（刚提交的 commit id、刚发布成功的 generation 回执）优先；只读查询回执与之矛盾时，先怀疑回执是回放/复用的旧输出。用带本次唯一标记的新查询或另一个独立面复核，两面一致才采信，并在交付中标注疑似回放。本集一次 git log 回执给出了旧 HEAD，与实测值不符，险些据此错判基线与部署代。
aliases: 回执显示旧提交, 命令输出像是缓存的旧结果, git log 和实际 HEAD 对不上, 回执复用了旧 stdout, 查询结果和自己刚提交的对不上
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:5648:58e12d76daf051493b56
evidence_refs: learning:learn:fde715c82978
created_at: 2026-11-02T08:49:03.088478+08:00
updated_at: 2026-11-02T08:49:03.088478+08:00
---
## Trigger
只读命令/查询回执中携带身份类字段（git HEAD、generation、record id），且该值与本会话自己刚执行并已获成功回执确认的身份事实（自己提交的 commit、自己发布的 generation）不一致

## Discriminator
冲突双方的信任不对称：一方是本会话动作的直接产物（有成功回执在案、时间序上晚于旧值），另一方是只读查询输出——二者矛盾时，回执复用旧 stdout 的可能性大于状态真的变了，除非另有外部变更证据。该判别事实在冲突出现当刻即已具备，无需事后信息。

## Short path
- 任何含身份字段的回执，先与会话动作日志比对（自己刚提交/发布并获确认的 id）
- 一致 → 直接采信，继续任务
- 冲突 → 冻结基于该回执的判断，不据此更新基线/部署代结论
- 发起带本次唯一标记（nonce/前缀）的新查询，或换独立面（如服务 status 回执的 git_head 字段、直读 .git）复核
- 复核值与会话事实一致 → 判原回执为回放并在交付中标注；复核值与原回执一致 → 判为真实外部状态变更，按外部变更重估

## Stop conditions
- 身份值已由带唯一标记的新回执或第二独立来源一致确认
- 确认冲突源于真实外部变更（如并行会话推进了 HEAD），转按外部变更处理而非回放

## Verification
- 复核查询的输出包含本次独有标记（nonce、唯一前缀）或来自不同工具面，排除缓存复用
- 最终采用的值与本会话 commit/publish 的成功回执一致

## Counterexamples
- 本会话对该身份值无先验事实（首次测量），冲突无从成立，回执应暂被采信
- 差异字段本身非确定性（时间戳、行数、计数），自然漂移不构成回放证据
- 多会话共享仓库且确有外部推进提交——冲突是真实状态变化，应直接采纳新值而非怀疑回执
