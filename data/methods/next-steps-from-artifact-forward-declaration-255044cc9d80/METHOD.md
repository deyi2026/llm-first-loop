---
method_id: next-steps-from-artifact-forward-declaration-255044cc9d80
name: next-steps-from-artifact-forward-declaration
description: 用户在一段工作刚闭合后询问"下一步建议"时，方向已被三类在手事实收窄：1) goal checkpoints/commit 表明什么落在了哪个 ref；2) 落地产物自己的前瞻性文档（README 使用场景、协议 future-work 段）显式声明了预期后续消费者；3) VCS 分叉状态（ahead/behind、未推送）给出收敛决策项。直接由这些 provenance 事实合成排序建议；仅当产物文档沉默或问题指向其他领域时才做宽检索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:201:ebfa32fd11c4762d038d
evidence_refs: learning:learn:5755ff0536f8
created_at: 2026-09-17T22:37:43.239093+00:00
updated_at: 2026-09-17T22:37:43.239093+00:00
---
## Trigger
用户在 goal 刚闭合（checkpoints 显示 complete、成果已落某 ref）后请求下一步建议，且 goal 状态与落地产物文档可查

## Discriminator
落地产物自身的文档是否显式声明预期后续消费者/用途（README 'when to use'、协议 future-work 句），以及 VCS 状态是否显示未推送/未合并分叉——这两条在手事实把"任意可能方向"缩到"产物声明的下一消费者 + 收敛决策"两类

## Short path
- 查询 goal/checkpoint 状态：解决"完成了什么、落在哪个 ref（commit id）"
- 对比当前 checkout、落点 ref 与远端：解决"成果是否已推送/收敛"，得到 ahead/behind 分叉事实，构成需用户拍板的收敛项
- 从落点 ref 读取产物自带的前瞻文档（README 使用场景、协议 future-work）：解决"这份工作自己声明的下一步是什么"
- 仅在建议复用某个旧 harness 契约时，定点核对该被引用协议一处；跳过面向"下一步"的宽 doc 搜索
- 合成按价值排序的建议（含需用户授权项），每条可追溯到手头事实，停止

## Stop conditions
- 产物前瞻文档已声明后续方向 且 VCS 分叉状态已量化 → 事实充分，进入综合，不再发起新发现
- 每条建议都能追溯到 checkpoint / 产物文档 / 分支计数三类观测之一

## Verification
- 最终建议中每个方向是否引用了具体 commit、文档语句或分支数字
- 复盘 tool trace：上述事实齐备后是否还有 search/枚举类调用（post-sufficiency actions 应为 0）

## Counterexamples
- 产物 README/协议对未来用途沉默或明显过期 → 宽检索（docs、历史 PLAN）是合理的
- 用户问的"下一步"属于另一子系统而非刚闭合的 goal → goal checkpoints 与本产物文档无关，本方法不适用
- 成果已推送且与远端收敛 → 不应再给出分支收敛建议项
