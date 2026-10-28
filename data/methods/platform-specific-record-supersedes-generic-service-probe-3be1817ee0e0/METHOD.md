---
method_id: platform-specific-record-supersedes-generic-service-probe-3be1817ee0e0
name: platform-specific-record-supersedes-generic-service-probe
description: 用户点名"按以前经验"执行某本机应用操作（如重启向日葵），检索已命中同时写明平台（"在这台 Mac 上"）、精确实体/路径与端到端步骤的已验证记录。此时不要再跑平台通用服务枚举：平台不匹配时（macOS 上 systemctl、tasklist）空输出/退出码127是结构必然，无法区分"未安装/未运行/命令不适用"，属零信息动作且易被误引为状态证据（本集最终答复就把 systemctl 空输出错归因于别名问题）。残余未知只剩当前运行时状态（pid），用记录字面 token 做一次平台正确的定点检查，随后按记录步骤执行，以 pid 新旧对比验证收尾。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:ef2eae2c-dfe1-4a01-8c66-440fa10c9637:0:a52f413cf188bd927eec
evidence_refs: learning:learn:817f9c2590cb
created_at: 2026-10-15T19:29:13.960322+08:00
updated_at: 2026-10-15T19:29:13.960322+08:00
---
## Trigger
用户要求按经验/记忆执行某本机应用操作，且记录检索已命中同时包含平台标识、精确实体名/路径与完整操作步骤的已验证记录；或已持有本机平台证据，而下一步候选是平台类型化命令（systemctl/tasklist/launchctl/sc query 等）做服务或进程发现

## Discriminator
记录是否已同时给出 (a) 平台 (b) 精确实体/路径 (c) 端到端步骤。三者齐备时，平台通用枚举被记录整体取代，唯一残余未知是可定点查询的当前 pid/运行状态；且平台不匹配命令的空输出是结构必然而非状态信号——本集此前已有 tasklist 退出码127、systemctl 空输出两次同类空烧

## Short path
- 按用户指示检索记录；用户原词 miss 后只宽化一次（换 kind 或别名），命中含步骤的记录即停
- 检查命中记录是否齐备平台+实体+步骤；齐备则宣告唯一残余未知=当前运行时 pid，不再做发现性探测
- 用记录字面 token 做一次平台正确的定点检查（如 ps aux | grep -i awesun），同时确认进程存在且与记录平台一致
- 严格按记录步骤执行：kill 记录点名的角色进程（主客户端+桌面代理），不动记录声明保留的进程（root 服务），再 open -a 记录路径
- 事后用同一 token 复查：目标进程 pid 已换新、保留进程 pid 未变即验证完成；无法取证的信号（如服务端 online）如实标注未核验后停止

## Stop conditions
- 记录步骤已执行且定点复查显示目标进程 pid 更新（或等效运行时证据）
- 字面 token 定点检查为空且记录断言该实体在运行时，先用记录 token 重写 pattern 复查一次，仍矛盾才转入发现模式并怀疑记录过时
- 检索宽化一次后仍未命中含步骤的记录，才允许平台通用发现（且须先确认平台）

## Verification
- kill 前后同一字面 token 的进程快照对比：应换新的进程 pid 已变、记录声明不动的进程 pid 不变
- 最终结论只引用平台正确命令的输出；任何平台不匹配命令的空结果不得写入证据链
- 逐字核对执行命令与记录一致：进程角色、app 路径均取自记录而非同义改写

## Counterexamples
- 记录未写平台或来自另一台机器（如 Linux 的 systemctl 单元名）——须先 uname 确认平台再选命令，此时通用探测是必要步骤而非冗余
- 记录只给目标不给步骤（"把它重启就行"）——方法本身是残余未知，状态发现不可省略
- 记录已过时（应用卸载/改名）——字面 token 与重写 pattern 均为空时，应怀疑记录本身并回到发现模式，而不是继续套用旧步骤
