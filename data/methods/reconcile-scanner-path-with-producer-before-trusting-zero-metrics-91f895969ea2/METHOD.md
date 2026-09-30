---
method_id: reconcile-scanner-path-with-producer-before-trusting-zero-metrics-91f895969ea2
name: reconcile-scanner-path-with-producer-before-trusting-zero-metrics
description: 当基于路径/glob 约定的扫描型指标（health/census/计数器）返回空或零，而另一来源声称有数据时，不要把零当作数据面事实，也不要先扩大审计范围。第一怀疑是读取端的布局假设与生产者写路径错配：用机械盘点确定数据文件真实位置，核对生产者写路径构造，对齐后重放指标并与源文件逐条对账；只有布局一致且解析正常时，零才是可信事实。本集证据：find 显示 usage.jsonl 仅在 store 顶层、grep store.py 确认写路径为 self._dir/usage.jsonl，而读取端 glob */usage.jsonl 恒空——指标'零回流'曾被误登记为事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1233:b7a990a3581c69276702
evidence_refs: learning:learn:a4644589058f
created_at: 2026-09-30T00:40:47.800888+08:00
updated_at: 2026-09-30T00:40:47.800888+08:00
---
## Trigger
扫描型指标读空/归零，或与其他来源给出的非零计数矛盾；且该指标实现依赖对数据文件的 glob/路径约定扫描

## Discriminator
机械盘点显示数据文件实际存在于另一位置（如 store 顶层单文件而非每方法子目录），且生产者源码的写路径构造（如 self._dir / "usage.jsonl"）与读取端 glob（如 */usage.jsonl）不一致——该事实当时即可把候选假设从'数据缺失/断流'缩成'读取端布局 bug'

## Short path
- 对矛盾信号做一次机械盘点（find/ls）确定数据文件真实位置；解决未知量：数据到底在哪、是否存在
- grep 生产者（写入方）的路径构造确认权威布局；解决未知量：布局本应是什么
- 对比读取端与写入端；不一致则改写读取端镜像生产者布局（去重键等派生语义随布局同步重审）
- 在真实数据池上重放指标，与源文件内容逐条 reconcile
- 同步修正依赖该指标的 fixture/下游断言，跑相关测试后停止

## Stop conditions
- 读取端路径与生产者写路径一致，且重放值与底层记录精确吻合（如文件 2 条 ↔ with_usage=2、use_decisions 逐条对应）

## Verification
- 重放后指标与原始文件逐条对账：总数与按 method_ref 去重后的 distinct 值均吻合
- 相关单测全绿，且测试 fixture 已改为生产者真实布局而非沿用旧假设布局
- 下游曾引用该指标的错误结论/登记被显式更正，而非只改代码

## Counterexamples
- 盘点显示数据文件根本不存在、写入侧确认从未落账——零是真断流（数据面问题），此时修布局会把真病灶洗白
- 文件位置正确但内容解析失败（schema 变更/坏行）——同症状不同根因，路径对齐后仍零则需验解析器
- 读取端有意做多位置兼容扫描（双写迁移期）——扩大 glob 是设计而非 bug，不应套用本方法'修正'它
