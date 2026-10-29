---
method_id: scrub-inherited-config-env-before-isolated-smoke-1940ed0c7197
name: scrub-inherited-config-env-before-isolated-smoke
description: 在宿主 shell 里起隔离测试/冒烟实例时，隔离边界是『子进程继承的整个环境』而不是我显式设置的变量。设计文档的隔离条款通常已枚举必须重定向的全部路径型变量（临时 DATA_DIR、临时 ENV_FILE、独立端口等），只实现清单子集（如只设 DATA_DIR）会让子进程继承指向生产 .env 的 env-file 变量，把测试凭据/默认模型等持久化写进生产配置。先逐项实现隔离条款、枚举 shell 中项目前缀的路径型变量并用 env -i/临时值清洗，再以生产配置文件 sha256 前后对照作为隔离成立的机械证据。
aliases: 隔离冒烟写脏生产 .env 怎么防, env -i 启动隔离测试实例, 子进程继承 env 文件变量污染生产配置, 冒烟前清点继承的路径型环境变量, 测试实例隔离不彻底先查 LFL_ENV_FILE
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:2594:54598ecb939ee2104e87
evidence_refs: learning:learn:13d9b0904d41
created_at: 2026-10-28T22:43:57.780609+08:00
updated_at: 2026-10-28T22:43:57.780609+08:00
---
## Trigger
在已带工作环境的会话 shell 中启动隔离测试实例（临时端口+临时数据目录），而被测程序以环境变量/env 文件为权威配置、且存在把配置持久化写回 env 文件的路径（凭据写入、默认值落盘等）时

## Discriminator
两个当时即可见的事实足以提前收窄：(1) 设计文档隔离条款本身逐项枚举了必须重定向的变量（『临时数据目录 + 临时 ENV_FILE + 不触碰 live .env』）——只设 DATA_DIR 即违反契约，且缺失项正是写路径变量；(2) 一条 env | grep -E '^(LFL|WEB|LLM)_' 即暴露当前 shell 继承的 LFL_ENV_FILE=<repo>/.env 这类生产路径，而配置加载优先级 env>文件意味着继承值会静默压过临时目录。

## Short path
- 启动隔离实例前，把设计文档隔离条款逐项转成必须重定向的变量清单（DATA_DIR、ENV_FILE、端口、上游 URL），缺一即不启动
- 枚举当前 shell 的项目前缀环境变量（env | grep），识别每个指向生产路径的继承变量，作为清单的补集
- 用 env -i（仅保留最小 PATH/HOME）或对每个生产路径变量 env -u/显式指向临时值启动子进程，使清单中每项要么临时要么不存在
- 以生产配置文件（.env、providers 配置）运行前后各取一次 sha256 作对照：哈希不变=隔离成立；哈希已变=先备份还原并核对还原哈希，再修启动方式重跑
- 在隔离实例内回读配置来源（source/default_source 指向临时路径）确认生效来源正确；冒烟全绿且生产哈希未变后停止

## Stop conditions
- 隔离清单中每个变量都已重定向或清除，且生产配置文件 sha256 在整轮冒烟中保持不变
- 发现没有现成隔离条款时，先从配置加载代码（config.py/providers.py 的 env 读取与优先级注释）枚举权威变量集，再回到清洗步骤，不凭记忆猜变量名

## Verification
- 冒烟运行前后对生产 .env 与 provider 配置文件各取一次 sha256 并显式比对不变
- 在隔离实例内回读配置来源字段，确认 default_source/persistence 指向临时文件而非生产路径
- 冒烟产生的凭据/默认值只在临时 env 文件中出现，生产文件 diff 为空

## Counterexamples
- 目标程序只接受显式 CLI/config 路径参数、完全不读环境变量时，无需环境清洗，直接传临时配置路径即可
- 测试对配置纯只读、不触发任何持久化写路径时，继承变量不会污染生产——但必须先确认被测流程不含写操作
- CI runner 环境本身干净且一次性时，env -i 反而可能破坏依赖 PATH/HOME 的工具链，应保留最小必要变量而非全清
