---
title: "安全正则闸的\"数据区/非命令位\"误判：先按 bash 语义分区，再用真实 bash + HEAD/工作树 A/B 双证"
scenario: "命令闸/检测层用正则扫整条原始命令串时，把 stdin 数据（引用定界符 heredoc 正文）、文件名尾巴（gen.sh 里的 sh）、源码标识符（SH、PY）当成命令判定，导致写文档/写测试夹具/写验证脚本本身被硬阻断。本轮实测 5 次真实误拦，其中 2 次发生在\"正在修这个 bug 的工具里\"。"
root_cause: ""
solution: "三步：①语义分区——只让「bash 会执行的命令文本」进入判定：引用定界符（word 内含 '/\"/\）的 heredoc 正文完全不展开（bash 手册），是纯数据，可剥离；未引用定界符正文会做 $( ) 展开，必须保留（fail-closed 整体不剥）；正则窗口 [^|;]* 收窄为 [^|;\n]*，解释器词锚定命令位（行首/操作符后，允许 /usr/bin 前缀），否则文件名 .sh 尾巴会被当成解释器。②剥离时保留声明行原文，只消费正文行——否则 python3 <<'EOF' 剥掉 <<'EOF' 后「解释器 heredoc」硬规则整体失灵（我第一版就这么崩了，7 条既有测试红）。③双证：用真实 bash 跑各定界符变体确认展开语义（quoted/partial/dq/backslash 都不展开，unquoted 才展开）；再用 git worktree add 起 HEAD 副本，同一探针在 HEAD 与工作树各跑一遍，输出 A/B 表，凡 HEAD 也红的就是既有漂移，不算回归。改面越小越好：只收窄出问题的那一条规则，不做全局语句切分。"
evidence: bash 实测：bash /tmp/lfl_sem.txt 输出 A/B/C/D 四个变体为字面 $(echo …)，仅 unquoted 变体展开执行。A/B：同一 17 条探针 HEAD 8 条判定错误 / 工作树 1 条（既有间隙）；tests/test_catastrophic_data_payload.py 21 条在 HEAD 10 红、工作树全绿；tests/unit/test_tools_skills.py 新增 3 条在 HEAD 1 红。
tags: [safety-guard, regex-precision, heredoc, fail-closed, a-b-testing, worktree-baseline]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T12:11:10.050213+08:00"
updated_at: "2026-11-01T12:11:10.050213+08:00"
---