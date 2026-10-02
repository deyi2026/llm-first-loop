---
title: search_files 可能漏检嵌套文件，用 find 兜底定位
scenario: 用户要求定位一个文件名已知但路径未知的文件（如 needle_target.txt），且文件位于工作区较深层子目录。
root_cause: search_files 的文件名匹配在本工作区未覆盖嵌套子目录（默认 root 与 root=. 两次均无匹配），而文件确实存在；负向工具回执不等于文件不存在。
solution: "先用 search_files(pattern=<文件名>) 尝试；若返回\"无匹配\"，不要据此断言文件不存在，也不要猜路径。改用 execute_command 的 `find . -type f -o -type l`（工作区小时开销极低）拿到真实相对路径，再 read_file(snapshot=true) 读取。需要原样复制文件内容时用 `cp` 而非重写文本，随后用 od -c + shasum -a 256 + diff 三重校验字节级一致，最后 read_file 独立读回确认。"
evidence: "同一会话：search_files(pattern=needle_target.txt) 默认 root 与 root=. 均\"无匹配\"；find . -type f 返回 ./nested/deep/needle_target.txt；read_file 读到 gamma-locator；cp 到 result.txt 后两文件 sha256 同为 fd002cabc1d71cf84319193f1e2738917dc27b0343e94af5d70aacf1fcc947e4，diff 无输出。"
tags: [search_files, discovery, tool-behavior, file-copy, verification]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-30T20:04:15.148021+08:00"
updated_at: "2026-09-30T20:04:15.148021+08:00"
---