# 审批申请 — Rule28 限定入口 Web-only Canary

**申请状态：PENDING USER AUTHORIZATION（尚未授权、没有生产动作）。**

## 1. 可交付候选

- 当前 `main` 基线：`c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`，生产 Web/Feishu/Learning 尚运行该代码。
- 收敛隔离分支：`fix/rule28-jev-converged-20261015`，已审源码提交：`604592a243080bc4bb366853764992114605840b`；完整补丁 SHA-256：`dced89e9733fb289cfbdea0d04407d6da9041fbb6358ddb27b598da2d054af0f`。
- 采用 Jev 专项已提交 `c0f577d181bb677109b7ced2b3474a5b1e87eedf` 的 `wire.py` 完全一致 blob，且保留 Rule28 两项历史测试修复。新独立 GLM-5.3 Reviewer PASS、P0/P1=0；新原生 full R9 exit0，**8959 passed / 146 skipped**。
- 正式记录：`docs/results/RESULT-20261015-rule28-jev-convergence-r9.md` 与 `docs/governance/receipts/RECEIPT-20261015-rule28-jev-convergence-r9.json`。

## 2. 请求用户批准的准确操作（必须全部满足前置条件）

1. **代码合并范围**：仅在当前 `main` 与已审目标之间没有新的未评估漂移、在最终合并树成功重复独立 GLM-5.3 审查和**原版完整 R9**后，允许将本分支已审核代码和审计文档**本地受控合入 main**。不授权 push 到远端。
2. **发布范围**：只允许执行**一次 Web-only** 受控 canary 代码发布与必要的 Web 服务重启。**Feishu/Learning 运行代码、进程、Learning 队列不动**；用户未授权其他通道推广或全平台重启。
3. **执行前核验**：重新冻结 Git SHA；查 Web live generation/commit/PID/配置身份、活跃会话、子代理、未结算工具动作、任务生命周期和旁路工作树状态。存在不可安全中断的任务则暂停，不抢占或强行 kill；先证明旧 Web release 可以一键受控回滚。
4. **观察与用例**：保留登录、发送消息、工具调用、正常定向测试与代码编辑能力。只用临时试验仓库、模拟副作用和**私密未公开**文章草稿测试，未审 full test / 已识别 git push / 明确 Publish button 是否在物理派发前拒绝；取得真实独立 Reviewer 的资格后能放行**一次**，文件或文稿 SHA 改动后失效。**不进行实际远程 git push、真实公众文章发表或破坏性外部动作**。
5. **止损与回滚**：身份不符、独立 Review/R9 不合格、Provider 连接或 Schema 异常、误拒普通工具、审核放行越权、Web 错误率上升或无法回滚时立即 NO-GO；若已经 Web-only 切换，则按冻结的旧 release 身份回滚 Web，不影响其它服务，并记录回执。

## 3. 不属于此次授权的事

- **不推送远端，不执行真实 `git push`；不对外发表真实文章；不更新 Feishu、Learning，不自动切换所有用户和所有模型**。
- 不宣称已对 DSH 独立进程、任意 shell/API/CDP、含糊 Submit 或非 click 发表实现硬阻断；只验证已识别物理入口。
- 本次批准不成为未来主分支提交、Provider 真实发布或多通道重启的一揽子持续授权。

## 4. 需要用户的明确回复

建议授权措辞：

> **授权 Rule28 限定入口 Web-only canary：允许在最终合并树独立审查与完整 R9 通过、在跑任务可安全切换且回滚可用时，本地合入 main 并执行一次 Web-only 受控发布/重启及私密正反验收；不 push、不重启 Feishu/Learning、不真实远程推送或公开发表，异常立即停止或回滚。**

如无法满足上述任一先决条件，自动保持未发布，必须如实说明阻断，不能将条件性授权解释成强制部署。
