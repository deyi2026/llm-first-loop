---
method_id: scan-unpushed-range-before-first-push-under-privacy-line-76d0b6a472df
name: scan-unpushed-range-before-first-push-under-privacy-line
description: 用户对推送/公开镜像声明隐私红线时，检查面必须是『远端将收到的完整对象集』：全部未推送提交的 full diff + 即将入库的未跟踪文件，尤其覆盖自动入库的知识/经验卡——它们由真实 episode 派生，结构性携带内网 IP、用户名、home 路径、免密 SSH 拓扑。本集 episode：只查了 gitignore 对本地配置的覆盖（前向防护），昨日 knowledge 提交随今日改动一并推上第一个远端，敏感内容暴露约 10 分钟后才被只覆盖另一远端的审查门抓到，事后被迫 force-with-lease 重写历史。判据：首跳巡检同时出现『knowledge 入库』类提交与未推送提交，即可把扫描对象从今日文件缩到待推区间。
aliases: 推之前先扫一遍要传的提交, 经验卡里的内网信息别带出去, 隐私检查不只看gitignore, 自动入库的知识卡会带环境信息, 第一次推送前做完敏感扫描
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1850:374aa686a8dcf252514d
evidence_refs: learning:learn:d6709ef2d92a
created_at: 2026-10-29T21:31:27.471353+08:00
updated_at: 2026-10-29T21:31:27.471353+08:00
---
## Trigger
用户对对外不可逆动作（push / 发布 / 公开镜像同步）声明隐私或敏感红线；且首跳仓库巡检回执已显示存在非本会话产出的外传内容：近期有 knowledge/方法卡/经验卡等 episode 派生资产的自动入库提交，并且本地领先远端至少 1 个提交。

## Discriminator
首跳巡检输出同时含两个当时已知事实：(a) 提交历史里出现『knowledge 入库 N 张方法卡与经验卡』类自动入库提交——episode 派生资产天然嵌入环境标识；(b) 本地有未推送提交——外传载荷 ≠ 今日改动。二者合用即把『要隐私检查什么』从『今日文件 + gitignore 覆盖』缩到『待推送区间的全量 diff』。

## Short path
- 红线声明后第一个未知量：这次 push 远端到底会收到哪些对象？用 git log @{u}..HEAD 加待提交的未跟踪文件，定出确切外传载荷集合。
- 载荷集合含 episode 派生资产（knowledge/experience/方法卡目录）或任何非本会话提交 → 对整个区间 full diff 跑敏感模式扫描：内网 IP 段、user@、/home|/Users/<用户名>、免密/ssh 描述、token/密钥样串、主机名。
- 命中 → 在向任何远端首次推送之前完成脱敏与历史重写，让所有远端从第一天起只收干净提交；不得先推一个远端再等只挂在另一渠道的下游审查门。
- 推送后对最终区间 diff 复扫，回执 CLEAN 且各远端指向同一干净提交即停止。

## Stop conditions
- 待推送全区间（含即将入库的未跟踪文件）敏感模式扫描回执 CLEAN，且对每个对外远端分别独立确认过
- 或载荷确认仅含本会话新写内容、无任何自动派生资产，且逐文件人工审查已覆盖全部外传文件

## Verification
- 逐字核对扫描对象清单 = rev-list 远端..HEAD 的全部对象 diff + 新增 blob，而不是工作区状态或 gitignore 覆盖检查
- 每个远端分别确认最终区间扫描 CLEAN；不可用只覆盖单一渠道的审查门回执替代全渠道确认

## Counterexamples
- 全新仓库单提交、内容全部为本会话刚写、无任何自动派生资产 → 审今日 diff 即足够，全区间重扫是冗余动作
- 目标本身是内网私有远端且内网主机名/路径是交付必需 → 红线只约束公开渠道，盲扫脱敏会破坏功能
- 同一待推区间已有本会话的独立扫描 CLEAN 回执 → 不重复扫描，直接进入推送
