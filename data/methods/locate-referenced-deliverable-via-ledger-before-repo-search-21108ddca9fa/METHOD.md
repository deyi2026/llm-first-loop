---
method_id: locate-referenced-deliverable-via-ledger-before-repo-search-21108ddca9fa
name: locate-referenced-deliverable-via-ledger-before-repo-search
description: 当用户要求修改/增补一个既有交付物（措辞如'改为''只加一条'），目标文件通常是本会话先前产出的 deliverable，而不是仓库源码。此类文件的窄索引是会话自身的 provenance 账本（list_evidence → present_files/execute_command 记录）和 deliverables/ 目录，应先沿它定位，再读文件、预览、写入。本集中 3 次仓库级搜索全部作废：文件名搜索只命中无关仓库文档（截断20条），对文档自身关键词'表决权''授权委托书'的内容搜索双双 no-match——证明搜索索引不覆盖 deliverables，宽搜索从一开始就是错误的工具类；之后才经 list_evidence→hydration→ls 找到目标。语义改写本身（全权化+单条保护条款）完成质量好，无需新方法。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:7:64e7516479e874196509
evidence_refs: learning:learn:c46dcaceca01
created_at: 2026-09-29T13:07:19.929103+08:00
updated_at: 2026-09-29T13:07:19.929103+08:00
---
## Trigger
用户请求修改/增补一个以既有口吻提及的文档（'把X改为…''只加一条'），且 X 疑似本会话先前产出的 deliverable，而非仓库源码

## Discriminator
任务起点即可观察：(a) 用户措辞预设文档已存在且只需修改（'改为''只加一条'），(b) 会话证据账本与 deliverables/ 目录正是此类产物的权威窄索引且早于本请求。事后佐证（不用于倒推）：对该文档自身关键词的内容搜索全部 no-match，说明 deliverables 在搜索索引覆盖之外

## Short path
- 从用户措辞判定两个未知量：目标文件在哪、当前内容是什么
- 先查 provenance 账本（list_evidence）或直接 ls deliverables/，1-2 次调用定位候选交付物
- read_file 目标模板，确认标题与用户指称一致（表决权授权委托书）后才编辑
- dry_run 预览最小变更（全权化改写+仅新增一条保护性义务条款），确认后原子写入并复读校验
- present_files 声明交付物并总结变更

## Stop conditions
- 已从账本/目录定位到与用户指称匹配的唯一文件
- 写入后复读一致，变更规模与预览一致
- 账本与 deliverables/ 均无匹配时才降级为宽搜索，并向用户说明文件可能不存在

## Verification
- 定位到的文件标题与用户指称的文档名一致后才进入编辑
- dry_run diff 显示变更仅覆盖用户要求范围（全权化+一条新增），其余条款仅顺延编号
- 写入后复读字节数/行数与预览一致

## Counterexamples
- 用户要求从零起草新文档：无既有 deliverable 可循，直接创作即可，不必查账本
- 目标确实是仓库源码或文档（如'改 README 的 X 节'）：按已知路径或正常仓库搜索定位，账本中不会有
- 证据账本为空或产物在会话外创建：ledger-first 无边可沿，应用 ls/grep 定位
- 首次内容搜索即唯一命中目标文件：搜索本身就是最短路径，无需绕行账本
