---
method_id: restart-bound-head-ci-closeout-failed-step-drill-ownership-guard-ade01954ba67
name: restart-bound-head-ci-closeout-failed-step-drill-ownership-guard
description: 重启/发布核验已把 live 进程绑定到具体 git head、且该 head 即仓库 tip 时，收口不止于『进程活着』：一次有界询查同时核对同步状态与该 head 的 CI 状态。若 CI 红，先从 run 列表分类——失败是否锁定在门禁 job（相邻扫描/安装验收 job 仍绿）、push 与 schedule 是否连续多轮同挂（持续回归 vs 偶发）；再只拉失败 job 的失败步骤日志，提取步骤名/错误数/涉事文件；作为新事实报告，并按涉事文件归属判断并发会话所有权，抢修邀约必须带防踩脚前置检查。
aliases: 重启对上了但流水线是红的, 部署提交 CI 挂了怎么定位, 只拉失败步骤的日志, CI 连红几轮算真问题, 别的会话在推这条线别抢修, 门禁挂在类型检查步骤
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:5263:51272f0888df0e7c778a
evidence_refs: learning:learn:083d25c777f6
created_at: 2026-10-31T11:11:32.947357+08:00
updated_at: 2026-10-31T11:11:32.947357+08:00
---
## Trigger
权威 status 回执已把重启/发布的 live 进程绑定到具体 git head，且该 head 与本地/远端 main tip 一致，收口还需确认仓库同步状态（未推提交、ahead/behind）时

## Discriminator
读任何日志之前，该 head 的 CI run 列表已同时给出三个可裁决事实：失败是否集中在门禁 job 而相邻 job（安全扫描、安装验收）仍绿；是否 push 与 schedule 触发连续多轮同挂（持续回归而非偶发）；失败 run 的提交是否即重启所绑 head。三点齐备才值得花一次日志查询下钻。

## Short path
- 从重启 status 回执钉死绑定 git_head 与 per-target 终态（沿用既有重采样判据）；未知量：重启是否生效
- 一次有界收口询查该 head 的仓库健康：ahead/behind、未推提交数、main 的 CI run 列表；未知量：同步是否收口、该 head 流水线是否绿
- CI 绿则收口；红则先用列表分类持久性（连续轮数+触发类型+失败 job 分布），此阶段不读日志不重跑
- 分类为持续门禁失败后，仅查看失败 job 的失败步骤日志（如 --log-failed），提取步骤名、错误数、涉事文件；不拉全量日志
- 作为新事实报告（job/步骤/文件/连续轮数），并核涉事文件归属哪条活跃改动线；提出修复邀约时显式声明先确认并发会话不在改同一批文件，未确认不动手

## Stop conditions
- 重启终态与仓库收口事实（同步状态、该 head CI 状态）都已取得即停止；修复动作须等用户确认
- 该 head CI 全绿：不做任何日志下钻
- 失败日志显示为环境/基础设施类偶发（安装或网络步骤超时）而非代码诊断输出：改判偶发，最多回看一轮历史 run

## Verification
- 核对失败 run 的提交 SHA 与重启绑定 head 一致，避免把其他分支/提交的失败记到本次部署头上
- 被短路未执行的步骤（如测试因类型检查失败被跳过）必须如实描述为『未跑』而非『通过』
- 连续失败轮数与触发类型从 run 列表逐条对上后才可断言『不是偶发』
- 报告的涉事文件清单与日志中的错误数量一致

## Counterexamples
- 部署 head 是刻意固定的旧版本/回滚（落后 main）：main tip 的 CI 红不说明部署版本不健康，最多查 pin SHA 自身的 CI
- 失败只发生在 nightly/非门禁 job（如真实 LLM 冒烟）：非 main 门禁回归，如实上报即可，不必下钻抢修
- 涉事文件全部属于本会话自己的在途改动：无并发所有权冲突，直接修，不需要防护性协调
- 任务范围明确只答『服务起没起来』且无任何收口授权：只报重启事实，不外扩到仓库健康检查
