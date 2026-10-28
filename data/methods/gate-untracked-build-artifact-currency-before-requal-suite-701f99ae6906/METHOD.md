---
method_id: gate-untracked-build-artifact-currency-before-requal-suite-701f99ae6906
name: gate-untracked-build-artifact-currency-before-requal-suite
description: 对钉在特定源码提交上的候选重跑验收/资格/回归套件、且套件经 git 未跟踪的构建产物（可执行文件、动态库、打包环境）执行时，工作树干净只证明源码就位，不证明产物含目标提交行为。入口先比对产物 mtime 或内嵌身份与验收区间内改动其上游源码的提交时间戳；陈旧则重建并以 sha/新增 flag/版本 banner 核验后再跑套件，避免产出绑定错版本的无效验收记录。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:572:4a91ab99dbb158449b03
evidence_refs: learning:learn:465f0da0b126
created_at: 2026-10-22T08:15:33.492251+08:00
updated_at: 2026-10-22T08:15:33.492251+08:00
---
## Trigger
延续型任务要求对当前精确源码候选重新验收或重跑既有套件；套件通过工作树内未被 git 跟踪的构建产物执行；git status 干净且 HEAD 与目标提交一致

## Discriminator
工作树干净+HEAD 正确只覆盖被跟踪源码，build 产物是未跟踪输出、可能停留在旧提交。可观察判别：产物 mtime（或内嵌 sha、缺失目标提交新增的 flag/行为）早于『上次验收点→目标提交』区间内最后一个改动其上游源码文件的提交时间戳，即产物不含被验收的增量行为，直接跑套件只会产出无效结论

## Short path
- 从权威记录钉绑定：旧 PASS 对应旧提交、manifest 对应当前提交，用带时间戳的 git log 列出两提交之间的 delta 及各自改动文件
- 跑任何套件前，先对套件将执行的每个构建产物做货币性检查：产物 mtime/sha 是否晚于 delta 中最后一个改动其上游源文件的提交
- 若陈旧：重建，并用内嵌身份证据（sha、版本 banner、目标提交新增 flag 是否在位）核验产物确实对应目标提交
- 跑套件，并确认 delta 的每项增量行为都有对应用例覆盖（增量行为优先于全量回归解读）
- 验收记录只对已核验身份的产物书写；身份未核验前不解释 pass/fail

## Stop conditions
- 产物身份已由 mtime+内嵌证据核验对应目标提交，套件已跑完并按 delta 增量行为解读
- delta 中没有任何提交改动产物上游源码（纯文档/纯测试改动）→ 无需重建，直接用现产物
- 套件必需的不可再生资源缺失（如资格模型已删且无副本）→ 如实标注阻塞等级，不把确定性门冒充全量验收

## Verification
- 产物 mtime ≥ delta 最新源码改动提交的时间戳，或产物内嵌 sha/新 flag/banner 与目标提交一致
- 通过的用例集合覆盖 delta 的每一项增量行为，而非只覆盖旧提交已有行为
- 重建后重新记录产物 sha 并与验收记录一起归档，使结论可绑定到具体产物身份

## Counterexamples
- delta 提交只改文档或测试文件、不改产物上游源码：mtime 比较会误报陈旧，应跳过重建
- 构建系统把 commit sha 编进产物并在启动时断言：直接比对内嵌身份即可，不需要 mtime 推断
- 产物由 CI 或包管理器按不可变版本分发：身份由分发渠道保证，本地 mtime 无意义
- 纯解释型代码无构建步骤、套件直接跑源码：不存在产物货币性未知量
