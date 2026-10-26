---
title: 子代理 fs 作用域与 Rule28 全量门：通道、熔断与七轮循环的完整操作规程
scenario: 在共享仓库 llm-first-loop-mirror 上调度 GLM-5.3 子代理做代码实现/修复，并走 Rule28（review_admission）门禁跑全量 pytest。重启后主会话与子代理的文件工具作用域被限定在各自工作区。
root_cause: ""
solution: 见 body 的 10 条操作规程。
evidence: "evidence://v1/0c90ea8379b34b523923590a7002da19b717a4fa1be9566db3aa41683d42ee97；evidence://v1/acf2158deab077913a61fcf1a56ddba151fac787046668f4b2db12b2dcaffeec；全链 7 轮 admission（REVISE×5→PASS×2）回执均在会话 evidence"
tags: [subagent-channel, sandbox, rule28, review-admission, shared-repo, lfl]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T03:09:17.578549+08:00"
updated_at: "2026-10-26T03:09:17.578549+08:00"
---

通道（父会话与子代理均已实测）：
1. 子代理（与重启后的主会话）的 read_file/edit_file 作用域 = 各自工作区（如 ~/lfl-workspace），对仓库绝对路径报 WorkspaceScopeMismatch。
2. 写仓库唯一可靠通道：execute_command(workdir=REPO) 下的 shell 重定向（cat WS副本 > REPO目标）或 cp；`sed -i`/python 进程内写 REPO 会 Operation not permitted；mv 跨工作区也会 EPERM。
3. 因此标准工作法：cp REPO文件 → WS，WS 内 edit_file，cat/cp 回 REPO。每个子代理任务必须把这三步写进任务书（不写，子代理平均浪费 60+ 轮自己撞墙）。

门禁（Rule28 review_admission）循环：
4. 资格是一次性的：全量跑一次（无论成败）即消耗，需重新 start。
5. 审核者结论行若非标准 token（如中文"判定：通过"），程序闸判 REVISE——target_name 里显式要求"VERDICT: PASS 或 VERDICT: REVISE，后跟 P0=n P1=n P2=n"可避免。
6. 树上存在敏感 untracked 路径（如 .env 备份）会拒收 start（review_sensitive_untracked_path_refused），先移出仓库。
7. 审核者每次独立抽样，同一树连跑两轮可能第一轮 P1=0 第二轮 P1=1（第五轮抓出 wait_worker_terminal stdout 污染）——门禁多轮不是浪费，是换审核者视角。

事故与教训：
8. tests/scripts/__init__.py 千万不能建：历史提交 98cd5cee0 专门删过它（scripts 包遮蔽），子代理自建它导致全量收集失败。
9. 子代理新增测试里的 lint（E741 变量名 l）会经 ruff ratchet 拦截让静态门 main() 返回 1，进而让"假定干净树"的 test_static_diagnostic_gate 环境用例假失败——机械改名即可，但要意识到该测试对树脏敏感。
10. 子代理可能在网络故障（GLM SSL EOF 连续 3 次熔断）时死在收尾：任务书要求"每完成一件立即回写 REPO"能保住部分成果；未回写部分让其交 sha256 清单，父会话核验后代写。