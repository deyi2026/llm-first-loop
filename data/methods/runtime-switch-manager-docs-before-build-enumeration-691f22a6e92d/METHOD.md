---
method_id: runtime-switch-manager-docs-before-build-enumeration-691f22a6e92d
name: runtime-switch-manager-docs-before-build-enumeration
description: 替换正在运行的本地模型服务时，ps 已给出现任服务命令行（runtime 家族+端口），目标模型目录格式（GGUF vs MLX）已决定继任 runtime 家族，两事实合并即锁定『停旧 MLX 服务 + 起平行 llama.cpp 服务』两段式结构。下一个未知量是生命周期管理（谁监管进程、KeepAlive、停启与部署约定），它由现任管理层回答——状态输出里的 observer/manager 及其 README/config。应先读管理层文档拿到 bootout/bootstrap 约定与『勿跑存档脚本』警示，再去选定二进制；而不是先跨多棵构建树枚举全部候选 llama-server。用已存在的管理约定把『全目录找最优启动方式』缩成一条可验证路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cba0dcfa-4656-4850-921d-1fad481ce73d:43:691dfe7d69d147dfd57e
evidence_refs: learning:learn:43c0c8101d30
created_at: 2026-09-20T17:17:16.334176+00:00
updated_at: 2026-09-20T17:17:16.334176+00:00
---
## Trigger
任务要求关停一个正在运行的本地模型服务并用另一模型优化重启，且(a)进程列表已显示现任服务命令行与端口，(b)目标模型目录已暴露格式（GGUF/safetensors）并与现任 runtime 家族不匹配。

## Discriminator
当时已知三事实：①ps 显示现任是 mlx_lm.server --model ...MLX --port 8901（MLX 家族）；②目标目录只含 GGUF 多分片 + mmproj（mlx_lm 无法加载，必然要走 llama.cpp）；③状态 JSON 中出现 observer=lfrt 及服务重启说明 ⇒ 存在有文档的服务管理层。这三条把『在 research 全目录里找启动方式』缩成『读管理层文档拿停启约定 + 选一个 llama.cpp 构建』。

## Short path
- ps/grep 定位现任服务：确认 runtime 家族、端口、命令行（未知量：要停的是什么、由谁监管）。
- ls 目标模型目录：格式与现任不匹配 ⇒ 必然是两段式切换（未知量：继任 runtime 家族——已锁定 llama.cpp）。
- 读状态输出指向的管理层文档（runtime/README、config）：拿 launchd label、KeepAlive、bootout/bootstrap 约定、plist 存放位置、哪些脚本是存档勿跑（未知量：干净停启机制）。
- 按文档约定选最新完整 llama-server 构建，每个 build 目录一次定向检查，不跨树全量枚举（未知量：用哪个二进制）。
- 按同一约定新建 launchd 条目（目标 GGUF 多分片 + 加速/上下文参数），bootout 旧 label、bootstrap 新 label，保持原端口使消费方零配置。
- 验证端口由新进程监听、模型身份正确、短生成冒烟通过、旧进程未复活；记录回滚路径后停止。

## Stop conditions
- 新服务在原端口返回正确模型身份且冒烟生成成功
- 旧 label 已 bootout，旧进程消失且未被 KeepAlive 拉回
- 回滚路径已明确（重新 bootstrap 旧条目即可恢复）

## Verification
- lsof/ps 确认原端口监听进程是新 llama-server 且命令行含目标 GGUF 路径
- /v1/models 或等价端点返回目标模型身份，完成一次短生成
- launchctl 确认旧 label 未注册、新 label 已加载，且未执行文件头标注 ARCHIVED/Do-NOT-run 的脚本

## Counterexamples
- 目标模型与现任同为 MLX 格式：无 runtime 失配，应直接用现任管理器换模型（如 switch 命令），不要并行新建第二套服务。
- 现任服务是手工临时启动、无 launchd/管理器文档：bootout 无对象，kill 后定向启动即可，构建树枚举反而是必要发现。
- 管理层文档已过期、与实际 launchd/plist 状态不符：须以 launchctl list 与实际 plist 为准，不能照抄 README。
- 用户已指定确切二进制或构建树：跳过选型枚举，直接进入停启与验证。
