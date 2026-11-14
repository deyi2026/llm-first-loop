---
method_id: derive-delta-integrity-from-ls-tree-not-parsed-diff-text-8d97fd201676
name: derive-delta-integrity-from-ls-tree-not-parsed-diff-text
description: 对 git 冻结候选做零字节/缺失/大小等机械完整性筛查时，不要把解析 diff/status/log 显示文本得出的结论当作事实：非 ASCII 路径默认被引号+八进制转义包裹，字段错位会让正常文件被判为空或异常，足以把 PASS 误翻成 REVISE。完整性事实一律取自对象库权威通道——git ls-tree -r -l <冻结commit> 一次给出全部路径的 blob 大小；文本筛查报出的异常若路径带引号转义，先按解析伪影挂起，经对象库复核后才进入 P0/P1 结论。
aliases: git 报空文件先别信, quotepath 引号伪影, 八进制转义路径解析坑, 文件完整性筛查走对象库, 零字节复核 ls-tree
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8f7a9539-1739-4119-af7b-e783613d8918:38:05764030d572af751958
evidence_refs: learning:learn:a9ea4f2452ec
created_at: 2026-11-14T11:31:18.066198+08:00
updated_at: 2026-11-14T11:31:18.066198+08:00
---
## Trigger
对 git 管理的冻结候选/delta 做机械完整性筛查（零字节、缺失、大小异常），筛查输入是 diff/status/log 的显示文本，且仓库含非 ASCII 文件名（中文文档、回执等）

## Discriminator
被标记为异常的路径在原始输出里被双引号+八进制转义包裹（core.quotepath 默认行为）：这是显示层产物而非 blob 属性——此刻任何从该文本推出的完整性结论都未经验证

## Short path
- 完整性筛查直接对对象库做：git ls-tree -r -l <冻结commit> 一次取全部路径的 blob 大小，替代解析 diff 文本
- 若文本筛查已跑且报异常：检查异常路径是否带引号/转义；是则按解析伪影挂起，不进入裁决
- 用 ls-tree 的 blob size 复核每条挂起项；仅对象库确认的零字节/缺失才写进 P0/P1
- 路径计数对账（ls-tree 覆盖数与 delta 文件数严格相等）后停止，完整性事实并入最终裁决

## Stop conditions
- 全部零字节/缺失/大小事实均由 ls-tree 或 cat-file 确认，无仅凭显示文本支撑的残留异常项

## Verification
- ls-tree 覆盖的路径数与 delta 清单文件数逐一对账相等
- 显示文本筛查的每条'异常'都能在 ls-tree 结果中找到对应 blob 并给出真实大小

## Counterexamples
- 异常对象是未跟踪/工作树文件（不在对象库内）：ls-tree 看不到，应直接用 filesystem stat
- 任务本身就是审计显示层内容（人类在 diff 输出里实际看到什么）：显示文本才是权威面
- 筛查通道已是机器可读格式（git -z 输出、显式禁用 quotepath、--numstat）：解析即直接来源，无需对象库兜底
