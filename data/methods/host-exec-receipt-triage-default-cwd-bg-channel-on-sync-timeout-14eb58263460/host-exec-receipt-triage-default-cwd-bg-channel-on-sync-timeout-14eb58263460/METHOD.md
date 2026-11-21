---
method_id: host-exec-receipt-triage-default-cwd-bg-channel-on-sync-timeout-14eb58263460
name: host-exec-receipt-triage-default-cwd-bg-channel-on-sync-timeout
description: 受管任务做宿主侧命令核实时，失败回执的层次决定修复轴。参数层错误（命名某目录无效）：若该无效值在全部任务材料中从未出现，就是从旧环境移植的虚构字面量，修复=删除该字段、回退会话默认 cwd——材料对目标全程只用相对路径引用，本身就是默认寻址根的证据。超时层错误：回执是工具级固定 60s、零输出，且被超时的命令本身是 pwd 级平凡短命令，则故障在同步通道而非命令，修复=同一探测改投同工具的后台 job 通道，一次调用既验证通道假设又取回事实，不原地重试同步通道。后台 job 内把全部待核 git 事实打包一次取齐。调度绑定遇参数约束拒绝按回执自述差分修参数即可，不开诊断。把『虚构路径→超时→重试→再超时→后台』压成默认寻址+后台打包一两步。
aliases: shell命令一直60秒超时怎么办, 前台shell卡死换后台job, workdir不是有效目录报错, pwd都超时疑似通道故障, 别猜仓库绝对路径, 后台任务一次打包git核实
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:70:14b3b4db6af3d1268a86
evidence_refs: learning:learn:bab154f14ad9
created_at: 2026-11-18T23:47:40.595381+08:00
updated_at: 2026-11-18T23:47:40.595381+08:00
---
## Trigger
受管任务需宿主侧命令核实 worktree/git 事实，首个 execute_command 类调用返回命名无效 workdir 的参数错误，或对平凡短探测返回工具级固定时限超时且零输出

## Discriminator
两条当时可见事实：(1) 任务材料对目标仓库的全部引用都是相对路径（形如 .worktrees/…），任何绝对仓库根都未在证据中出现过 ⇒ 会话默认 cwd 即寻址根，调用里出现的绝对 workdir 是无证据移植值；(2) 超时回执是工具级（固定时限、无 stdout/exit code），且被超时命令本身是 pwd 级平凡命令 ⇒ 同步通道整体故障，而非单条命令挂起

## Short path
- 发起探测时不携带任何虚构绝对 workdir：材料全是相对路径 ⇒ 直接对默认 cwd 执行，命令首行放 pwd 顺便裁决寻址根
- 若被参数层拒绝且回执点名的值不在任何材料中 ⇒ 删除该字段重发，不从旧环境移植替代值
- 若平凡短探测遭工具级超时零输出 ⇒ 不重试同步通道，同一探测改投后台 job（一次既证通道假设又取事实）
- 后台 job 内打包全部待核事实（pwd/HEAD/分支/清洁度/基线/远端分支存在性）一次取齐
- 后台回执 exit=0 且输出与授权逐项一致 ⇒ 核实完成转入受管闸；调度类参数约束拒绝按自述差分修参数即可

## Stop conditions
- 后台 job 回执 exit=0 且 HEAD/基线/分支/清洁度与授权精确一致 ⇒ 停止核实，转入受管闸流程
- 同一探测在后台通道同样超时 ⇒ 通道假设被证伪，停止换通道，转查沙箱/资源等机器级原因
- 任何核实事实与授权不符 ⇒ 立即 HOLD 回报，不再继续执行层排障

## Verification
- 后台 job 回执 exit=0，stdout 含 pwd 行且 rev-parse 输出与授权 SHA 逐字符一致
- 后续 git 核实回执中标注的 cwd 与 pwd 输出一致，确认默认寻址根成立

## Counterexamples
- 任务书或平台文档明确给出仓库绝对根路径或规定 workdir 取值 ⇒ 直接采用，相对路径推断不适用
- 超时的是重命令（跑测试套件、网络 clone、可能卡凭据提示）⇒ 单次超时更像命令级挂起，先简化命令或加预算判别，不立即换通道
- 工具面根本没有后台/异步执行模式 ⇒ 升级分支不可用，改为排查 pager/凭据等交互挂起
- 后台 job 也超时 ⇒ 同步通道故障理论被证伪，别继续换执行面，应查沙箱与机器资源
