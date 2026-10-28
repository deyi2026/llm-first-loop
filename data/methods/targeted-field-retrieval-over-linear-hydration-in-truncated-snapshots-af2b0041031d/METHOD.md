---
method_id: targeted-field-retrieval-over-linear-hydration-in-truncated-snapshots-af2b0041031d
name: targeted-field-retrieval-over-linear-hydration-in-truncated-snapshots
description: 控制面/生命周期工具的大型状态快照常以截断回执呈现，头部被同质历史审计数组（如逐元素的 generation_lag 旧代条目）占据。当截断点落在该数组内部时，按字符区间线性水合的产出可预测仍是噪音；而决策所需的当前事实（desired generation、matches_desired_generation、restart_required、pid 等）是数组之外的结构独立命名字段。方法：先对截断回执做结构判别；若截断在噪音数组内，跳过线性水合，直接用目标对象名+状态关键词做定向 evidence 检索跳到当前状态块，读取命名字段得出唯一决策（如 desired 已是新代而运行时未对齐→只需 restart 无需重发布），再以动作回执与终态核验闭环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:1173:d7d0edbc7163ddf56786
evidence_refs: learning:learn:cdfdb6c75e41
created_at: 2026-10-17T14:03:03.544852+08:00
updated_at: 2026-10-17T14:03:03.544852+08:00
---
## Trigger
工具回执为大型状态快照且被截断，截断点位于同质历史/审计数组元素内部，而任务需要的是特定对象的当前状态事实（desired 状态、运行时对齐、健康/重启标志）

## Discriminator
截断回执的可见尾部是均匀重复的旧代审计条目（元素结构一致、仅 generation/lag 数值不同），据此可判定相邻字符区间仍是同类噪音；所需事实以命名字段形式存在于快照别处，可用目标名+状态词直接检索命中——这个结构判别在发起水合之前即可做出，无需先读一段验证

## Short path
- 复用首次快照回执做结构判别：截断点落在哪个结构段；若在历史数组内，把按字符区间的线性水合标记为低价值路径
- 用目标对象名与状态关键词（服务名 + desired/generation/对齐标志）做定向 evidence 检索，直接跳到结构独立的当前状态块
- 从命中片段读取命名字段（desired_git_head、matches_desired_generation、restart_required、pid_alive），得出唯一决策事实（如无需 publish、仅 restart 到期望代）
- 仅当检索无法命中或确需完整上下文时，按结构边界（数组结束处）而非噪音偏移做区间水合
- 用后续动作回执（受理的 generation/target）与检索到的 desired 事实互相印证，避免重复读取快照噪音段

## Stop conditions
- 已从当前状态命名字段取得决策所需全部事实（期望代、是否对齐、是否需要动作），不再消费快照其余噪音段
- 检索命中片段与任务未知量一一对应，且来自同一工具的最新观测

## Verification
- 后续动作回执的参数（generation/target）与检索到的 desired 事实一致
- 动作终态以 action_id/status 查询为准，确认 matches_desired_generation=true 才宣布运行时对齐，而非依据快照中的历史段

## Counterexamples
- 截断点恰在目标内容段内部（当前状态块本身被切断）——此时相邻区间水合正是正确手段，关键词跳读反而可能丢失字段上下文
- 数组本身即目标内容（需要全量审计条目或统计计数）——必须分页/水合完整读取，不能只检索跳读
- evidence 存储没有检索设施、只有区间水合接口——退化为按结构边界跳读，但仍不应从已知噪音偏移起线性推进
