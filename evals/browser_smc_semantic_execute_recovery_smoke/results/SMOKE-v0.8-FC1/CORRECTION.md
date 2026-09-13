# v0.8-FC1 更正记录（追加，不覆盖原冻结证据）

原报告冻结提交 `02a00261`；运行源码 `2794b2cd`；通过率仍为 2/6，主 Gate 仍 FAIL。
本更正优先于 REPORT.md 中冲突的统计与归因。原 report/results/manifest/raw 均保留。

- `partial_checkpoint_count=265` 只覆盖五个写出 worker-result 的行。row4 原始日志另有 214 个，六行合计 **479**；v0.7 为 394。
- row4 第 8 轮有 162 个 partial，首尾跨度约 164 秒，未观察到工具草稿或派发；按已有 scorer 定义 `partial_only_loop_rounds=1`。D 的 partial-only 类已出现；这不等于批准 watchdog 或自动重放。
- row4 有成功 navigate 终态回执，故 navigate_ok 是 **6/6**，不是 5/6。
- 五个正常结束行 surface exact；row4 启动 surface 未独立落盘，覆盖为 unknown。`infra_valid=false` 的直接原因是 Gate 排除 TIMEOUT；补观测不改变 TIMEOUT 的 Gate 失败语义。
- 归一化的独立终态动作按行计数为 **1/1/1/1/3/1**，合计 8；文本出现 4–10 次不等于独立应用次数。FC1 在六行真实生效的结论保留。
- args_normalization 元数据覆盖 ActionReceipt；compiler 的 invalid_ref 拒绝路径不返回该 JSON 字段，不能宣称 every rejection 均覆盖。
- row1/6 各有一次未解决拒绝后的 wait；最终导航恢复成功不等于全程遵守 A 恢复合同。
- 跨 v0.7/v0.8 成功集不相交只支持补同处理 repeat，不能独立证明随机方差或因果收益。

可复算附件为 `CORRECTION.json`；仅记录机械计数与 exact source SHA256，不包含私有路径、原始推理或页面正文。
复算命令（在仓库根目录）：

```sh
.venv/bin/python evals/browser_smc_semantic_execute_recovery_smoke/audit_observations.py evals/browser_smc_semantic_execute_recovery_smoke/results/SMOKE-v0.8-FC1 --output /tmp/fc1-correction-recomputed.json
```

下一步：独立补超时观测 → 同基线 12 轮 repeat → 16 轮 diagnostic → FC2 实现裁决 → A3。
当前三字段合同不批准从裸 URL 自动补 page/resource_ref/version；保持 ref-shape recovery receipt。
