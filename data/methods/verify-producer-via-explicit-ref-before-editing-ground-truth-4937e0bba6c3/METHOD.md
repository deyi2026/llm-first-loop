---
method_id: verify-producer-via-explicit-ref-before-editing-ground-truth-4937e0bba6c3
name: verify-producer-via-explicit-ref-before-editing-ground-truth
description: 当数据驱动测试失败（如期望事件 0 vs N）且已倾向"补全权威数据声明"时，先沿数据条目内显式引用的生产者（builder/handler/源码）确认真实行为，再改真值。修改共享 ground truth 是高风险动作：凭记忆或推断写入的声明一旦有误，会把错误固化为"正确期望"。本方法用一次源码确认把"该不该改、改成什么"的不确定性收敛掉，避免错误真值固化后的回滚-重修循环；同时坚持修数据层而非在消费者写路由特例。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:168:22baf1dabe1e1b6496d1
evidence_refs: learning:learn:917e5f3991c4
created_at: 2026-09-17T22:25:15.936947+00:00
updated_at: 2026-09-17T22:25:15.936947+00:00
---
## Trigger
数据驱动消费者（runner/test）出现缺失型失败（期望效果 0 vs N），初步定位指向权威数据声明缺口（而非消费者断言 bug），且即将编辑共享 fixture/manifest/期望文件

## Discriminator
待改的数据条目中存在指向行为生产者的显式引用（本例：manifest 条目里的 "builder": _page_unique_select），该引用在本轮尚未被读过——这条已可见的 provenance 边能把"凭推断改真值"缩成"读一个函数确认后改"

## Short path
- 读失败输出，分类为缺失型失败（0 vs N），确认消费者统一策略依赖数据声明，排除消费者侧断言/交互 bug
- 用同数据源兄弟条目做 diff 判断缺陷层（如 fill 页双 canonical 对象 vs select 页单对象的不对称）
- 沿条目内显式 builder/handler 引用读生产者源码，确认交互门槛与上报行为：谁触发 expected_event、对象 kind/name/id 是否与拟添加声明一致
- 源码确认后才补全数据声明并同步 README/文档，消费者保持零路由特例
- 全量重跑共享该数据的所有套件（qual + 自检 + smoke）；数据修复与消费者变更分开提交，保留"谁暴露了缺口"的因果记录

## Stop conditions
- 生产者源码逐字段确认了拟新增声明（确认控件存在、其点击触发该 expected_event）
- 源码行为与推断不符 → 停止改数据，重新定位缺陷层（消费者或页面 builder）
- 生产者源码不可读或行为运行时才确定 → 用受控探针（运行后查事件日志 /state）替代源码确认，否则不改真值
- 全量套件绿，且消费者 diff 中没有为通过测试新增的特例分支

## Verification
- 拟新增声明的每个字段（kind/name/expected_id）都能在生产者源码中找到直接对应
- FAIL→PASS 的变更 diff 中仅含数据与文档改动，消费者代码零变更
- 共享该 fixture 的其他套件（冒烟/HTTP 自检）无回归

## Counterexamples
- 失败根因在消费者侧：如浏览器将属性序列化为双引号导致单引号 marker 子串匹配失败——此时必须修消费者断言（归一化或改用 DOM API 查询），改 fixture 迁就属错误方向
- 权威数据是外部冻结契约或第三方规范，既无生产者源码可读也不可编辑 → 只能消费者适配或上报，本方法不适用
- 无兄弟条目可对比、且生产者行为依赖运行时状态源码读不出结论 → 源码确认必须换成事件日志/实测探针，否则同样不得修改真值
