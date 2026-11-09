---
method_id: read-gate-blast-radius-before-typed-escalation-choice-30a71b773a1c
name: read-gate-blast-radius-before-typed-escalation-choice
description: 协调/治理消息 API 里的命名枚举字段（need=block/info、severity、escalate）是被共享闸机械消费的杠杆，不是描述性标签。意图只是请求对方行动/催促时，先读消费该字段的闸源码谓词——重点看作用半径（全局 vs 单 lane）与触发状态（pending 即生效）——再选与意图一致的值，默认最小强制值。回执里的局部措辞（如「不放行该 lane」）可能是错误转述，不能当闸语义。可避免「发出→发现全局误伤他人合并窗→撤回→重发」的往返，以及共享收件箱里的可见churn。
aliases: 催别人处理该发 block 还是 info, 发 block 消息会不会把别人 lane 也锁住, help_request 的 need 字段怎么选, 合并闸 help_blocking 是不是全局判定, block 消息发错了怎么撤回, 机检字段选值前先看闸源码
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:b0f42188-bede-4dd0-a783-7cf26f7f556c:93:c817f06c454b43fbb301
evidence_refs: learning:learn:04308fb7df8f
created_at: 2026-11-09T10:24:06.278283+08:00
updated_at: 2026-11-09T10:24:06.278283+08:00
---
## Trigger
向被机检/合并闸管辖的共享协调层（lane/goal/工单/收件箱）发消息，消息 schema 带命名枚举字段且取值会被闸消费，而本次意图是定向请求对方处理，不是全局升级或冻结

## Discriminator
发送前已可见：该治理层由机检驱动（回执/close_reason 已出现机检字样、动作存在准入闸），且闸/守卫源码早被检索命中、一次有界读可及——枚举词的字面义（block=我被你阻塞）可能与闸的真实谓词相反（任一 pending block 即让所有 lane fail，与 lane_id 无关）

## Short path
- 拟发消息时识别出强制型枚举字段（block/escalate/severity）→ 下一未知量：该取值在闸里的谓词与作用半径
- 定位并只读消费该字段的闸判定段（此前检索已命中守卫/闸文件，一次有界读即可）
- 谓词为全局生效而意图是定向请求 → 改选最小强制值（如 info 级）再发送
- 以发送后回执核对机制计数：阻塞类计数应保持 0
- 汇报所选值与闸谓词的一致性，及对他人闸面的影响范围

## Stop conditions
- 闸谓词已确认与意图一致：作用半径不覆盖任何不应受影响的实体
- 确认该字段无机械消费者（纯人工元数据）→ 直接按自然语义选值，停止读闸

## Verification
- 发送后收件箱/闸回执中阻塞类计数为 0、pending 状态与预期一致
- 所选用值的实际效果逐条对上闸源码谓词（作用域+触发状态），而非只对回执转述

## Counterexamples
- 意图本就是全局冻结（P0 要求暂停一切合并/部署）→ 全局半径正是目的，读闸后仍应选 block
- 字段无闸消费、仅收件人人工阅读 → 按自然语义选即可，读闸是浪费
- 闸源码不可读且时限极紧 → 直接用最小强制值发送并在汇报中标注语义不确定，不为读闸阻塞
