---
method_id: pull-canonical-evidence-refs-from-list-evidence-on-unsupported-ref-080676c1bb34
name: pull-canonical-evidence-refs-from-list-evidence-on-unsupported-ref
description: 收口类受管工具（update_goal/task_update 终态）自报 evidence_refs 被终局证据门拒收且回执 status=unsupported_ref 时，被拒对象是引用字符串的可解析性，而非证据不足：立即停止变换自造格式重试，直接调 list_evidence(scope='recent') 取当次任务真实回执的 ref= 串（按 source 与 acquired_at 匹配本 run 的工具调用）原样替换后重试一次；仍拒才定点读 verifier 判定源或请人工 waive。本环境工具回执自动入册，登记处返回的 ref 就是门禁唯一能解析的引用形态。
aliases: 收口被证据门打回怎么补引用, 关闭 goal 时提示引用校验未通过, 正规的引用串去哪里拿, 手写格式连拒两次, 从回执登记挑规范串重试
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:64c99558-2dc2-48f5-95ed-4530f60c6d33:224:efe7b6783abcbefc4fde
evidence_refs: learning:learn:8eced806e6f0
created_at: 2026-11-19T07:55:54.991899+08:00
updated_at: 2026-11-19T07:55:54.991899+08:00
---
## Trigger
需要自报 evidence_refs 的收口/门禁调用被拒，回执给出 reason_code=evidence_below_threshold 且 status=unsupported_ref，出口提示'修正引用后重试'。

## Discriminator
被拒回执明示 unsupported_ref＝引用不可解析（不是数量/覆盖不足、也不是需要 waive）；且环境事实是每次工具回执自动写入证据登记，list_evidence 返回的 ref= 字段即门禁可解析的规范形态——两者在被拒当下均已可见，无需读实现代码。

## Short path
- 首次被拒即把唯一未知量定为'verifier 认哪些引用'，停止再猜格式
- 调 list_evidence(scope='recent', limit≈12)，按 source=产生关键回执的工具、acquired_at≈本 run 时间筛出 2~4 条直接支撑终态的条目
- 逐字复制其 ref= 串替换自报引用，重试一次
- 通过即收口；仍 unsupported_ref 则定点读 verifier 判定逻辑或请人工 waive，不再枚举格式

## Stop conditions
- 已用登记处真实 ref 通过终局门禁，收口成功
- list_evidence 无本 run 条目或重试仍拒：升级为读判定源/人工 waive，不再继续猜

## Verification
- 重试回执显示门禁通过/目标状态变更成功
- 所选 ref 的 source 与 acquired_at 能一一对应到本 run 产生关键证据的工具调用回执

## Counterexamples
- status=unavailable_owner 或证据主体失效：是归属/存活问题，应恢复 owner 或补归属，不是换引用来源
- 回执指证据数量/覆盖不足而非引用不可解析：需补做产生证据的核验动作，换引用无效
- 环境没有证据登记/list_evidence 类工具且无文档：此时才需定点读 verifier 源码确认合法形态
- 无门禁校验的普通记录场合：自由文本描述即可，不必强转 evidence:// 形态
