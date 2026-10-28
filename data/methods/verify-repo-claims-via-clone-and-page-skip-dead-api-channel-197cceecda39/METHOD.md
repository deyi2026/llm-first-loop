---
method_id: verify-repo-claims-via-clone-and-page-skip-dead-api-channel-197cceecda39
name: verify-repo-claims-via-clone-and-page-skip-dead-api-channel
description: 评估二手文章/转述对某远端 Git 仓库的断言时，先枚举可核查断言并为每条指定最廉价且已验证可用的权威通道：内容计数/license/提交史→浅 clone；页面可见元数据（stars/描述）→仓库 HTML 页；仅 API 独有事实才调 metadata API。任一通道回执显式退化（解析后全 null 字段，或明文 rate limit）即标记该通道本次会话不可用，把剩余未知量改道到替代通道，而不是 sleep 后同参重试。本集对 api.github.com 先后 3 次尝试（全 null、限流、sleep20 后仍限流），而 star 数最终由第 1 步已成功用过的 HTML 页一次取回；clone 早已给出全部内容真值（90 bot/598 SKILL/2 commits/无 LICENSE）。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:881d9c3f-2c5a-47a8-b605-9596af0a61b1:4:8c0f29b148e4f9405f67
evidence_refs: learning:learn:232788efc8bd
created_at: 2026-10-17T07:39:54.123406+08:00
updated_at: 2026-10-17T07:39:54.123406+08:00
---
## Trigger
用户要求评估或核实关于某远端代码仓库的转述性断言（文章/摘要给出的数量、license、历史、社区信号），且同一事实存在多条获取通道（git clone、仓库 HTML 页、静态 Pages/raw 资源、metadata API），其中至少一条通道已成功返回过同域事实

## Discriminator
回执本身显式给出通道状态：API 响应解析后所有期望字段为 null（保存的是错误报文而非元数据），或正文明文 rate limit exceeded 且退出码非 0；同时 git clone 已成功给出目录计数/提交史/license，且仓库 HTML 页在更早步骤已成功取回 README——这些当时已知事实足以判定继续调用该 API 不会新增信息，star 等剩余元数据应改走已验证可用的 HTML 通道

## Short path
- 枚举转述中的可核查断言（数量、license、提交史、star），每条标注最廉价权威通道：内容→clone，页面可见元数据→HTML 页，仅 API 独有者→API
- 一次取仓库 HTML 页：同时解决存在性、README、stars 多个未知量
- 浅 clone：对内容断言直接 diff（目录计数、SKILL.md 计数、git log、LICENSE 存在性）
- 静态发布物（Pages index.json）核对发布一致性
- 本机只读合成（--dump-config/--help 类命令）验证兼容性，不安装
- 汇总'转述 vs 实测'对照表并停止；期间任何通道显式退化即改道，不再同参重试

## Stop conditions
- 每条可核查断言均有具体通道回执支撑，对照表足以回答用户的借鉴决策
- 某通道返回明文限流/全 null 退化回执 → 该通道本次会话封禁，禁止同参重试
- 安全面按固定扫描线（脚本哈希、依赖、注入模式、外发域名、disabled 条目）覆盖后停止，不逐字读全部 SKILL.md

## Verification
- 对照表中每个'实测'值能指回具体回执（clone 计数、index.json plugins 长度、HTML 页 stars）
- 轨迹中不存在对已显式限流通道的第二次同参调用
- 兼容性结论来自本机只读合成输出而非文档声明

## Counterexamples
- 需要 API 独有且页面不可见的事实（精确 forks/issues 计数、贡献者列表、时间戳）且持有认证 token 时，应换认证头使用 API，限流退避重试合理
- 私有或超大仓库无法 clone 且仅 API 可达时，API 是唯一通道，不应跳过
- 只需快速印象、无逐条核数需求时，读 README 即可，clone 属过度
