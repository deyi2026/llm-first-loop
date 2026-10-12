---
method_id: lifecycle-registry-first-restart-not-name-grep-absence-0acaca0d0557
name: lifecycle-registry-first-restart-not-name-grep-absence
description: 重启/检查一个以口语名引用的应用（如“向日葵”）时，不要用名字关键词 ps|grep 的空/近似空输出来判定“未运行”——该管道至少会匹配到 grep 自身，退出码 0 即代表至少有 1 行匹配，逻辑上不可能证明缺席。应直接查系统 lifecycle registry（launchctl list / systemctl 等价物）：vendor bundle-ID（com.<vendor>.*）不随产品改名漂移（向日葵→Sunlogin/AweSun），一次调用同时给出运行状态、服务标签与 PID。再按组件的管理者选重启机制：launchd 组件用 kickstart -k，GUI 用 pkill 真实二进制名 + open -a。权限错误按组件单独报告，不混入任务成败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1696:469003bb91ee7ef0f65a
evidence_refs: learning:learn:9035595d469f
created_at: 2026-09-30T11:56:34.167469+08:00
updated_at: 2026-09-30T11:56:34.167469+08:00
---
## Trigger
用户要求确认或重启一个以口语名指代的应用/服务，其进程、二进制或服务标签可能使用另一品牌名或 vendor bundle-ID，而首个探针是基于名字关键词的 ps|grep 类命令。

## Discriminator
进入下一步之前回执已可见：ps|grep 管道退出码为 0 且有 1 行输出——grep 退出码 0 表示至少匹配 1 行（至少匹配到含模式的自身命令行），因此该探针不可能作为“无进程”的证据；同时本次助手却宣称“无输出、没有运行中的进程”，被随后 launchctl list 显示的存活 PID（GUI 54526 / desktopagent 54594）直接证伪。当时即可据此判定该缺席结论无效，转而使用以 bundle-ID 为键、改名不漂移的 lifecycle registry。

## Short path
- 第一步即查 lifecycle registry 并覆盖所有已知别名族：launchctl list | grep -iE 'oray|sunlogin|awesun|向日葵'（或 systemd/SCM 等价物）；一次调用同时回答“在不在跑、叫什么标签、PID 是多少”。
- 从 registry 行读组件结构：有 PID 的 label = 运行中的 launchd 组件；application.* 条目对应 GUI 进程；两者结合即可确定重启对象与所属域（gui/<uid>/<label> 或 system/<label>）。
- 按组件的管理者选重启机制：launchd 管的 agent/daemon 用 launchctl kickstart -k（KeepAlive 与否都成立）；非服务管理的 GUI 用 pkill -x <真实二进制名> && open -a <app名>，二进制名取自 registry/plist/lsof 回执而非口语名。
- 只读与重启机制直接相关的那一个 plist（确认 KeepAlive/域/路径）；不为“更确定”枚举全部 plists 或全目录扫描——本次 *unlogin* glob 就未命中 AweSun.app，app 路径直到第 3 步 lsof 才出现，说明别名枚举不可穷举。
- 一次合并的状态复查（registry + ps）确认新 PID ≠ 旧 PID 后停止；权限错误按组件单独标注“未动、需 sudo”，不进入重试循环。

## Stop conditions
- registry + ps 复查显示目标组件均已换新 PID 且正常运行
- 某组件因权限无法重启且无提权通道——停止并明确报告该组件需 sudo

## Verification
- 重启断言必须由同一次回执内的最新 registry+ps 列表支撑（新 PID ≠ 旧 PID），不得引用探查阶段的旧快照
- 区分权限类失败与真实重启失败：权限错误只标记单个组件状态，不否定整体任务

## Counterexamples
- pgrep（或 ps|grep -v grep）以退出码 1 干净地证明缺失、且用户只需“是否在跑”的布尔答案——名字探针已足够，不必强制查 registry
- 目标是无服务管理器登记的裸进程/脚本（registry 根本不收录）——会漏报，仍需 ps/lsof 直接探查
- 名字探针命中且 PID 明确、任务只是重启单个前台 app（pkill+open 即可）——不需要走 registry 全链路
