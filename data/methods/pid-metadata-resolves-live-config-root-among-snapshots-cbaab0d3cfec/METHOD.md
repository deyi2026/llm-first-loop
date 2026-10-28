---
method_id: pid-metadata-resolves-live-config-root-among-snapshots-cbaab0d3cfec
name: pid-metadata-resolves-live-config-root-among-snapshots
description: 要在运行中的本地服务上更换 API key/provider 配置，而工作区充斥带日期的快照/镜像/worktree 副本时：先用进程表锁定活进程，再用进程自身元数据（cwd、环境变量、lsof 打开的配置文件）直接映射出权威配置根。live registry dump 只给配置内容，不给「磁盘上哪份文件正被读」。随后按 编辑.env → 服务自身 reload/重启 → 直连 provider 实测 的最小链路交付。避免：先全库内容搜索（命中测试日志）、把 worktree/快照副本当真值、跨候选根 git head 匹配找运行目录（本集 2894beda 在可见各仓均未命中）。
aliases: 换API key要改哪个文件, 运行中服务读哪份配置, lsof找正在用的.env, 一堆镜像目录哪个在跑, 改.env后怎么热加载, 进程定位配置根目录
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e5c9c31f-62a6-4b69-a4d1-45695cc16692:1:f09bec1703c6b1c52bdd
evidence_refs: learning:learn:d6ab28f83b09
created_at: 2026-10-27T00:42:44.558988+08:00
updated_at: 2026-10-27T00:42:44.558988+08:00
---
## Trigger
用户要在正在运行的本地多进程服务上更新凭据/provider 配置（换 key、换 base_url），且文件系统存在同一项目的多个带日期快照/镜像/worktree 副本；或首次内容搜索命中测试日志与快照副本而非运行时配置。

## Discriminator
用户措辞已表明存在正在消费旧 key 的活服务，且 ps/状态回执已给出 pid 甚至 live registry dump（含 api_key_env 变量名）——此时唯一未决的是『该进程从哪个根目录读哪份文件』。运行进程自身的 cwd、环境变量、打开文件句柄就是这条 服务名→权威配置路径 映射的权威来源；registry 内容与磁盘路径是两个不同未知量。

## Short path
- ps aux 定位服务名对应活进程 pid；未知量：是否存在活消费方、是哪个进程
- lsof -p <pid> / ps eww <pid> 取 cwd、已加载的目标环境变量、打开的 .env/providers 文件；未知量：权威配置根与确切文件路径
- 只读该根下 provider 定义文件的目标块与 .env 对应行，确认 api_key_env ↔ 环境变量名绑定与 base_url；未知量：要改的确切对象
- 输出最小操作链：改 .env 该行 → 服务自身管理面 reload 或重启 → 用新 key 带 Authorization 直连 provider endpoint 实测连通；必要时确认是否换平台需同步改 base_url

## Stop conditions
- 进程元数据确认的唯一配置文件已读取，且 api_key_env 与 .env 变量名一致、reload 方式已明确 → 停止枚举任何其他副本
- 进程在容器/远端导致本地 lsof 不可见 → 改走服务自身 status/admin 接口取配置路径，停止本地目录枚举

## Verification
- 编辑目标路径应与进程 cwd/打开文件一致，而非仅与某镜像目录同名文件一致
- provider 文件声明的 api_key_env 变量名必须与 .env 实际行匹配
- 新 key 用一次直连 provider 的认证请求验证；旧 key 可选实测以确认/证伪『用不了』前提

## Counterexamples
- 单仓项目无快照杂物 → 直接读仓内配置即可，进程探针是多余开销
- 配置由部署平台/secrets 管理而非运行时读本地文件 → 改本地 .env 不生效，权威管理面在平台侧
- 配置仅启动时读入并落库，运行中无打开句柄 → lsof 看不到配置文件不等于文件不权威，需改用环境变量/进程启动时间 vs 文件 mtime 判断
- 服务跑在容器或远程主机 → 本地进程元数据不可用，应退回服务自身 admin/status 表面
