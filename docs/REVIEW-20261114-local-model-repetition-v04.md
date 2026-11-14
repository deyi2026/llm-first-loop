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

## P0-A 只读证据补充（2026-11-14，设计正文 v0.4 SHA 不变）

可机读回执：`docs/governance/receipts/RECEIPT-20261114-local-model-repetition-P0A-offline.json`。
本次对事故 EventLog 2,509 行、SHA256 `01ca4d749bed93d80640dd53cfbb040bb394fa4e0c77cb3bc1318e286089a556` 与有效 Provider 文件 SHA256 `790e9429f1d0c8d24e89466b6106c72a02cb2d19468cf21c59b23defdf649a6f` 精确校验后，取得以下事实：

1. **模型身份合同存在实际不一致**：事故 `request.meta` 记录 `cognilocal/ornith-ai/Ornith-1.5-35B-A3B-MLX`、`max_tokens=32768`、`temperature=0.0`、`wire_protocol=openai`。相同 Provider 文件将 `cognilocal` 路由到本机 `8901`。当前监听 `8901` 的进程为 `llama-server`（启动时间 2026-10-22 09:04:56），`-m` 指向 GGUF 文件 `Qwen3.8-Flash-Next-UD-IQ3_XXS-00001-of-00003.gguf`，`--alias=qwen3.8-flash-next`，`-c=65536`；只读 `GET /v1/models` 返回且仅返回 `qwen3.8-flash-next`。这对「事故使用 MLX 后端」构成强反证；但没有事故时的 `/v1/models` 截图或权重哈希，不能冒充精确历史线包证明。
2. **事件级 RED 可复核**：首 Run 8 轮 `request.meta` 的 `provider_structure_fp=de0a18705a0240c813b0044e`、`messages_count=2`、`tools_count=101` 完全相同。前 7 次工具回执均有合法 assistant→tool 配对、先追加再归档，并在下一请求前被压缩；这些请求的 `messages+tools` 结构指纹与**第一次工具调用前**的请求相同。由此支持「最新回执未交付到下一轮最终模型结构投影」，**不等于**已捕获实际 HTTP 请求字节。
3. **原始证据可恢复但未交付**：7 条 `evidence://` 引用均能按原会话 owner 从现有 `EvidenceLedger/BlobStore` 精确水合，blob SHA256 均通过；跨会话 owner 读取被拒；`ArchiveStore` 也能按 `tool_call_id` 找回完整工具消息。注意：Evidence blob 只覆盖原始工具输出（本例 3902 字符），事件消息另有包装和提示（3916/4005 字符），**不能将 blob 与完整 tool-role 消息说成逐字节相同**。没有证据证明这 7 个恢复 ref 已进入下一次 Provider 视图，也尚未证明事故时 101 个工具 schema 实际包含 `read_evidence`。
4. **离线专项回归**：Evidence phase4、tool factualization、factory shadow 与 E1–E5 四组测试 `72 passed / exit 0`。它们验证当前实现的既有能力，不替代事故预算下的最终投影 RED→GREEN 或原版完整 R9。

**剩余 HOLD 项**：事故实际 HTTP 请求体/响应模型身份、事故时 101 工具是否暴露 `read_evidence`、事故时完整 effective config、最终投影是否有 raw/exact-ref，以及历史 GGUF 权重 SHA/运行资格。独立 Reviewer 必须据此判断 v0.4 是否仍可 PASS；若发现设计方向因模型身份错配需改变，应给出 REVISE，而不是机械签 PASS。

**执行边界**：本补充只读日志、现存证据、当前进程与本机模型清单；未发起推理、未重放工具、未改模型配置、未动业务代码、未重启服务、未处理旧 M4-C 债务。
