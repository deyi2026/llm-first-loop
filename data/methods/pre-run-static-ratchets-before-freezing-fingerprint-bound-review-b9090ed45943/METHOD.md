---
method_id: pre-run-static-ratchets-before-freezing-fingerprint-bound-review-b9090ed45943
name: pre-run-static-ratchets-before-freezing-fingerprint-bound-review
description: 多阶段提交门禁（独立审查先冻结产物 SHA → ruff/pyright/全量测试链）启动前，先把链内便宜、确定性的静态棘轮段在本树单独跑绿，再冻结审查候选。静态失败若在审查 PASS 后才暴露：修复提交改变产物指纹→原 PASS 回执失效→窄复审+二次全量门禁，成本翻倍；同类失败在冻结前发现只花一次本地修复。判据不是『门禁已红』而是覆盖缺口：HEAD 含最近一张全量回执之后的代码提交，且该提交验证未覆盖全部静态分析器（本集上轮只跑 ruff+定向 pytest 漏 pyright；getattr 动态取鸭子方法静态返回 object 违反 dict 签名）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:2b31dcc4-fd74-4c8f-8057-a38edd911d3a:323:f3f605a1cf86ab29301a
evidence_refs: learning:learn:cd158a4aae78
created_at: 2026-10-20T16:45:48.566163+08:00
updated_at: 2026-10-20T16:45:48.566163+08:00
---
## Trigger
即将启动指纹绑定的门禁序列：独立审查准入会冻结候选产物 SHA，随后运行的提交门禁链含多个相互独立、fail-closed 的静态棘轮；同时 git log 显示最近一次全量门禁 PASS 回执对应提交早于当前 HEAD，其后存在 src/ 级代码提交，且这些提交的验证范围未覆盖链上全部静态分析器。

## Discriminator
三个当时已知事实同时成立：(1) git log 中最近全量回执落后 HEAD 若干个含代码修复的提交（覆盖缺口）；(2) 门禁入口文档写明链路为多分析器独立棘轮，『修改文件零红』按分析器分别判定，ruff PASS 不蕴含 pyright PASS；(3) 规则文本明确回执与产物指纹绑定、产物变化须按新指纹窄复审——静态失败后置必然作废已取得的 PASS。

## Short path
- 对账回执覆盖：git log 定位最近一次全量门禁 PASS 回执对应提交，与 HEAD 求差，得到未被任何回执覆盖的代码提交集（未知量：待闸增量是什么）
- 读门禁入口（ci_gate.sh 类）文档，把链分段并标注性质：确定性静态棘轮（可先跑）vs 昂贵动态段（须在审查 PASS 后）（未知量：哪些段允许且值得预跑）
- 冻结审查候选前，单独运行全部静态棘轮段——只跑静态分析器，不触发被规则闸住的全量测试（未知量：本树是否通过所有确定性检查）
- 静态段红 ⇒ 按诊断定位（如 getattr 动态派发返回 object），对照声明类型上的真实签名与 fail-open 契约本地修复（isinstance 收窄而非 cast），提交后重跑静态段至绿
- 此时才冻结审查候选 SHA、派独立审查；PASS 后完整门禁一次通过——全程无『PASS 后改产物→窄复审→二次全量』循环

## Stop conditions
- 静态段全绿，且冻结的审查候选 SHA 与最终通过完整门禁的树完全一致（审查后零产物变化）
- 静态段失败根因超出静态可判范围（行为/语义问题）⇒ 不再为预验阻塞，按正常顺序交审查与动态段处理
- 无覆盖缺口（HEAD 即最近回执提交）⇒ 跳过预跑，直接进入受闸动作

## Verification
- 收口时核对：独立审查轮数=1、完整门禁运行次数=1、无由静态失败触发的窄复审或二次冻结
- 预跑命令与门禁链实际静态段同源（同 ratchet ledger、同分析器版本），否则预验不构成覆盖证据

## Counterexamples
- 最近全量回执即当前 HEAD、无新代码提交 ⇒ 无覆盖缺口，预跑纯重复
- 流程规则明确禁止审查 PASS 前执行门禁链任何一段（含静态段）⇒ 预跑违反闸序；须先核规则闸的精确语义（本集 Rule28 只闸全量测试，静态诊断不在闸内）
- 仓库无确定性静态棘轮，或静态段耗时与整个门禁同量级 ⇒ 预验不省周期，直接按原序列走
- 预期失败模式只有运行时测试或人工审查能暴露 ⇒ 静态预跑拦不住，不应为等完美预验而延迟审查
