---
method_id: narrow-recheck-delegation-from-prior-pass-receipt-plus-delta-c05655a7602e
name: narrow-recheck-delegation-from-prior-pass-receipt-plus-delta
description: 受审查闸约束的工件在已有同 issue 全量 PASS 回执后仅做了可逐行枚举的小修订时，复审义务就是 delta 覆盖而非重开全量：先读既有回执建立 finding→锚点基线，diff 出变更主张，委派窄复审（范围=变更行+锚点，工具白名单排除发现型工具），并以子代理终态+产物 sha 结算资格。本集首发 broad 复审（含 search_files）319k tokens 爆窗死亡，重派窄审 6 轮即 PASS；中途还曾以运行中子代理的中间 qualification 文本推动 push。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7c026852-7867-4a41-9ab0-1340271874dc:1157:2a6c72b6edcd7d2b7e7e
evidence_refs: learning:learn:a2906da1ec3b
created_at: 2026-10-22T16:18:00.109123+08:00
updated_at: 2026-10-22T16:18:00.109123+08:00
---
## Trigger
闸门要求工件再次取得审查/合规资格，且同时满足：同 issue 已有有效全量 PASS 回执；本次修订 diff 可逐行列举（少数行、主张带已知锚点）

## Discriminator
既有回执已给出 finding→权威锚点映射（文件:行/常量/实测值），且 diff 显示变更仅触及这些已覆盖主张——复审范围可由『既有覆盖 ∩ delta』直接导出，无需发现型搜索

## Short path
- 读同 issue 既有全量 PASS 回执：建立覆盖基线与 finding→锚点清单（未知量：已审过什么、凭什么过）
- diff 修订前后工件，枚举变更行与受影响主张（含采纳 P2 后的字节变化），确定覆盖缺口大小
- 委派窄复审：范围=变更行+主张锚点，工具白名单只读/定点执行（排除 search_files 等发现型工具），要求回执带产物 sha 与覆盖关系
- 阻塞等待子代理终态；仅终态 completed 且 PASS、sha 覆盖当前字节才结算资格——运行中回执的提示文本与中间 qualification 串不构成资格
- 执行 push/发布动作，回读对外工件字节与受审文件比对相等即停；若采纳复审 P2 改了字节，回到第 2 步再做一次窄复审

## Stop conditions
- 窄复审 PASS 回执（子代理终态 completed）且 artifact sha == 即将/已发布字节
- 回读对外工件与受审文件 rstrip 后完全相等，narrow→原全量的覆盖关系已留痕

## Verification
- 回执 scope=narrow 且指向原全量 PASS 的覆盖关系成立
- 资格判定只看子代理终态字段与产物指纹；运行时标注 unverified_verdict_text 的中间 PASS 不算
- 每个变更数值主张在回执中有锚点实测值逐项对应

## Counterexamples
- 同 issue 无既有全量 PASS 回执（首次发表）：必须全量独立审查，用自枚举清单缩窄会引入偏置并漏掉未知问题
- delta 是结构性改动（标题层级重排、段落重写）或触及回执未覆盖区域：窄复审不足以保持覆盖关系，需重新全量
- 既有回执产物指纹与当前工件差异超出已知 delta（覆盖已断裂）：先重判覆盖再决定窄/全量
- 审查设计要求对抗式发现 unknown-unknowns 而非核对已枚举主张：预喂锚点清单会破坏审查独立性
