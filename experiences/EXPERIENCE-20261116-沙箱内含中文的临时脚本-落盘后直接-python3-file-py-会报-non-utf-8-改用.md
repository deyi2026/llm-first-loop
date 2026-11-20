---
title: 沙箱内含中文的临时脚本：落盘后直接 python3 file.py 会报 Non-UTF-8，改用 exec(compile(open(...).read())) 执行
scenario: 在 macOS sandbox-exec 沙箱里用 heredoc 写一个含中文的 Python 补丁/自验脚本到 /tmp 再执行
root_cause: ""
solution: "现象：脚本用 heredoc 落盘后，同一命令内 `python3 /tmp/x.py` 报 `SyntaxError: Non-UTF-8 code starting with '\xe5' ... but no encoding declared`；而同一时刻用 `open(p,'rb').read().decode('utf-8')` 读取该文件完全合法（字节是合法 UTF-8），说明是「解释器按脚本路径读取」这条路径被沙箱读过滤改写，而不是文件真的坏了。绕法（已实测有效）：把脚本内容用 open(...).read() 读成 str 再 exec(compile(src, path, 'exec'))，即 `python3 -c \"src=open(P,'rb').read().decode('utf-8'); exec(compile(src,P,'exec'))\"`。另注意：把 heredoc 直接喂给解释器（python3 - <<EOF）会被安全硬阻断拦截，应按提示先落盘再执行；纯 ASCII 的脚本不受影响，可直接 python3 file.py 运行。"
evidence: 本会话实测：heredoc 写含中文脚本后直接执行报 SyntaxError（字节层校验显示文件本身合法 UTF-8）；改用 exec(compile(open(...).read())) 后同一脚本成功执行并完成后续补丁与自验。
tags: [sandbox, execute_command, heredoc, encoding, workaround]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-16T21:55:04.453322+08:00"
updated_at: "2026-11-16T21:55:04.453322+08:00"
supersedes: [EXPERIENCE-20261026-三条执行层硬约束-heredoc-喂解释器会被硬阻断-子代理默认-64k-上下文会耗尽-replac]
---