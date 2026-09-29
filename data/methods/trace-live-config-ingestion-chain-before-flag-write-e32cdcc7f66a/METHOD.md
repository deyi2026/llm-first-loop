---
method_id: trace-live-config-ingestion-chain-before-flag-write-e32cdcc7f66a
name: trace-live-config-ingestion-chain-before-flag-write
description: 给已在运行的服务启用开关/业务配置时，先用 ps 拿真实入口命令行，沿 入口→配置resolver→闭集schema 追一遍摄取链，确认目标 key 是否属于被治理集合，再决定『写配置』还是『改代码』。本集由此发现 .env 写入永远到不了 web 进程（闭集 resolver），真正修复是扩展 TOML_SCHEMA+测试，而非写 .env。避免全库 search_files 枚举和凭目录布局猜 service/ 入口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:947:32be36c23ad5aa232af4
evidence_refs: learning:learn:07b53c9c90b6
created_at: 2026-09-24T11:51:46.620215+00:00
updated_at: 2026-09-24T11:51:46.620215+00:00
---
## Trigger
需要为已运行的服务启用/切换 feature flag 或业务配置项，且默认计划是『写 .env/配置文件 + 重启生效』

## Discriminator
运行进程的真实命令行(ps)指向入口模块，入口与 resolver 的 docstring 已写明配置优先级（CLI>gated进程env>runtime.toml>legacy .env）和闭集 TOML_SCHEMA——目标 key 是否在受治理集合内，直接决定写配置文件是否有效；key 名本身可从刚合入的特性代码直接 grep 得到

## Short path
- 核对部署面状态：运行中 generation vs git head，确认特性代码是否已发布、是否需 publish+restart
- ps 取 web 进程命令行与 cwd → 定位真实入口模块；不凭仓库目录布局猜 service/ 等入口，也不做全库 search_files 枚举
- 读入口模块 docstring → 配置 resolver；读 resolver 头部的优先级说明与闭集 TOML_SCHEMA
- grep 目标 key 是否在 schema/白名单：不在 → 写 .env/env 是无效路径，必须在代码中扩展 schema 并补投影与非法值 fail-safe 测试
- 写入受治理配置（如 runtime.toml），用 --dry-run 验证 effective 值与来源字段符合预期
- publish + 重启（受理≠完成），登记定时唤醒核验 manifest 新 head 与该 flag 的遥测产出

## Stop conditions
- --dry-run 显示目标值且来源为预期的受治理配置源
- 重启后进程 manifest 指向新 git head，且该 flag 的遥测文件开始产出

## Verification
- --dry-run / effective config 输出的值与 source 字段
- schema 投影、stale shell 压制、非法值 fail-safe 等关联测试全绿
- 重启后 manifest 的 generation/git head 与发布一致，目标遥测（如 shadow jsonl）出现

## Counterexamples
- 普通 12-factor 服务直接 load_dotenv/os.environ、无闭集 resolver：grep load_dotenv → 写 .env → 重启 即最短路径，全链追踪冗余
- 目标 key 已在受治理 schema 内：直接写配置并 dry-run 验证即可，无需动代码
- 该开关有更高优先级的一次性 CLI 参数：直接传参生效，无需追踪配置链
