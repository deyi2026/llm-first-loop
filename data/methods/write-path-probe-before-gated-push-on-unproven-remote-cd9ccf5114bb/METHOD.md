---
method_id: write-path-probe-before-gated-push-on-unproven-remote-cd9ccf5114bb
name: write-path-probe-before-gated-push-on-unproven-remote
description: 多远端推送序列中，审查闸审计的是待推内容（提交清单/敏感文件/目标 ref），不审计『本环境能否通过该远端认证』；对公开 HTTPS 仓库，匿名 ls-remote 即 exit 0，绿灯对写凭据零信息。因此对从未在本环境成功推送过的次远端，应在付出闸成本（独立审查子代理+阻塞等待）之前，先用非变更的写路径探针（git push --dry-run 或 git credential fill）确认认证可用；探针报 could not read Username / Device not configured 即分类为凭据缺失：跳过闸、直接向用户升级（补凭据/换 SSH/暂缓），不为注定执行失败的动作排队过闸。各远端结论独立收口，互不污染。
aliases: ls-remote 通了不代表能推上去, push 报 Device not configured 先查钥匙串, 公开仓库读不登录写要登录, 没推成功过的远端先探认证再过闸, 别为推不动的远端白等一轮审查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f4fefaa7-cbbe-40e2-8ebf-3d7c794b1dd7:89:a300f6a748ff0e5ccc12
evidence_refs: learning:learn:bb774d2c8cc6
created_at: 2026-10-24T23:12:23.667718+08:00
updated_at: 2026-10-24T23:12:23.667718+08:00
---
## Trigger
计划依次向多个远端 git push（或执行任何带强制前置闸/高 setup 成本的非幂等远端写动作），其中存在本环境无成功写历史、走 HTTPS 匿名可读的次远端；运行环境非交互、无 TTY 凭据输入。

## Discriminator
推送前已知的两条事实：(1) records 检索『该远端的 push 历史』返回未找到匹配（无本环境成功写记录）；(2) 该远端 URL 为 HTTPS 公开仓库，ls-remote 不触发认证即可成功——读路径绿灯不构成写凭据存在的证据。真正的判别事实只能来自写路径探针的退出码。

## Short path
- 主远端推送并 ls-remote 复核后，列出剩余待推远端；当前未知量：每个次远端在本环境是否具备写凭据。
- 对每个次远端跑非变更写路径探针（git push --dry-run <remote> <branch>，或 git credential fill）；exit 0 → 环境可执行。
- 探针失败且错误为 could not read Username/Device not configured → 分类为凭据缺失（非分叉、非网络）：跳过审查闸，直接向用户报告缺口与选项（补凭据/换 SSH remote/暂缓）。
- 探针通过者才进入审查闸 → 等待有效 PASS → 执行 push → ls-remote 复核远端 SHA = 本地待推 SHA。
- 各远端独立收口：一个远端缺凭据不影响已成功远端的完成判定，也不触发对失败远端的盲目重试。

## Stop conditions
- 每个远端要么 push 后 ls-remote SHA 与本地待推 SHA 一致，要么已确认凭据缺失并升级用户；不再对缺凭据远端发起闸或等待。
- 探针报 non-fast-forward/分叉类错误时退出本方法，转分叉根因诊断。

## Verification
- 探针退出码与错误串分类：could not read Username / Device not configured = 凭据缺失；其他错误另行根因分析，不复用同一处置。
- push 后逐远端 git ls-remote <remote> main 复核远端 SHA 等于本地 SHA。
- 确认探针全程只读：未更新任何 ref、未改工作区。

## Counterexamples
- 私有远端：ls-remote 本身就要求认证，失败的 ls-remote 已是探针，无需再加 dry-run。
- SSH remote + ssh-agent：身份单一随连接可用，写探针多余，直接走闸。
- 远端已有本环境成功推送史（凭据助手有条目）：按已验证远端处理，可跳过探针直接过闸。
- 闸成本极低（秒级同步审查）时，探针省不出时间，走闸失败后再分类反而更短。
- 闸规则明确要求『任何推送意图先过闸』且禁止任何前置远端接触时，不得重排——本方法只前置只读探针，须确认其不落入场规则的禁止范围。
