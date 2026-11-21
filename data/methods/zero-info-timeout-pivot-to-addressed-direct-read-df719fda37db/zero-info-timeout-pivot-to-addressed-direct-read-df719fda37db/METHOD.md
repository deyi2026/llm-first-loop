---
method_id: zero-info-timeout-pivot-to-addressed-direct-read-df719fda37db
name: zero-info-timeout-pivot-to-addressed-direct-read
description: 同步工具回执只有『执行超时 Ns 未完成』、无错误码/部分输出/退出码（零信息）时，不要对同一工具原样重发——每次重试都是固定时间成本换零新信息。立即改走本会话已证明秒回的直读通道：从已成功读取的回执里取精确路径或目录前缀，用一条轻量 ls/read_file 直达取证，目录清单即可替代宽域 search_files。直达通道也超时才升级为环境级故障如实上报；操作本身合法长时时改 nohup 后台+轮询，不占同步墙。反模式：超时后对同一工具同参重发≥2次；已有目录前缀线索仍做全库宽搜索。
aliases: 工具超时60秒怎么办, search_files一直超时, 超时后别原样重发, 用ls直取代替宽搜索, 超时回执零信息
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:dc72c34b-f327-413b-934b-cd5f868f6553:12:2439cc5881426c664fb9
evidence_refs: learning:learn:5979320da61c
created_at: 2026-11-19T17:11:04.457978+08:00
updated_at: 2026-11-19T17:11:04.457978+08:00
---
## Trigger
会话内某工具回执仅为『执行超时（如60s）未完成』，不含错误码、部分输出或退出码；同环境此前已有直读类回执（read_file/简单命令）正常秒回。

## Discriminator
两类当时可见事实把『原样再试一次』从选项中排除：(1) 超时回执零诊断信息，同参重发=固定60s成本换零新信息；(2) 已成功读取的回执中已显式给出目标的目录前缀与相对路径（如 docs/promotion/ 前缀、receipts/ 子目录），直达 ls/read_file 即可枚举并取得宽搜索想找的全部候选。

## Short path
- 首个零信息超时后禁止原样重发同一工具；把当前未知量改写为『哪些精确路径/目录需要看』
- 从已成功回执中取目录前缀与相对路径，用一条轻量 ls（可并列多路径）枚举候选，替代宽域 search_files
- 对清单命中的目标用 read_file 精确读取，拿齐事实即停止
- 若直读通道也超时→判环境级故障，如实上报并暂停，不再换措辞重试
- 若原操作本身是合法长时任务→改 nohup 后台启动+轮询回执，不占同步墙

## Stop conditions
- 直达 ls/read_file 已返回目标清单或内容，原搜索目标被覆盖
- 直读通道也超时（升级为环境问题处理）
- 目标事实已从权威回执取得

## Verification
- 替换通道后的回执状态=success 且耗时远低于超时墙（秒级）
- 目录清单能覆盖原 search_files 的候选集合
- 轨迹中不再出现对同一工具的同参重发

## Counterexamples
- 超时回执带错误码/部分输出（EPERM、404、exit≠0、traceback）——那是可诊断错误，按错误语义处理，不属零信息超时
- 首条命令本身已知是长活（限流 API 全量抓取、长编译）——应首次即后台化/分片，而非判环境故障或换搜索策略
- 环境文档已声明某工具确定性降级（如沙箱内 ps EPERM、launchctl 空输出）——用文档化替代工具（lsof/sysctl），属已知降级映射，不适用本卡
