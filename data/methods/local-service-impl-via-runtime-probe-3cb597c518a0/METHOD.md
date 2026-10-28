---
method_id: local-service-impl-via-runtime-probe-3cb597c518a0
name: local-service-impl-via-runtime-probe
description: 当客户端脚本/bench/配置已引用本地 HTTP 服务端点（127.0.0.1:port/path）且需定位其实现、API 能力面或数据路径时，先用运行时回执解析服务身份：lsof 查监听进程 → ps 读完整命令行得到包名与 venv → 读同目录 serve 日志确认路由归属 → 直接读 venv site-packages 内的包源码；健康/绑定类回执给出的绝对路径原样使用，不猜相对路径。避免全仓库字符串搜索超时与路径试错。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:158:6a47c574261d2877e767
evidence_refs: learning:learn:4eea3e81718f
created_at: 2026-10-16T21:00:59.213359+08:00
updated_at: 2026-10-16T21:00:59.213359+08:00
---
## Trigger
客户端 artifact 已引用本地 HTTP 服务端点（127.0.0.1:port/path），需要定位该服务的实现、API 能力面或其数据存储路径；且仓库内按 URL 字符串的文件名/内容搜索未命中，或仓库大到全量 grep 会超时。

## Discriminator
客户端 artifact 当时已印出确切的本地端点 URL——这意味着存在一个活着的监听进程，它是实现身份的权威指针，与仓库内字符串搜索是否命中无关；同时健康/绑定回执已给出数据目录的绝对路径。

## Short path
- 读客户端 artifact，提取确切本地端点 host:port/path 与所在工作目录；未知量：谁实现该服务。
- lsof 查监听该端口的进程 → 得到 PID 与可执行文件；未知量：服务进程身份。
- ps -p PID -o command 读完整命令行 → 得到包名（如 startlux-decide）与 venv 路径；未知量：实现源码位置。
- 读客户端同目录的 serve 日志，确认 'serving on <同一端点>' 的路由归属；未知量：交叉验证。
- 在 venv site-packages 的包目录内 grep 端点路由与 API 面文件；绑定回执中的绝对路径（experiences_dir/methods_dir 等）原样用于取记录格式样本，不做相对路径猜测。
- 路由归属、API 能力面、记录格式三者确认后停止，进入构建。

## Stop conditions
- 已确认监听进程/安装包拥有该端点路由（日志与源码双重印证）
- API 能力面足以支撑要构建的集成（参数、返回结构、问题类型已知）
- 数据存储路径采用权威回执的绝对路径且文件确实存在

## Verification
- 在定位到的包源码中 grep 端点 path 命中路由定义，且 serve 日志 ready 行与客户端 URL 完全一致
- 绑定回执给出的 experiences_dir/methods_dir 等绝对路径 head 成功，全程无 'No such file' 路径试错

## Counterexamples
- 目标是构建期库/纯函数代码，没有运行中的进程和监听 socket：运行时探测无物可查，应走定义面代码检索（method-repo-api-discovery）
- 端点在远端主机而非 localhost：无法本地 lsof/ps，只能靠文档、OpenAPI 或维护者
- 仓库很小且 URL 字符串本就在源码中：窄范围内容搜索一步命中，运行时探测是多余动作
- 进程只是薄启动器，语义在模型权重/外部配置里：拿到包名仍不等于拿到业务语义，还需 case/bench artifact 补充
