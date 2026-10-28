---
method_id: consult-artifact-repair-history-before-reproposing-change-20f25d77c4e0
name: consult-artifact-repair-history-before-reproposing-change
description: 在被问'改这个配置/系统设置有没有把握'时，先别急着评估方案本身或打包票，先查目标 artifact 的干预历史：定位输出里若出现带时间戳的备份目录、Before/After 成对文件、repair-report/receipt，且命名与当前问题同域，先读记录再表态——方案可能已被执行过、已验证、且其局限已被写明。本集首轮 locate 已显示 .repair-backups/<时间>/ 下的 Before-AweSun-Repair / AweSun-Repair 成对文件，却先枚举了进程、路由、应用目录约 9 步，最后读 repair-report 才发现'B 方案'昨晚已做过：机制已验证（/32 走 en0），但局限（对端动态 IP 不自动覆盖）也已写明，今晚恰好命中，直接推翻'根治'判断。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:87a1296f-1ec4-4fb1-9307-a09a02309ac3:92:a87452809c2adeef9ac1
evidence_refs: learning:learn:d81444971345
created_at: 2026-10-16T19:28:18.221322+08:00
updated_at: 2026-10-16T19:28:18.221322+08:00
---
## Trigger
准备提出、评估或批准对一个存在历史改动痕迹的可变 artifact（配置文件、系统设置、部署）的修改方案，并被要求对风险或把握表态；或定位该 artifact 时，输出中已出现时间戳备份、before/after 成对文件、report/receipt 类干预痕迹

## Discriminator
定位/枚举输出（或目标配置 key 的当前值）中是否出现与当前问题同域的显式干预痕迹：带时间戳的 .bak / .repair-backups/<时间戳>/ 目录、'Before-X-Repair'与'X-Repair'成对文件、repair-report.md / receipt.json / 被标 superseded 的初版报告；或目标 key 中已存在同域专属条目（如指向远控对端的公网 /32）。存在即应把'该方案是否已被试过、记录的结论与局限是什么'列为第一未知量，而非先评估方案新颖性

## Short path
- 定位目标 artifact；同屏扫描输出中的相邻干预痕迹（时间戳备份、before/after 对、report/receipt），判断命名是否与当前问题同域
- 同域则先读 report/receipt（注意以最终版为准、redacted 文件只作线索），diff 非 redacted 的 real-source 备份对：未知量=方案是否已被执行、验证结论、已记录局限
- 用最小只读命令把历史结论与当前 runtime 对账：复现记录中的关键验证（如 route get 记录里的旧对端 IP），再测当前新值（如今晚对端 IP 走哪个接口）
- 若机制已验证但记录的局限命中当前场景，直接宣布原方案不适用并转向可证伪的临时可回滚实验（如运行时路由试探），不再重复提案原方案
- 回答用户时把'改动写入安全性'（有语法样本、有备份、可回滚）与'方案疗效'（以对账证据为限）分开陈述，不用前者给后者背书

## Stop conditions
- 已确认方案是否被执行过，且记录中的验证结论与当前现场对账一致（或发现记录被 superseded 而改用最终版）
- 确认无同域干预痕迹，转入常规现状检查

## Verification
- 记录中的关键断言在当前现场复现一致（如旧对端 /32 仍走物理口 en0）
- 记录声明的局限用现场观测证实或证伪（如新对端 IP 仍走 TUN 口 utun4）
- 报告目录存在 superseded 标记时，核对最终版时间戳晚于被撤回版，且最终版描述的回滚源（real-source 备份）确实存在

## Counterexamples
- artifact 无任何历史痕迹（新建文件、无备份目录）：没有可读记录，直接做现状检查即可，套此法只增加步骤
- 备份目录属无关工具（编辑器自动保存、包管理缓存）或命名与问题域不匹配：不展开读
- 历史记录本身可能已被撤回或过时（本例旁就有 initial-report-superseded.txt）：不能当终极真值，必须与现场对账后采用最终版
- redacted/脱敏副本不能当可加载真值：恢复与 diff 只能用 real-source 类备份（记录里通常自会声明）
