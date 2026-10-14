---
method_id: ground-next-step-advice-in-delivery-vs-deployed-delta-4acaaf9ba59c
name: ground-next-step-advice-in-delivery-vs-deployed-delta
description: 交付刚完成后被问『下一步建议』时，不能直接从计划/roadmap 文本生成排序：先用两个当时已可见的事实做现实锚定——①交付报告/git log 暴露的交付 HEAD 哈希；②运行时诊断已暴露的 release 哈希（binding.code_root=.releases/<hash>、admission/audit 回执的 generation lag）。对二者做一次 containment 核对（运行 release 是否包含交付 HEAD），并逐个候选计划项核对『是否已做完』。本集由此发现线上 dc56f532 缺交付终态后 10 个提交（含两个 P0 修复），第一顺位从『立项 Phase4』改为『先 publish+冒烟』；智能层四阶段计划前提两个月未重验、阶段一现状不清，降为需先重核的备选。规则抽象：建议按『运营缺口＞设计明文预留的后续＞旧计划（先重核）＞卫生项』排序；一次 git 差集核对即可机械得出最高优先项，替代继续翻计划文档排期。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:1281:488a77179a9b71339bed
evidence_refs: learning:learn:1a9ac94d3435
created_at: 2026-10-13T14:54:43.637066+08:00
updated_at: 2026-10-13T14:54:43.637066+08:00
---
## Trigger
用户在一段交付/goal 刚完成后问『下一步做什么/怎么排期/建议』，且会话中已同时可见交付终态 commit 哈希（交付报告、git log）与运行时 release 身份（诊断回执、binding、admission/audit），而候选建议可能来自滞后于现实的计划文档。

## Discriminator
进入建议排序前已可见的两条事实（满足 knowledge-at-time）：①交付报告里程碑表与 git log 给出交付终态哈希（c028134aa）；②更早的诊断回执已暴露运行 release 哈希（knowledge_health binding 的 code_root 指向 .releases/dc56f532…）及 admission 的 generation lag。两哈希不一致 = 存在『交付≠上线』的运营缺口；此外候选计划文档的时间与前提明显早于刚完成的交付，可能推荐已完成的活。

## Short path
- 确认交付事实：读 goal 终态与交付报告，记下里程碑/终局 commit 哈希。
- 从已有诊断输出提取运行身份（binding.code_root 的 .releases/<hash>、admission/audit 回执），不为此新开宽搜索。
- 做一次包含性核对：git 判断运行 release 是否包含交付 HEAD；不一致则量化 delta（几条提交、是否含 P0/终审修复）。
- 对每个候选『下一步』核实现状：计划阶段项是否已被实现（查代码/配置/goal），避免推荐已完成工作。
- 排序输出：①补运营缺口（publish+冒烟）；②当前设计非目标里明文预留的后续（如 t_effect 优化）；③旧计划先重核现状再排；④卫生项垫底；成稿时重读部署回执确认事实未漂移。

## Stop conditions
- 运行 release 已包含交付 HEAD，且候选计划项均未实现 → 无运营缺口，直接按计划文本与优先级给建议。
- 取不到运行身份/诊断回执 → 如实声明『未核部署状态』，不把未验证事实写进建议排序。
- 用户只要战略构想、明确不涉及运行时部署 → 跳过门控，只做计划层排序。
- 哈希差异被证明是 canary/灰度等多版本并存的设计内状态且有独立发布流程 → 不当作缺陷项。

## Verification
- git containment/merge-base 证据：运行 release 是否包含交付 HEAD，并输出差集提交列表。
- 发布动作完成后重读 binding/admission 确认运行哈希已等于交付 HEAD，并用交付报告的验收场景对新部署冒烟。
- 每个被采纳的计划项给出『未完成』的可观察证据（缺对应代码/配置/goal 记录），而非仅凭计划文本存在。

## Counterexamples
- 运行环境本就是多版本并存（canary/灰度），release 哈希滞后是设计内常态且发布由独立流程负责——哈希不同≠欠账，须先按回执 branch 判断再定性。
- greenfield/无运行服务的纯规划任务：没有运营缺口可查，方法无锚点，不适用。
- 结论本身是『已上线/已收官』类终局断言时，应改用 fresh-read-authoritative-record-before-finality-claim（成稿时重读权威记录）；本方法只用于给下一步建议排序提供事实输入。
- 仓库与运行版本一致但配置/feature flag 未生效：哈希 containment 查不出这类『部署了但没开』的失效，需要另行验证。
