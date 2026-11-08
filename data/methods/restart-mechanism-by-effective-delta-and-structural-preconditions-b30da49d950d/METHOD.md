---
method_id: restart-mechanism-by-effective-delta-and-structural-preconditions-b30da49d950d
name: restart-mechanism-by-effective-delta-and-structural-preconditions
description: 用户要求'让已发布状态生效'式重启常驻服务时，重启机制由实测生效差值决定，而非继承上轮报告的编号方案或入口权威度。先取活进程事实(pid/argv/cwd/父进程/env)+部署清单+资产盘点，逐一确认运行代码身份(仓库HEAD或已装包src与目标commit比对)；若各进程代码已≡目标、唯一差值是启动期扫描的内存索引落后于物理资产，且权威受管入口的身份类前置(运行根须为git worktree、须有.venv)在本布局结构性缺失，则按原进程形态逐个TERM→验证→下一个的保形重启即充分最小机制；记账如实保留desired，不伪造.venv/.git闯身份门，不虚报代次对齐。
aliases: 重启方式跟生效差值走, 代码已经一样还要不要换部署, 老进程原样拉起, 身份门过不了别硬闯, 索引计数对不上先查是不是启动扫描, 接管手工拉起的服务进程
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7007267a-8cde-4b7c-bcc4-b677b3653671:78:c2d48682ac3c8628c756
evidence_refs: learning:learn:10ef8107de74
created_at: 2026-11-07T01:40:26.477638+08:00
updated_at: 2026-11-07T01:40:26.477638+08:00
---
## Trigger
'让已发布代次/知识资产在常驻服务生效'的重启请求，且存在继承来的或惯用的'权威受管入口'方案(managed service_control/官方重启脚本)，而当前宿主布局与其拓扑假设是否相容未经核实；或已发现现有进程并非受管拉起。

## Discriminator
机制精读前已在手的三类事实：①拉起关系——目标进程父进程/cgroup(裸bash、终端scope=非受管；systemd unit dead)；②代码身份——cwd为仓库则git log显示HEAD≡目标commit+纯知识提交，wheel包则src与目标diff逐文件一致；③差值定位——服务自报的索引计数(9/0)落后于物理资产(19文件/2卡)且属启动期扫描。②③把候选从'整套受管重启'缩为'原样重启触发重扫'；布局事实(运行根=安装器状态目录非git仓库、目标checkout无.venv)再预判权威入口结构性不可行。

## Short path
- 取活进程真值：ps+/proc(cwd/argv/父进程/env/cgroup)+部署清单+资产物理盘点 → 解决'实际在跑什么代码、由谁拉起、生效差值是什么'
- 逐进程定代码身份：cwd为仓库则git HEAD/短log比对目标commit，wheel包则src目录diff目标 → 解决'差值是代码还是仅内存态'
- 若代码≡目标且差值仅启动期索引/缓存：对拟用的权威入口只做一次定点前置检索(其身份类硬门要求哪些目录/仓库结构)，不做全文精读 → 解决'该机制在本布局是否结构性可用'
- 前置结构性缺失且明确不可override → 判定受管绑定在本布局不可运行并如实上报，改走保形重启：逐个TERM→新pid+健康锚点验证通过→再动下一个，按原cwd/argv/env用setsid拉起，零绑定漂移
- 端点差值验证生效(索引计数对齐物理盘点、心跳connected、manifest healthy)，记账按事实输出：desired保留、不宣称代次对齐

## Stop conditions
- 三服务均换新pid且各自健康锚点通过(/health ok+索引计数=物理资产数、心跳connected且reconnect=0、manifest healthy且pid一致)
- 权威入口的结构性不可满足已定点核实并如实上报，不再尝试闯门或伪造目录结构
- 任一服务重启后验证失败即停，不连锁杀下一个

## Verification
- 新pid≠旧pid，启动时刻晚于TERM时刻
- 内存态差值消失：索引计数从落后值对齐物理文件数
- 绑定无漂移：工作区/资产目录/cwd与重启前一致
- 记账诚实：generation状态按事实描述(desired保留/不可运行)，不输出'已对齐'

## Counterexamples
- 运行代码≠目标commit(存在真实代码差值)→保形重启不充分，须先部署/升级，最小机制选择不适用
- 服务真由service_control/OS unit受管且有desired/live回执→必须走正式action/lease入口，TERM+自行拉起会造成记账脱管(registry-first场景)
- 索引为逐调用枚举而非启动扫描→根本无需重启，走刷新/失效即可
- 重启目标包含改变进程形态本身(如迁移到systemd守护)→保形即错误目标
- 用户明确把代次记账对齐当交付物→须先修复布局前置(把运行根做成合规worktree等)，不能跳过
