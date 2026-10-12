---
method_id: binding-verify-config-first-probe-86ba90942add
name: binding-verify-config-first-probe
description: 验证外部绑定（浏览器 CDP、loopback 服务、目标 ID）在重启/重绑后是否存活一致时，先读权威配置工件（.env/部署清单）提取精确连接参数（URL/端口/TARGET_ID），再据此构造探针；绝不在同一条命令里既 grep 配置又按熟知默认值（如 9222 端口）发请求。本例 .env 已写明 CDP 在 45918，先 curl 默认端口 9222 得空响应并触发 JSON 解码失败，虽随即纠正，但按'先读值再探测'可整体避免。适用于'环境绑定核对→功能恢复验证'类收尾任务，每步只收窄一个未知量：代码版本→绑定参数→端点存活→核心感知路径→旧故障依赖路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:0:569f9252d5b86fd5a9e1
evidence_refs: learning:learn:4267b0cb418e
created_at: 2026-09-18T13:06:36.480343+00:00
updated_at: 2026-09-18T13:06:36.480343+00:00
---
## Trigger
任务要求验证某个外部绑定/连接（如 CDP 端点+TARGET_ID、服务 URL）在重启、重绑或恢复后是否存活一致，且任务上下文已指明记录这些参数的权威配置工件（.env、manifest）

## Discriminator
权威配置工件在计划阶段已被点名（如'.env TARGET_ID 与 CDP 目标列表核对'）且读取成本极低——探针参数应从其内容导出而非假设默认值；grep 输出本身即刻揭示真实端口(45918)与默认值(9222)不同，证明默认假设在读取前就已被固化为命令参数

## Short path
- 读部署状态（generation/git_head）：服务是否运行在预期代码、阻塞工作线是否已提交
- 读权威配置（.env）提取 CDP_URL 与 TARGET_ID：确定要验证的确切端点与目标，不引入默认端口假设
- 用配置中的精确 URL 探测 /json/version 与目标列表：CDP 是否存活、TARGET_ID 是否以预期类型（page target）存在
- 调用感知工具取 snapshot：重绑+重启后感知是否端到端恢复（看 grounding_ref 与 completeness，非空壳回执）
- 调用一个轻量谓词（此前死锁链中的依赖路径）：旧缺陷在恢复会话中是否已不复现
- 绑定一致性+核心路径+旧故障路径均以真实回执 PASS 即停；仅当存在既有记录未覆盖的新事实时才补录经验

## Stop conditions
- 配置中的 TARGET_ID 已在 CDP 目标列表中按预期类型存活
- snapshot 与轻量谓词两条路径均拿到真实回执且 PASS（如 observer_error_count=0）
- 检索既有记录确认无未沉淀的净新增事实，不再扩查

## Verification
- 回执中的 target id / url 与配置值逐字一致
- snapshot 回执含有效 grounding_ref 与 completeness 状态
- 谓词回执 satisfied 且采样错误计数为 0
- 部署 git_head 与主仓 HEAD 一致（前提未被推翻）

## Counterexamples
- 配置工件可能过期（进程以不同 env 启动）时，应读运行时真实状态（ps/lsof/连接表）而非信配置文件，本方法不适用
- 被测工具自身能返回含绑定信息的明确错误时，直接调用工具是更便宜的预言机，先探原始端点反而多余
- 不存在配置工件且默认值有文档约定时，按默认端口首探是正确做法
- 任务只是验证工具自身行为而非绑定时，无需先核配置，直接最小用例调用工具即可
