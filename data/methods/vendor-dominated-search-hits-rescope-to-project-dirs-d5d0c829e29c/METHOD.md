---
method_id: vendor-dominated-search-hits-rescope-to-project-dirs-d5d0c829e29c
name: vendor-dominated-search-hits-rescope-to-project-dirs
description: 项目仓库内做仓级文件名/符号检索时，若回执命中被依赖树（.venv/site-packages/node_modules）占满且截断、零项目自有文件，把命中构成本身当作『作用域错误』的判别信号：不再重试同一通用词的检索变体，而是用任务领域词作用域到 ls 已展示的项目自有目录（scripts/、evals/、docs/、data/ 等）并显式排除依赖树；定位到目标组件后先读其 README 取得契约与标准命令，再读当前状态工件确定阻塞点。本集一次 version 类通用词检索 50 条命中全部落在 .venv-da site-packages，随后 ls scripts|grep 领域词 + 排除性有界 find 两步即定位 evals/methodcard_rsi_v1 与 method_mutator.py。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:2495:124c7ef5d329ea88cb66
evidence_refs: learning:learn:6579b1594dde
created_at: 2026-10-19T14:03:53.746305+08:00
updated_at: 2026-10-19T14:03:53.746305+08:00
---
## Trigger
在项目仓库内定位自有组件/脚本时，仓级文件名或符号检索（search_files、无排除的 find）的回执命中全部落在 vendored 依赖树路径下，出现截断且没有任何项目自有文件，而任务目标显然是本项目的组件而非某个已安装依赖。

## Discriminator
检索回执的命中构成是当时已知的判别事实：50 条命中全部位于 evals/pilot/.venv-da/.../site-packages、无一条在 scripts/ 或 evals/ 顶层；同时首个 pwd;ls;ls scripts 已展示项目自有目录集合与脚本命名风格。两者合起来说明查询词过于通用、作用域错误，而不是目标不存在，因此下一步应换作用域而非换检索词变体。

## Short path
- 消费首个 ls 输出确定项目自有目录集合（scripts/、evals/、docs/、data/methods/），不再对 version 这类通用词发仓级检索变体
- 把任务领域词（rsi/method/calib/gate/mutat 等）作用域化到自有目录：ls scripts | grep -iE '<领域词>'，并用带 -not -path '*/.venv*' 排除的有界 find 定位 evals/methodcard_rsi_v1 与 scripts/method_mutator.py
- 定位后先读该目录 README 取得套件契约与标准命令（判分、冻结校验、变异器、闸门），再读当前状态工件（calibration_v3.json、results_*）确定唯一阻塞未知量（题库饱和/可用题数）
- 按文档化命令补题并重跑校准与闸门，验证闸门停位反映真实状态（NO_PAIRS 表示实验未跑而非失败），把高成本实验的启动决策交回用户后停止

## Stop conditions
- 目标组件已在项目自有目录中定位且与任务领域词匹配，不再发同一通用词的检索变体
- 作用域化 grep 无命中时，按序扩展到 docs/、data/methods/ 等自有目录，仍无命中才考虑带依赖排除的仓级检索
- 闸门/校验停位已被解释为与已执行/未执行事实一致，剩余动作需要用户决策或大额预算授权

## Verification
- 重取的定位结果路径应落在项目自有目录内，不含 .venv/site-packages 路径段
- 对照首个 ls 的目录与脚本清单，确认未遗漏同名项目自有脚本（如 scripts/method_mutator.py）
- 修复后重跑的闸门输出停位与真实状态一致（跨过的门与未跑的实验一一对应）

## Counterexamples
- 命中构成混合（既有依赖树又有项目文件）时，查询词未必错误，应做路径过滤而非放弃检索
- 任务目标就是排查某个已安装依赖库的源码或版本行为时，site-packages 命中是目标本体而非噪声，不应排除
- 无 vendored 依赖树的小仓库里，仓级文件名检索成本低且直接命中项目文件，无需预先作用域化
