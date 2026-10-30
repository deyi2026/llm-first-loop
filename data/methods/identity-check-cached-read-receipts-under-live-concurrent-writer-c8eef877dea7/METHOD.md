---
method_id: identity-check-cached-read-receipts-under-live-concurrent-writer-c8eef877dea7
name: identity-check-cached-read-receipts-under-live-concurrent-writer
description: 多会话共享工作区且已观察到并发写入（文件 mtime 分钟级新鲜、非本会话所写）时，带缓存/复用标记（如 evidence_reuse）的读取回执代表历史版本而非现价。以回执内容为前提下结论前，先做一次廉价身份核对（回执行数/sha 对比 wc -l 或 git show HEAD:path），不一致则以现价面重读差异区间、把新增段落当作新前提再决策——避免按旧快照遗漏新增段，或执行其前提已失效的指令。
aliases: 读文件拿到缓存旧版本, 并发写共享仓库 读到旧快照, read_file 回执不是最新文件, 别的会话在改文件 我读到的对不对, 回执行数和现价文件对不上, 缓存读取先验身份再下结论
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:2617:5862d6c0a807885bae52
evidence_refs: learning:learn:34ce82581f6b
created_at: 2026-10-30T14:51:04.403747+08:00
updated_at: 2026-10-30T14:51:04.403747+08:00
---
## Trigger
共享工作区存在活跃并发写入（目标或同批文件 mtime 分钟级新鲜且非本会话所改），随后任一内容读取回执自带缓存/复用标记，且下一步决策要以该回执内容为前提

## Discriminator
两个当时已在场的事实叠加：①读取回执自带 evidence_reuse/缓存标记（内容身份未绑定现价文件）；②并发写者活跃（同批文件 mtime 分钟级新鲜）。二者同时成立即把『回执=现价』缩为『回执=历史版本，须一次身份核对』；最廉价判别是行数身份（本集为回执 201 行 vs 现价 245 行）

## Short path
- 建立并发事实：status/mtime 显示文件分钟级被改且非本会话所写 → 本回合所有读取回执降级为『可能过期』
- 收到带缓存/复用标记的读取回执 → 先核对内容身份：回执行数/sha 对 wc -l 或 git show HEAD:path
- 身份一致 → 直接使用回执，不重读
- 身份不一致 → 以现价面重读（优先差异/新增区间），把新增段落的指令当作新前提输入，推翻或确认原判断
- 现价内容中的指令/禁令若依据可检验事实（路径存在性、主题匹配度），逐条实测后再执行
- 落地后在报告中自证所用版本面（哪次回执、是否已按现价复核）

## Stop conditions
- 身份核对一致：回执内容即现价，停止怀疑、直接决策
- 工作区独占（无并发写者、目标文件 mtime 早于读取时间）：缓存回执默认可用
- 决策所需事实已由现价面权威来源（git show 或直读现价文件）验证

## Verification
- 回执行数/sha 与 wc -l 或 git show HEAD:path 的一致性核对
- 决策所引的具体段落（行号区间）在现价面仍存在且语义未变
- 最终报告标明依据的版本面，可被第三方复查

## Counterexamples
- 独占工作区且目标文件 mtime 早于读取时间 → 缓存回执即现价，核对是纯开销
- append-only 历史记录（事件流/日志）→ 旧头部内容不因尾部并发写而失效
- 回执自带可验证 version_token 且已确认与现价一致 → 走『按锚点段落有界重读』而非整体重取
- 读取内容与任何后续决策无关（仅为背景浏览）→ 无需身份核对
