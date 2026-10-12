---
title: 后台 job 报 running 但进程不可见时，先触发终态同步再判死
scenario: "检查后台 execute_command job（python3 -m pytest tests/unit -q | tail -3）：job_output 连续多次返回 running 且 0 行输出；ps/pgrep 均找不到 pytest/tail 进程（只剩旧会话孤儿 Chrome）。据此误判\"进程已死、job 无法产出结果\"并另起重跑 job。"
root_cause: "durable job registry 的 running→terminal 状态同步滞后于进程实际退出；命令经 tail 管道缓冲，运行期间 0 输出加剧\"卡死/已死\"错觉。"
solution: "判\"无法产出结果\"前先触发终态同步：job_kill 该 job（回执'任务已结束'即证其已 terminal），随后 job_output 立即返回 done exit=0 与真实输出（7393 passed, 108 skipped, 306.63s）；随即 job_kill 终止了多余的重跑 job。"
evidence: "job-0cd9c412b6964d56bed9 于 ps 快照（evidence://v1/05ce7221aa3a1f63b01521391fe71127fed8b64d87f04d030c8ca34064bcc745，acquired_at 2026-10-11T00:55:47，14 行仅剩周五孤儿 Chrome）后获终态 done exit=0，输出 7393 passed, 108 skipped in 306.63s；期间 job_output 连续 4 次报 running/0 输出，job_kill 回执\"任务已结束\"后才见终态。"
tags: [execute_command, job_output, background-job, state-lag, false-positive-dead]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-11T00:58:04.764225+08:00"
updated_at: "2026-10-11T00:58:04.764225+08:00"
---

job_output 持续返回 running 且 0 输出、ps/pgrep 找不到命令进程时，不等于 job 无法产出结果：本例 pytest 全量 306.63s 跑完、进程恰在 ps 快照前结束，而 registry 终态多分钟未同步。正确顺序：1) 先 job_kill（幂等，回执会揭示真实终态）；2) 再 job_output 取终态与输出；3) 仍无终态才判"无法产出结果"并重跑。重跑应改为"完整日志落盘+摘要"（cmd > /tmp/x.log 2>&1; echo exit=$?; tail）而非裸 tail -N，保失败定位能力。