---
method_id: audit-warm-state-from-receipt-before-rediscovery-1e16e716d8fc
name: audit-warm-state-from-receipt-before-rediscovery
description: 当用户质疑某个缓存类指标是否在全新（冷）状态下测得时，先从手头报告/回执中找'热状态泄漏'证据（首请求已有命中），再用唯一标记冷启动对照补一个真冷数字；而不是先在证据库/代码库里反复换关键词重搜。
status: candidate
source_model: glm/glm-5.3
teacher_refs: method:method-self-distill-root-cause,method:method-self-distill-repo-api,method:method-self-distill-ab
source_episode_refs: session:d3e8d89f-0695-48ca-8061-5ba53bfe928c
created_at: 2026-09-09T17:45:54.175252+00:00
updated_at: 2026-09-09T17:45:54.175252+00:00
---
trigger:
- 用户质疑已报告指标是否为全新/冷基线测量（'是全新桶吗？基线真的冷吗？'）
- 指标来自系统级缓存（provider 前缀缓存等），可能被近期运行预热污染
discriminator:
- 判别事实在最初报告表格里就已存在：同条件对发的第一次请求（R1）是否已有命中。强一致前缀缓存下，从未发过的前缀首请求必然 0 命中；R1 hit>0 即证明测量时状态已被先前运行写热。辅证：固定测试前缀在近时间窗内被多次发送（时间戳可从回执 acquired_at 聚类看出）。
short_path:
1. 从手头报告/回执读 R1 命中数，判定热/冷，直接回答'是否全新桶'——无需任何证据库搜索
2. 可选：读测量脚本 docstring 中记录的冷态形态（R1=0%）作权威佐证
3. 跑一次唯一标记冷启动对照（前缀加本次唯一 nonce，两连发），取得真实冷桶 R1/R2，冷热数字并列呈现
4. 对'为何没提升'类问题，从变更设计文档/断言语义回答：该变更目标是契约正确性而非命中率提升，并指出当前负载下指标的结构天花板
5. 诚实披露此前报告漏标测量条件，记入 checkpoint 更正
branch_on_evidence:
- R1=0：回执已是冷测量，直接引用，无需对照实验
- R1>0 且缓存强一致：热桶，补 nonce 冷启动对照
- R1>0 但缓存最终一致/多分片：R1 波动可能来自分片抖动，不能单凭 R1>0 判热，须 nonce 实验或多采样
stop_conditions:
- 冷热状态已从回执判定，且冷桶对照已取得（或原测量已被证明是冷）
- 变更是否以'提升该指标'为目标已从设计文档确认
verification:
- 冷启动对照的 R1 必须为 0 命中；若仍>0，说明 nonce 不唯一或另有预热源，换标记重跑
- 对比数值前先统一标注测量条件（热/冷），不跨条件直接比较
anti_patterns:
- 面对测量条件质疑先做证据库关键词反复重搜（本例 5 次 search_evidence、2 次空结果），而判别数字本就在报告表格里
- 用固定前缀重跑同一实验当作'冷验证'——重复运行永远测的是热桶
counterexamples:
- 回执 R1 本来就是 0 命中：测量已是冷态，无需 nonce 对照
- 指标与缓存无关（延迟/成本/正确率）：R1>0 推理不适用，须另找状态泄漏证据（运行顺序、共享状态）
- provider 缓存最终一致/多副本：R1>0 不构成'被自己写热'的强证据
- 用户只问结果对错、不问测量条件：无需此审计流程
programizable:
- 解析回执提取首请求 hit 计数，R1>0 自动打'热态嫌疑'标记
- 对固定负载在近时间窗内的重复执行做时间戳聚类检测
model_owned:
- 判断指标与缓存语义的相关性、provider 一致性档位、nonce 是否足以保证冷启动、何时披露已足够
why_shorter: 判别事实（R1 已命中⇒热桶）在最初报告里就存在，沿它一步即可回答第一问，把 18 次调用缩成'读回执→nonce 冷启动对照→设计文档答第二问'约 4-5 步。
