---
method_id: map-audit-dimensions-to-enumerated-evidence-before-discovery-c33abfe6afc7
name: map-audit-dimensions-to-enumerated-evidence-before-discovery
description: 审稿/核对任务若随附被审全文与完整性哈希、并给出显式审核维度清单，首轮批量清单命令（目录枚举+哈希核验）通常已同时暴露各维度所需对照物：同类旧稿目录、生成脚本、权威源文件、资产清单，且哈希一致已证明随附正文=本地文件。此时应把每个维度映射到已定位证据源并直接取证；哈希与随附文本一致的文件不整篇重读；无已定位来源或受只读/禁外联约束的维度标 UNVERIFIED，而不是转成 search_files/search_docs 式宽发现。省去对已知位置对象的重复发现与冗余重读。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:bbab1c19-0000-4976-a571-5ea7879b7859:0:261642f7717bd71081f9
evidence_refs: learning:learn:501da382dc64
created_at: 2026-10-14T20:11:08.803040+08:00
updated_at: 2026-10-14T20:11:08.803040+08:00
---
## Trigger
任务随附被审对象全文与 SHA256，并附带显式审核/核对维度清单（事实、图文对应、重复旧稿、免责等）；首轮批量命令（ls/find + 哈希）的同一份回执里已枚举出各维度的对照物（同类旧目录、生成脚本、README/pyproject 等权威源、资产清单）

## Discriminator
每个审核维度能否指认一个已在回执中枚举的证据源：随附正文哈希一致→正文类维度免重读；清单已见同类旧目录→重复性维度直取该目录；权威源文件已定位→版本/命令类维度直接 grep。当全部维度可指认时，任何泛化 search 只会重现已知对象（本集 search_files 仅命已知标题行、search_docs 未命中，最终报告零引用其结果）

## Short path
- 一条批量命令完成目录枚举+文稿与资产哈希核验，存在性与完整性一次锁定
- 把每个审核维度映射到回执中已枚举的证据源；无法映射的维度记为待定或 UNVERIFIED 候选
- 对已定位来源定向取证：旧稿标题与发布变体、逐图视觉审读、权威源 grep 版本/安装命令；哈希一致的随附正文直接引用不重读
- 仅当某维度在已枚举来源中确无证据时，才为该维度做一次定向搜索；受约束不可及的项保持 UNVERIFIED
- 汇总 P0/P1/P2 与 FINAL_VERDICT，每条结论回指具体证据源（文件/行号/图号）

## Stop conditions
- 所有审核维度均已从已定位来源取证，或已显式标 UNVERIFIED
- 随附文本与本地文件哈希不一致时立即中止本路径，转为重读本地真实内容作为审核对象

## Verification
- 复查轨迹：没有为已知路径的对象再调用发现式搜索；未重复读取哈希已证一致的随附全文
- 终稿每条 P0/P1/P2 结论可回指一个具体证据源；不可及项（远端可达性、外部发布事实）均标 UNVERIFIED 而非推断

## Counterexamples
- 本地文件哈希与随附文本不符：随附文本不可作审核对象，必须重读本地真实内容
- 清单中不存在旧稿或同类对照目录：重复性/一致性维度才需要全库搜索乃至外部检索
- 任务只给哈希未给全文：read_file 全文是必要首步，免重读判断不成立
- 权威源与图面/工具副产物说法冲突且本地无法裁决：标 UNVERIFIED/待核，而非采信任一侧
