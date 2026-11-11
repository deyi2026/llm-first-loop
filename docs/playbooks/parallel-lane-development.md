# PLAYBOOK | 并行 lane 开发运行手册（M1 实测提炼）

- 依据: docs/REPORT-20261111-parallel-lane-development-m1.md §3（11 项全实测）+ GOAL-20261111-3cb818eb 三线合入 + EXPERIENCE-20261109（未提交 dirty 树门禁假绿，见 §4 末条）
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

- merge-review 在 **lane 确认队首**（lane_queue_status 无前序待合并项）时才派发，终审锚点以 **verify 凭证的 base-sha**（签发时 issue_verify_receipt 显式传入的当前 main）为准，不以审查者读到的即时值为准。
- 实测依据（§3#8）: 两次 base 卫生竞态窗口——终审者在 main 前进窗口内读到旧值误判"未前进"；排队首再派发同时消掉竞态与重复终审两类成本。
- 操作序: 全量门禁 PASS → 确认队首 → 派 merge-review → PASS 后签发 verify 凭证 → **立即**带凭证 lane_queue_submit → confirm/ff/done。门禁可提前并行跑，终审不提前。
  - 顺序约束来自机检而非偏好: submit 的机检 d 要求**提交时已持**本 lane 专属、pass、TTL 内、base 匹配的 verify 凭证，而凭证只能 merge-review PASS 后由 issue_verify_receipt 签发——先入队再终审的字面顺序会烧掉一条不可逆 failed 队列项。签发与 submit 之间不插入其它动作，竞态窗口压到最小（机检 a 在 submit 时复核 base==当前 main）。

## 4. 提交姿势与查询失效

- worktree 内提交一律 `git -C <worktree>`；`cd && git commit` 姿势在他人 live lane 共存时会被 main 直写防护误拦（§3#9，姿势即纪律）。
- `subagent_result` 报"句柄不存在"≠ 子代理失败: 以回执文件/topology 为权威再判定（§3#10）。
- 全量门禁必跑且在 rebase 后重跑: 定向测试抓不到跨面回归（§3#6）；未提交 dirty 树上的 exit=0 对 HEAD 锚定型棘轮测试是假绿。

## 5. 机制类改进（未批准前不降级）

以下两项为演进提案通道，现行纪律不变（rebase 后全量重验、任何树变更整轮重审）:

1. **门禁增量/降级重验通道**: rebase 为零冲突纯 replay 且 paths 与前进提交不相交时，全量重验成本（实测 3×10min）高于增量风险——降级通道需机械判据 + fail-closed（见 EVO 提案，人工审阅中）。
2. **机械修复快速通道（已落地，EVO-20261111-8c5b88df）**: 切片内机械修复（仅注解/纯格式，无语义/控制流/签名变化）触发轻量复审而非全新审查轮。
   - **机械判据**（`src/llm_loop/tools/mechanical_diff.py`，全部机检、fail-closed）: 触碰文件全为 `.py` 且解析成功; 每文件判为 `format_only`（AST 完全相等）或 `annotation_only`（注解消除归一后 AST 相等——新增/收窄/删除注解不影响运行时语义）; 非 .py、语法错误、越出切片、任何语义变化 ⇒ not mechanical，按全新变更整轮重审。
   - **接入点**: `review_admission.start(previous_child_id=...)` 续审时，宿主自动用两轮冻结 HEAD 做 git diff 预检，结论（MECHANICAL/NOT MECHANICAL + 逐文件类别）注入任务书; 预检是**信息注入**，不改变任何资格判定——判不了按 NOT MECHANICAL 披露。
   - **测试**: `tests/unit/test_mechanical_diff.py`（12 例含应拦分支）+ `test_review_host_admission.py` 集成 2 例（注解修复标 MECHANICAL; 值变化标 NOT MECHANICAL/semantic_change）。
