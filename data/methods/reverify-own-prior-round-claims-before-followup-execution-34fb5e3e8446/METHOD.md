---
method_id: reverify-own-prior-round-claims-before-followup-execution-34fb5e3e8446
name: reverify-own-prior-round-claims-before-followup-execution
description: 后续轮计划引用上一轮自己总结的事实断言（某符号/测试是否在 HEAD、量具实际 import 哪份代码、某指标位移该和哪个臂比）时，自产断言不享信任折扣：先按断言类型各做一次最廉价直检——存在性断言对 HEAD 做 scoped grep/ls；来源断言按量具确切调用方式跑一次 import 解析回显 __file__；归因断言核对比较臂是否为『干预前状态』而非『机制关闭臂』。被证伪的前提先从计划剔除，量具修复与消融只建立在幸存前提上，并把来源钉住固化为量具启动断言与 provenance 记录防复发。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:cf1db8d6-5f5a-449e-9226-c1bdc6b0fa97:867:3e61810ff3e13cf6c8b4
evidence_refs: learning:learn:29b4973a654b
created_at: 2026-10-23T04:30:44.781979+08:00
updated_at: 2026-10-23T04:30:44.781979+08:00
---
## Trigger
延续上一轮的后续任务（如『按建议顺序执行』），且要执行的计划引用了上一轮自己报告中的具体事实断言：代码里是否存在某字段/测试、量具实际测的是哪份代码、某指标变化该归谁的账或与哪个臂比较

## Discriminator
每条被引用断言是否都能被一次当下廉价动作直接裁决：对 HEAD 的 scoped grep/ls 命中与否、按量具确切解释器跑一次 import 回显 __file__、消融矩阵臂标签写明的各臂状态——『可直检却未直检』是上一轮四处说错的最小公分母

## Short path
- 从上一轮报告提取计划承重的可复核断言清单，按存在性/来源/臂比较三类分拣
- 存在性断言：对 HEAD 做一次作用域受限 grep/ls（符号名、测试文件路径），命中即撤回『不存在』类说法
- 来源断言：用量具的确切调用方式跑一次 import 解析并回显 __file__/PYTHONPATH，钉死测的是哪份代码
- 归因断言：核对增量比较臂＝自己动手前的状态（如既有 29 别名臂），而非机制关闭臂（0 别名臂）
- 剔除被证伪前提对应的计划项，再执行量具修复与消融；把来源钉住固化为启动断言并写入每次运行的 provenance
- 结论只建立在幸存前提与超过重跑噪声底的位移上（同参数重跑定 ±1 位噪声底）

## Stop conditions
- 每条被引用的上一轮断言均已被一次直检确认或证伪
- 修复/保留/回退决定所依赖的全部前提都来自幸存断言

## Verification
- grep HEAD 能（或不能）找到该符号/测试文件，与引用断言一致
- import 解析回显路径与量具写入的 provenance 记录一致
- 归因叙述里的比较对象与矩阵臂标签一致；被解读的位次变化超过同参数重跑的抖动范围

## Counterexamples
- 断言对象当下不可直检（外部服务状态、已删除历史）——只能显式标记为假设，不为验证烧轮次
- 上一轮断言本身已附权威 provenance 产物（如运行输出里 config.provenance 写明 src 路径）——直接消费记录即可，重跑直检是冗余
- 后续任务与上一轮断言无依赖关系（独立新任务）——无需逐条裁决
