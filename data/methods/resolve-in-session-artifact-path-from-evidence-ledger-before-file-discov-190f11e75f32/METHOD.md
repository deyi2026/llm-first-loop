---
method_id: resolve-in-session-artifact-path-from-evidence-ledger-before-file-discov-190f11e75f32
name: resolve-in-session-artifact-path-from-evidence-ledger-before-file-discovery
description: 当任务要求对“本会话已产出/已修订过的文件”做后续操作（转换、导出、再交付）时，路径这个未知量应首先从 session evidence ledger 解决：list_evidence 回执的 source 字段直接给出精确相对路径并带 freshness。一旦 ledger 列出目标 artifact 且最新记录为 verified_current（或 present_files 已声明过），发现阶段即告完成——不要再发起文件名关键词搜索或目录枚举。本集可审计事实支持两点：(1) ledger 给出精确路径后，随后的宽搜索仅返回 50 条无关仓库文件，属 post-sufficiency discovery；(2) 反向看，两次 pattern 关键词搜索均 miss（工具作用域未覆盖 deliverables 下真实存在的文件），说明关键词搜索不能作为该类 artifact 的路径权威。仅当 ledger 无记录、freshness=stale 或同名歧义时，才转入文件系统发现并用时间戳/内容消歧。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:28:9cad71c76602a95180d1
evidence_refs: learning:learn:ec90e1570393
created_at: 2026-09-29T13:10:09.232854+08:00
updated_at: 2026-09-29T13:10:09.232854+08:00
---
## Trigger
用户要求对会话中先前已编辑/产出过的 artifact 执行后续操作（如导出 DOCX、重新交付），需要先定位其路径，而流程中出现或即将出现 search_files/目录枚举式发现。

## Discriminator
list_evidence 回执已显式给出目标 artifact 的精确路径——如 source=edit_file:deliverables/<文件名>.md 且 freshness=verified_current（数分钟前），并有配套 present_files 记录。该事实在当时即把候选空间从“全库文件”缩成唯一路径：路径未知量已被权威证据解决。

## Short path
- 一次 list_evidence（或直接采用上下文已有路径）解析“该文件”指代：取 source 精确路径 + freshness=verified_current 的最新记录
- read_file 该路径一次，确认当前内容与版本（同时验证磁盘存在）
- 一条复合命令探测转换工具链（which pandoc + python import 检查）
- 执行转换（pandoc md -> docx）
- 机械验证产物：file 类型为 Word 2007+、zip 完整性 OK、关键内容标记存在
- present_files 声明交付物并报告绝对/相对路径，停止

## Stop conditions
- ledger 已给出精确路径且最新 evidence 为 verified_current：发现阶段结束，直接进入读取/转换，不再搜索或枚举
- 产物通过机械校验（文件类型、zip 完整性、内容标记）且路径已报告：任务完成，不追加额外验证轮

## Verification
- file 输出确认为 Microsoft Word 2007+ 且 zip 完整性 OK
- 产物内容含关键标记（核心条款标题、签署页等）且段落数合理
- 交付路径与 ledger 中 source 路径同目录一致，文件大小/时间戳对应本次转换

## Counterexamples
- ledger 中查无此文件、或最新记录 freshness=stale（磁盘可能已被并发修改）：此时关键词搜索/目录发现是正当第一步
- 存在多个同名或同主题候选版本且 ledger 记录无法消歧：必须用文件系统枚举加时间戳/内容比对选择，不能盲取 ledger 路径
- 任务对象是全新文件，或用户明确要求全库检索内容：发现本身就是任务目标，本方法不适用
