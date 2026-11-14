# LFL 本地模型重复/漂移 v0.4 独立设计审查与处置

- 日期：2026-11-14
- 设计正本：`docs/ANALYSIS-20261114-local-model-repetition-root-cause.md`
- 独立首审：`glm/glm-5.3`，零工具、单次真实 Provider 尝试、`finish_reason=stop`、`truncated=false`
- v0.3 冻结候选：`3d735072e7f7b51727be0eaa332b8140467a34ca`，文档 SHA256 `70389a9d2df4f5e368d2694e2b8878b4d8b1a9981e628c07e19ede6bfd8db8fc`
- **有效裁决：HOLD，P0=0/P1=0/P2=4**；12/12 对抗性设计检查由 Reviewer 判 PASS，但关键运行事实未全部资格化
- v0.4 修订候选：`fa78be9c646f36bf52efdecc50ba9a156fd162cd`，文档 SHA256 `747e074ba93dabbcd03e8d53e978aaae03f51d026a83abdf458cd0063310e483`
- **v0.4 尚未独立复审**。不能继承 v0.3 的审查结论，更不能把 HOLD 改写为 PASS

## 四项审查意见的最小处置

| ID | 意见 | 处置 |
|---|---|---|
| F1 | 冻结身份与候选绑定不清 | 采用本文件配套的外部 JSON manifest，绑定文档 SHA、Git commit、审查回执 SHA；不将文档自身哈希写入正文，避免自引用 |
| F2 | 历史初稿 P0/R1–R7 可能误导实施 | 第 3–5 节逐项 `SUPERSEDED`；固定 6000/8000 字符、四次自动断路器、关键词工具裁剪均不准实施 |
| F3 | 无进展指纹可能误拦合法探索 | 只作诊断；机械 HOLD 必须同时证明最终 Provider 视图缺失最新 raw/exact-ref 且合法容量/权限/版本路径不可用 |
| F4 | 重复提示放大器缺事故时证据 | 事故 Git tree 精确为 `103e9730...`；`tool_cycle.py:258–310` 回执尾注；EventLog `seq=85` 含提示、`87/88` 归档、`96` 下一轮结构回到 2 条消息 |

## 本轮额外核验

事故树对应的关键 `tool_cycle/history/history_projection/compaction_gate/routing` 文件与本地 main 无 Git diff；本地 `origin/main` 超前 3 提交仅涉及 `task_get` 同族文件，不包含本问题修复（只代表本地追踪引用）。

离线相关回归：**105 passed，exit 0**，包含 E1–E5、convergence、stagnation、antidrift、working-set projection、ingress、recent continuity 和 reasoning-tail。未运行原版完整 R9，也没有执行真实事故 Provider/Tool 重放。

## 下一阶段准入

先只读核对实际后端/模型身份、最终 provider-visible 请求和 exact-ref 可恢复性；随后对 **v0.4 精确 SHA** 发起新的独立 GLM-5.3 审查。只有真实 PASS、P0/P1=0 后，才在新的隔离实施工作树进行最小 RED→GREEN 修复。任何代码变更还须再次独立审查、原版完整 R9 和远端门禁。M5 Goal、旧 M4-C 债务、主工作树、研究仓、生产配置、服务重启均不属于本轮变更范围。

完整可机读绑定见 `docs/governance/receipts/RECEIPT-20261114-local-model-repetition-v04-design-review.json`。
