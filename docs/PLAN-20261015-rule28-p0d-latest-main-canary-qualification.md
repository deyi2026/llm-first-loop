# Rule28 P0-D：c8e50 main 联合验收、覆盖事实及上线资格

日期：2026-10-15。状态：**隔离候选**；不是生产发布授权。

## 1. 事实与源代码

- 冻结基线是 `main=c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`，此版本已包含 Jev/Knowledge 的 6 个新增提交，不需要回退或覆盖任何其他 Agent 的变更。
- 从上一阶段已经独立审核并经原生 R9 验收的 `7e6cf1134`（P0-A/B/C 合一源码提交）逐文件无冲突移植 22 文件，原始 P0-C 补丁 SHA-256 = `ef0b15dbdbbf10cd6011adf46b7e333616a897cf7ab1e3e6370a415e00bbbca1`。
- 只使用新隔离工作树 `fix/rule28-main-c8e50-joint-20261015`；绝不直接写主工作树、Rule31/Jev 工作树或运行中的服务。后续额外 P0-D 文件及容量修复必须重新冻结 SHA 并由**本阶段**的独立 Reviewer 验证；不能复用旧 PASS。

## 2. 发现的真实阻断：128KB review cap 对集成候选误拦

- 旧 Host `_source_snapshot` 的 `review_artifact_exceeds_128kb` 在真实 22 文件候选上确实触发，导致**即使代码符合规则也不能启动独立审核或完整测试**。原始 staged 差异 152,674 bytes，完整 Host 材料约 153KB；这是可复现的执行能力缺口，不是 Reviewer 不合格。
- 最小修复：完整材料上限升至 **192,000 bytes**，**保留硬拒绝、敏感路径过滤、no-textconv、绝不截断与单次独立审核**。测试 155KB 完整材料正常可审核，超过上限的 193KB 材料拒签；原有敏感单文件 200KB 上限不放宽。
- 192KB 并非无限长度审查能力：更大变更仍要拆分候选，或另行设计可校验的完整分段 Reviewer 审计；不能把摘要当作整份完整审核，也不能依靠静默增大模型预算保证弱模型可完成。

## 3. Provider-free 的实际入口探针（零副作用）

证据：隔离运行数据 `data/rule28-p0d-qualification/coverage-witness.json` 与 `physical_entrypoint_probe.py`。测试只构造 Fake shell / Fake DSH，不启动真 DSH、不执行真 git push / pytest、不连接 CDP / Provider。

| 入口 | 实际结果 | 资格边界 |
|---|---|---|
| Registry `execute_command` → 未审全量 pytest | `E2_REVIEW_ADMISSION` BLOCKED，fake shell 调用次数 0 | 实体 shell 派发前生效 |
| Registry `dsh_task` → 独立 DSH agent | Fake DSH 正常经过其工具调度；**Rule28 check_shell 未调用** | 不证明 DSH 能绕过其自身权限政策，只证明 Rule28 的 Host 审核不能随 DSH 进程自动透传 |
| Browser 明确 `Publish` 且有文章编辑器 | 未审被 Host 阻断 | `BrowserActionAdapter` 的确切 click 边界 |
| Browser 模糊 `Submit` | 未纳入 Rule28 article gate | 不能不看站点语义就把任意 Submit 都当发表，否则误拦合法表单 |
| Browser `fill` 等非 click 动作 | 未纳入文章发表判定 | 不等于任意平台的 Enter、Form submit、HTTP、CDP、外部 Publish 已获保护 |

既有 P0-C 提供真实 Fake actuator 的正反物理派发测试：明确发表无独立审核为零 dispatch；通过真实资格后仅一次 dispatch；普通 UI/定向 pytest 不误拦。`retry_tool` 通过 `registry.execute` 间接执行 `execute_command`，不会重建无审查的独立 shell 入口。

## 4. 面向 Agent 能力的设计选择

- **不通过对 DSH、未知脚本、网页 Submit、普通文件编辑全局禁用来伪造百分之百覆盖率**。这会严重降低模型工作能力，并且不能机械证明阻断全部可能的真实副作用。
- 如果后续确需声明“所有实际 push/完整测试/发布都被硬审核”，应分别在 DSH 执行侧 Git/测试/发布真实副作用边界、受控浏览器提交/页面导航边界和外部发布 API 层建立可验证的 ReviewAdmission 合约，保持用户授权、作业租约和独立 Reviewer 三者互不替代。未知副作用类型维持明确的安全/权限约束，不对正常辅助工具做不必要的语义限制。
- `service_control publish` 是**代码发布**，不是文稿发表：应由既有服务发布权限控制，而不是拿文章 Reviewer 覆盖。任何通道的真实 Git push 还必须有用户授权与独立 Push Reviewer，不因为 code-review PASS 而默认允许。

## 5. 新 main 独立静态债证据与单文件最小修复

- 在 **clean main c8e50** 独立只读基线 worktree 运行原版 `scripts/check_static_diagnostics.py --tool pyright`，实际 **exit 1**：historical=45、current=24、new=5、touched=0；五项均为 Jev `src/llm_loop/knowledge/jev/wire.py` 的动态 JSON probability/confidence `float(...)` 类型推断缺失。Rule28 尚未合入时同样失败，因而是**上游已存在的联合门禁阻断**，不是 Rule28 回归。
- 只在本隔离候选将类型校验的已成立条件显式暴露给 Pyright：数值投影复用已验证的 int/float 且非 bool 条件，`_validate_choice`/`_validate_score` 返回前明确校验 confidence 类型；**不修改 Jev 的概率和、合法选项、NaN/null/boolean invalid 定义或真实 Provider**。
- 新增 `tests/unit/test_jev_wire.py` 中概率与 score 的异常数值、缺失 confidence 回归用例；Jev 专项 **105 passed**。重跑全树 Ruff/Env-pin/Pyright：**new=0, touched=0, PASS**；无 known-red 宽化，不用配置忽略错误。
- 此项是**附带且必要的上游兼容修复**，须作为与 Rule28 共审的准确变更记录。后续如 Jev 维护者在 main 自行收敛，须比对语义和新 commit 后决定是否还需要此单文件修复，绝不覆写其他 Agent 工作。

## 6. 联合验收、审查与退出准则

1. 最新 main 基线 + Rule28 来源校验、真实 192KB 闸正反对照、DSH/Form/命令假执行器覆盖探针、Jev/Knowledge 与 Rule28 联合定向测试；
2. Ruff/Pyright/env-pin、staged 安全扫描、无 unstaged 源码漂移；冻结**完整最终补丁** SHA 和已运行 Jev 修改摘要；
3. 必须取得独立 GLM-5.3 Reviewer 真实唯一 terminal completed、隔离身份、完整补丁准确 SHA、格式化 `VERDICT: PASS` 且 `P0=0 P1=0`；失败停止，不通过重用历史 PASS；
4. 仅在独立 Reviewer 合格、无其他 Agent 并行完整 CI 时执行仓库原版 `bash scripts/ci_gate.sh`，真实 exit 0、原始日志、无 known-red 基线宽化。对 CI 自生成的 18 份历史 report 仅经精确白名单归档并恢复；
5. 完成条件才本地隔离源码提交及第二个安全脱敏证据提交；复核提交差异 SHA、隔离工作树清洁及生产未更动。

## 7. Jev 两套并行方案的最终收敛依据（本阶段前向集成）

- 权威偏好：独立 Jev 专项分支 `fix/jev-wire-pyright-narrowing-20261015` 的 **2 文件、3,675 bytes、SHA-256 `b31c73f5d8da7d5d001253c10414e59801b1a60b1eeb858bfeb1924a913ed331`** 冻结补丁。它只增加 confidence/probabilities 的明确类型收窄，不改变概率求和及概率字典的投影代码；独立 GLM-5.3 的新 SHA 原生审查 `subagent_02e85983e7a7` 为 PASS（P0/P1/P2 均 0）。
- 上一版 Rule28 的 Jev 修订功能正确且完整 R9 通过，但用更大的类型过滤表达式改写了概率求和和字典推导；这属于**不必要的代码形式漂移**，即使合法输入下结果等价，也不作为收敛后的最终 Jev 代码。新的独立工作树只应用 Rule28 除 Jev 以外的 24 文件源码，以及 Jev 专项分支按 SHA 冻结的两个文件补丁；再补齐 `bool`、数值字符串、NaN、Infinity 的互补回归。
- Jev 专项分支自身的独立完整 R9 原始结果为 **8,850 passed / 146 skipped / 2 failed**；失败定位在 `test_backup_store_durability` 历史日期漂移和 `test_browser_attestation_v01` 固定端口占用，**不是 Jev wire 运行时失败**。恰好这两项测试修复已存在于 Rule28 的 24 文件组合中。不得称专项分支自身全量绿，必须在**最终收敛树**独立审查并原版 full R9 才能获得统一资格。
- 不修改 Jev Agent 的仍被其持有的 worktree、不覆盖其未提交文件、不替它签发 R9 PASS；本收敛候选如与它后续自行提交的最终方案发生版本差异，需重新核对来源和并发。
- 当前结论仍是**限定 Host 入口开发候选**，不是 universal Gate，也不是自动授权 Web-only 发布。

## 8. 两套严格不同的准入结论

- **限定入口候选 DEV-QUALIFIED**：上述四项验收完整通过，才能说“已识别入口的 Web-only canary 候选具备开发资格”。
- **全域生产三闸 NO-GO**：DSH 的真实下游副作用、任意 shell/第三方发布 API 和键盘/表单触发表达均没有完整证据，因此绝不宣称任意动作可由 Rule28 Host 门控。最新 main 若又前进，须重新做并发冲突/联合测试资格。
- 生产 **Web-only canary** 需要进一步独立授权、最新 main 受控集成、部署前 in-flight 会话/任务检查、真实运行提交/PID/工具 schema 一致性、sandbox 中正反实体动作验证和 rollback；本轮**不合并 main、不 push、不发布、不重启**。
