---
method_id: metric-mismatch-locate-input-caliber-then-converge-by-commit-0759db4676a1
name: metric-mismatch-locate-input-caliber-then-converge-by-commit
description: 同一代码度量出现『我测 X、守卫报 Y』式分歧且两边算法相同时，唯一自由变量是各自解析的输入版本（工作树/staged/HEAD/快照）。直读守卫度量函数的输入获取层与口径注释，差异即被解释——两个数都对，无需对拍重测或挖计数公式。随后用最小动作收敛输入（提交让工作树改进进入守卫口径），并在收敛之后再做受该门禁管辖的实现，避免新工作被旧口径评判。
aliases: 守卫报数和本地实测对不上, 改完代码门禁还报旧行数, 两个工具量同一指标结果不一样, 先提交还是先过棘轮, 度量分歧先查读的是哪个版本
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:2525:a4fa7c13775349dd7164
evidence_refs: learning:learn:d52a7d60ce2c
created_at: 2026-11-06T20:31:24.023213+08:00
updated_at: 2026-11-06T20:31:24.023213+08:00
---
## Trigger
本地实测一个代码度量（函数行数、复杂度等）与守卫/门禁/另一工具的报数不一致，且两者名义上用同一算法或定义；或门禁持续报告一个工作树里已明显改进的旧数值。

## Discriminator
定位到度量函数后先比两处：计数公式与本地测法是否相同（如同一 AST end_lineno span）；若相同，再看解析输入是否经过带版本口径的间接层（如 _read_source 及『未 staged 回退 HEAD』注释）——公式相同＋输入间接层存在，即可把『谁对』缩成『各读哪个版本』：守卫读 HEAD 而本地读工作树，则两个数皆真。

## Short path
- 核实任务前置状态（审批回执对应执行项的真实状态），这是用户显式要求的独立未知量
- 定位守卫/另一方的度量函数，优先读其计数公式与解析输入两处，而不是先挖 span 等算法细节
- 公式相同→只追输入口径：读输入获取函数或其 docstring 的版本语义（工作树/staged/HEAD/快照回退）
- 口径读到即分歧闭合：写出双方口径解释，不再重复测量或对拍数值
- 最小动作收敛输入：git add+commit（必要时推送）使本地改进进入度量方口径
- 收敛之后再实现受该门禁管辖的变更，收尾重跑守卫/ratchet 测试验证口径已对齐

## Stop conditions
- 已从度量代码的输入获取处直接读到版本口径事实，分歧获得单一解释
- 提交（或推送）后守卫/相关门禁测试通过，且报数与本地测量一致

## Verification
- 重跑对应守卫/ratchet（或等价门禁）测试，确认读数与本地测量一致
- 结论同时陈述两边口径（如 HEAD vs 工作树），而不是只给一个『正确』数值

## Counterexamples
- 两边计数定义本就不同（裸行数 vs AST span、是否含装饰器/空行）：输入相同也会不一致，应对齐定义而非提交
- 度量方在 CI 独立 checkout 上运行：本地 commit 不进入其口径，须 push 后再验证
- 守卫自身有 bug 或读的是无 HEAD 回退语义的缓存快照：收敛 git 输入无效，需修守卫/清缓存
- 分歧只是测量时机不同（改动前 vs 改动后）且无门禁在途：以较新测量为准即可，无需口径排查
