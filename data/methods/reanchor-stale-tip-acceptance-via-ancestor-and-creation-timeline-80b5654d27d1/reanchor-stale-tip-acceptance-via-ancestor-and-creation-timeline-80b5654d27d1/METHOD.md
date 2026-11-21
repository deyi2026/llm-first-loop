---
method_id: reanchor-stale-tip-acceptance-via-ancestor-and-creation-timeline-80b5654d27d1
name: reanchor-stale-tip-acceptance-via-ancestor-and-creation-timeline
description: 受管多步 goal 的任务验收与 goal 文本常在创建时钉死一个 commit tip；分支随后继续演进，续跑时真实 tip 已前进。先裁决 pin 是否『演进型过期』再执行验证：cat-file 确认命名 commit 存在、git log 证实其为 live tip 祖先、且提交时间早于任务 created 时间——三者成立即重锚：所有依赖 tip 的验收项（独立审查 PASS、push/ls-remote SHA 核对）改以 live tip 为对象并显式记录重锚；绝不为过期 pin 补做一轮全量验证，也不把不一致当记录损坏。命名 tip 缺失或非祖先时属记录完整性问题，应改走对账而非静默换锚。
aliases: 任务书里的commit号过期了怎么办, 验收标准和分支tip对不上, 分支在任务建完后又有了新提交, goal里写的旧SHA和实际不一致, 续跑时commit变了以哪个为准
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:ef19b98b-a401-41d3-9bc9-31d5cd6ff0e1:567:d7ab536b19bd9b076406
evidence_refs: learning:learn:46fb8fd829fe
created_at: 2026-11-20T10:14:52.852751+08:00
updated_at: 2026-11-20T10:14:52.852751+08:00
---
## Trigger
续跑/恢复受管 goal 后读任务验收时，验收或 goal 文本钉死的 commit tip（如『对 tip X 取得 PASS』『远端 SHA == X』）与已核实的分支 live tip 不一致。

## Discriminator
演进型过期三联证据（当时即可核）：①命名 commit 经 cat-file -t 确认真实存在；②git log 显示它是 live tip 的祖先（同一 first-parent 链）；③其提交时间戳早于任务的 created 时间戳。三证齐 → pin 因分支演进而过期，重锚到 live tip；任一不成立 → 本方法不适用。

## Short path
- 用一次定向查询（rev-parse / branch）拿到 live tip，与验收 pin 对比一次，不重复枚举分支状态
- 不一致时：cat-file -t <pin> + git log --format 含 %ci 取命名 tip 身份与提交时间；读任务 created 时间戳
- 祖先且更早 → 判定演进型过期；把全部 tip 依赖验收项重锚到 live tip，状态账显式记录旧pin→新tip及证据
- 回执面若显示 live tip 上在途工作无落盘结论 → 按 fail-closed 视为未完成，直接在 live tip 重排该验证，不为旧 pin 补做
- 一次 diff --stat <base>..<origin_main> 过滤分支触碰文件，预判合并冲突面后再做 base 更新

## Stop conditions
- 祖先关系与时间序成立 → staleness 裁决完成，停止对命名 tip 身份的进一步调查
- 重锚后的验证在 live tip 取得权威 PASS/回执 → 停止发现阶段
- 命名 tip 缺失或非祖先 → 切换到记录对账（fail-closed），不静默重锚

## Verification
- 状态账/交接记录含显式重锚条目：旧pin、新tip、pin提交时间 vs 任务created时间
- 最终审查回执的 SHA 覆盖 live tip 而非过期 pin
- push/ls-remote 核对对象为重锚后的 SHA

## Counterexamples
- 任务明文把范围封顶在该 tip（如『仅核验某轮存档材料』）——字面 pin 就是合同，不重锚
- 命名 tip 不是 live tip 祖先（历史被改写/分叉）——记录完整性问题，走对账或上报，不静默换锚
- live tip 上有声称作已完成的工作但无落盘回执——done-ness 裁决属恢复对账 fail-closed 方法域，本卡不判完成性
- pin 是记录库乐观锁版本号且写冲突报错驱动——用 CAS 过期刷新方法，非本卡
