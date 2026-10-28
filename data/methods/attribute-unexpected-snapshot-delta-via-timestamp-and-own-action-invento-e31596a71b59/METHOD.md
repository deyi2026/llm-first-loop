---
method_id: attribute-unexpected-snapshot-delta-via-timestamp-and-own-action-invento-e31596a71b59
name: attribute-unexpected-snapshot-delta-via-timestamp-and-own-action-inventory
description: 在带冻结面/身份闸的受控流程（staged diff、回执、gate）中，若两次状态快照之间出现无法由本次会话命令解释的新增变更，先做写者归因而非反应：用『自有命令清单 + 已派遣子代理的真实结算观测时间 + 变更文件 mtime + 仅针对该路径的 diff 内容』三角证据把候选写者缩到一个；随后只验证受保护不变量（冻结面 count/bytes/hash、既有回执哈希）是否被触碰。结论为外部并发时如实披露、不回滚、不吸收、不改判已结算 child 的裁决，避免误归因触发无谓重审或污染 PASS 语义。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25393690-39c2-43d8-b50f-3157a58aaea2:174:75a2d3e6e9ff528c182e
evidence_refs: learning:learn:2d190fdc6f4f
created_at: 2026-10-15T08:01:50.508546+08:00
updated_at: 2026-10-15T08:01:50.508546+08:00
---
## Trigger
受控/冻结面工作流中，紧邻的前一次 status 快照之后的复查里出现新的 modified/untracked 路径，且这些路径不在本会话写入清单内、也不在受保护面上

## Discriminator
归因时刻已持有的三件可观察事实：(1) 前一次干净快照证明该变更当时不存在；(2) 任何子代理的真实结算观测时间戳（结算回执的 acquired_at）；(3) 本会话完整命令清单。若变更路径的 mtime 晚于子代理结算时间、且不在自有清单内，写者唯一剩余解释即外部并发活动；再用仅限该路径的 diff 内容刻画其性质（例如含对 live 服务的真实请求记录=另一会话在跑场景套件），完成闭合

## Short path
- 逐路径对比两次快照，精确枚举意外变更集合，不扩大为全库重扫或重跑审查
- 对且仅对这些路径做 stat mtime + 目标 diff，与子代理结算时间、自有命令清单三角对齐，归因写者（自有/child/外部三择一）
- 复验受保护不变量：staged 冻结面（文件数/字节数/内容哈希）与既有回执文件哈希逐项不变
- 归因为外部并发时不 revert、不 absorb、不推翻 child 裁决；按时间戳+内容特征把外部活动写入最终披露
- 收口成稿前再做一次 fresh status 复读（并发可能仍在进行），把状态结论表述为带时间戳快照而非终局

## Stop conditions
- 全部意外变更完成有证据支撑的归因，且冻结面与既有回执哈希逐位不变 → 披露后正常收口
- 变更落在受保护面（冻结面、回执、权威 SoT）或归因证据链无法闭合 → 停止收口并升级为 BLOCK/人工裁决，不得披露后继续

## Verification
- 冻结面三项指标在派遣前、子代理结算后、收口前三次读取完全一致
- 既有回执文件哈希与字节数不变，证明新增动作未被用于覆盖旧凭证
- 归因链条闭合：mtime 晚于子代理结算观测 ∧ 路径不属于自有写入清单 ∧ diff 内容与外部会话活动特征吻合

## Counterexamples
- 确认无并发会话的单写者环境出现意外变更：更可能是自有早期命令或 child 违反只读白名单，应先审计自身与 child 工具轨迹，而不是外推为良性外部并发
- mtime 早于前次快照却当时未显示（被 index/ignore 状态掩盖）：单一时间戳证据会误导，必须以内容 diff 与 git 状态机为准
- 变更可由自有命令合理解释（如写入工具顺带更新配置/报告）：不得外部化归因，先核对自己 trace 再下结论
