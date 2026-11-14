---
method_id: absorb-quiesced-concurrent-writer-base-after-fidelity-audit-e05cbc100f80
name: absorb-quiesced-concurrent-writer-base-after-fidelity-audit
description: 独占写授权任务中途，发现仍有并行写者在重写本任务文件（先前 read 回执的内容身份漂移：总行数/version_token 不符，或自己刚建的 helper 被改写），即任务书『无并行写者』前提被证伪时：立即停写→广播协调→有界等待写入静止。静止后第一未知量不是『如何恢复我的实现』而是『以谁的实现为基底』：先对照钉死判据（pinned 测试语义、契约约束如纯标准库/禁隐藏导入、公开 API 兼容）完整审读对方实现；若忠实且质量不低于自己→采纳为主体，自己只保留机械性 delta（import 排序/格式），全量验证后单次提交并在 commit message 注明归属。与规格的字面偏差若语义等价或更强，披露并 offer 机械替换，不静默重写、也不静默接受。检测环节本身另见 prewrite-recheck/liveness-triage 卡，本卡覆盖其后置裁决。
aliases: 另一个会话在写同一个worktree怎么办, 并行写者停了以后用谁的实现, 我的代码被并发会话改写了要重写吗, 吸收别的会话写好的修复再提交, 协调并发写者后采纳对方实现为主体
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c9019487-438e-49b5-9e59-a6d93c7787c6:0:2832e661e324d904797c
evidence_refs: learning:learn:f5ce0c459a73
created_at: 2026-11-13T16:54:57.353184+08:00
updated_at: 2026-11-13T16:54:57.353184+08:00
---
## Trigger
独占写任务进行中，写前内容身份核验（早前回执的行数/sha/version_token vs 当前，或自己的产出被第三方改写）显示另一活跃会话正写同一批文件，且任务书声称该会话已停止

## Discriminator
先前 read 回执的内容身份与当前内容漂移，且外来改动与任务目标一致（同一符号、同一修复方向、同一测试名）——这一事实把候选空间从『我的工作被破坏→回滚重做或抢先提交』缩到『等写者静止后裁决以谁为基底』

## Short path
- 发现漂移立即停写：不 revert、不覆盖对方改动、不抢先 commit
- 广播 block 协调请求，有界等待写入静止（数分钟无写入）
- 静止后完整审读对方实现，逐项对照钉死判据：pinned 测试的 fail-closed/字段语义、架构契约约束、公开 API 兼容
- 忠实且质量达标→以对方实现为主体，自己只追加机械性修正，不重写已验证代码
- 全量验证链（原失败守卫+回归+静态检查）通过后单次提交，commit message 注明实现主体归属
- 向用户披露冲突时间线、采纳理由、与规格的字面偏差（语义等价或更强时不重写，offer 机械替换），并建议核查前提失效来源

## Stop conditions
- 写入已静止且对方实现通过完整审读与全量验证
- 对方改动与目标不一致或破坏 pinned 语义→停止采纳，在更强基底上修复前进
- 有界等待后写者仍活跃或协调无响应→升级用户，不在移动的树上提交

## Verification
- 重跑最初失败的红测/守卫确认全绿，且为本会话真实回执
- 提交前 git status 与内容身份稳定，无二次漂移
- commit message 含实现主体归属；最终报告列出冲突事实与字面偏差

## Counterexamples
- 外来改动与目标不一致或质量更低（破坏 fail-closed 语义/契约）→不吸收，修复前进
- 『并发写者』只是自动格式化/linter 的机械 diff→无需协调与裁决，直接继续
- 不存在可裁决保真度的钉死测试或契约判据→无法安全吸收，优先自己的已验证实现
- 写作者长时间无法静止→不提交，交用户处理其调度来源
