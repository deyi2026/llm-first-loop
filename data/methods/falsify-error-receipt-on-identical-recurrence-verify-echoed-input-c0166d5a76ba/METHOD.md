---
method_id: falsify-error-receipt-on-identical-recurrence-verify-echoed-input-c0166d5a76ba
name: falsify-error-receipt-on-identical-recurrence-verify-echoed-input
description: 错误回执把『缺失/无效』归到一个与调用方自供输入逐字相同的路径/参数上，而回执的操作性子句实际描述另一条件（本集：'code_root/runtime_root must exist' 是根路径存在性失败，却被归类成 artifact_missing）时，回显只是输入的报告，不是世界观测；规范值应取自权威状态记录（status/desired）或用一条存在性检查先验证自拟值。若已按回执处方整改而同一错误零变化复现，处方诊断即被证伪：直接检验其未验证前提并更正输入来源，而不是加大整改剂量（重建/重试）或转入实现源码取证。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b73b9f9b-96fe-44f5-a9a7-3a450b409a7f:411:ae65929b7f2a3b961b0a
evidence_refs: learning:learn:e0a60ce83fed
created_at: 2026-10-02T12:49:52.943583+08:00
updated_at: 2026-10-02T12:49:52.943583+08:00
---
## Trigger
调用结构化工具/CLI 收到拒绝回执，其 payload 内嵌调用方自供的路径/ID/参数并附整改处方；尤其当按处方执行后回执逐字复现同一错误，或回执的 missing/invalid 值与操作子句描述的条件不一致时。

## Discriminator
失败当时已可见的两条事实：(1) 回执报缺失的路径与我发送的 code_root 逐字相同（~/llm-first-loop/webui/dist 是自拟拼写，源自上一轮复述错误）——工具是把调用方输入回显成 missing；(2) 同一回执操作子句写明 'code_root/runtime_root must exist'，即失败发生在根路径存在性校验而非 dist 内容检查，且前一步 git 命令刚在真实仓库内成功，说明真实根存在。任一条都足以把候选假设从『产物缺失/过期/校验逻辑有 bug』缩成『我供的路径错了』。

## Short path
- 发送前从权威记录取参数：status/desired 已含部署绑定信息，规范 code_root/runtime_root 从记录取；或先 git rev-parse --show-toplevel / ls 验证自拟路径存在
- publish 用验证过的规范路径执行
- 若被拒：先对齐回执的操作子句与回显值；子句为 must-exist 类时，用一条存在性检查直接区分『路径拼错』vs『产物真缺』
- 若按处方整改后同一错误零变化复现：停止重试/重建/读源码，转入证伪回执分类——检验其未验证前提并更正输入来源
- 以权威记录核对生效（desired 绑定目标 HEAD 的新 generation，restart 绑定同步更新），达成即停

## Stop conditions
- publish/restart 按权威记录的规范参数成功受理，desired 已绑定目标提交
- 操作子句所述条件已被直接检验并消除（路径存在、产物在位）
- 终态核对完成，同一错误不再复现

## Verification
- status 显示新 generation 与目标 git_head 绑定，live/desired 差异与两阶段重启语义一致（restart_required）
- 同一错误未在规范参数下再次出现
- 重试所用参数与权威记录值逐字一致

## Counterexamples
- 回执缺失清单来自工具对世界的独立扫描（列出实际扫描到的缺失文件）而非回显调用方输入：按处方整改是正确路径，勿过度怀疑回执
- 整改后错误内容发生变化（不同错误码/不同缺失项）：处方方向正确，继续原修复循环，不要切换成证伪模式
- 产物从未构建过（如干净 checkout 后 dist 确实不存在，且无 must-exist 与回显的矛盾）：先构建再 publish 是对的
- 首次失败、无回显-子句矛盾、无零变化复现：单次失败不足以证伪回执诊断，先按处方走一轮再评估
