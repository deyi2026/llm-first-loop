---
method_id: live-pid-first-runtime-lookup-abefca85b64f
name: live-pid-first-runtime-lookup
description: 在含大量陈旧副本的 checkout（.worktrees/.venv/evals 等）里需要某运行中服务的运行态事实（监听端口、实际生效 env、cwd）时，先回看先前回执是否已给出该服务的存活 pid；有则以 OS 进程为第一来源：lsof -p <pid> -i 直接得端口，ps -E 得实际 env，再用 curl 等最小探针验证端点；repo 全文 grep 仅作 fallback 且必须限定路径排除噪声目录。本 episode 中 web UI 端口本可由已知 live pid 一步取得，却先经 evidence 检索、runtime 状态查询、全仓 toml grep（命中 evals chrome-profile 噪声）三步绕行后才用 pid 定位到端口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:882:0b54448dab8d6773b1e9
evidence_refs: learning:learn:37c58ad37f51
created_at: 2026-09-20T17:15:42.640609+00:00
updated_at: 2026-09-20T17:15:42.640609+00:00
---
## Trigger
需要获取某个正在运行服务的运行态事实（监听端口/实际生效环境变量/cwd），且早前回执（restart receipt、service status）中已出现该服务的 pid 且 pid_alive=true

## Discriminator
先前回执已明确给出目标服务的存活 pid——这一事实当时就把『在整个 repo/config 里搜端口』缩成『对该 pid 做一次 lsof/ps OS 级查询』，无需任何文本搜索

## Short path
- 明确未知量（如 web UI 端点）；回看已有回执，确认目标服务 live pid 与 pid_alive=true，此即第一手线索
- lsof -Pan -p <live_pid> -i → 得到该进程 LISTEN 的 host:port；若需登录/env 再用 ps -E -p <live_pid> 定位其加载的 env 文件
- 用最小直接探针验证：curl 该 URL 的 HTTP 状态码（如 303→/login 200），确认服务本身健康
- 仅当 pid 未知、进程已退出或非 TCP 监听时，才退回 repo/config 文本搜索，且限定 src 与配置路径、显式排除 .worktrees/.venv/evals 等噪声目录
- 若探针工具（如浏览器）连接被拒而直接探针成功，转向查该工具自身后端配置（如 CDP endpoint 是否在线），而非重试页面导航

## Stop conditions
- 已由 pid→OS 查询加独立探针取得并验证所需运行态事实
- 目标进程已退出或 pid 从未在任何回执中出现 → 切换到 config/文档来源
- 探针失败与 lsof 结果矛盾 → 判定为探针侧问题，停止对目标端点的重复尝试

## Verification
- lsof 显示所得端口确由该 pid LISTEN（端口-pid 一致性）
- 独立最小探针（curl HTTP 状态码）确认端点实际响应
- 若最终来源是 repo 文本，确认命中属于当前运行版本（src/HEAD）而非 worktree/evals 陈旧副本

## Counterexamples
- 服务尚未启动、需要的是部署前的配置端口 → 无 pid 可查，config/文档是唯一来源
- 服务仅监听 unix socket → lsof -i（TCP）返回空，需 -U 或改查 config
- 对外端点由前置代理/隧道持有 → 目标服务 pid 的端口不是用户要测的地址，须沿代理配置解析而非止步于 pid→port
