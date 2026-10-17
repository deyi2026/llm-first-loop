# LLM 120 秒超时恢复修复（2026-10-17）

状态：四文件独立代码审查PASS（未解决P0/P1/P2=0）；原版完整R9退出0（遵循原有serial复核策略，详见下文）。尚未合并main、推送、发布或重启；main仍有其他Agent活跃未提交修改，等待合并审查正式裁决。

## 实际故障与结论

- 事件源：`data/event_logs/881d9c3f-2c5a-47a8-b605-9596af0a61b1/2.jsonl`，只采用 2026-10-17 09:15:55+08 的 `program.final` 之前同一失败调用，不混入同会话后来新 run。
- 失败调用：`pcall:ac352b456d335bfdd124be943a36b392`，GLM-5.3/OpenAI-compatible，round 184，385 messages，provider-visible 546752 chars。
- 真实请求 timeout_s=120.0；09:13:54 发起，09:15:54 `ReadTimeout`，transport elapsed 约120.28秒；正文/推理/工具草稿均为零，未产生首分片；transport_retry_index=0。
- 已落 `provider.transport.settled(error)`、`provider.call.settled(error)`、`llm.interrupted`、`program.final(answer_origin=program)` 和 `run.end(reason=llm_error)`。此样本是本轮终止，不证明 Web 输入锁永久卡住。
- 主进程快照为 release b68dbc2a53c87295c7f160502795a4bd26f2f91d；现有 .env 与实际请求均为120秒。没有证据证明 Key、模型名错误，也不能单凭上下文长度区分网络等待与 provider 排队/处理耗时。

## 最小改动

- 仅实际故障协议 OpenAI-compatible：零 provider 输出的 ConnectTimeout/ReadTimeout 与现有断连共用 `retry_disconnect` 总次数（默认重试1次；0关闭）。同一模型、原payload、不增加程序恢复prompt、不重新跑整轮工具。
- 任何原始正文（含尚在think parser缓冲的内容）、推理、opaque reasoning details 或tool delta均阻止自动重发。
- WriteTimeout、PoolTimeout、总流deadline、任务预算拒绝/取消均不变为可重试；异常后先检查已建立的deadline，不能因最后一次read超时重新计时。
- 复用现有run/generation取消权威和child Stop；取消权威读取失败不授权重试；ConnectError退避结束再核对Stop。
- 每次物理attempt保留原有opened/settled及parent lineage；错误attempt不因随后成功被擦除。
- 超时反馈单独说明本轮结束，保留原异常；不把超时误诊为Key/模型名错误；提醒在当前会话继续前核对已有工具结果。

## 验证与审查事实

- 原始新增回归：4 failed / 8 passed，证实超时无恢复及误导反馈。
- 独立审查发现raw details/think缓冲/过期deadline三项P1，新增反例3 failed / 12 passed，修订后通过。
- Stop三反例真实3 failed / 16 passed；ConnectError退避期Stop反例真实1 failed；均已局部修复。
- 最新新增回归20 passed；上一轮邻接182 passed；架构33 passed；Ruff和定向Pyright通过。最终完整R9需有效独立PASS后执行。
- 宿主独立Reviewer `/root/timeout_code_review` 未参与开发，不冒称GLM-5.3；一次额度不足终止不构成PASS；恢复后已对最终候选真实PASS。回执：`docs/governance/receipts/RECEIPT-20261017-llm-timeout-independent-review.json`。
- 隔离分支 `fix/llm-timeout-recovery-20261017`，base `41f500ecb92c7aea881d8e15809194187b7b1dd3`。
- 最终四文件指纹 `346563ad78647bbb7556ac04c5e18c61aab1c86355b471edf4979a0bf16408f5`（依次path+NUL+sha256+LF合成），文件：`src/llm_loop/llm/client.py`、`src/llm_loop/feedback/honesty.py`、`tests/unit/test_timeout_recovery.py`、`tests/integration/test_fault_isolation.py`。

## 后续优化建议与未完成范围

1. 将existing transport attempt事实呈现为“同模型重试中/已等待时长”，区分provider失败与SSE断线续收；不得把程序进度注入为模型回答。
2. 基于首分片、read idle和total stream延迟分布再评估GLM专属超时；本次没有放大或关闭全局120秒，也未更换模型/裁剪输入。
3. 评估长会话provider输入成本须保留exact source及可恢复引用，与并行上下文治理任务保持边界；54.7万字符是事实，不是已证明的超时根因。
4. 待当前候选独立审查、原版完整R9、最新main集成审查通过后，办理受控上线；真实provider恢复率尚未验证。

## 最终验收结算

- 既有集成矩阵的Timeout分支已单独验证新反馈；其他类型继续严格要求原generic反馈。集成文件+新增回归35 passed。
- 第二次原版`bash scripts/ci_gate.sh`真实退出0：Ruff、env-pin、全树Pyright、tier0 319passed均通过。
- 全量xdist首轮9297 passed /146 skipped /1 failed：`tests/phase4/test_m2_inflight_interrupt.py::test_c_s15_race_two_branches`。原脚本串行复核该文件6passed/0failed，随后自带trace-leak schema扫描1passed，按未修改的既有策略放行。
- 并行波动已登记观察，不称本次修复了该race，也不称xdist全绿；没有修改门禁或守卫baseline。
- 全量回执：`docs/governance/receipts/RECEIPT-20261017-llm-timeout-full-r9.json`。原始日志在本任务ignored data目录并绑定SHA256。
- 每次测试生成的18处reports差分已原样归档后恢复，不夹带进修复提交；未处置主仓其他Agent的任何修改。
