---
title: "zsh 交互模式默认不解析 # 注释，给用户的验证命令块不要带行内注释"
scenario: "给用户（zsh 交互终端，macOS 默认配置）提供带行内 # 注释的多行 shell 验证命令，用户整块粘贴执行"
root_cause: ""
solution: "给 zsh 用户的命令块不写行内 # 注释，改用独立 echo 标记行分隔输出；判断 Web 就绪时区分直接状态码（可能 303 登录跳转）与 -L 跟随后的最终状态码"
evidence: "用户终端输出：tail: #: No such file or directory 等多条；curl -w %{http_code} 输出 303,000,000,000；随后复跑无注释版命令验证：/ui/v2 303 → follow → 200 (/login?next=/ui/v2)，ps pid 19909 存活、3399 退出"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-18T21:46:52.629725+08:00"
updated_at: "2026-09-18T21:46:52.629725+08:00"
---

用户终端是 zsh（macOS 默认），交互模式默认不启用 # 注释（需 setopt interactivecomments）。给用户的多行验证命令若含行内 # 注释，注释词会被当作 tail/curl 等工具的参数：tail 报 "No such file or directory"，curl 把词当 URL 报 000。做法：拆成独立 echo 标记行，或干脆不含注释；另外 303 对 /ui/v2 是登录跳转的正常行为，直接跟随后 200 才是完整判定。