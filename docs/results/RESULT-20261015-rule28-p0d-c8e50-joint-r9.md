# RESULT — Rule28 P0-D c8e50 最新 main 联合资格与 Web-only canary 前置条件

日期：2026-10-15。

**阶段结论：`DEVELOPMENT_QUALIFIED_AWAITING_EXPLICIT_RELEASE_AUTHORIZATION`。原生 full R9 PASS；全域生产三闸仍 NO-GO。**

## 1. 隔离源代码与并发边界

- 在提交 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac` 的**干净且不含 Rule28**的 main 已提交快照上创建唯一隔离 worktree/branch：`fix/rule28-main-c8e50-joint-20261015`。由 P0-C 已验收源码 `7e6cf1134` 逐文件移植，不反向覆盖 Jev/Rule31/其他 Agent 的未提交内容。
- 包括 bounded Host admission、Runbook、入口覆盖审计、真实大补丁审查容量修复，以及上游 Jev Pyright 类型修复，**总共 26 个文件**。
- **本地源码提交 `f5219e21d5360383fef5adbbae74fa40aac33ded`**。冻结 `git diff HEAD^ HEAD --binary` 的 SHA-256：`accd3bd8ac1ddd35caf46cdd9d5a10dd0d334fe11bd55bcd06d750aceb38466d`，169,283 bytes；与新 Reviewer 完整输入二进制指纹一致。本轮 `main` 在集成、独立审查和 R9 期间均保持 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`。

## 2. 大补丁审查能力：事实先于放行

- 只读实测真实 22 文件集成源码约 153KB 的完整 `_source_snapshot` 被旧 128KB 上限拒绝（`review_artifact_exceeds_128kb`）。这使得正常代码任务无法启动真正独立审核，不能把“有规则但无法得到有效审查”视为可用。
- 最小修复把**整份材料硬上限改为 192KB**，155KB 正例可见**全部代码**，193KB 反例拒绝，保持敏感文件/单文件大小/最多 40 个 untracked 文件、`--no-textconv` 和 `--no-ext-diff`。这不是无上限扩容，也不授权截断或摘要当作完整 Reviewer。
- 真实集成树的新 `_source_snapshot` 已通过，完整材料大小按 `coverage-witness.json` 的现场证据记账。

## 3. 真实物理入口覆盖探针：确认未覆盖范围，不增加普遍限权

Provider-free 的离线探针 `data/rule28-p0d-qualification/coverage-witness.json`，SHA-256 `815648a45dd017b1c3a0647647357dbef7926c6034bb34d499d1516d1ee66724`（**没有启动真实 DSH / git push / CDP / 外部发表**）：

- `ToolRegistry.execute -> execute_command:pytest -q` 真正返回 `E2_REVIEW_ADMISSION`，fake shell dispatch 次数 0。
- 另一路 `dsh_task` Fake 任务在 Registry 内被执行，但 **HostReviewAdmission.check_shell 没有因 DSH 自动再调用**。这只证明 Rule28 审核门**不向 DSH 子进程透传**，不等于证明真实 DSH 可绕过它自身独立的安全/权限机制。
- 文稿编辑器下明确 `Publish` click 被阻断；`Submit` 语义含糊、fill/非 click 不受本文章审核分类器保护。无法由字面规则安全覆盖所有平台的发表/表单提交入口。
- 现行 `retry_tool` 经过 `registry.execute`，仍继承 direct `execute_command` 审查入口；普通定向测试、只读、编辑/学习工具不机械阻断。
- 更广覆盖应在 DSH 下游真实不可逆执行器、明确的网页文章提交、外部 API 效果边界建立独立审核与权限，不靠通用 prompt、“只提醒不阻断”或过度禁止所有工具模拟硬安全。

## 4. 真实最新 main 的 Jev 类型基线缺陷（已由干净 main 证明）

- 先在**从 main c8e50 单独 detached 的完全干净工作树**运行原版 Pyright ratchet，真实 exit 1、historical 45/current 24/**new 5**、touched 0；全部在未被 Rule28 修改的 `src/llm_loop/knowledge/jev/wire.py`。原始日志 SHA-256 `02f7b9a0e742ce95016c1d4d668ffacc80b1e0fc32dcf267a78150b104715adc`。
- 只在本隔离候选对 `wire.py` 的概率 `sum`、值映射、choice/score confidence 返回前补 `isinstance(int|float)` 类型收窄条件，维持既有数值范围、bool/NaN/null/非法协议拒绝语义。增加 `test_jev_wire.py` 相关异常数值用例，没有改变实时 Jev Provider 或策略逻辑。
- Jev 类型修复后 Ruff、Pyright 再次全部 **new 0/touched 0 PASS**；环境声明扫描 862 测试文件 PASS。联合 Rule28 + Jev/Knowledge 定向测试 **373 passed**（日志 SHA-256 `7df05c9a0590ba674ae0875114020f3d88d1a405ea29adbf47b2ea5d506ba1bb`）。
- 该修复属于新 main 本身已有的联合验收阻断，后续如 Jev 维护者独立修复，应对新提交核对语义而非直接覆盖。不能把曾经的 clean main 静态红伪装为 Rule28 改动导致。

## 5. 真正独立 GLM-5.3 Reviewer

- 实际 child `subagent_5def8a81bb64`，唯一 EventStore terminal `d404484c-c403-429f-99db-8a0e426ca52e`、status completed、`review_isolated=True`，parent `review-parent-rule28-p0d-c8e50-main-joint-a1-20261015`，没有代理父会话 steer 权限，审查中不开放工具。
- Reviewer 输入包含上述**整份 26 文件补丁**，以及冻结的 Jev 新 main 运行时增量（SHA `a8ac796fb99834e1d9b4eadac565f0b27ab17e46efc8538df37448cf75aa0ab4`）与 Jev wire 全文（SHA `4d69a8379d3c28f7d27ee1a1570872694a2c9652521acc40be21056cd801aa57`）。这不是只对 Rule28 的旧十文件补丁复用 PASS。
- 独立审查结论 **VERDICT: PASS；P0=0，P1=0，P2=3；机器资格 PASS**，与 `accd3bd8ac1ddd35caf46cdd9d5a10dd0d334fe11bd55bcd06d750aceb38466d` 严格一致；原始 JSON `data/rule28-p0d-qualification/glm-child-review.json`，SHA-256 `3b366f3a045e2db428ffcabd103118ab4c3cbd80d5e90b2a3362fb03e2d106ef`，全文 SHA `054bda5d2e3c76221086cee1d0f930f02b19132e66546efafc588f49fd6da21d`。
- 三项 P2：pytest 分类器内不可达 return，离线测试模式下无 EventStore 可返回 True 的可见性，反复受保护命令会重新冻结 Git 快照的成本；**未宣称这些问题已修复**，不能以后据此放宽真实权限/审查。

## 6. 原生完整 R9，未跳门与无并发

- 单次原版 `bash scripts/ci_gate.sh`，真实 shell **exit 0**，运行前机械验证独立 child 唯一 terminal + P0/P1 零 + 精确 SHA，且当时无其它完整 CI 在跑。
- Ruff PASS、Pyright PASS、EnvPin 862 PASS、WebUI candidate 构建；Tier0 **319 passed / 8795 deselected / 3 warnings**。
- 4-worker xdist 全量 **8,952 passed / 146 skipped / 13 warnings**，没有失败或串行降级；guard report 1 passed。
- 原始完整日志 `data/rule28-p0d-qualification/native-full-r9.log`，SHA-256 `cb379550c8c40886c6a0b792625052fd3573d8059ebf0080eb8110823888bb60`；测试后补丁 SHA 与独立 Reviewer 完全不变。
- 全量执行仅导致**18 份历史 reports** 由测试重写；逐个确认精确白名单后保存二进制 diff `data/rule28-p0d-qualification/r9-generated-reports.patch`（SHA `fc8d107f90f49d383f29fcf9bf0c27f37be8819594b659fd54c7dce10c489f15`），仅对这 18 文件做 `git restore --worktree`，其它 Agent 资产及主仓 tracked 文件未动。

## 7. 当前生产事实与下一步的明确授权点

- 收口核验时 Web、Feishu、Learning 的 runtime manifest 都以 `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac` 为 live code commit、`identity_ok=true`，**未包含本 P0-D 隔离源码提交**。
- **限定入口的本地开发资格 PASS**，但**全域生产三闸仍 NO-GO**：DSH 下游真实效果、外部 API、模糊网页 Submit/非 click、任意动态 shell 及 OS 级防旁路尚未全部签发物理审核能力。
- Web-only canary 的预授权 Runbook 已在 `docs/RUNBOOK-20261015-rule28-web-only-canary-approval.md`；上线需用户新一笔明确许可，先合并目标 main 的最终版本、审查真实运行工具 schema/commit/PID/in-flight 子代理、用受控无破坏场景验证拒绝与一次性通过、可回滚。不得顺带重启 Feishu/Learning。
- 本轮 **未合并 main、未 push、未发布、未重启**。代码在新隔离分支本地提交，审计报告另单独提交。用户可以在完成下一阶段受控合并资格之后决定是否允许 Web-only 发布，不能把“继续”自动升级成长期生产权限。
