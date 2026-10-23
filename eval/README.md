# Agent 评测体系

建立日期: 2026-10-14。承接三步计划: T1 回归基线 → T2 真实评测 → T3 研究型专项。
Goal: GOAL-20261014-9377455f (durable, 跨会话)。

## 纪律 (第一行代码之前生效)

1. **回归集版本锁死**: terminal-bench-core==0.1.1 + terminal-bench==0.2.18 (uv tool, Python 3.12)。
   升级版本 = 新基线, 不与旧基线混比。
2. **小子集先行**: 任何新基准先跑 3-5 题估成本/时延, 再放量。
3. **T3 holdout**: 研究型专项库自建任务, 30% 私有 holdout 在首次划分时即锁定并记录划分哈希;
   holdout 题目与答案不进入任何调参/开发回路。规则详见 rules/holdout.md (T3 时落盘)。
4. **结果落盘**: 每次运行存 results/<date>_<bench>_<model>/, 含命令、逐题结果、总分。

## 目录

- baselines/  基线快照 (可复现命令 + 结果)
- results/    每次运行的原始产物
- rules/      holdout 等纪律文档
- logs/       长时后台任务日志

## 环境事实 (2026-10-14 核验)

- macOS (arm64), Docker 29.4.0, uv 0.13.1, terminal-bench 0.2.18 @ ~/.local/bin/tb (未入 PATH)
- 待测模型主通道: glm-5.3 @ https://open.bigmodel.cn/api/coding/paas/v4 (OpenAI 兼容, GLM_API_KEY)
- agent: terminus-2; 接法: -m openai/glm-5.3 -k api_base=<端点>, OPENAI_API_KEY=<GLM key>
