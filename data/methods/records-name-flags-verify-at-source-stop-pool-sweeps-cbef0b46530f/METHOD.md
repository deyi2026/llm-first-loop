---
method_id: records-name-flags-verify-at-source-stop-pool-sweeps-cbef0b46530f
name: records-name-flags-verify-at-source-stop-pool-sweeps
description: 当任务要断定本地系统『当前』的配置/行为（哪些检索或加载开关开启、注入策略、路径现状），且此前检索回执中的记录已点名具体 flag、路径或模块时，位置性检索空间已经闭合：继续跨池（docs/experience/method）换主题词扫描无法提高分辨率。正确动作是从已命中记录提取点名清单，用一次定点读取（grep 配置前缀、读指名文件、读快照字段）取得当前值，与记录值逐项对照，冲突处标注『记录时间 vs 当前实读』并列为未核实。记录只回答『当时如何』，被点名 artifact 才回答『现在如何』。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:0f0a5645-b407-4183-bd45-9c5d82003d93:5:bd2db78d1b9814849b8a
evidence_refs: learning:learn:ca6ee5eb805c
created_at: 2026-10-10T00:14:09.196880+08:00
updated_at: 2026-10-10T00:14:09.196880+08:00
---
## Trigger
任务需要断定本地 runtime 当前的配置/行为（分层加载开关、注入策略、模块现状），且已返回的检索记录中出现了具体配置项名、文件路径或模块名

## Discriminator
记录回执里已存在带状态的点名清单（如 semantic_memory=true 而 method/experience/docs=false、MEMORY_TOP_K、指名 store/factory 路径）。这一事实在当时就把『当前值是多少』的候选来源缩到唯一权威 artifact：换一个池、换一组主题词再检索，命中率与分辨率都不会提升

## Short path
- 从已命中记录中提取全部被点名的 flag/路径/模块清单（只用当时已返回的信息，不引入后续读取结果）
- 用这份清单拼一次定点读取（如一次按配置前缀 grep .env、读指名文件或快照对应字段），目标是当前值而非记录转述
- 将读到的当前值与记录值逐项对照；冲突处标注日期与来源并列为 unverified，不追加检索去追查
- 每个待回答/待比较维度拿到一次权威读数后立即停止检索，转入分析产出
- 仅当清单中某项在权威 artifact 中不存在或不可读时，才做一次定点定位检索，而不是退回全池主题词扫描

## Stop conditions
- 清单中所有点名配置项均已从权威 artifact 读到当前值
- 剩余不一致（如统计停滞、记录与实读冲突）已显式标为 unverified，而非继续发起新检索
- 未知量已从位置性（当前值是什么）转为语义性（借鉴什么、怎么改），不再需要新的位置性事实

## Verification
- 每条『当前配置/行为』结论都能映射到本回合的一次权威读取（.env 行、代码行、快照字段），不能只引用记忆记录的转述
- 记录来源的数值仅作带日期的上下文引用；与实读冲突时以实读为准并显式标注冲突
- 复查工具计数：清单拼读应以 ≤2 次读取替代此前多池主题词扫（本集 search_docs miss 与 experience 扫描两次属可省的扩散动作）

## Counterexamples
- 记录只给模糊叙述、未点名任何 flag/路径时：此时先做一次定点检索定位路径，再读权威源；不能跳过检索直接猜文件
- 未知量是历史事件或审计结论本身（记录即证据），不是当前值：应引用带日期的记录，而非重读配置
- 权威 artifact 不可读、不存在，或记录指向多个互斥版本：此时需先问用户或做版本定位，不适用本方法
