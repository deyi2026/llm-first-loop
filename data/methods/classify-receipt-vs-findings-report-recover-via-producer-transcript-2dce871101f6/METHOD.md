---
method_id: classify-receipt-vs-findings-report-recover-via-producer-transcript-2dce871101f6
name: classify-receipt-vs-findings-report-recover-via-producer-transcript
description: 当用户要求按审稿意见修文档、引用 P1/P2 等 findings 清单，而按命名直觉取到的 receipts 文件实为机械复核回执时：先用回执自身字段当场分类（reviewer=独立子代理、verdict=PASS、逐项 checks 结构 ⇒ 它核验某次变更，不可能承载 REVISE 问题清单），再沿 reviewer 这个 producer 线索到子代理会话事件日志恢复报告全文，而不是继续在 docs/ 按名字或 mtime 枚举一份从未落盘的报告。恢复后对日期/行数/路径类修正先取机器证据（created_at、行数、实存校验）再落笔，证据不足的时点如实标注“未核验”。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:1134:0390ddc32ce80494313b
evidence_refs: learning:learn:4b9370b55d1d
created_at: 2026-10-13T03:19:50.215466+08:00
updated_at: 2026-10-13T03:19:50.215466+08:00
---
## Trigger
用户要求按审稿 findings（如 P1×5+P2×9）修订文档，但该清单不在上下文中；按命名相似取到的文件读出后是 verdict=PASS 的机械复核回执，其中没有这些条目。

## Discriminator
回执里当场可见的两个事实：(1) "reviewer": "dsh independent subagent" 说明审稿报告的生产者是子代理，其交付物通常不落盘 docs/，而持久化在子代理会话日志；(2) verdict=PASS + checks[] 逐项核验结构，与用户引用的“问题清单”内容签名不符——该文件可被排除，真正的报告必须去生产者的会话产物里找。

## Short path
- 读疑似报告文件，用 verdict/结构/content-signature 分类：PASS 核验回执 vs REVISE 问题报告；与用户引用的条目数（5+9）不符即排除
- 排除后不再在 docs/ 内按名字/mtime 继续枚举找报告；沿 reviewer 字段的 producer edge 到子代理会话日志（如 data/event_logs/subagent_*.jsonl）定位
- 在日志中按报告标记（P1/P2、整体判定）提取全文，超长则分两段取完
- 同步读两份待修文档；对事实类修正（日期、行数、路径、created_at）先取机器证据（备份回执+快照双证）再改，无证据处写“未核验”
- 逐条修改并验证每处旧表述唯一命中，输出修订去向与验证结果后停止

## Stop conditions
- 已从子代理日志提取到与用户引用条目数一致的完整 findings 清单（并核对其内部结构确为问题列表），可以开始修
- 发现报告实际已落盘为 REVISE 文档（搜索直接命中且内容签名吻合）——直接读它，终止恢复流程

## Verification
- 提取报告的 P1/P2 条数与用户引用一致（本集 5+9），且与文档现存可查交叉引用吻合
- 每处替换旧串唯一命中、正文零残留；每条事实修正有机器双证或显式标注“未核验”，不沿用审稿建议中未经复核的数值

## Counterexamples
- 回执本身 verdict=REVISE 且含问题清单——它就是报告，直接使用，不必去日志恢复
- 用户消息已内联粘贴 findings 原文——无需任何定位动作，直接进入取证与修改
- 审稿者是主会话自身或人类，不存在子代理会话存储——此时 mtime/目录枚举才是合理的发现手段
- 审稿方已明确声明报告落盘路径（如附录引用）——沿该显式路径直接读，不要绕道事件日志
