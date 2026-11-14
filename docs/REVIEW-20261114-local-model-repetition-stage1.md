# 本地模型重复/漂移 · Stage 1 代码级 RED→GREEN 候选

状态：**仅隔离候选；待独立 GLM-5.3 代码审查，未达 R9/发布门禁**。

- 设计：v0.5 独立 GLM-5.3 PASS（P0=0/P1=0/P2=1），冻结 SHA `96220978276263e6511bdc1e4ea0d00278f0398f7554d0ee3e955dd02c88dab1`。
- Goal：`96b13a77-8f83-4022-b2ad-b1c41ff2f876`；实施分支：`fix/local-model-repetition-presend-20261114`；起点：`9c3cc78a98ebf6754ba9ae9f2c701ffd0e671c37`。
- 原始 RED：101 有效工具、32,768 输出预留、28,659 工具 schema tokens、3,698 历史字符；第二次模拟 Provider 发送前丢失最新完整工具交换且无授权 exact-ref，测试 `1 failed / 1 passed`。
- GLM-5.3 单一开发代理：首版 patch 有效输出但 hunk 计数需 `git apply --recount` 规范化；第二轮修订 `finish_reason=length` 且零正文，未被采纳。验收方最小修正了“同 ID 内容变更误认完整”与“软预算误拦”。
- GREEN：在最后投影/重建后、Provider attempt 前核验最新同 Run 完整 assistant→tool 组的**调用名/参数与逐字原始工具回执**。缺失时复用现有无副作用 conservative rebuild，合法时投影真实原文；物理预算/协议不能安全交付且无合格 exact-ref 时，阻止第二次 Provider 发送，`run_incomplete=true`、`provider_sent=false`，不自动重发工具。
- 负向：缺失/截断/改写内容、改参、重复/不完整 ID、跨 Run 旧组、假 evidence://；正向：正常首轮、双工具配对、变化轮询、低软预算下合法 search_archive 恢复。
- 专项：`211 passed`，Ruff 0 错误，Pyright 0 错误；命令/文件 SHA/日志 SHA 见 `docs/governance/receipts/RECEIPT-20261114-local-model-repetition-stage1-GREEN.json`。

## 仍未完成，严禁提前发布

1. **P1 候选缺口**：owner/version/权限/分页核验的 exact-ref **模型可见投影尚未实现**。目前超大工具结果无法原文容纳时会安全 HOLD，不能宣称生产重复问题已完全修复。
2. **独立模型身份核验**：事故请求 Ornith-MLX 名称与现有 `8901` Qwen GGUF 服务身份不一致，不能沿用 MLX 资格或直接改模型配置。
3. **门禁**：独立 GLM-5.3 代码 Reviewer PASS/P0=P1=0 → 原版完整 R9 exit 0 → CI → 经授权 main/push/受管发布；旧 M4-C 未决债务继续 HOLD。

**未发生**：真实事故工具重放、生产 Provider 推理、模型配置变更、main 合并、push、发布或重启。
