# 代码审查回执：S15 30ms 时序断言 → 结构性断言（方案B）

- 审查人：GLM-5.3 独立审查子代理 `subagent_3aa04901993f`（未参与产出；产出方为 `subagent_3b3602f5c0a7`）
- 日期：2026-10-27
- 被审产物：worktree 未提交 diff，`git diff tests/unit/test_semantic_resource_safety.py | shasum -a 256` = `bb9441f57ca3cae9c6aca27719522a62e5f4c3b59fb68932a010fec76df4bac9`；基线 HEAD `7dade3de4`
- 范围：单文件 +42/−4，仅测试，不改 src

## Verdict: PASS

## 审查发现
- P0：无。
- P1：无。
- P2（非阻断，3 条）：
  1. `tests/unit/test_semantic_resource_safety.py:91` 的 gate 用 `assert self.release.wait(5.0)` 承担控制流，`python -O` 下会被剥离、gate 退化为直接放行。**决定不采纳**：pytest 与 CI 均不以 `-O` 运行，该文件所有断言在 `-O` 下同样空转，非本改动引入；采纳会使已 PASS 的产物指纹失效并需重新窄复审，收益不抵成本。记录留痕。
  2. 若真回归形态为"save 路径同步调 embed_batch 并等待"，终局拦截仍必红，但经由 `_wait_background` 超时兜底，失败消息不直指"save 等待了后台"，且先挂约 7s。**接受**：拦截力未丢失，属可诊断性折扣，不阻断。
  3. 原 `save_ms < 30` 意外覆盖的"save 总耗时"侧面改写后无守卫。**接受**：该侧面从来不是本测试既定意图，且 30ms 已被 CI 实证为负载敏感伪阈值；如需通用延迟哨兵应另立显式测试。

## 核心争议结论（是否弱化断言）
否，是强化。原 `save_ms < 30` 只测机器负载、对最快真回归形态（同步向量化 ~20ms）完全失明，CI 43.27ms 失败恰好证明这点；新三元组断言直接证明"后台已启动且 save 未等待它完成"，把概率性代理变为确定性证明。

## 验证证据
- 审查者实跑：串行 16 passed、并行 `-n 4` 16 passed、目标用例 5 连过（各约 0.06s）
- 主控独立复跑：`.venv/bin/python -m pytest tests/unit/test_semantic_resource_safety.py -q` → 16 passed in 1.08s
- 确定性论证：`retriever.py:1686-1695` 锁内同步置 `_prewarm_inflight=True`，先于返回；`archive.py:280-287` hook 在 archive() 返回前同步调用；gate 未释放前 `returned` 必为 False，断言 (b) 无 flaky 窗口

## 授权边界
- 本轮仅授权执行用户选定的方案 B（改写断言）。push 另行经 push 闸与 Host 准入。
