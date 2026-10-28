---
method_id: restart-binds-pinned-desired-state-compare-receipt-head-to-pushed-sha-7c4354481ad7
name: restart-binds-pinned-desired-state-compare-receipt-head-to-pushed-sha
description: 用户把『合并/推送新代码』与『重启服务』耦合在同一指令里时，重启通常只重放已发布的 desired state（代码 head+配置），不会运行刚推送的提交。回答『服务现在是否跑新代码/新能力』只需一次机械比对：重启回执中的 git_head vs 推送回执中的 SHA；再定点查配置中目标 scope 段是否存在。head 不等 ⇒ 披露『需 publish+restart』，能力开关另需配置变更并重发布；不要用状态重轮询、同一 evidence ref 反复 hydrate/search、全文件重读或源码 grep 来回答这个部署问题。与事故复盘中的同 head 归因证伪卡机制相近但触发不同：本卡用于运维执行期的部署缺口披露，而非事后归因。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f6f1dadc-64d2-4789-bbac-44b68f133442:1135:1112c1749a8f3db843bf
evidence_refs: learning:learn:418e21456774
created_at: 2026-10-20T08:19:55.258855+08:00
updated_at: 2026-10-20T08:19:55.258855+08:00
---
## Trigger
用户指令把代码合并/推送与服务重启耦合在一起（或推送后立即执行重启），且隐含期待重启后即运行新代码或新能力开关

## Discriminator
重启回执显式携带 desired-state 的 git_head 与 verify 状态，而推送回执已给出新 SHA——两者不等这一当时在手的事实即可判定『重启未部署新代码』；配置文件中目标 scope 配置段缺失则判定能力开关未变。无需状态轮询、证据重取或源码考古即可闭合这两个未知量。

## Short path
- 推送后从 push 回执固定新 SHA，并确认远端 ahead/behind 归零（排除『不等是因为没推上去』）
- 重启后读回执的 git_head/generation/verify 字段，与推送 SHA 做一次比对——这是回答『是否跑新代码』的唯一关键未知量
- head 不等 ⇒ 结论即『重启重放了旧 desired state，需 publish+restart』，停止状态重轮询与同一 evidence ref 的反复 hydrate/search
- 对用户期待的能力开关，一次定点 grep 配置中该 scope 段是否存在（而非全文件重读或追踪 env 变量到源码）
- head 比对与 scope 存在性两个事实落定后，向用户披露部署缺口并停止扩散验证

## Stop conditions
- 回执 head == 推送 SHA 且目标配置段符合预期：新代码已上线，部署问题闭环
- 回执 head ≠ 推送 SHA：缺口已定位为缺 publish 步骤，不再枚举其他验证角度

## Verification
- 重读同一回执确认 git_head 与 generation/deploy id 指向同一 desired state，避免读串相邻快照
- push 后核对远端计数 0/0，排除推送未成功的替代解释
- 对能力开关结论，确认配置中确无对应 scope 段而非读取范围截断漏看

## Counterexamples
- CI/CD 或重启即拉取最新版的部署方式：回执 head 会等于新 SHA，不存在 publish 缺口，不得机械宣称『没上线』
- 开发模式或直接从工作树 exec 的脚本服务：重启即运行当前文件，desired-state 绑定模型不适用
- 用户重启仅为应用配置/运维变更、无新代码预期时，head 比对与缺口披露是噪声，不触发本方法
