# OPS-RULE: eval Chrome Profile 清理规则 v1

- 设立日期: 2026-10-14
- 工具: `scripts/clean_eval_chrome_profiles.py`
- 适用范围: 本工作区 `evals/` 与 `data/browser_mount_test/`

## 背景

browser_smc 系 eval 每个 run 会物化一个独立 `chrome-profile/` 目录
（路径形如 `evals/*/results/<批次>/<NN-task-rN-variant>/chrome-profile`），
单个几十~几百 MB，多次迭代后累积可观。结论数据（同目录 `worker-result.json`、
`results/` 下的 JSON）与 profile 是分离的，profile 删除不影响结论。

## 现状基线

- 2026-10-14 实测: `evals/` 下 chrome-profile 目录数 = 0（rglob 全深度核查）。
- 本规则自基线起生效，规范后续 eval runs 的清理。

## 规则

1. **唯一清理入口**: 只允许通过 `scripts/clean_eval_chrome_profiles.py` 清理，
   **禁止手动 `rm -rf` 任何 chrome-profile 目录**。
2. **触发时机**: eval 收官或结项、结论数据已固化之后执行一次；磁盘紧张时可提前，
   但必须保留仍在分析中的 run 的 profile。
3. **两步流程（强制）**:
   - 先跑默认 dry-run，审查待删清单与体积；
   - 确认清单合理后加 `--apply` 执行。
   ```bash
   python scripts/clean_eval_chrome_profiles.py                 # 1. 预览
   python scripts/clean_eval_chrome_profiles.py --apply         # 2. 执行
   # 可选: --min-age-hours 2   排除 2h 内活跃/新建的 run
   ```
4. **保护边界（不可绕过）**:
   - `data/runtime/` 下任何路径一律不清理（活跃 provider profile 所在），
     该保护不因任何参数改变；
   - 脚本只删 `chrome-profile` 目录本身，结论数据一律不碰；
   - 被进程占用（pgrep 命中）的 profile 自动跳过，不得强行删除；
   - `data/browser_mount_test/` 默认不清理，需显式 `--include-mount-test`。
5. **执行后验证**: `--apply` 后重跑一次 dry-run，确认待删数为 0；
   抽查同目录结论 JSON 仍在。

## 记录

| 日期 | 动作 | 结果 |
|---|---|---|
| 2026-10-14 | 规则设立；脚本交付并验证（防护/占用检查/apply 均实测） | evals 基线 0 个 profile |
