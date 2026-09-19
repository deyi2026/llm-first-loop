---
method_id: anchor-narrow-wiring-at-construction-site-7f3ff30de391
name: anchor-narrow-wiring-at-construction-site
description: 当任务是『把已存在注入点的组件经 opt-in settings 接进生产装配点、缺省零差异』时，把全部取证锚定在装配点那一次构造调用上：调用的实参清单就是完整接线面，装配文件的 import 行就是组件真实模块路径（不猜目录）；settings 命名先查权威短文档（短文档一次整读，不做关键词 grep 往返），无权威再取同一装配文件里最近的 opt-in 惯例；先写含缺省零回归守卫的 RED 再改码；测试绿后如实标注构造级测试覆盖不到的运行时行为边界。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:1037:8e3e763817e88fe56b50
evidence_refs: learning:learn:09f8a42a76a4
created_at: 2026-09-19T03:23:38.283080+00:00
updated_at: 2026-09-19T03:23:38.283080+00:00
---
## Trigger
任务形态为『把组件 X 接线到生产装配点（factory/entrypoint），settings 显式开启、缺省与现状零差异』，且任务本身已知是窄接线而非新组件设计；典型信号是开始猜测组件文件路径、反复重读同一装配区域、或对很短的权威文档做多轮关键词搜索。

## Discriminator
动手前已可见的三个事实把搜索空间缩到极窄：(1) 装配点对组件的构造调用已完整列出全部实参（本例 factory 构造 SubAgentRunner 的逐 kwarg 清单）——这就是全部接线面；(2) 装配文件必然 import 该组件——import 行唯一确定模块路径，无需猜 src/xx/runtime/ 之类目录；(3) 组件 __init__ 中注入参数默认 None=关（slice 已预落地注入点），说明剩余工作只是 settings 字段+条件构造+传参。第一处扩散正是抛开了 (2) 去枚举猜测的文件布局。

## Short path
- 定位装配点对组件的唯一构造调用并整段读一次：实参清单=接线面，同文件的 import 行=组件真实模块路径；不再猜测目录布局
- 读组件 __init__ 签名一次：确认注入点已存在且缺省 None=关；若不存在则本方法终止，转入设计/切片任务
- 权威设计文档若很短则一次整读：确认是否规定 settings 命名/行为；未规定才采用同装配文件最近的 opt-in 惯例（env 前缀+空值=关闭），并引用该惯例代码位置作为命名依据
- 读被注入组件的构造签名一次（如 coordinator 的必填字段），逐字段推导应由 settings 提供什么、缺省值是什么
- 先写 RED：opt-in 路径构造出被注入组件且 spawn 产生预期副作用；缺省路径写显式零回归守卫（无该组件、无其落盘产物、既有工具回执行为不变）
- GREEN→相邻测试套件→全量；最终回答如实标注构造级单测覆盖不到的运行时行为（如 live spawn/跨进程），停止

## Stop conditions
- 构造级 RED→GREEN、相邻套件与全量测试 exit=0，且缺省零回归守卫通过
- 组件注入点不存在（需先做设计变更落地注入参数），本方法不适用即停
- 权威文档/schema 已固定命名或接线约定——遵循权威并停止惯例推导

## Verification
- 缺省配置下：装配产物中无被注入组件、无其落盘状态文件、既有工具回执与接线前逐字一致
- opt-in 配置下：被注入组件以 settings 推导的实参构造并传入目标组件
- RED 先失败、实现后 GREEN；相邻测试与全量套件通过
- 最终答复中显式标注单元/构造级验证未覆盖的行为边界，不以构造级测试宣称端到端验证

## Counterexamples
- 组件尚无注入参数（前序 slice 未落地注入点）：这是设计任务而非窄接线，锚定构造调用会漏掉真正的工作量，应先做接口设计
- 权威 spec 已明确规定 settings 命名或 wire schema：必须遵从权威，套用仓库惯例会制造第二套命名
- 接线正确性只能在 live/跨进程运行中观察（真实子会话完成、跨代 CAS reclaim）：构造级单测不能作为行为验证，需另行 live qualification，本方法的 stop 条件不满足
