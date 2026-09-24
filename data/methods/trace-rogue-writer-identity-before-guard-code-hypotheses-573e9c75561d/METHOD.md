---
method_id: trace-rogue-writer-identity-before-guard-code-hypotheses-573e9c75561d
name: trace-rogue-writer-identity-before-guard-code-hypotheses
description: 当权威回执证明动作已成功、而派生观察面（面板/status/manifest）报失败时，先读矛盾记录自带的身份元数据（pid/作者/时间戳）并与权威身份比对；把不一致的那条身份当作 provenance 边，沿它去运行日志与进程时间线找该写入者的产生通道与触发时刻，而不是先深读防御代码语义或自行构造竞态假说。代码只在时间线锁定『谁在何时写』之后用于确认机制。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2507:337d6588f7638264d159
evidence_refs: learning:learn:cc205522e7ad
created_at: 2026-09-24T05:43:19.170088+00:00
updated_at: 2026-09-24T05:43:19.170088+00:00
---
## Trigger
权威证据（receipt/回执/检查点）与派生观察面（面板/status/manifest）对同一事件结论矛盾，且矛盾记录内含可核验身份（pid/author/时间戳）与权威身份不一致

## Discriminator
矛盾记录内嵌身份（如 pid=29502，已死）不等于权威回执身份（如 pid=29418，存活且监听端口）——这一条事实把『动作是否发生/代码是否有 bug』缩成『谁在何时产生了写入者 29502』；若守卫代码 docstring 已点名已知肇事类（restart 探测路径短命进程），它就是现成的 provenance 边，无需再枚举写序竞态假说

## Short path
- 核对权威侧：重启回执（rc=0、pid、git_head）+ 当前端口监听者（lsof）→ 动作确已发生；未知量收窄为『观察面为何相反』
- 读观察面数据源（如 runtime_manifest.web.json），取其内嵌身份与回执比对 → 隔离出一个野写入者身份（pid 已死、非权威通道产物）
- 沿该身份查运行日志与进程时间线（guard/拉起脚本日志、ps 启动时间），定位其产生通道与触发时刻；已知其非权威通道所生，必存在第二通道
- 时间线锁定『谁在何时写』后，再读相关代码确认机制（守卫 docstring 点名的探测路径即首要嫌疑），而非先从模块第 1 行通读
- 根因确立即停止发现；实施修复（源头互斥 + 观察面兜底）、双向单测、并拨正观察面记录

## Stop conditions
- 野写入者的产生通道与触发时刻已有日志实证，且落在权威动作造成的时间窗（如端口空窗）内
- 记录无可用身份或日志不可得时，已显式切换到代码分析/复现分支

## Verification
- 时间线一致性：野写入者 spawn 时刻落在权威动作的窗口内（如停旧进程到新进程监听之间的空窗）
- 修复后双向用例：误报场景消除 + 真死场景仍如实上报；观察面结论与端口监听者一致

## Counterexamples
- 矛盾记录不含任何身份元数据（无 pid/author/ts）→ 无 provenance 边，应直接代码分析或宽发现
- 记录本身正确、是观察逻辑误读 → 应先读观察面代码；时间线只会还写入者清白
- 日志已轮转/缺失 → 时间线相关不可行，退回守卫语义分析与复现
- 权威回执自身可能过期或不可信 → 不可单边锚定，两侧需独立核验
