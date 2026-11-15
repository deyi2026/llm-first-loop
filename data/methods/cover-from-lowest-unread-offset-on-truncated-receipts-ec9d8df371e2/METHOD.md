---
method_id: cover-from-lowest-unread-offset-on-truncated-receipts-ec9d8df371e2
name: cover-from-lowest-unread-offset-on-truncated-receipts
description: 工具回执被截断、需要靠分页恢复读取（hydration/evidence 分页或分段重取）时，把回执自带的截断标记与 range 元数据当作覆盖图：先算出工件总量与已覆盖区间，从最低未读 offset（通常是头部 0 段）按序取齐、确认无空洞后，再基于内容下结论。不要默认『shell 显示过的前缀就等于头部已完整进入上下文』——diff/文件的头部常含契约与 schema 变更；读到尾部才发现头部缺口要多一次补读往返，漏读则直接污染结论。
aliases: diff截断后从哪开始补读, 分页读取头部空洞, 输出截断400行只显示了一部分, 别默认开头已经读过了, 读一半的输出算不算读过, 补读diff开头
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5ef796f-1083-475d-a81b-8eade5649df3:2:621056b7cd772adf9b13
evidence_refs: learning:learn:3b4d5ae2873d
created_at: 2026-11-14T15:45:09.710550+08:00
updated_at: 2026-11-14T15:45:09.710550+08:00
---
## Trigger
任何工具回执（shell 命令输出、read_file、git diff 等）带截断标记（如『输出 N 行』但内容中断、complete:false、range.next_start 非空），且当前任务的结论依赖该工件的较完整内容（逐 hunk 审查、全文件理解、基于 diff 的裁决）

## Discriminator
首个分页回执的 range.start>0，而此前那次被截断的原始回执本身带有截断标记、并不能证明 [0, start) 区间已完整进入上下文——这一事实在开始分页那一刻就可见，足以判定『头部区间未经显式覆盖、必须先补』，而不是读完全部尾页后靠缺失感才发现

## Short path
- 收到截断回执：先读其截断标记与 range/行数元数据，未知量=工件总量 extent 与已覆盖区间
- 对覆盖区间求并集，取最低未读 offset（通常为 0）作为下一页起点，未知量=头部是否已被显式回执覆盖
- 按 offset 升序分页直到 complete:true 或区间铺满 [0, extent)，覆盖闭合
- 覆盖闭合后才基于该工件做结构性结论与行号引用；若任务只需定位已知未知量，改用有界 span 读取并明示不据此断言全貌

## Stop conditions
- 决策相关区间已被显式回执覆盖并核对（complete:true，或各页区间并集无空洞铺满 extent）
- 任务退化为定位已知目标（某个命中行/符号/字段），有界 span 已回答该未知量

## Verification
- 把各分页回执的 range 区间求并集，确认覆盖 [0, extent) 且无空洞、无对已覆盖区间的重复整读
- 最终结论引用的具体内容（hunk/行号/契约字段）确实落在已覆盖区间内，而非假定其存在

## Counterexamples
- 小工件首读即 complete:true：没有分页恢复环节，直接分析即可，套用本方法属过度流程
- 定位型读取（已知命中行只取上下文窗口）：有界 span 是正解，强求全文有序覆盖是浪费；此时唯一纪律是不得据 partial 覆盖断言『不存在』
- 无界/流式持续追加的输出：没有可闭合的固定 extent，应按到达序消费并另行定截断点
