---
title: 凭先验编造 service_control CLI 的 restart 子命令（接口未核验就给用户命令）
scenario: 用户需要重启 LFL 共享服务（web/feishu/learning）到新代码版本。我在未核对 CLI 实际接口定义的情况下，凭印象给出了带不存在子命令的 python3 -m llm_loop.runtime.service_control 命令，导致用户侧执行失败，需要返工纠正。
root_cause: "把\"工具层 service_control 有 restart 动作\"错误泛化为\"CLI 模块也有对应子命令\"，用类比先验替代了对当前代码 argparse 定义的核验；且未先跑 service_control status 确认当前 generation。"
solution: 给用户任何 CLI 命令前必须先核对当前代码：inspect_code/read_file 定位 main() 里 add_parser 注册的子命令，再给命令。此例中 CLI 仅 4 个子命令：publish（CAS 发布 desired deployment，generation=expected+1，要求 worktree clean）、show、verify、worker（配合 --action-id）。重启没有 CLI 入口，唯一入口是运行时工具 service_control restart（target+expected_generation+action_id）。
evidence: "src/llm_loop/runtime/service_control.py L1225-1246：argparse 仅 add_parser(\"publish\"/\"show\"/\"verify\"/\"worker\")；publish 分支仅做 build_deployment+compare_and_swap(generation=expected+1)，无任何重启逻辑。service_control status 回执（2026-09-19）：action_id=svc-d1be262039cc4111bcd0105fe94725eb, generation=51, 三服务 git_head=c9f33b4c…, pid_alive=true, matches_desired_generation=true。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T19:30:25.006629+08:00"
updated_at: "2026-09-19T19:30:25.006629+08:00"
---

时间线：用户要求重启共享服务 → 我直接给出 CLI 命令，其中使用了不存在的子命令 → 用户执行失败/被纠正 → 实际正确路径：用户跑 publish 发布 desired deployment，我调工具层 service_control restart 登记 action 并拉起 worker → status 验证 generation 51 成功。