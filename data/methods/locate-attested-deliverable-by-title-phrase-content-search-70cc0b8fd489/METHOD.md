---
method_id: locate-attested-deliverable-by-title-phrase-content-search-70cc0b8fd489
name: locate-attested-deliverable-by-title-phrase-content-search
description: 当交付物已被任务图/checkpoint 证实存在但落盘路径未知时，不要按猜测的文件名前缀或目录约定去枚举（本集先文件名搜索命中两个无关 DESIGN/ARCHITECTURE 文档，再查 reports/phase4 目录失败，浪费两跳后才用内容搜索定位 docs/phase4-effect-latency-design.md）。任务记录中的规范标题短语与工件首行正文逐字对应，本身就是现成的精确内容检索键；用它做一次内容搜索即可定位，再读文件头部与任务记录交叉核对版本。把『命名约定猜测』的全部候选空间压缩成『记录中已给出的文本键』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:1478:aa8acb1916242dd12118
evidence_refs: learning:learn:3a169ea14446
created_at: 2026-10-13T15:17:31.234752+08:00
updated_at: 2026-10-13T15:17:31.234752+08:00
---
## Trigger
工件/交付物的存在已被任务图或 checkpoint 证实（task done、评审定稿），但其落盘路径未知，且任务记录中已含该工件的规范标题/主题短语。

## Discriminator
进入搜索前已可见：task frontier 行『M4 Phase4 设计书：生效时延优化（t_effect）』给出了与目标文件第 1 行正文逐字对应的标题短语——它是现成内容检索键，当时却选择了猜测文件名/目录。

## Short path
- 从 task frontier / checkpoint 取得工件的规范标题短语，唯一未知量=落盘路径
- 直接以该短语做一次内容搜索（而非文件名模式或目录猜测）
- 在命中行中筛选『文件标题行=该短语』的条目，锁定唯一文件（本集应为 phase4-effect-latency-design.md:1）
- read_file 头部核对修订记录/版本与 checkpoint 描述一致
- present_files 声明交付物并停止

## Stop conditions
- 内容搜索命中行逐字包含规范标题且路径确定，即停止发现动作
- 文件头部版本/修订信息与任务记录交叉一致后即收口，不再扩展搜索

## Verification
- 命中片段中文件首行与任务记录标题逐字匹配
- 文件内修订/处置记录与 checkpoint 的评审结论（P0/P1/P2 数量、r2 等）交叉一致

## Counterexamples
- 记录或 evidence 已显式给出路径/文件名时，直接读取该路径，不做任何搜索
- 目标是无稳定文本的产物（二进制、图片、纯编号文件如 S01-S12.json）时内容搜索无效，应按扩展名/命名模式做文件名搜索
- 主题短语在多个文件中被引用（本集 8 个文件提及『生效时延』）时，须以『文件标题行=短语』筛选唯一交付物，而非把所有提及文件都当交付物展开阅读
