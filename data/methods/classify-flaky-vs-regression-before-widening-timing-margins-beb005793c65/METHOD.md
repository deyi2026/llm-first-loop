---
method_id: classify-flaky-vs-regression-before-widening-timing-margins-beb005793c65
name: classify-flaky-vs-regression-before-widening-timing-margins
description: 时序敏感测试（sleep/竞速/超时断言）在 CI 变红、拟通过放宽测试自身参数修绿时，先裁决『环境抖动还是真回归』再动手：用失败 run 的逐样本日志（同一构造兄弟样本是否通过、失败样本时延指标、断言实际值）加 last-green→first-red 的 diff 是否触及被测时序路径，两条只读证据把假设空间缩到一类。兄弟通过且 diff 无交叠⇒抖动，放宽合法；全红或交叠⇒回归，应改产品代码而非余量。裁决成本仅 2~3 条命令，必须在派发修改之前完成，且失败日志本身已点名测试文件与构造，可替代全仓关键词枚举。
aliases: CI 偶发红要不要加 sleep, flaky 还是回归怎么判断, 测试超时改大之前先定性, 单样本失败算不算回归, 先看失败样本再决定改余量
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:869:a618e9d954f4922ebc86
evidence_refs: learning:learn:67996c26663e
created_at: 2026-10-27T21:52:46.851183+08:00
updated_at: 2026-10-27T21:52:46.851183+08:00
---
## Trigger
CI 中时序敏感测试变红，已拟定的修复是放宽测试参数（加长 sleep/timeout/余量）而非改产品代码；或任何『增大容忍余量』型测试修改即将派发执行时。

## Discriminator
失败 run 的失败步骤日志（--log-failed 或等价物）是否显示：同一构造多个样本中仅个别失败、兄弟样本通过、失败样本带具体时延数值与断言实际值；配合 last-green 到 first-red 的提交 diff 范围与被断言的时序代码路径是否交叠。这两份当时即可获取的事实唯一化抖动/回归结论。

## Short path
- 由 CI 运行清单钉出失败 run 与 head SHA，确认 last-green/first-red 边界；失败日志会直接点名测试文件与构造，无需先做全仓关键词搜索
- 读失败步骤日志，提取失败测试名、样本 tag、时延指标、断言期望值 vs 实际值
- 对比边界区间 diff 范围与被测时序路径是否交叠，并核对同一构造其余样本是否通过
- 兄弟通过且无交叠→判抖动，才派发/执行放宽；全红或交叠→判回归，转向审查产品改动
- 放宽后重复运行验证确定性，并把量化后的有效安全预算写进注释防止后人调回旧值

## Stop conditions
- 逐样本日志与 diff 交叠两份证据已把结论唯一化为抖动或回归，不再枚举其他解释
- 修改后 N 次重复运行（串行+并行）全绿，且实测失败指标落在旧容忍窗之外、新容忍窗之内

## Verification
- 用失败样本观测时延反推系统滞后量，应落在旧容差外、新容差内；数字对不上说明机制解释错误，重查而非提交
- 重复运行同一测试（如串行与并行各 20 次）确认确定性恢复
- git diff 确认改动只触及目标构造与注释，未动产品代码与兄弟构造

## Counterexamples
- 同一构造所有样本在多次 run 全失败→稳定红，大概率真回归，放宽余量只会掩盖问题
- last-green→first-red 的 diff 恰好改了 runner/调度/超时逻辑本体→回归假设优先，先审这段 diff
- 测试目的就是断言绝对时延上限（性能预算本身是被测属性）→不能放宽，只能重构测试或接受失败
- 本地无法取 CI 日志且无法复现→抖动/回归不可裁决，先建立可复现性再谈修法
