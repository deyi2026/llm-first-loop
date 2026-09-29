---
method_id: trace-local-service-ownership-before-broad-enumeration-bf7770f56abe
name: trace-local-service-ownership-before-broad-enumeration
description: 调查本机未知端口服务时，先沿监听进程这条 provenance 边确权：PID→exe/cwd/打开文件→应用自身配置目录，读其自带配置（脱敏）拿到绑定、隧道/公网入口与凭证，再用它自己的 token 做一次鉴权握手取权威能力清单（tools/通道/OAuth 客户端记录）。在归属确认前，不对当前仓库做全量内容搜索、不先上网找文档。工具回执显式给出拦截原因与替代通道（如 SSRF 防护建议改走 shell）时，换一次通道即可，不重试原通道。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:1:750c7472a0486517689b
evidence_refs: learning:learn:4de79d02b465
created_at: 2026-09-25T10:19:14.210449+00:00
updated_at: 2026-09-25T10:19:14.210449+00:00
---
## Trigger
用户提供本地/回环地址上的未知服务（host:port）并问它是什么/能否集成；或 web_fetch 访问私网被策略回执拒绝且回执已给出替代通道建议

## Discriminator
监听回执（lsof/ps）当时已给出占有进程的命令名与 PID。若它是独立的打包应用进程而非工作区 dev server，则最窄下一跳是进程元数据（exe、cwd、打开的 db/配置文件）指向该应用自己的数据目录，而不是当前仓库内容搜索或公网检索；服务自身的配置+鉴权握手就是其能力的权威描述

## Short path
- web_fetch 访问回环被 SSRF 回执拒绝且回执已给替代建议 → 立即切换 shell（curl+lsof）一次到位，不重试原通道
- 用 PID 做 ps/lsof -p 得 exe、cwd、打开的配置/db 文件 → 定位应用包与其专属数据目录（如 ~/.mcp-console/）
- 读该应用自带配置（脱敏）→ 绑定地址、隧道/公网 hostname、admin token 等集成关键参数
- 配置给出公网入口时，用本地与公网 /health 的同一实例标记（如 bootId）验证同源
- 用其自身凭证做一次鉴权握手（tools/list、通道与 OAuth 客户端记录）→ 以服务自己的使用记录直接回答集成问题并停止

## Stop conditions
- 服务归属、配置、能力与使用证据已由其自身工件（进程元数据+自带配置+鉴权握手回执）闭环，足以回答用户的集成/能力问题
- 只有当问题是外部平台政策/官方要求等本地记录无法回答的内容时才继续查外部文档，且一次未命中即以本地权威证据作答并明示未核项

## Verification
- 最终结论引用服务自身证据链：进程→配置路径→握手回执/DB 记录，而非网页摘要或仓库噪声命中
- 公网入口与本地实例用同一实例标记（bootId 等）对齐后才断言同源

## Counterexamples
- 监听进程的 cwd/exe 就在当前仓库（venv 里的 uvicorn/node 等 dev server）→ 归属是仓库代码，进程元数据只用于确认归属，随后应走代码/调用点检索而非读外部应用配置
- 服务跑在容器或远端主机，本地查不到 PID → 进程 provenance 不可用，应退回端点探测与厂商文档
- 用户问的是外部平台政策/ToS/官方接入要求 → 本地握手记录回答不了，文档检索仍是必要步骤而非可跳过
