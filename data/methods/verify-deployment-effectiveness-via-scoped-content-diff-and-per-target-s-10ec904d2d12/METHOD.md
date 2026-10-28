---
method_id: verify-deployment-effectiveness-via-scoped-content-diff-and-per-target-s-10ec904d2d12
name: verify-deployment-effectiveness-via-scoped-content-diff-and-per-target-stage-facts
description: 部署/重启被报告完成（『已经重启』）而我方关键修复仍在未合入分支时，不把『已部署』当整体事实，拆成两问以内容裁决：①重启回执已按目标给出成功/失败分区，失败目标清单即待处理服务核查表，不从日志枚举重推；②对我方关键提交做祖先包含检查，但 SHA 不在 main ≠ 修复丢失——移植/cherry-pick 会换 SHA，且合流提交自述的移植范围可能小于全批，唯一裁决是对关键文件的 scoped git diff（deployed..head）。失败目标用最小通道核活进程谱系后经受管通道重启。本集一次 diff 实锤 992 行安全修复不在部署内，并发现 web 之外两服务仍跑旧代码。
aliases: 部署了但我的修复生效没, 语义移植到底带没带我的提交, 重启后部分服务还在跑旧代码, commit 不在 main 是不是丢了, 部署生效性核实, 版本分裂对齐
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9982762e-d202-481b-9ca3-178124e943de:4035:0d6e71dd366820e4389d
evidence_refs: learning:learn:650f53cffbd3
created_at: 2026-10-25T23:15:37.615810+08:00
updated_at: 2026-10-25T23:15:37.615810+08:00
---
## Trigger
用户或并行会话报告『已经重启/部署完成』（回执含实际部署 commit 与逐目标 stage 结果），而我手上有关键修复提交（P0/P1）尚未合入 main，或部署 commit 与我方分支 head 不一致

## Discriminator
重启回执本身已分区逐目标成败（web ✓ / feishu、learning ✗）并给出部署 commit id；main 合流提交信息把『语义移植』范围自述为仅 webui 子集。这三个当时已知事实把『我的修复是否生效、哪些服务真跑新码』缩为一次祖先检查 + 一次对关键文件的 scoped diff，无需按提交枚举 stat、重列区间或扫全部重启日志

## Short path
- 读重启/部署回执：提取 deployed commit 与逐目标 stage 结果；失败目标清单=待处理服务清单，不再从日志枚举重推同一事实
- 逐个关键提交跑 git merge-base --is-ancestor <sha> <deployed>（或 branch --contains），一次回答 SHA 包含性
- SHA 缺席且合流信息提到移植/语义移植时，禁止按 SHA 或提交信息下结论：git diff <deployed>..<head> --stat -- <我方关键文件> 以内容裁决（空 diff=已移植生效；非空=真缺失，量化行数并给出用户风险窗口）
- 失败目标：最小通道核活进程谱系（启动时间/加载 release 路径 vs 部署时刻），经受管 service 通道重启后验证心跳/generation
- 汇报量化缺口、风险提示与合入路径选项；包含性与逐目标存活两问均答复后停止

## Stop conditions
- 关键文件上 deployed..head 的 scoped diff 为空（或仅剩测试/格式差异）→ 修复已生效，关闭风险窗口，不再继续核
- 所有目标活进程确认运行 deployed commit 且包含性已判 → 汇报即止
- 逐目标 stage 结果与活进程谱系已相互印证后，不再扫重启日志/会话文件重推

## Verification
- 进程加载的 release 路径与启动时间同 deployed commit 及部署时刻一致
- 祖先检查与 scoped diff 互相印证：SHA 缺席+非空 diff=真缺失；SHA 缺席+空 diff=已移植，两个方向都不单凭 SHA 判
- 重启后失败目标心跳/generation 更新且运行版本等于 deployed commit

## Counterexamples
- 部署 commit 是我方分支的 fast-forward 后代：祖先检查一次即足，无需再跑内容 diff
- 移植真实完整（scoped diff 仅剩测试/格式差异）：SHA 不在 main 不代表修复缺失，禁止仅凭 SHA 告警
- 进程从 .releases/<sha> 发布镜像树加载：包含性必须对该树判定，本地 main 可能领先/落后，先钉实际加载树再比
- 单服务系统：逐目标分区退化，只剩包含性一轴
