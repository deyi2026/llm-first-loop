---
method_id: verify-finding-vs-base-commit-before-prescribed-fix-1ac34dbf5b31
name: verify-finding-vs-base-commit-before-prescribed-fix
description: 修复工单连同审查 finding 的『该怎么改』一起下发时（如『修正某字段路径』），先不照单实施：直读涉事代码当前构造，再用 git show <base>:<file> 做锚点对比，判断指控缺陷是本补丁引入、base 已有同语义、还是审查切片误读。若 base 同行已有相同语义，指控即误读，真实缺陷常是零测试覆盖+隐式重复耦合——此时先用绿的特征测试锁定真实语义，再统一到单一实现并保持绿；确证为真才走 RED→GREEN 最小修复。后续审查轮再指控同类点，先逐行核源码语义，误读不盲改正确逻辑，最多做无语义变化的形态重构。
aliases: 审查说啥就改啥之前先核对原始提交, 工单给的修法先验证再动手, 上轮审查结论和代码对不上, 按审查意见修复前先确认 bug 真的存在, 特征测试锁行为后再重构, reviewer 把正常代码看成缺陷
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:871:398beb7d439cf7984e9c
evidence_refs: learning:learn:f27b8d867c69
created_at: 2026-11-07T20:36:15.887155+08:00
updated_at: 2026-11-07T20:36:15.887155+08:00
---
## Trigger
修复轮/工单把上游（独立审查、CI、上一轮 finding）的缺陷指控连同具体改法一起下发，指控是可静态核验的代码事实（字段路径、调用时序、比较分支），且当前 worktree 源码与 base 提交都可读。

## Discriminator
涉事锚点行的当前实现与 git show <base>:<path> 同一锚点是否一致：一致且语义正确 ⇒ 指控是切片视野误读，缺陷应重分类为『零覆盖+隐式耦合』；不一致或当前实现确有缺陷 ⇒ 指控成立。（本集实例：base L2223 与 worktree L2430 同为 raw.get('build_identity')，当场证伪『字段路径错误』指控，而『零测试覆盖』指控成立。）

## Short path
- 直读涉事代码当前真实构造（schema/调用点/比较分支），确认指控的缺陷形态是否真的存在。
- git show <base>:<file> 锚点对比：缺陷是补丁引入、base 已有、还是误读？据此把 finding 裁为『成立』或『误读』，并把证据记入 checkpoint。
- 误读分支：先写绿的特征测试锁定现行真实语义（真实数据结构+缺字段/mismatch 行为），再把重复实现统一到单一 helper，重构全程保持绿，而不是按描述改代码。
- 成立分支：先写能证明缺陷的 RED 回归，再做最小修复变绿。
- 后续审查轮再次指控时，先逐行核源码语义（区分易混形态，如事务结束标志 vs 指针切换时机）；确属误读不改正确逻辑，最多把调用移到不诱发误读的位置，语义不变。

## Stop conditions
- 每条授权 finding 均已裁为『成立并 RED→GREEN 修复』或『误读并有源码/base 证据记录』，不存在未裁决项。
- 不为误读项重写正确逻辑、不扩大授权范围；裁决证据已 checkpoint，可进入冻结/审查。

## Verification
- 新测试确实触发目标路径：移除或变异被测检查/统一后的 helper 会让测试变红。
- 对误读项证明『按原描述实施』要么无事可改、要么破坏现行语义（特征测试会红）。
- 统一重构后特征测试与既有定向测试全绿；diff 只落在授权路径内。

## Counterexamples
- 直读即确证的缺陷（如 revoke 的 tmp+rename 旧 inode CAS 复活竞态）：跳过 base 祖先考证，直接 RED→GREEN 最小修复。
- base 不可达（无版本控制、历史被 squash、只有外部快照）：退回当前定义面/运行时面裁决，不做无意义的考古。
- 指控来自语义权威（用户明确要求的行为变更，而非对现状的推断）：出现矛盾应先向其澄清确认，不自行重分类缺陷。
