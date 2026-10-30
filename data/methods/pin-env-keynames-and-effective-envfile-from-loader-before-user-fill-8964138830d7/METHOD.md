---
method_id: pin-env-keynames-and-effective-envfile-from-loader-before-user-fill-8964138830d7
name: pin-env-keynames-and-effective-envfile-from-loader-before-user-fill
description: 教用户手工往 .env 填凭据（BotID/Secret/token）前，先从可执行工件钉死两个未知量：①键名以 loader 源码常量为准——既往运行回执里的报错/日志键名与设计文档冲突时，运行回执+loader 常量压倒文档（本集：文档 WECOM_* vs 代码 WECHAT_*，照文档填会静默不生效）；②生效文件以目标进程入口的 .env 加载路径 + runtime manifest 的 workspace_root 判定（手动 -m 启动按 CWD 读工作树 .env；受管服务读 .releases 快照 .env），不要靠枚举部署根目录猜。全程输出打码，验证只打印键名+长度，绝不让 secret 值出现在任何回执。
aliases: 教我填 .env 凭据, 变量名跟文档对不上听代码还是听文档, 好几个 env 文件不知道改哪个, 机器人 ID 和密钥填哪一行, 照文档配了却没生效是不是名字写错了, 改 env 前先确认代码读的是哪个键
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:2197:65ae4a3e49fabbfd57a2
evidence_refs: learning:learn:e7d89b5d7af1
created_at: 2026-10-30T07:07:29.221172+08:00
updated_at: 2026-10-30T07:07:29.221172+08:00
---
## Trigger
用户要求自己动手把凭据/密钥填进项目 .env（而非 agent 代填），且至少存在一个信号：设计文档与既往运行回执对环境变量名说法不一致；仓库有多个 .env 候选（工作树 mirror、.releases 发布快照、受管服务配置）；填错键名会静默不生效（loader 读到空即报缺失或跳过启用）。

## Discriminator
任务开始前已持有的既往运行回执（报错/日志）已给出代码实际读取的键名，与设计文档键名形成显式冲突——冲突本身就是判别信号：键名权威在 loader 常量定义（config 模块顶部 *_ENV 常量），一次作用域受限 grep 即可终局裁决，无需读文档长文或多轮试探；文件权威在入口加载路径与 runtime manifest 的 workspace_root，无需枚举部署根候选目录。

## Short path
- 对比既往运行回执键名 vs 设计文档键名；有冲突 → 未知量定为『loader 实际读什么键』，grep loader 常量定义一次裁决。
- 负向 grep：文档专用前缀（如 WECOM_）在 src/scripts 零命中 → 证实文档命名是孤本，键名结论关闭。
- 未知量『目标进程读哪个 .env』→ 读目标组件入口（__init__.py/main）确认 .env 加载方式（CWD 相对 load_env_file 即工作树根 .env）。
- 未知量『受管服务读哪个 .env』→ 读 runtime manifest 的 workspace_root（.releases/<hash>），并核对服务枚举是否含该组件——不含则用户只需填入口对应的那个 .env。
- 在目标 .env 以打码方式定位占位行号（只显行号/键名，不显值），给出锚定行号的填法与只打印长度的验证命令，停止。

## Stop conditions
- 键名已由 loader 常量 + 负向 grep 双重确认；
- 生效 .env 已由入口加载路径或 manifest workspace_root 唯一确定；
- 占位行号已定位且验证方式不回显任何值——立即交付填法，不再扩大枚举（不列部署根候选目录、不读与目标组件无关的 manifest 键）。

## Verification
- 打码回读：grep -n 定位键行并遮值，确认恰好是预期的键/行号、没有误写其他键；
- awk 只打印各键值的 length（长度>0 即已填入），secret 值不出现在任何输出或对话上下文；
- 负向验证：按文档前缀 grep src/scripts 零命中，确认『照文档填会静默不生效』的警告成立。

## Counterexamples
- loader 按前缀迭代或从远端/数据库 schema 动态读键时，单一常量 grep 不足，必须读迭代或 schema 代码；
- 目标组件已纳入受管服务枚举（service_control）时，生效文件是 .releases 快照内的 .env，『入口按 CWD 读』规则会误导，工作树 .env 填了也不生效；
- 文档与运行回执键名一致时，跳过键名仲裁，直接进入文件定位；
- agent 代填（值进上下文）与用户自填（值绝不进上下文）是不同路径，本方法只针对用户自填。
