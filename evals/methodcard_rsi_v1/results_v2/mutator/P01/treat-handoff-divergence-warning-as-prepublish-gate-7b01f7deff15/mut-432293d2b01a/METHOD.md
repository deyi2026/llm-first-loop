---
method_id: treat-handoff-divergence-warning-as-prepublish-gate-7b01f7deff15
name: treat-handoff-divergence-warning-as-prepublish-gate
description: 接手既往会话写下的多步骤计划时，若交接记录显式写有『当前主线缺少已上线功能 X，直接从主线发布会覆盖/回滚生产』这类已点名的分歧警告，而计划终点是对共享资源（主线、部署线）做 push/publish/restart，则不要按字面顺序机械执行：把警告当作阻塞前置条件，先用直接 diff（commit/tree 层面）核验『计划隐含前提（发布树 ⊇ 生产内容）』在当前时刻是否成立。成立则按原计划走；不成立则在计划中插入整合步骤（把生产全链合并进主线、逐字节验证内容一致）后再继续。不信任上一轮的口头结论（如『内容已被吸收』），只信当前树的直接 diff。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:007a1251-ae2c-4786-9ada-61948115af41:21:a955449eb4c949f72a3d
evidence_refs: learning:learn:4e5310e4567d
created_at: 2026-10-09T23:59:24.732414+08:00
updated_at: 2026-10-09T23:59:24.732414+08:00
---
## Trigger
执行一个由先前会话交接的多步骤计划，且交接记录同时包含：(a) 主线为选择性移植/与生产存在已知内容分歧的声明，(b) 针对『后续直接发布』的显式警告；而计划的后续步骤含发布类变更（push/publish/restart 共享资源）。

## Discriminator
读取计划的第一刻即可见的两个事实：报告中写明 main 仅含生产 19 提交中的 2 个（原始生产 SHA 不在 main 祖先链上、TaskBudget 生产实现未入主线），且显式警告『以后若要直接从 main 发布，应先完成生产差异的独立整合与验证，避免覆盖现有功能』；而计划终点恰为 publish+restart——即计划隐含前提在执行前已知未满足。

## Short path
- 读交接报告，把点名的分歧警告判定为计划终点步骤的阻塞前置条件，而非背景备注
- 核验生产/权威源当前状态（仍为 Gen 216 / 7d70f0eaa），确认警告仍然适用
- 用 git log/diff 量化分歧：生产不在 main 的提交集合、缺失功能所在提交与承载分支（TaskBudget 13 提交在集成分支、19 提交全链在 feat/soul-prefix 分支）
- 用 tree diff 验证候选合并树是否覆盖生产内容（发现候选分支相对生产缺文件、无 TaskBudget → 直接发布会回滚）
- 在原计划中插入整合步骤：merge 生产全链进主线，逐字节 diff 验证 src/tests/scripts/config 与生产一致，再回到原计划的 merge/门禁/push/publish
- 以『合并树 vs 生产树的 diff 仅剩预期 runtime 数据、全量门禁通过』作为进入发布前的停止条件

## Stop conditions
- 直接 commit/tree diff 证明发布树已包含生产全部内容，或缺失项与本次目标无关且已记录 → 按原计划继续，不重复整合
- 整合后合并树与生产树的差异只剩预期内容（runtime 数据），且全量门禁通过 → 才允许进入 publish/restart
- 警告所涉功能已被后续权威记录（提交/门禁回执）补齐 → 单次核验后按原计划执行，不插入冗余整合步骤

- Verification 未逐条通过前不结案（覆盖全部 1 条验证条目）

## Verification
- 发布前：diff 生产提交与合并后 main 的 tree，确认生产面文件逐字节一致、被警告的缺失功能（如 TaskBudget I5 系）在位
- 发布后：主线推进为纯快进、远端无分叉、部署回执与目标 SHA 一致；把『警告→核验→整合→再核验』链路写进汇报供审计

## Counterexamples
- 交接警告已被更晚的权威记录解决（main 已含该功能或有通过的整合门禁回执）——警告只是历史，重复插入整合步骤是无信息动作
- 计划终点只改本地/临时状态（无 push/publish/restart），分歧记录只是备注，不构成阻塞门
- 警告含糊无点名对象（『可能有问题』）——按低置信假设做一次廉价核验即可，不要据此重构计划
- 发布目标是全新/冷启动服务，从未运行过生产内容——不存在回滚语义，无需生产对齐门
