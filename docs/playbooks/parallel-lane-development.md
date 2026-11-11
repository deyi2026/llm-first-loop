# PLAYBOOK | 并行 lane 开发运行手册（M1 实测提炼）

- 依据: docs/REPORT-20261111-parallel-lane-development-m1.md §3（11 项全实测）+ GOAL-20261111-3cb818eb 三线合入
- 适用: 同仓多 lane 并行开发（主会话调度 + 子代理执行体），含开发、验证、审查、合并全链路
- 性质: 流程纪律沉淀；机制类改进（门禁增量、机械修复快速通道）走演进提案，见 §5

## 1. 并行形态

- **执行体**: spawn_subagent 走远程模型（实测 glm-5.3），不占本地 prompt_concurrency 队列——主会话 1 条 + 开发子代理 2 条三路并行可用（推翻"并发=1 并行子代理不可用"旧结论，EXPERIENCE-20261106 前提已证伪）。
- **三面分工**: 开发面并行（正交 paths 的独立 worktree+分支）；验证面并行（全量门禁后台 job + 审查子代理）；合并面**串行**（lane 队列 + 全局合并槽）。
- **成本结构**: 第 k 条 lane 承受 k−1 次 rebase + 重验（§3#11）——lane 数与串行合并成本线性相关，拆分时计入。

## 2. 拆分前置查依赖面（建议②落地）

- paths 两两不相交是零冲突 rebase 的前提，但**文件路径正交 ≠ 依赖面正交**。
- 实测教训（§3#6）: 私有函数 `_atomic_write` 被 u5_child e2e 脚手架 monkeypatch——Lane-A 改签名触发 lane 内定向测试抓不到的跨面回归，最终以白名单外后果面补入 + 补审收口。
- 拆分检查单:
  1. paths 文件级不相交？
  2. 各 lane 涉及的私有签名是否被 lane paths 之外引用？——在 `tests/`（含 e2e）、`scripts/` 里 grep 目标模块/函数名；
  3. 命中即把引用面纳入该 lane paths 或显式声明后果面白名单，避免合并后补审。

## 3. 终审时序：排队首再派发（建议①落地）

- merge-review 在 **lane 成为队首**（lane_queue_status 无前序待合并项）时才派发，终审锚点以 **lane_queue_submit 入队 preflight 的 main_head** 为准，不以审查者读到的即时值为准。
- 实测依据（§3#8）: 两次 base 卫生竞态窗口——终审者在 main 前进窗口内读到旧值误判"未前进"；排队首再派发同时消掉竞态与重复终审两类成本。
- 操作序: 全量门禁 PASS → 入队（取 preflight main_head）→ 成为队首 → 派 merge-review → verify 凭证 → confirm/ff/done。门禁可提前并行跑，终审不提前。

## 4. 提交姿势与查询失效

- worktree 内提交一律 `git -C <worktree>`；`cd && git commit` 姿势在他人 live lane 共存时会被 main 直写防护误拦（§3#9，姿势即纪律）。
- `subagent_result` 报"句柄不存在"≠ 子代理失败: 以回执文件/topology 为权威再判定（§3#10）。
- 全量门禁必跑且在 rebase 后重跑: 定向测试抓不到跨面回归（§3#6）；未提交 dirty 树上的 exit=0 对 HEAD 锚定型棘轮测试是假绿。

## 5. 机制类改进（未批准前不降级）

以下两项为演进提案通道，现行纪律不变（rebase 后全量重验、任何树变更整轮重审）:

1. **门禁增量/降级重验通道**: rebase 为零冲突纯 replay 且 paths 与前进提交不相交时，全量重验成本（实测 3×10min）高于增量风险——降级通道需机械判据 + fail-closed（见 EVO 提案，人工审阅中）。
2. **机械修复快速通道**: 4 行 pyright 类型收窄即触发整轮重审（§3#7）——切片内机械修复（类型收窄/格式）的轻量复审通道需程序可判判据，无法判定即整轮重审（见 EVO 提案）。
