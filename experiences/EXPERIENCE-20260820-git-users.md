---
title: git 提交被安全扫描拦截（本地绝对路径 /Users/*/）的修复模式
scenario: "git commit 含测试/脚本文件时被 git_security_scan 拦截：文件内容匹配本地绝对路径规则 /Users/[A-Za-z0-9_]+/，提交拒绝。典型场景：测试里子进程代码字符串硬编码了开发机绝对路径。"
root_cause: 测试/脚本硬编码机器绝对路径，入库即泄露用户路径且不可移植；安全扫描规则按文件内容匹配拦截，属正确拦截而非误报。
solution: "①先读文件定位绝对路径（read_file 全文），不要申请 _ALLOWLIST 豁免（测试样例硬编码用户路径本就不该入库）；②改为动态构造——同文件内用 Path(__file__).resolve().parent；子进程代码字符串（-c 模式无 __file__）由父进程注入：_scripts_dir = str(Path(__file__).resolve().parent); child_code = r'''...sys.path.insert(0, r'%s')...''' % _scripts_dir；③修改后重跑该测试验证功能未破坏（本次 4 项 PASS），再重新 git add + commit（扫描会重新跑并放行）。"
evidence: 2026-08-20 提交 scripts/harness_mock/ 时 test_managed_cleanup.py 第 76 行 /Users/yyj/... 触发拦截；修复为动态注入后 commit 2c64320 通过（git_security_scan 3 文件放行）。
tags: [git, 安全扫描, 绝对路径, 测试, 可移植性]
source: {}
status: active
created_at: "2026-08-20T05:47:17.054522+08:00"
updated_at: "2026-08-20T05:47:17.054522+08:00"
---