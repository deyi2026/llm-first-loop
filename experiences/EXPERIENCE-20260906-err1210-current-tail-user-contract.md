---
title: ERR1210 当前恢复合同：只对尾部连续 user 做无损聚合，2..16 不是 provider 阈值
scenario: 排查或恢复 OpenAI-compatible provider 的 HTTP 400/code 1210 时，经验库存在多代历史结论：tool_call arguments 序列化、连续 user、旧 compact-first recovery gate 等。需要先区分历史阶段，再按当前 runtime 合同处理，避免把旧实现或实验边界当成当前 provider 事实。
root_cause: 1210 是 provider 黑盒错误码，历史不同阶段可能由不同 wire 形态触发；当前 LFL 不能从错误码本身推断语义根因。现行可机械证明的恢复面只有：检查尾部连续 role=user 组，若在实现 guard 内可无损聚合且 payload 实际改变，才允许一次结构化重试。
solution: ① 先核对当前 payload/source 与当前 recovery_controller，不从旧经验标题直接套结论；② exact ERR1210 时，仅尝试把尾部连续 role=user 无损聚合为一条；③ 当前实现 guard 为 2..16 条，仅决定 recovery 是否尝试，绝不能解释为 provider “>=2 必失败”或真实阈值；④ 聚合后 payload 未改变则 retry_count=0，如实失败；改变后最多重试一次；⑤ tools 数量/消息规模等其它结构维度只能按新证据继续诊断，不把历史 drop-tools/truncate-tail 变体误当当前恢复链。
evidence: "current source: src/llm_loop/core/loop/engine_services/recovery_controller.py::_aggregate_tail_users/try_recover_err1210；structural oracle: src/llm_loop/eval/oracle_1210.py::_struct_variants (merge-tail-user / drop-tools / truncate-tail 单变量轨)。oracle mock 明确不模拟 provider 1210 语义。"
tags: [err1210, tail-user, wire-contract, current-recovery, historical-applicability]
source:
  kind: current_source_audit
  recovery_controller: src/llm_loop/core/loop/engine_services/recovery_controller.py
  oracle: src/llm_loop/eval/oracle_1210.py
status: archived
created_at: "2026-09-06T00:09:26.141519+08:00"
updated_at: "2026-09-06T00:12:36.510891+08:00"
last_verified_at: "2026-09-06T00:12:36.510891+08:00"
---

## 当前与历史的边界

- 当前实现的 `2..16` 是本地恢复 guard，不是 provider 阈值证据。
- `merge-tail-user` / `drop-tools` / `truncate-tail` 是 oracle 的单变量诊断设计；生产恢复链只保留尾部 user 聚合。
- 历史 1210 经验保留 exact ref 以便考古，但普通任务先以当前源码和当前 payload 为准。
- 经验被检索到仍只代表历史证据，`task_applicability` 由模型结合当前事实判断。
## 2026-09-06 lifecycle review

该条目已从 active 转为 archived/dormant。镜像权威 action_trace 的最后一次真实 1210 为 2026-08-30T16:17:43Z（+08 为 08-31 00:17），随后截至 2026-09-05T13:41:40Z 有 6425 条 action.llm_decide/llm_response、84 条其它 llm_error，真实 1210 为 0。主区旧 trace 最后一例为 2026-09-01T23:48:55Z（+08 为 09-02 07:48），但其日志仅延续到当日 09:05Z，证据窗口较短。当前 production source `tail_assembly.py` 明确不再生成 program-owned user tail，`base_assembly.py` 保留零内容 assistant role frame 以避免 user→user 结构。

因此本条保留为历史 wire-compatibility / 回归诊断资料，不再参与 active 普通经验召回；当前 exact ERR1210 机械 recovery 仍由源码与测试作为低成本防御边界维护。

