---
method_id: targeted-range-recovery-before-full-pagination-4afd292bd116
name: targeted-range-recovery-before-full-pagination
description: 当结构化工具观测被截断但附带 range/offset/complete 元数据时，先锁定阻塞下一步动作的单个未知字段，只取该字段所在片段（或按前缀已可见的命名模式构造候选引用，用不会 dispatch 的动作回执作廉价探针验证），而不是顺序分页读完整块 blob。同时注意：若计划中的变更（如 navigate）会使当前页的 per-object 引用失效，则全量投影这些条目没有下游消费者。附带两条机械节约：绑定共享资源（端口）前先一条命令查占用；遇语义化拒绝码时对精确 reason 字符串做一次全仓 grep，直接读唯一命中处，不先猜文件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:2893:01bdd74266302b33f8f0
evidence_refs: learning:learn:06fe26f03f73
created_at: 2026-09-18T12:27:38.165172+00:00
updated_at: 2026-09-18T12:27:38.165172+00:00
---
## Trigger
工具观测被截断并返回 range/start/next_start/complete 元数据；下一步动作只依赖其中一个特定字段（如页面级 resource_ref）；且会话处于恢复场景（存在遗留后台进程/旧实例），或收到带精确 reason 码的拒绝回执

## Discriminator
截断前缀当时已暴露 snapshot 版本、scope_ref 和 grounding ref 命名模式；range 元数据标明剩余内容位置与总量（~15K、4 页）；同时计划已明确要导航离开当前残留错误页——即当前页全部对象投影会被导航作废，唯一真正阻塞 navigate 的是页面级 target ref；恢复场景中旧 http server 占用 8799 也是当时一条 lsof 即可确认的已知风险

## Short path
- 从截断前缀提取已可见事实（runtime 版本、scope、ref 命名模式），明确唯一阻塞字段是页面级 target ref，而非 19 个对象的完整投影
- 仅请求该字段所在 range（依 next_start/complete 元数据定位尾部资源级字段），或按前缀可见模式构造候选 ref，用 rejected-but-not-dispatched 的动作回执作廉价探针验证
- 按原计划执行负路径探针（如 file:// scheme 的 navigate，预期精确拒绝码）
- 绑定共享端口前先一条 lsof 查占用，避开遗留旧 server，省去一次 bind 失败重试
- 遇 resource_scope_mismatch 类语义拒绝时，对精确 reason 字符串做一次全仓 grep（不先猜 action.py），读唯一命中处（perception.py:1991）后修正 scope 参数重发
- 变更后必须 re-observe 验证语义终态（fill/select/click 的 JS 副作用），不把回执 success 当结论

## Stop conditions
- 阻塞字段已恢复且其 snapshot id 与 live perceive 的 observed_version 一致，或探针回执确认构造 ref 可用
- 计划动作加重新观察已闭环确认目标状态变化（如 h1/input/select 与预期一致）
- 对残留 blob 的其余分页仅在有明确下游消费者（后续动作要引用这些条目）时才继续

## Verification
- 恢复的 ref 内嵌 snapshot 版本必须等于当前 perceive 的 observed_version，不得跨版本拼接
- 每次变更后用 re-observe 独立验证语义效果，回执状态只证明 dispatch 结果不证明页面语义
- 拒绝码修正后重发，确认新回执 status 与 before_version 均符合预期

## Counterexamples
- 所需字段位置未知且 blob 很小（一两页即读完）——顺序读完整块更便宜也更稳，猜测 range 反而可能漏字段
- 当前页的对象引用正是后续操作目标且无导航计划——完整投影是必需输入，跳过分页有害
- 证据系统不支持 range 请求，或下游版本校验要求完整 bundle——只能完整顺序分页
- 构造引用所需的命名模式未在可见前缀中出现——探针失败信息量低，应直接读数据源而非瞎构造
