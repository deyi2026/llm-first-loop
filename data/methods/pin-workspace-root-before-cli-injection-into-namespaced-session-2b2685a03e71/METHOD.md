---
method_id: pin-workspace-root-before-cli-injection-into-namespaced-session-2b2685a03e71
name: pin-workspace-root-before-cli-injection-into-namespaced-session
description: 跨会话唤醒/注入任务中，平台无专用 wake 工具时，官方机制是第一方 CLI 的会话复用入口（--session <id> 追加用户消息并触发 run）。首次调用前必须先解决两个先决未知量：①注入入口是什么——读 CLI 自述/help 即可得，勿全树 grep wake/inject 关键词；②被调进程解析的 workspace root 是否与会话存储命名空间一致——会话目录按 workspace 路径编码分目录（data/sessions/<encoded>/），安装版/venv 内 CLI 的默认 root 常落到 .releases 安装目录，于是『会话明明存在却 Session not found』的第一假设是命名空间错位：用 CLI 的 paths 自报命令查解析值并显式传 --workspace 重发，而不是回头重搜会话是否存在。注入消息须注明出处与授权边界（由哪个会话在用户授权下注入，非用户本人发言）。
aliases: Session not found 但会话明明存在, 给休眠会话发消息唤醒, CLI 默认 workspace 落到安装目录, 会话按 workspace 路径分目录存储, lfl --session 注入消息触发 run, 跨会话唤醒的官方入口在哪
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:1914:13864398c984b5ec0dfd
evidence_refs: learning:learn:756db550aa69
created_at: 2026-11-08T10:08:05.859243+08:00
updated_at: 2026-11-08T10:08:05.859243+08:00
---
## Trigger
需要向另一个（休眠的）agent 会话注入消息并触发其 run（唤醒、催收、移交），平台无专用 notify/wake 工具，只能走本仓第一方 CLI 的 --session 会话复用入口；且此前回执或目录枚举已可见会话存储按 workspace 路径编码分目录存放。

## Discriminator
store 命名方案已在数据树中暴露：data/sessions/<workspace路径编码>/ 这一目录名证明会话查找按 workspace 命名空间键控；被调 CLI（安装版二进制/venv 入口）会自行解析默认 workspace root，与当前项目 root 不一致时，对确实存在的会话也返回 not found。『记录存在却查不到』= 命名空间错位信号，而非记录缺失。

## Short path
- 从已拉取的协调/会话状态回执确认目标会话 owner 与 last-activity（确属休眠）及待消费的协调请求；未知量：官方注入入口是什么。
- 读第一方 CLI 头注释或 --help（会话管理一行通常已写明 '--session <id> 复用'），确定追加消息并触发 run 的入口与参数（--session、--message-file 或位置参数文本）；不做全树 wake/inject 关键词 grep。
- 首次调用前解析命名空间：跑 CLI 的 paths 自报命令（或沿用此前目录回执中 data/sessions/<encoded>/ 的命名证据），确定被调进程将解析的 workspace root；与项目 root 不一致则在同一条命令里显式传 --workspace（必要时连同 --data-dir）。
- 调用注入：--session <完整会话ID> + --message-file（消息内注明'由会话 X 在用户时间戳授权下经 CLI 注入，非用户本人发言'及动作边界）；成功判据 exit=0 且 run 被触发。
- 在独立面核验唤醒被消费：目标会话 last-activity/消息数前进、对应协调请求离开 pending、lane 侧出现对方动作；满足即停止。

## Stop conditions
- 注入命令 exit=0 且目标会话 run 被触发（消息数/last-activity 前进）。
- 独立面确认对方已消费唤醒（协调请求出队或对方在 lane/goal 侧出现动作）。
- 若 CLI 报 Session not found 但存储树内确有该会话目录：一次 root 修正（显式 --workspace）后即闭合，不再回头重搜会话记录。

## Verification
- 重查协调/会话状态面：目标会话 last 时间戳更新到注入时刻之后、消息计数增加。
- 对应待消费协调请求状态离开 pending；无越权副作用（注入消息的出处声明在案，未触发被禁动作如 push/改产品代码）。

## Counterexamples
- 目标 store 是全局账本、按记录 ID 直接寻址而不按 workspace 分目录（如 audit 下的 jsonl）：not found 即记录不存在，应转 ledger 按 ID 检索，而不是调试 workspace root。
- 环境已显式导出正确 workspace root，或 CLI 在项目目录内运行且默认解析本就正确：not found 另有原因（会话 ID 抄错、需要完整 ID 而非短前缀），本卡不适用。
- 平台工具面本身提供专用 session-message/notify 工具：直接用工具，shell 出 CLI 反而是绕远。
- 目标会话属于另一 workspace 或另一宿主、本机存储树内无其记录：本地 CLI 注入结构性不可达，应升级到用户/宿主侧通道。
