---
method_id: classify-tracked-dirt-authorship-data-commit-not-revert-before-publish-c7ab5a1b809c
name: classify-tracked-dirt-authorship-data-commit-not-revert-before-publish
description: 发布/部署被干净树校验拦截（或合同文本已声明 tracked 树必须干净）且脏改动来自运行时自动写入 tracked 数据文件时，先用 diff 内容判定作者与持久性：状态语义翻转（记录被置 invalid、updated_at 刷新、无代码逻辑变更）且该路径有数据提交先例，说明这是持久权威状态，不能静默回滚、也不能混进代码提交，应以单独数据提交如实入库以恢复干净树；可再生的构建/闸副产物才走备份还原。合同文本+status 已能预判必拒时，不用失败试探。
aliases: 发布被脏树拦了 运行时改的文件怎么办, 部署前工作树被知识结算弄脏, 记录卡被自动置 invalid 要不要回滚, 干净树校验失败 数据提交还是还原, 后台进程改了 tracked 文件 部署被拒
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:2245:a8d56dfbd90bde165fe5
evidence_refs: learning:learn:271e8851ca73
created_at: 2026-11-01T14:00:50.143501+08:00
updated_at: 2026-11-01T14:00:50.143501+08:00
---
## Trigger
部署/发布类工具的前置合同（schema 文本、文档或拒单）要求 tracked 工作树干净；git status 显示 tracked 文件被改动，且 diff 表明改动非本会话所写（结算语义、后台时间戳），典型为运行时知识结算把记录状态翻转或后台进程写 tracked 数据文件。

## Discriminator
三条当时可得事实：①工具 schema 明写『程序校验 tracked 树干净』而 git status 显示 tracked M，调用必拒可预判；②diff 为纯数据语义（frontmatter status 翻转 + updated_at 刷新，无代码变更），说明写者是运行时结算而非人；③该路径 git log 存在 knowledge/数据提交先例，证明入库是既有惯例。三者把『还原？混入代码提交？单独提交？』缩成『以什么身份如实提交』。

## Short path
- 读合同文本（schema/文档）中的前置条件并与 git status 对照；已可判定必拒时不发试探性调用，先消解脏改动。
- git diff 脏文件判断作者与持久性：运行时权威状态翻转（非可再生）vs 构建/闸副产物（可再生）vs 并行会话在途编辑。
- 查该路径 git log 是否有数据提交先例，确认入库惯例与 message 风格。
- 持久状态翻转 ⇒ git add 精确路径 + 单独数据提交，message 如实写明是运行时结算产物；可再生副产物 ⇒ 备份后还原；他会在途 ⇒ 归属仲裁，不代提交。
- 树干净后重发发布；回执的 git_head 应即该数据提交，再进入 restart/后续动作。

## Stop conditions
- tracked 树恢复干净，且发布回执的 git_head/code_root 与该数据提交一致。
- 结算结果在文件中保留（未被回滚复活），提交钩子（如安全扫描）通过。

## Verification
- git status 无 tracked M；publish 回执绑定 sha == 数据提交 sha。
- 下一运行周期读取该记录时状态仍为翻转后的值，证明没有静默回滚破坏运行时结算。

## Counterexamples
- 脏改动是 CI/闸重写的 reports 等可再生产物：应还原或重新生成，作为数据提交入库会污染历史。
- 脏改动来自仍活跃的并行会话在途编辑：不能替别人提交或回滚，先做写者归属仲裁。
- 只有 untracked 文件脏而合同只校验 tracked 树：不需要也不应造数据提交，直接发布。
- diff 含敏感内容且扫描钩子告警：不得为过闸而提交，先清洗内容再处理。
