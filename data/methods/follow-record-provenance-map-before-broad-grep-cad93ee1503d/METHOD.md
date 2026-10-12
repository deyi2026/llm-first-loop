---
method_id: follow-record-provenance-map-before-broad-grep-cad93ee1503d
name: follow-record-provenance-map-before-broad-grep
description: 当任务工单/记录已自带'代码核验、函数级定位'的事实清单（file:line+函数名锚点）时，把它当主 provenance 图：先对命名锚点做精确符号搜索与定点读取，宽关键词 grep 只能服务于一个已点名的未知量，且必须后置。grep 命中要按来源类分级：仅出现在 .pytest_cache/.ruff_cache/临时目录/历史治理文档中的候选工件应判为'历史先例'而非现存文件，先做一次现存树上的文件名确认再决定是否 read。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:209:b1ae0f7da19244a9137a
evidence_refs: learning:learn:66e9e856ad21
created_at: 2026-09-20T09:33:31.986098+00:00
updated_at: 2026-09-20T09:33:31.986098+00:00
---
## Trigger
开始执行一个自带函数级代码定位的任务记录/工单（如 evolution 描述、事故报告），需要定位实现挂钩点时；或准备对内容搜索命中的候选文件发起 read 之前。

## Discriminator
两条 knowledge-at-time 事实：① 首个 search_records 已返回'已代码核验，改写源定位到函数级'并给出命名锚点（core/history.py:818、history.py:853-854、build.py:548、中段 project_act…），足以直接定点跟进；② 宽搜命中列表中候选文件 test_run_prefix_stability.py 的全部引用均来自 .pytest_cache/.ruff_cache/.codeartsdoer/temp/docs/governance/submissions，现存 tests/ 树零命中——发起 read 前该事实已在屏幕上。

## Short path
- search_records 核实 evolution 状态，收到 executing 回执即停，不重复核实
- 解析记录中的命名锚点，逐个做精确符号搜索定位现存调用点（如 run_projection_gate、project_active_tool_working_set_with_stats 的 call sites）
- 先例核查压缩为一次现存树文件名搜索（prefix_stability）：无命中即结论'仅历史治理档案'，不发起 read
- 只读锚点周边代码段（tail_assembly/ingress_resolution 调用点上下文）确定挂钩位置；仅当出现点名未知量（如'是否触碰持久化白名单'）才追加定点读取
- 实现检查器+测试+挂钩，测试全绿且 diff 与计划一致即停

## Stop conditions
- 记录中点名的全部改写阶段都已定位到现存调用点
- 先例问题已由一次文件名搜索回答（无现存实现）
- 实现+测试全绿，git status 改动面与计划一致
- 状态核实收到权威回执后不再重复核实

## Verification
- 最终 diff 只含计划内文件（本例 4 文件），无探索期副作用或失败残留
- 挂钩点与记录命名函数的调用点一一对应
- 被判定'不存在/历史档案'的文件，其结论与后续事实一致（本例 read 确实失败，验证判定正确）
- 工具失败数为 0，或每个失败都有探索外正当理由

## Counterexamples
- 记录陈旧或未经代码核验（重构后 file:line 已漂移）：锚点不可信，必须先读当前源/宽搜确认再挂钩
- 任务未知量本身就是'找出所有做 X 的位置'且无命名锚点：宽 grep 是正确的第一步，本方法不适用
- 候选文件在现存源码树有真实命中（非缓存/历史来源）：应直接 read，不得因来源类规则跳过
- 本例读 reconcile.py 属正当发现：它服务于点名未知量'是否触碰 Session schema/持久化白名单'，不应被'少读文件'误伤——本方法约束的是无点名目标的枚举，不是定点核查
