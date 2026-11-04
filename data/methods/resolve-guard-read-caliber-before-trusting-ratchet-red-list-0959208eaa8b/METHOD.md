---
method_id: resolve-guard-read-caliber-before-trusting-ratchet-red-list-0959208eaa8b
name: resolve-guard-read-caliber-before-trusting-ratchet-red-list
description: 面对按外置基线度量源码的棘轮/尺寸守卫（函数行数、复杂度、计数）制定收缩计划前，先从守卫源码解析其读源口径：测的是 HEAD、index(staged) 还是工作树。当 git status 存在未 staged 的 ` M` 修改、且口径规则为『未 staged 回退 HEAD』时，当前红名单只覆盖 staged/HEAD 增量——未 staged 的在途改动（他人 EVO、半截工作）对守卫不可见，staged 之后才暴露为隐藏违规，导致按旧名单定的计划与对用户的红数汇报双双失真。正确顺序：先 stage（或按口径逐文件投影）再跑守卫差分拿完整违规集，按基线值设计收缩，最后在与提交目标相同的口径状态下验证。
aliases: 行数红线只报了两个其实有三个, 未staged的改动行数守卫量不到, 先stage再数超标函数, 守卫量的是HEAD还是工作区, 缩行数前先弄清守卫读哪版代码, 棘轮红名单不全先查读源口径
status: candidate
source_model: deepseek/deepseek-flash
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:887:df4a4f9e5f2a49a2c8a5
evidence_refs: learning:learn:83143d0146b2
created_at: 2026-11-03T15:33:19.447696+08:00
updated_at: 2026-11-03T15:33:19.447696+08:00
---
## Trigger
要把代码收缩回度量型棘轮基线（或按守卫红名单做修复计划），且 git status 显示目标文件或同仓库存在未 staged/未提交修改，而现有红名单来自一次口径未确认的先前运行

## Discriminator
守卫测量入口的源码/docstring 明示读源口径（如『外部漂移未 staged 文件回退 HEAD』），且 git status 回执同时列出未 staged 修改文件——两条当时在场的事实合起来即证明：可见红集合 ≠ 工作树真实违规集，未 staged 增量里的违规要到 stage 后才现形

## Short path
- 取 git status 回执，区分未 staged(` M`) 与 staged(`M `) 的修改文件——未知量：哪些增量对守卫不可见
- grep 守卫测量入口（_measure/_read_source 类）确认读源口径：HEAD / index / 工作树——未知量：守卫实际裁决的是哪份内容
- 按口径投影：把受影响文件 stage 后单跑该守卫测试，让断言打印登记 vs 实测差分——未知量：完整违规集（含隐藏项）
- 对完整集合逐函数对照基线值设计最小收缩（优先纯抽取、行为不变，新函数低于红线）
- 在与将提交状态一致的口径下复跑该守卫测试，绿后再走仓库全量门禁收口

## Stop conditions
- 守卫测试在与提交目标相同的口径状态下 PASS，且不再有未 staged 增量隐藏于口径之外
- 口径为直读工作树、或工作树干净：可见红名单即完整名单，跳过投影直接修复

## Verification
- stage 前后各跑一次守卫差分，确认红集合的每次变化都能被口径规则解释（无来路不明的第三方新红）
- 最终以仓库自己的门禁命令（如 ci_gate.sh）exit=0 收口，而非仅靠手工 AST 计数

## Counterexamples
- 工作树干净：口径不影响可见性，直接修可见红即可，无需 stage 投影
- 守卫直读工作树：未 staged 的红早已可见，先 stage 再数是多余步骤
- 守卫度量的是构建产物/dist hash 而非源码树：staged 源码不改变被测对象，应转查产物与源码的绑定/新鲜度
- 模型自己的一次性自查度量（无外部守卫裁决）：口径自定，不存在隐藏态突现问题
