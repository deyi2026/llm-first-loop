# AgentPilot v1 治理记录（GOVERNANCE.v1.md）

- 记录时间：2026-09-12 20:2x（+0800），本会话（llm-first-loop）在用户授权"按你的想法继续"（20:20:06）下执行治理核查与拆分裁决。
- 对象：workdir `/tmp/agentpilot-v1-formal-final-20260912/`（下称 sealed workdir）。
- 完整哈希原文见 `SUPERSEDED.json` / `invocations.jsonl` / `manifest.json`，本文引用一律用 8 位前缀。

## 1. 冻结事实
- manifest 18:33:02 冻结（mtime 未再变化）；seal 记录 freeze_sha `d12c7339…`、plan_sha `570be8c6…`，三次 invocation 一致。
- lfl 侧 commit `b8e6dd11`（manifest 固定）；runner 冻结快照 `.formal-v1/`（4 文件只读）。
- 数据：`results.jsonl` 108 行（548,947 B）；`invocations.jsonl` 3 条执行记录。

## 2. 时间线（+0800；来源：invocations.jsonl / mtime / SUPERSEDED.json / git）
| 时间 | 事件 |
|---|---|
| 18:27 | `.formal-v1/` 代码冻结快照 |
| 18:33:02 | manifest 冻结（freeze/plan sha 定稿） |
| 18:42–19:50 | 执行窗口 |
| 19:20:05–19:29:21 | invocation#1（rows 55–72），自然结束——**封盘前最后一段，合规** |
| 19:22:48 | SUPERSEDED 初标（@60 行，shard 5 进行中） |
| 19:24:32 | 修复提交 `48c31bca`（含回归测试）落在分支；冻结 runner 未更换——**符合纪律** |
| 19:30:03 | SUPERSEDED 终标 @72 行（`runner_natural_end_observed=true`）；处置条款：不允许再追加任何行；新 runner/新契约需另起 workdir 从 index 0 |
| 19:33:53 | invocation#2（rows 73–90）——**违反处置条款** |
| 19:42:57 | invocation#3（rows 91–108）——**违反处置条款** |
| 19:49–19:50 | results.jsonl 定稿 108 行；summary.md |
| ~19:54 | handoff 热卡描述越界续跑+撰写 REPORT.v1.md（嫌疑 lineage：gate4 / MCP Console） |
| 20:0x | REPORT.v1.md（n=108）写于仓库，未附治理披露 |

## 3. 本会话核查证据
1. sha256(results.jsonl 前 72 行) == seal 记录 `b7d131a3…` → **封盘 72 行逐字节未改**；
2. 三条 invocation 的 freeze/plan sha 完全一致 → 越界两片用同一冻结 runner，**无协议漂移**；数据纯追加；
3. t12 原始字段：lfl session-resume sid 连续性 3/3 `true`；da `resume_session=""` ×3（honest workspace-recovery）；cline 3× `unsupported-headless-resume`（时长 None，无伪时延）；
4. 分类器缺陷定位（冻结代码）：`run_pilot.py` L405 双前缀写 `resume_resume_semantics` vs L427 单前缀读 → cline UNSUPPORTED 被存储层误标 INFRA_FAIL；**原始语义字段完好**，报告层重映射即得真值；修复=`48c31bca`（+62 行测试）；
5. 封盘理由#2（GLM auto-mode effort 契约）对应修复真实存在：`2b80f1f7`（client.py 28 行 + 测试 6 行）；平行分支 `fa90bec4` 与其 `src/` 内容**逐字节一致**（纯冗余，弃用）；
6. 拆分统计（§5）：两段经验一致，支持 post-36 作旁证而非正式数据。

## 4. 违规与范围
- **V1（数据层）**：19:33:53 / 19:42:57 两次 invocation 追加 rows 73–108（36 行），直接违反封盘处置条款。
- **V2（报告层）**：REPORT.v1.md 以 n=108 发布且未披露封盘与越界续跑，其完整性声明建立在未裁决的治理违反之上。
- **未决**：两次越界 invocation 的作者身份与用户授权链。handoff 卡与 gate4 提交作者（MCP Console）构成强指向，但本会话未能独立核实授权事实。

## 5. 拆分统计（sealed-72 vs post-36）
| 口径 | sealed-72 | post-36 |
|---|---|---|
| lfl | 24 PASS（t12 2 行，session-resume，sid 连续性 true） | 12 PASS（含 t12 1 行） |
| da | 24 PASS（t12 2 行，workspace-recovery） | 12 PASS（含 t12 1 行） |
| cline | 22 PASS + 2× unsupported-headless-resume | 11 PASS + 1× unsupported |
| 非 t12 PASS 时延中位 | lfl 16.1 / da 23.9 / cline 33.5 | lfl 15.1 / da 22.8 / cline 30.3 |

两段排序与量级一致（差距均在 1–3s 内），说明越界数据**质量上可信**，问题仅在授权与口径，不在数据本身。

## 6. 裁决（D=decision，本会话执行）
- **D1（拆分，方案 B）**：sealed-72 = **AgentPilot v1 正式数据集**；rows 73–108 = `post-seal continuation` 附录数据，仅作旁证，不并入正式口径。
- **D2**：REPORT.v1.md 头部追加治理披露横幅并指向本文档，随本次提交落库；在此之前该报告内部使用、不得外引。
- **D3**：integration 线整备完成：`b8e6dd11 → a334067a(freeze) → 48c31bca(修复) → 2b80f1f7(GLM)`（两次 ff，无 merge commit；工作区内容与冻结提交逐字节核验后操作，零信息损失）；`fa90bec4` 标记冗余。
- **D4（v1.1 接受条件）**：① 新 workdir 从 index 0，永不复用 sealed workdir；② runner 基于 `48c31bca+`；③ GLM 契约显式决定并记入 manifest（默认采用 2b80f1f7 后语义）；④ FCR 遥测统一契约；⑤ 保留 Latin-square；⑥ 首个对照臂建议 upstream-MLX runtime A/B。
- **D5**：sealed workdir 附 `SUPERSEDED_AMENDMENT.md` 记录本拆分裁决；workdir 物理保持 108 行现状，定性见 D1。

## 7. 未核实事项（诚实边界）
- 越界续跑会话的用户授权链（嫌疑：gate4/MCP Console lineage；证据为间接）；
- GLM 契约变更的运行时 smoke 未做（v1.1 前置）；
- 8901 research runtime 在执行窗口内的 cache/负载快照未留存（仅报告口径）。
