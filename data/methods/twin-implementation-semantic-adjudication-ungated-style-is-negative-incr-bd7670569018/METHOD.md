---
method_id: twin-implementation-semantic-adjudication-ungated-style-is-negative-incr-bd7670569018
name: twin-implementation-semantic-adjudication-ungated-style-is-negative-increment
description: 分支上的具名提交被问『是否有用、要不要并入 main』时，若 merge-base 分侧 range diff 显示 main 侧已有同主题的独立实现，所有机械等价信号（--merged、patch-id、blob DIFFER）都会误报『不同』而失去裁决力。此时改为语义裁决：并排逐 hunk 比较两版实现的形式强弱，双向统计新增测试用例数（分支独有用例为 0 即增量归零）；对排版类提交用 `git diff -w` 证内容不变，再查仓库有无 markdown lint/格式化门禁与行尾空白回归——无门禁的纯排版是负增量，建议丢弃而非搬运。零/负增量结论须附边界（未跑 main 树测试、不可逆操作待用户确认）。
aliases: main已有同款改动分支还要合吗, 两边各写了一版同一个功能留哪版, 纯格式化排版提交是负资产吗, 分支提交有没有独有用例怎么数, 无lint门禁的样式提交要不要丢
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1067:5d682500aa656df0f5d6
evidence_refs: learning:learn:9b1530ec4ccf
created_at: 2026-10-28T23:34:21.891967+08:00
updated_at: 2026-10-28T23:34:21.891967+08:00
---
## Trigger
用户拿分支上具名提交问『是否有用/需不需要并入 main』，且 fetch 后以 merge-base 分侧 range diff 显示：main 侧已有同主题（同一守卫/同一需求）的独立实现，或被评提交属纯排版/格式类改动

## Discriminator
机械等价信号对『两侧各自实现同一需求』必然全部报『不同』（patch-id 不匹配既不证明内容缺失也不证明冗余），此时真正可裁决的事实是三条可观察证据：①base..main 与 base..HEAD 在同一锚点的 hunk 可并排读，形式强弱能逐语句判定（如单次取值+显式标注 优于 重复下标求值）；②触及的测试文件可双向数新增用例（分支独有=0 而 main 侧更多）；③排版提交 `git diff -w` 后内容归零 + 仓库 grep 无 markdown lint/格式化配置 + CI 不校验 docs + 分侧行尾空白计数显示引入回归

## Short path
- fetch 后取 merge-base，一次列出两侧各自触及被评文件的提交——先回答『main 到底缺什么』，不做 main↔HEAD 混合全量 diff
- main 侧存在同主题孪生实现 → 并排读 base..main 与 base..HEAD 的对应 hunk，逐语句比较哪侧形式更强，不比较提交标题
- 对触及的测试文件双向统计新增用例数：分支独有用例为 0 而 main 侧更多 → 功能类提交增量归零，建议丢弃
- 排版类提交 → `git diff -w` 证内容不变；分侧行尾空白计数；grep markdown lint/格式化配置与 CI docs 门禁；门禁全部缺位且引入空白回归 → 负增量，若确需该风格应在 main 上单独做并配门禁，而非搬运分支产物（否则下次保存即漂移回原样）
- 其余分支文件做 blob SAME/DIFFER 扫描与 fixture 键差集，确认无其他独有内容后收口
- 结论为丢弃时明示边界：未在并发写入的 main 树跑测试、静态检查器未实际运行、删除分支等不可逆操作等用户明确确认

## Stop conditions
- 每个被评提交均已给出：等价方向/形式强弱判定 + 双向独有用例数；排版类另附内容不变证明与门禁存在性检查
- 其余分支文件全部 blob 相同或为 main 超集，整支处置结论已成立
- 不可逆处置（丢弃提交/删分支）已交用户确认，未代执行

## Verification
- 语义等价结论须由同一锚点的两侧 hunk 并排支撑，且双向用例计数证实分支无独有覆盖，不得只凭提交标题或树级 diff 非空
- 『纯排版』须由 diff -w 统计近似归零 + 分侧行尾空白计数证实；『无门禁』须由 lint 配置与 CI 工作流 grep 证实
- 若类型收窄以通过静态检查门禁为动机，须实际运行检查器验证 main 版是否同样通过，不得只靠读码推断哪版更强
- blob/键差集扫描证实无其他独有内容后，才下『整支可弃』结论

## Counterexamples
- main 侧孪生实现有缺陷而分支版修复了行为差异 → 非冗余，须按行为而非形式比较并提取修复增量
- 仓库已有 markdownlint/mdformat 门禁且该排版提交使文件首次通过门禁 → 正价值，应合并
- diff -w 后仍有实质内容变化（新表格行、新列、改措辞）→ 不是纯排版，按内容评估
- 类型收窄针对 main 版未解决的 pyright/mypy 报错 → 分支提交有价值，跑检查器定论
- 测试无法运行、覆盖差不可数时 → 只读等价降级为假设，先补运行或在结论中明示边界
