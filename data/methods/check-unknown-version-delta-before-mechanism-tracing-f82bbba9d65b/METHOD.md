---
method_id: check-unknown-version-delta-before-mechanism-tracing-f82bbba9d65b
name: check-unknown-version-delta-before-mechanism-tracing
description: 当运行行为与我对代码的认知不符（预期输出缺失、日志行消失、特性看似失效），且已知运行服务正跑在一个比我最后插桩/最后已知版本更新的、非我所提交的 commit 上时：先用一条 git log/show 读完这段未知 delta，再决定是否追机制链。delta 是行为差异的先验解释，常能直接裁决问题（如特性已按用户指令整体移除），从而避免对现行源码做定位阅读与 formatter→receipt 拼接链追查。若 delta 直接解释了差异，把该疑点记为『随特性退役自然消解』并关闭线程；只有版本一致、delta 与疑点无关、或需对 delta 落地之前时刻做严格历史取证时，才转常规机制/代码追踪。与 method-root-cause 不同：那是回归实验方法论，本方法是追查前的单条廉价裁决性读操作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:2588:cb435c6bd060015831e7
evidence_refs: learning:learn:2d4252a5d084
created_at: 2026-10-07T15:32:41.719180+08:00
updated_at: 2026-10-07T15:32:41.719180+08:00
---
## Trigger
要诊断『预期应出现的内容缺失/行为与我所知代码不符』，且已从状态回执观察到运行工件（服务/进程）的版本标识（commit hash）比我最后插桩或最后已知的版本新、该 delta 内容尚未阅读、且提交者不是我自己。

## Discriminator
运行工件 commit ≠ 我最后已知/插桩的 commit，且这段 delta 内容未知——该事实在决定深挖之前已在手，它把『机制链是否断裂』这个开放问题缩成『这段 delta 改了什么』，一条 git show 即可裁决（本例：af480f80 的 message 直接写明 B 面回执尾注已按用户 14:05 指令整体移除）。

## Short path
- 按用户所求做状态检查，记录运行 gen/pid/commit，并与我方最后已知 commit 比对（未知量：当前跑的是什么）。
- 发现未知 delta 且非我所提交 → 立即 git log + git show 该 delta（未知量：delta 改了什么、是否触及疑点特性）；此时不要并行发出对现行源码的定位阅读来追机制链。
- delta 给出裁决性事实（特性已整体移除/换载体/改名）→ 疑点线程直接关闭，不做源码深读、不再追拼接链。
- 对用户实际所求做最小健康核验：重启时间点后该特性日志计数应为 0（与 delta 互相印证）、0 ERROR/Exception、工作树状态。
- 汇报：区分『用户所求的当前状态』与『历史疑点随 delta 自然消解』，不追加动作。

## Stop conditions
- delta 已解释行为差异（特性被移除/改名/换载体）→ 关闭该疑点线程，不再读相关源码或追机制链。
- 用户所需状态事实（健康度、版本、工作树）已核验 → 停止，不扩大检查面。
- 版本一致或 delta 与疑点特性无关 → 本方法到此为止，转入常规机制/代码追踪。

## Verification
- 行为解释必须能引用 delta commit 的 hash/日期/message 作为出处，而非推测。
- 与运行时观测交叉印证：重启后日志中该特性相关输出计数应为 0（本例 method_hint=0、0 ERROR/Exception），与 commit message 声称的移除一致。
- knowledge-at-time 自检：确认『版本 delta』事实在决定深挖之前已被状态回执暴露，不是用事后 git show 的结果倒推当初该怎么做。

## Counterexamples
- 运行 commit 与我插桩 commit 一致（无 delta）→ 行为差异不能归因版本，需正常追代码/链路。
- delta 内的 commit 全部与疑点无关（如纯文档、资产、无关模块改动）→ 版本解释不成立，回到机制追踪。
- 问题是对 delta 落地之前某时刻的严格历史取证（当时到底发生了什么）→ 当前 delta 只解释『现在为何没有』，不能重建历史行为（本例 delta 也未证明 14:05 尾注是否真被拼接，只是让该问题不再需要答案），须按时间点查当日日志/历史版本。
- 无版本控制或无法确定运行版本（外部黑盒服务）→ 方法不可用。
