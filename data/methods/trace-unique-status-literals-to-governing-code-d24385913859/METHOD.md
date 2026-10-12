---
method_id: trace-unique-status-literals-to-governing-code-d24385913859
name: trace-unique-status-literals-to-governing-code
description: 当权威状态/配置工具已返回含唯一字面标识（schema 名、专用字段名、deployment_id、精确 code_root 路径）的结构化输出时，把这些字符串当作从运行状态指向治理代码与操作文档的 provenance 边：直接在输出给出的 code_root（其次 runtime root 的 scripts/src）内 grep 这些字面量，定位读写该状态的模块/CLI 与操作指南，再据此导出精确操作命令并核对前提；而不是先用主题关键词做 evidence/docs/files 宽搜索。搜索空间从全部文档/文件缩到引用唯一标识的少数文件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:928:3bc785b9e37301b8acf5
evidence_refs: learning:learn:892d71c631e5
created_at: 2026-09-18T04:20:34.516683+00:00
updated_at: 2026-09-18T04:20:34.516683+00:00
---
## Trigger
任务要求弄清某运行时状态（部署/服务/配置 manifest）的修改或操作机制（如 publish/restart 步骤），且首个权威状态工具输出中已包含唯一字面标识：schema 版本串、专用字段名、具体 ID、精确 code_root/worktree 路径

## Discriminator
状态输出中的唯一字符串（如 schema 'managed-service-deployment/v1'、字段 webui_artifact_sha256、deployment_id、worktree 绝对路径）必然也出现在定义/读写/校验该状态的代码与文档中；这是比主题关键词更窄且可验证的下一跳，当时已可见，无需先宽搜索

## Short path
- 从权威状态输出提取唯一字面量：schema 名、专用字段名、ID、code_root 路径（schema 名通常还映射到 manifest 文件名，可做定点 find）
- 用这些字面量在状态输出给出的 code_root 内 grep *.py/*.sh/*.md，定位治理代码（如 service_control CLI）与操作文档
- 读命中的操作文档与治理代码，确认修改机制：子命令、CAS/expected 参数、artifact SHA 的计算方式，判断是否需手改文件或重建产物
- 按机制核前提（目标 HEAD、tracked 前端产物是否被新提交改动）后，导出给用户的 show→publish→verify 精确命令
- 以治理代码自身定义的回执/verify 一致为完成证据，停止发现

## Stop conditions
- 已定位读写该状态的权威代码/文档，且用户所需操作步骤可由其直接导出
- grep 唯一标识在 code_root 与 runtime root 均无命中 → 该边断裂，改走文档索引或上层运维工具，不再全库枚举

## Verification
- grep 命中的文件确实引用与状态输出相同的 schema/字段名（provenance 闭合）
- 给出的命令子命令与参数和治理代码 CLI 定义一致（如 expected-generation CAS 值取自刚读到的 show 输出）
- 操作后用同一治理工具 show/verify 确认代次与 SHA 已按预期变化

## Counterexamples
- 标识符过于通用（version、name、status）时 grep 噪声大于信号，主题词搜索文档反而更优
- 治理逻辑在仓库之外（托管平台/专有运维系统），仓库 grep 找不到机制，应改用提供的运维工具或文档索引
- 用户问的是'是否该发布'这类决策判断而非机制步骤，唯一标识追踪不解决语义问题
- 状态输出不含专用字段名或 code_root 指针时，不存在这条 provenance 边，先做宽发现建立上下文才是正确路径
