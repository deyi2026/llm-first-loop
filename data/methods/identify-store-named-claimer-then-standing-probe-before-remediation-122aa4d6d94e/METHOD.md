---
method_id: identify-store-named-claimer-then-standing-probe-before-remediation-122aa4d6d94e
name: identify-store-named-claimer-then-standing-probe-before-remediation
description: 多进程共享同一调度 store 的定时任务静默失效、且条目已具名 owner（owner pid / lease_owner / trace instance 字段）时，第一未知量是『谁在实际 claim、其运行参数是什么』，而不是重推投递管线源码：先用 trace 的 instance 字段与进程启动参数钉死 claimer 身份，把它的 engine workspace_root 与条目钉死的 workdir 并排比对；ps 类工具被沙箱拒绝只说明换证据源，不说明该线索死亡。裁决后再注册与条目同参数的最小 standing 探针实测投递链路：探针 started ⇒ 链路与钉死参数均无罪，应取消不必要的补救（如重签会消耗授权额度并重置计数），只在判据层修（消费触发改为释放让位），最后回收探针并留只读核验排程。
aliases: 定时任务没跑先查谁抢了claim, ps被沙箱拦了怎么继续查进程, 注册探针排程实测调度链路, 孤儿进程占着排程怎么办, 改判据前先用同参数探针验证, 静默空跑别急着重签排程
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9eecb62d-2512-4672-8ab8-7d335dfa7967:131:a78b8cffc6a71b7241b1
evidence_refs: learning:learn:f0408012e22f
created_at: 2026-11-11T11:49:19.981424+08:00
updated_at: 2026-11-11T11:49:19.981424+08:00
---
## Trigger
多进程共享同一调度/任务 store，周期任务静默失效（无报错、store 内触发时间照常推进或计数被消费），且 store 条目或 trace 行已直接给出 owner/claimer 身份字段（owner pid、lease_owner、instance 标识）；常见于上一轮已给出判据/配置类归因、本轮需要复核或执行补救之前。

## Discriminator
store 回执里两个并存事实：①条目钉死参数（如 wake_workdir）本身就是期望值、并未被写坏；②存在具名 owner pid，且开局快照已对其做过进程检查（哪怕被沙箱拒绝）。参数正确却仍静默失效 ⇒ 嫌疑从『判据/配置错』转移到『claim 被 workspace 漂移的进程抢走并消费』；ps 被挡时，trace 行的 instance 字段与进程启动参数记录仍是可用的 owner 证据源。

## Short path
- 读 store：并排记录每条目的钉死参数与 owner/lease 字段（未知量：参数是否本来就对、谁持有 claim）
- 钉 claimer 身份：优先用 trace 行 instance 字段与进程启动参数（如 --workspace）；ps 被挡就换证据源、不换线索（未知量：claimer 的 engine workspace_root 是什么）
- 比对 claimer 实际 workspace vs 条目钉死 workdir：不一致即根因成立，同时证伪上一轮『判据/配置错』归因；此时才定点读判据实现做修改（消费触发→释放让位），路径直取 src/ 主树，不做会命中历史快照副本的全库文件名搜索
- 停掉漂移 claimer；注册与条目同参数的最小 standing 探针实测投递链路（未知量：链路本身是否有罪）
- 探针 trace action_type=started ⇒ 链路与钉死参数均无罪：取消原计划的补救动作（重签会耗授权额度、重置计数），cancel 探针
- 留一条只读核验排程观察下一真实班次，拿到确定性 trace 后收尾

## Stop conditions
- claimer 身份及其运行参数已与钉死参数比对完毕，且探针或真实班次给出 started / 具名降级 reason 的确定性 trace
- 修复后的 mismatch 场景 trace 显示 defer/释放 claim，而非消费式降级通知
- 临时探针已回收，不残留会继续消耗额度的排程

## Verification
- 探针被预期进程 claim 且 trace action_type=started、session 非空
- 停掉漂移 claimer 后，后续真实班次 count/fires_used 出现 +1
- 判据修改经全量门禁通过并 publish，重启接管有既有 recovery 先例 trace 支撑

## Counterexamples
- store 不含 owner/instance 类字段、无法具名 claimer 时无从下手，应先做 store 状态与降级事件的对撞定位失败层
- 单进程独占 store、无并发竞争可能时，静默失效更可能在判据/配置本身，owner 比对无信息量
- 下一真实班次临近且探针/重签都消耗稀缺授权额度时，直接观察真实班次实测更省
- 失效与调度 claim 机制无关（一次性本地任务、无共享 store）时不适用
