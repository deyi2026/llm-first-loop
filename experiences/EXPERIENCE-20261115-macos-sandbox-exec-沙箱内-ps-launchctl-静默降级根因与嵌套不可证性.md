---
title: macOS sandbox-exec 沙箱内 ps/launchctl 静默降级根因与嵌套不可证性
scenario: macOS sandbox-exec 沙箱内做系统诊断/进程排查，或为沙箱后端能力写测试与验证
root_cause: ""
solution: ps 排查用 lsof/sysctl；launchd 查询用 launchctl print user/<uid>；沙箱相关 e2e 按环境感知设计（嵌套内 skip + 单测钉管道 + 裸机 runner 真执行）；嵌套实验放弃，改由宿主侧验证。落地于 EVO-20261115-488367d4（commit 14241223e：banner 降级提示 + docs/EXECUTION-ISOLATION.md 降级表 + sandbox_exec_available 公开探针）
evidence: "evidence://v1/0ed2824954a03c69a9e58f07d3935f2577fa58b7382636e03f43134b95a3db2b（profile 文本）；2026-11-15 本会话连续实测：ps EPERM+ls -l 显示 -rwsr-xr-x、launchctl list 两次空输出（exit0/exit1）、launchctl print 正常、嵌套 sandbox-exec sandbox_apply EPERM、uv run pytest 15231 passed exit=0"
tags: [sandbox-exec, macos, seatbelt, setuid, launchctl, ps, nested-sandbox, evo-20261115-488367d4]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-15T13:34:01.796656+08:00"
updated_at: "2026-11-15T13:34:01.796656+08:00"
supersedes: [EXPERIENCE-20261027-macos-沙箱内桌面自动化可行性基线-坐标系-权限-依赖三项实测]
---

sandbox-exec 后端（(allow default)(deny file-write*)）内的实测降级与根因：
1) /bin/ps 在 macOS 为 setuid root（-rwsr-xr-x），Seatbelt 沙箱内 execve setuid 二进制被内核直接 EPERM（bash 报 "/bin/ps: Operation not permitted"）——与 profile 过滤规则无关，加 (allow process-info*) 等规则无法修复。进程信息经 lsof -p、sysctl（kern.boottime 等实测可用）仍可得。
2) launchctl list 空输出且 exit 码 0/1 不定（假成功/假空表，不可作"服务不存在"证据）；launchctl print user/$(id -u) 实测可用。
3) 嵌套沙箱不可证：任何 execute_command 都已被外层 sandbox-exec 包裹，内层再用 sandbox-exec 做 A/B 对照实验必 sandbox_apply: EPERM——真执行验证只能由宿主/裸机 runner 承担（e2e 需环境感知分支 + 单测钉管道层）。
4) pytest 在会话内跑时 _probe_sandbox_exec 恒 False（嵌套 EPERM），依赖它的成功路径断言必须 fixture 钉 True，负例单独留 fail-closed 用例。
5) venv python3=3.13（PATH 中 python3 是 Xcode 3.9 shim 无 StrEnum）；测试走 uv run pytest（pythonpath=src 指工作树；.venv 安装的是 .releases 快照）。