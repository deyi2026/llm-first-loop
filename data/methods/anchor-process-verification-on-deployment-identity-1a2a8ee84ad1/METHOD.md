---
method_id: anchor-process-verification-on-deployment-identity-1a2a8ee84ad1
name: anchor-process-verification-on-deployment-identity
description: 验证重启/部署是否真正落地时，进程枚举的过滤键应从已拿到的部署记录（runtime_root、git_head、统一启动器命令模式）推导，而不是猜测组件关键词（如 uvicorn/服务名）。本例首轮 ps 用猜测关键词，漏掉一个服务并混入多个无关进程，被迫换过滤键重跑；若一开始就用部署身份作过滤键，一次查询即可精确枚举全部目标实例。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:570:304adc833b2855a7c3c5
evidence_refs: learning:learn:72cdaf79855a
created_at: 2026-09-18T17:22:51.063233+00:00
updated_at: 2026-09-18T17:22:51.063233+00:00
---
## Trigger
重启/部署动作完成后，需要核实全部目标服务实例已按期望代际（generation/git_head）真正运行，例如用户问“重启已完成，下一步”时的落地验证

## Discriminator
部署状态查询当时已返回部署身份：runtime_root/code_root 与 git_head；且 ps 输出中任一已匹配的目标进程行本身揭示了统一启动器模式（同一 runtime_root 下以同一 launcher 模块启动各服务）。这两条已知事实足以把过滤键从“猜测关键词”收敛为路径/模块精确匹配，一次枚举全部实例、零无关命中

## Short path
- 查询部署/服务管理器状态，记录 desired generation、git_head、runtime_root（部署身份）
- 以 runtime_root 或已见的统一启动器模式作为进程过滤键，一次枚举全部服务实例及其启动时间
- 核对每个实例启动时间晚于重启动作时间，且服务端口/端点健康响应
- 核对 git HEAD 等于部署记录 git_head 且 tracked 工作区干净，确认新进程未夹带未提交代码
- 输出核实结论（实例表+证据）与下一步建议，停止发现类动作

## Stop conditions
- 全部预期服务实例均在运行、启动时间晚于重启动作、代码指向期望 git_head、端点健康、tracked 工作区无修改
- 若任一实例缺失或启动时间早于重启，转查重启动作终态/服务管理器日志定位原因，而不是放宽或更换 ps 关键词重试

## Verification
- 用部署身份派生的过滤键重跑进程枚举，结果应恰好等于预期服务集合，无同名无关进程（如聊天客户端、cron 常驻脚本）混入
- 各实例的代码根/HEAD 与部署记录一致，端点探测返回预期状态码
- 对照部署记录中的代际/时间戳确认实例代际无误

## Counterexamples
- 部署管理器已直接返回每服务 PID/uptime 等权威存活状态时，无需 ps 模式匹配，直接信任管理器输出即可
- 部署记录不含 runtime_root/启动命令，且服务经 systemd/docker/supervisor 等多样方式包装运行时，单一路径过滤不可行，应按管理器逐服务查询
- 核实对象是一次性脚本或用户自装应用（非受管部署）时，关键词 ps 本来就是自然工具，本方法不适用
- 部署状态与实际运行环境分离（如 status 查询的是 desired 而非 live 状态）时，需另取 live 权威来源，仅靠身份锚定的 ps 不足以闭环
