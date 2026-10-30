---
title: shell 无 timeout 时 `timeout N cmd` 会整条不执行，空结果≠文件不存在
scenario: 在 llm-first-loop 工作区的 execute_command（macOS sandbox-exec shell）里用 `timeout 25 find data -maxdepth 3 -name 'runtime_manifest*' 2>/dev/null` 查运行态清单，两次都返回空，我据此写下「manifest 不在 data/ 下」的错误结论。
root_cause: "该 shell 没有 GNU coreutils 的 timeout（后续一次未吞 stderr 的调用才暴露 \"timeout: command not found\"）；`timeout` 不存在时整条命令不执行，而 `2>/dev/null` 把错误输出吞掉，只剩后续 echo，于是「命令没跑」被误读成「文件不存在」。"
solution: "1) 不用 timeout，依赖 execute_command 自身 60s 上限；2) 必须限时就先 `command -v timeout` 自检；3) 查仓库内文件优先用 `git grep`（走索引、毫秒级），实测 `git grep -ln runtime_manifest` 立刻命中 9 个文件；4) 任何\"搜索无结果\"的结论，先用一个已知存在的文件做阳性对照，再断言\"不存在\"。"
evidence: "同一次会话中：两次带 timeout 的 find 均未真正执行（输出仅剩 echo）；改用 git grep 后立即返回 9 个命中文件（evidence://v1/0eb5c3a8cd7bb49afc6178b26bdac3686f4f3a8c02fed8f3816d73759484e4c6）；`timeout: command not found` 的 stderr 出现在 evidence://v1/dc3509db0d35af429b112ad2f3d10e96ea95a71279049e358130b06ce0485e67 的失败回执中"
tags: [tooling, execute_command, self-correction, false-negative]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T23:39:20.104145+08:00"
updated_at: "2026-10-30T23:39:20.104145+08:00"
---