---
method_id: resolve-config-contract-before-relaunching-stateful-process-4efb420dd74a
name: resolve-config-contract-before-relaunching-stateful-process
description: 复活拥有独立状态目录的崩溃长驻进程时，把重启当作配置解析问题而非启动命令考古：不猜 env 名、不扫 wrapper 脚本/shell 历史，而是先读进程自身 config 解析代码，枚举确切 env 变量名与随 data_dir 走的文件查找链，在隔离环境中逐环预验证（文件存在、模型可解析、无 default 回退），再以启动日志断言 resolved 值后才放行。本例将 2 次猜 env 的失败启动和 1 次 default 直通的污染运行，压缩为一次读配置加一次受断言保护的启动。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5693816b-bf5b-467a-8a25-a8f48a50e29b:72:a8002856ae2163d59355
evidence_refs: learning:learn:33ae6f1efebf
created_at: 2026-09-22T16:09:57.261702+00:00
updated_at: 2026-09-22T16:09:57.261702+00:00
---
## Trigger
崩溃的长驻进程需带原状态目录/原会话复活，历史启动命令不可直接获得或已过期，且其运行配置由 env 变量加随数据目录走的文件查找链共同决定

## Discriminator
摩擦点之前已知：状态目录是已死 CLI 进程（PID 6113/6114）的完整 data 目录（sessions/audit/event_logs + 根级 workspaces.json），session 记录就在其中——重启的真正未知量是『CLI 用哪个 env 锚定该目录、模型经何种查找链解析』，这是 CLI 代码自身的属性，可一次读 config 解析确定，比 /tmp 脚本考古更权威；且首次重启前 audit 已暴露死因 LLMHTTPError(Context size exceeded)，要求在启动前而非启动后验证 resolved 模型与预算

## Short path
- ls 状态目录 + ps + 读 audit/proc_versions 与错误日志：确认 CLI 已死、模型服务端存活、死因是 context 超限（未知量：重启还缺什么）
- 读 session JSON：拿 session_id、原任务提示词、workspace 路径（未知量：恢复目标）
- 一次读 CLI 的 config 解析代码：确定锚定数据目录的确切 env 名与 provider 注册表查找链（env > {data_dir}/providers.local.json > seed），替代脚本/shell 历史考古（未知量：重启配置契约）
- 启动前在隔离目录逐环验证：查找链各级文件是否存在、目标模型能否解析出真实 context 预算（未知量：隔离环境是否满足查找链）
- 带断言单次启动：回显 model=真实provider/模型且无 default/ 前缀，不符立即杀掉，不让其写入会话（未知量：resolved 配置是否正确）
- 确认事件日志推进、原会话证据续上后停止工具调用

## Stop conditions
- 启动日志断言通过：model 串无 default 回退前缀、预算与 n_ctx 一致，且会话事件日志恢复推进
- config 查找链每一环在隔离 data_dir 中已存在或已补齐并复验通过

## Verification
- 将 config.py 中的 env 名与查找优先级，和实际启动使用的 env 逐一对照
- 启动回显的 model 串包含真实 provider/模型名，无 default 前缀，预算按真实 context 计
- 隔离 data_dir 下注册表文件存在且含目标模型条目（含 context 值）

## Counterexamples
- 已有权威 runbook/README 记录确切重启命令时，直接用文档命令，不读源码
- 状态目录可丢弃、无需续接原会话时，全新启动即可，无需逐环验证查找链
- 进程提供 --dry-run 或启动无持久化副作用时，试探性启动探测 env 名是可接受的更短路径
- 闭源二进制无 config 源码可读时，只能回退到 wrapper 脚本与 shell 历史考古
