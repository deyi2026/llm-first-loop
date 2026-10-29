---
method_id: exempt-vs-rollback-adjudicate-by-real-rollback-cost-and-consumer-audit-8b98727ca82a
name: exempt-vs-rollback-adjudicate-by-real-rollback-cost-and-consumer-audit
description: 守卫/基线台账登记值上涨违反『只减不增』类棘轮、用户问『豁免注记还是回退』时，不要凭台账数字或直觉二选一。先立三组事实：(1) 增长归属：用 git log -G 定位抬值 commit 及其源 diff，判真实增长 vs 计量漂移；(2) 回退的真实成本：若执行测试有『登记值>=实测值』红线，只改数字必 FAIL，『回退』实为砍已发布代码，可回收行数由 +N 行逐行消费端审计决定（死接线/死参常被同登记册的兄弟 finding 点名，删掉即合法下降）；(3) 注记的合规落点：exemptions 数组往往 schema 另有用途、不可新增。增长真实且是更强约束的显性代价、死接线清理可顺势下降时，选豁免并把清理捆进同一复审。
aliases: 基线变大了要豁免还是回退, 行数棘轮触发了怎么裁决, 登记值改回去会不会撞红线, 函数超标了必须砍代码吗, 豁免注记该写在哪里, 棘轮豁免还是把数字降回去
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:2044:8feadf2b46f1c0014511
evidence_refs: learning:learn:acf0ae6f42b9
created_at: 2026-10-29T09:10:27.728319+08:00
updated_at: 2026-10-29T09:10:27.728319+08:00
---
## Trigger
质量/架构守卫的基线台账登记值上涨（如函数行数 320→323）违反『只减不增』棘轮，登记为待拍板项，用户要求在『豁免注记』与『回退』两个字面选项间给出建议与理由

## Discriminator
三组当时可得的判别事实：(1) 执行测试里的红线断言（超阈值条目登记值必须≥实测值）——只把数字改回去必 FAIL，所以『回退』不是记账操作而是砍真实已发布代码；(2) 对台账 key 做 git log -G 可定位登记 commit 与抬值 commit，git show 源 commit 可逐行核对 +N 行的来源与性质；(3) 同一登记册的兄弟 finding（如『疑似死参』）常常正指向这 +N 行里的死接线，直接决定回退的可回收行数

## Short path
- 读登记条目锁定指标与 key；一次内容搜索定位守卫台账文件与执行测试；读台账 _meta 锁定计量口径
- git log -G <登记key> 取变值 commit 链；git show 抬值 commit 带入的源 commit，逐行核对 +N 行落在哪个函数、是什么接线
- 读执行测试的红线断言与 exemptions/注记 schema：确定『回退实际会触发什么』『豁免注记的合规落点在哪』
- 对 +N 行逐一 grep/awk 消费端，交叉核对同登记册的死参/死接线类 finding：划分真接线 vs 死接线
- 出裁决：增长真实 + 红线禁止纯数字回退 + 增长是更强约束的显性代价 → 建议豁免注记落合规通道，死接线清理捆绑同一 commit 顺势降值；否则按分支给回退或修计量路径

## Stop conditions
- 增长归属、回退实际成本（可回收行数 vs 需重构行数）、注记合规落点三件事均有工具回执支撑 → 给出建议即停，不试改台账或跑测试做『实证』（那是执行阶段的事）
- 红线 FAIL 若只是代码路径实读结论、未真跑测试，显式标注为未核声明

## Verification
- 每次变值（登记与抬值）都有 git log -G 的 commit 回执，且抬值 commit 引入的源 diff 行数与台账增量吻合
- 每条接线行都有 grep 消费端回执（文件:行号）；死参结论以『函数体内零引用、仅签名出现』的实读为证
- 红线断言与 exemptions schema 限制均引用测试文件行号；注记落点建议与台账 schema 不冲突

## Counterexamples
- 增长是纯计量漂移（重测口径变化、函数体没长）→ 该修计量并重登记，豁免和回退都不对
- +N 行全部是死接线 → 直接清理回退更便宜干净，不必留豁免注记
- 守卫只有『只减』弱约束、没有登记≥实测红线，且代码重构成本低 → 回退可能是正确答案而非更贵选项
- 改动尚未 commit/push → 撤销成本极低，不适用『砍已发布代码』的成本模型
