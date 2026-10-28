---
method_id: triage-dirty-worktree-real-vs-churn-before-child-dispatch-729b89e33672
name: triage-dirty-worktree-real-vs-churn-before-child-dispatch
description: 续跑/恢复会话后 git status 常同时显示两类修改：上一轮真实但未提交的源码改动，和测试重跑自动再生成的报告类产物（diff 仅时间戳与指标抖动）。在派子代理、建对比基线或验收之前，必须先把两者分开：按路径前缀分类、每类抽一份样例 diff 裁决，真实改动经目标测试验证后明确列文件提交，再生噪声 checkout 还原，确认工作树干净再开工，否则子代理 diff 不可归因、基线被污染。
aliases: 工作树一堆脏文件先分清哪些是测试重跑刷出来的, 派子代理前先提交上轮遗留改动, 报告只有时间戳变了要不要还原, 续跑后旧改动和重跑产物混在 git status 里, 子代理 diff 混入上一轮未提交代码, 开工前先把基线清干净
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:2400:db5dae4bcb871b728585
evidence_refs: learning:learn:453a4545e76c
created_at: 2026-10-28T12:35:51.136530+08:00
updated_at: 2026-10-28T12:35:51.136530+08:00
---
## Trigger
续跑或恢复会话后，git status 显示多文件混合修改（源码/测试 + reports 等生成产物目录），且下一步动作是派子代理、建立 diff 基线或做验收对比

## Discriminator
被修改文件的路径前缀天然分成两类；对每类各抽一份样例 diff 即可裁决：产物类 diff 只含 started_at/finished_at 时间戳变更和指标抖动（如 148.6→180.5ms），无语义字段变化；源码类 diff 含实质新增逻辑。这一差异在第一次 git status + 第一次样例 diff 时就已可见，无需逐文件全量排查

## Short path
- git status 按路径前缀把修改分成『源码/测试』与『生成产物』两类，不逐文件枚举
- 每类抽一份样例 diff：产物类仅时间戳/指标漂移 → 标记为重跑噪声；源码类 → 标记为上一轮真实工作
- 用项目权威解释器（一次探明 .venv 真实指向与 requires-python，不逐个试 PATH）跑覆盖源码改动的目标测试
- 验证通过后 git add 明确列出真实改动文件并提交（不用 -A）；对噪声目录 git checkout -- 还原
- git status 确认干净后再派子代理/建基线，子代理的 diff 基线即该提交，可归因

## Stop conditions
- 工作树已干净，或全部修改可归为单一类别
- 样例 diff 显示产物文件出现语义变化（status ok→fail、门值翻转、新增字段）→ 停止按噪声还原，转回归排查
- 真实改动对应的目标测试未通过 → 不提交，先回修复循环

## Verification
- 提交后 git show --stat 只含预期的源码/测试文件
- git status --porcelain 为空或仅剩已知无关项
- 子代理回执的 diff 基线 commit 恰为本次提交，无混入的上轮改动或还原前的报告抖动

## Counterexamples
- 报告文件本身是本次交付物（验收报告必须反映最新一轮实测数据）→ checkout 还原反而销毁交付内容
- 产物 diff 中出现 PASS→FAIL 或验收门翻转 → 这是回归信号而非噪声，不能还原
- 单人短任务、不派子代理也不做 diff 对比时，此清理是纯开销，直接继续即可
