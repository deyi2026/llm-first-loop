---
method_id: verify-sink-and-background-before-heavy-env-installs-f23d33455b3e
name: verify-sink-and-background-before-heavy-env-installs
description: 本机要装重量级依赖（git+https 包、mlx/transformers 级依赖栈、venv、模型下载）时，先用安装前已知信息做两项预检：(1) 依赖规模对照工具超时上限，预计超时就直接以后台 job 启动，不同步阻塞；(2) 核实 cwd/工件落点被 VCS 忽略或在专用 scratch 目录，避免把 venv 建进用户主仓库。完成后以退出码+引擎自带 self-check（如非默认注意力的加载自检）+git status 干净作为『环境可用』门槛，再用最小规格模型跑通一次真实请求即停。本次因同步安装撞 60s 超时、且 venv 落在主项目根目录，额外付出一次超时重试、一次目录排查与迁移重装。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:d643a7c4-20a9-438d-a61f-dd25be27bf55:12:f9aadad510ceb5688417
evidence_refs: learning:learn:bea939487713
created_at: 2026-10-16T19:57:12.508179+08:00
updated_at: 2026-10-16T19:57:12.508179+08:00
---
## Trigger
准备执行重量级环境构建（大型依赖安装、venv 创建、模型/权重下载），且 shell 会话的 cwd 归属未经验证，或依赖集与工具超时上限的对比尚未做时。

## Discriminator
安装前已存在的事实：依赖声明（pyproject/extras：git 源 + mlx-vlm + transformers 级别的栈）估算耗时明显 ≥ 工具 60s 超时上限；同时该操作将创建持久工件（venv/缓存/下载目录）而 cwd 是否被 git 跟踪尚未核实。任一成立即应先做预检而不是直接同步执行。

## Short path
- 读依赖声明（pyproject/extras/lock）估算安装时长并与工具超时比较；预计超时→从一开始就用后台 job 启动，不同步等待
- 创建任何持久工件前，用 pwd / git rev-parse --show-toplevel / git check-ignore 核实落点，把 venv 与下载放进已忽略目录（如 tmp/）或专用 scratch 区
- 等待后台 job 期间不空转，可并行准备验证脚本与最小真实请求样例
- job 结束后一次性验证三件事：exit=0；引擎自带 self-check 证明非默认架构行为（如双向 prompt attention 的 first_position_change≠0）真实生效而非仅『能出结果』；git status 无新增被跟踪文件
- 用最小规格的真实模型跑一次覆盖全部题型/接口形态的请求，通过即停，不在方向未定时预拉大权重

## Stop conditions
- 安装 job exit=0、引擎 self-check 通过、git status 干净，三者同时成立才宣布环境可用
- self-check 失败或发现仓库污染：先修容器位置/引擎选择，禁止继续往下做选型或拉大模型

## Verification
- 后台 job 退出码为 0 且安装日志完整到达结尾
- 引擎加载时的 self-check 输出（如 prompt_attention_check.first_position_change 非零）确认非默认行为生效，而不只是推理不报错
- git status / check-ignore 确认主仓库无新增跟踪文件
- 最小真实请求一次跑通全部题型/接口形态后才声明可用

## Counterexamples
- 只读探测命令（curl 模型卡、sysctl、uv 解析 dry-run）既不落盘也不会超时，无需容器化或后台化
- 预计几秒内完成的小 wheel 安装：同步执行更省往返，后台化反而增加等待轮次
- 已在一次性容器或专用 scratch 工作区内执行，污染与超时风险均不存在，预检纯属浪费
- 工具本身无超时限制且无后台 job 机制的环境，本方法退化不适用
