---
method_id: traverse-live-process-edge-before-path-guessing-ae43cfe9f739
name: traverse-live-process-edge-before-path-guessing
description: 回答'本地服务/模型正在跑什么任务'一类运行态问题时，若进程清单已给出服务端及其显式监听端口，先沿活连接边遍历：端口→ESTABLISHED 客户端 PID→客户端命令行/状态目录→最新事件日志尾部；不要依据无关服务的目录命名去猜 session 路径，也不要用文档搜索查实时状态。结构化状态工具对该子系统明确报 observation_failed 时视为非权威，以 ps/lsof 的 OS 级事实为准。该方法把'在某处跑什么任务'变成两次确定性查表，消除猜测路径与宽泛检索两类扩散。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5693816b-bf5b-467a-8a25-a8f48a50e29b:47:83ac428da803c6ee86ec
evidence_refs: learning:learn:900bf06f695a
created_at: 2026-09-22T16:05:37.623873+00:00
updated_at: 2026-09-22T16:05:37.623873+00:00
---
## Trigger
用户询问某本地进程/模型服务当前正在执行的任务或实时状态；已通过进程清单看到该服务端命令行含明确监听端口（如 --port N）；或结构化状态工具对该子系统返回 observation_failed/不可观察

## Discriminator
服务端 cmdline 中的显式监听端口把未知量'在跑什么任务'缩小为'谁与该端口建立 ESTABLISHED 连接'，lsof 一步即可得客户端 PID；同时状态工具已报 observation_failed，说明重查观察器或搜文档不会新增事实——本轨迹正是在持有该端口事实后转去猜 dsh sessions 路径（失败）并做宽泛文档搜索，属首次扩散

## Short path
- 查结构化状态；若目标子系统报 observation_failed，标记为非权威，改用 OS 级事实（未知量：是否存在结构化真值）
- ps 按模型/服务关键字过滤，从服务端命令行读出可执行文件、模型路径、监听端口、启动时间（未知量：服务是谁、在哪监听）
- lsof -i :端口（或 lsof -p 服务PID）枚举 ESTABLISHED 客户端连接（未知量：谁在消费该服务）
- ps -o pid,lstart,command -p 客户端PID，从其命令行与环境提示定位启动器与状态目录（未知量：任务载体与状态在哪）
- 在客户端状态目录内按时间取最新事件日志并 tail，读出任务 prompt、当前轮次与时间戳（未知量：任务内容与进度）
- 交叉验证连接双边 ESTABLISHED、日志时间戳/轮次在推进、CPU 非零 → 证据充分，停止发现并作答

## Stop conditions
- lsof 显示该端口无任何 ESTABLISHED 连接 → 服务空闲，直接回答'无任务'，不再挖状态目录
- 事件日志尾部已含任务描述与推进中的轮次/时间戳 → 用户所需事实已被权威来源验证，停止发现
- 结构化状态工具一次查询即成功且完整回答 → 无需进程遍历

## Verification
- 客户端连接与服务端端口双边 ESTABLISHED，PID 与命令行互相印证
- 事件日志中的模型/会话配置与服务端 alias、端口一致
- 进度结论有时间戳支撑：再次 tail 日志或 CPU 占用非零证实运行活跃

## Counterexamples
- 结构化状态工具正常工作并返回完整运行态 → 直接采用其结果，进程遍历属多余动作
- 服务端有多个并发客户端（网关/共享推理服务）→ 单条连接边无法唯一确定'那个任务'，需查服务自身任务注册表或向用户澄清
- 客户端是通用代理层 → 连接边只通到代理，还需读代理的上游请求日志才能定位具体任务
- 用户问的是设计/历史/文档问题而非实时状态 → 文档与代码搜索才是正确工具，本方法不适用
- 进程显示无连接且 CPU 近零 → 答案即'空闲'，继续枚举状态目录属于过度搜索
