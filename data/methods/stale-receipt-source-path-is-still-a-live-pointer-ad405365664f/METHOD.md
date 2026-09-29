---
method_id: stale-receipt-source-path-is-still-a-live-pointer-ad405365664f
name: stale-receipt-source-path-is-still-a-live-pointer
description: 定位包含用户引文的源文件时，搜索/证据回执中列出的 source=精确路径 是当时最窄的下一跳——即使该回执同时被标记 stale/blocked/historical_only。stale 限制的是“引用其缓存内容作为证据”，并不否定路径本身；对已知路径的直接 read_file 是允许的，且快照回执（workspace_path_state=current_match + sha256）恰好能一步验证现行版本是否仍含目标内容。因此拿到精确路径后应立即直读，而不是升级为全库文件名枚举或敏感目录搜索——本集错误路线产生了 50 条无关命中加一次权限失败。分支逻辑：直读命中且与引文逐字匹配→停止发现进入编辑；直读失败、内容不符或回执无任何路径→才扩大搜索范围。与泛化的 provenance-following 的差异点：本方法显式处理“回执带 stale/blocked 标记”这一情形，断言标记不杀死指针。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6f6aaff7-affa-4ddd-ba99-dd5932331bbc:190:7451529c248833206bbb
evidence_refs: learning:learn:6ba13a6fe8ca
created_at: 2026-09-29T14:47:11.579382+08:00
updated_at: 2026-09-29T14:47:11.579382+08:00
---
## Trigger
修改类任务需要定位包含用户所引原文的交付物/源文件，且某个 search/search_evidence 回执已显式给出 source=<精确文件路径>，哪怕该回执同时带 stale/blocked/historical_only 标记。

## Discriminator
回执文本中已出现与任务语义匹配的精确路径（本集：source=edit_file:.../deliverables/表决权放弃承诺书模板.md）；回执中 blocked 的字面含义是 historical_search_requires=allow_stale（限制历史内容作证据），不是该文件不可读——同轮之后对该路径的直接读取返回 current_match，证实指针在读取时刻仍有效。

## Short path
- 未知量：用户引文在哪个文件。先做一次窄检索（content/evidence），不要先猜扩展名做广搜。
- 回执给出精确 source 路径→立即 read_file 该路径；未知量：现行版本是否仍含引文。用快照回执的 current_match/hash 验证，stale 标记由这次直读本身消解。
- 命中且逐字匹配→停止发现；只补一次同目录跨文件 grep 查交叉引用，避免他处引用悬空。
- 执行编辑并同步派生产物（如 docx 重新生成），做残留校验后交付。

## Stop conditions
- 直接读取的快照含用户引文原句且回执确认 workspace_path_state=current_match：发现阶段结束，进入编辑。
- 直读失败（文件不存在/被移走/内容与引文结构不符）或回执未列出任何 source 路径：此时才允许升级为宽发现。

## Verification
- 两要素同时成立：快照回执的 current_match/sha256 校验通过 + 正文逐字包含用户引文（本集为 5.5/6.1 两行原句）。
- 编辑后 grep 残留检查 + 派生产物（DOCX）内容抽查，确认无悬空引用和旧条款残留。

## Counterexamples
- 回执是纯 miss、未列出任何具体路径：宽搜索就是正确的下一步，本方法不适用。
- 路径指向的 artifact 与用户目标语义无关或类别不符（如要改数据表而指针是无关文本模板）。
- 对该路径本身的读取被敏感目录/权限策略拒绝：应走权限或替代流程，而不是反复枚举相邻目录。
- 指针指向归档/历史快照而任务需要的是外部系统的现行值（currentness_scope 指向 source_version 而非 live system）：直读归档不能当真值，须另行查现行来源。
