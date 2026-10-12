---
title: LFL workdir 勘误：~/code 不存在；本机仅 mirror（活跃）+ archived（勿动）两副本，shell 默认省略 workdir
scenario: 用户命令显式指定 workdir=/Users/yyj/code/llm-first-loop，该路径不存在导致执行失败。实际本会话默认 cwd 即为正确仓库 /Users/yyj/Project/llm-first-loop-mirror。本机 llm 相关目录仅两个：mirror（活跃镜像）与 archived-20260908（9 月 8 日归档副本）。与既有 lesson EXPERIENCE-20260911-edit-file（edit_file 相对路径在双仓间解析错位）同属工作区拓扑混淆这一故障族。
root_cause: "workdir 取了未经核验的假设路径（~/code 布局是常见惯例先验），既未确认存在，也未与会话默认 cwd 对照。本次暴露是安全失败（cwd 缺失立即报错）；更隐蔽的风险是命中 archived 副本这类\"存在但错误\"的路径，会成功地做错事。"
solution: "三层防护：(1) 会话内 execute_command 默认省略 workdir，让会话默认 cwd 生效——本案例根因正是\"默认 cwd 已正确却额外手写猜测路径\"；(2) 确需跨树操作必须显式 workdir 时，先只读核验\"路径存在且是预期仓库\"（如 git -C <path> remote -v 看 remote 是否为 lfl），防误入 archived 副本；(3) 用户给的路径执行失败时，依据报错输出反推真实路径再重试，不做无证据的路径猜测。"
evidence: 本会话 execute_command：ls -d /Users/yyj/Project/*llm* 仅返回 archived-20260908 与 mirror；ls -d /Users/yyj/code 返回不存在；纠正后 git 命令在 mirror 成功且与 lfl remote main（de3eaaf7）同步。
tags: [workdir, 路径核验, LFL镜像, 工作区拓扑, 防呆]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-12T13:03:43.042892+08:00"
updated_at: "2026-09-12T13:03:43.042892+08:00"
---

canonical 路径映射（本机，2026-09-12 核验）：活跃开发树=/Users/yyj/Project/llm-first-loop-mirror（LFL 会话默认 cwd）；归档树=/Users/yyj/Project/llm-first-loop-archived-20260908（只读勿改）；主区 llm-first-loop 已不在 ~/Project 下；/Users/yyj/code 不存在。防护三层：(1) 会话内 shell 命令默认省略 workdir；(2) 必须显式时先 ls -d / git -C <path> remote -v 核验存在且为预期仓库，排除 archived 副本；(3) 用户原话路径执行失败时按错误输出定位真实路径，不凭目录布局惯例猜测重试。