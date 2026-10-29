---
title: 给用户的可复制命令禁用反斜杠续行；cp 报错≠全部失败，按目标路径逐一核验
scenario: "在聊天回复里给出跨行 `cp src \` + 换行 + `dst` 的两行命令块，用户整块粘贴到 zsh 后：反斜杠后紧跟空格被解析为\"转义空格=一个字面空格参数\"，argv 变成 [src, \" \", dst]；BSD cp 逐源处理并把 src 当作\"多个源+目录\"形式拷入 dst，只对 \" \" 报 `No such file or directory`，退出码 1 但**第一个源其实已成功复制**。"
root_cause: ""
solution: "1) 给用户的命令一律写成单行、不用 `\` 续行、不在续行后带空格；多命令用分号或分条给出。2) cp 出现 \"No such file or directory\" 时，不要判定整体失败：BSD/GNU cp 会逐源继续处理，先 `ls -la <目标目录>/<文件名>` 与 `shasum -a 256` 源/目标对拍，确认哪些已落地，只补缺失的那份。3) 本次实证：目标目录已有 push-f5fec37c1-lfl-main-20261028.json，sha256 双方均为 7b37662e67a953b73f034f8c62522ff7fae0984dd15ff0a6fa405a88e526f149；缺 push-20261028-dgui-to-github-main.json，需用户在自己终端补（我的 sandbox 对 /Users/yyj/Project/ 只读，cp 返回 Operation not permitted）。"
evidence: "execute_command 回执：ls 确认 push-f5fec37c1-lfl-main-20261028.json 存在于镜像 docs/governance/receipts/（3285B，mtime 15:48）；shasum -a 256 源与目标均为 7b37662e67a953b73f034f8c62522ff7fae0984dd15ff0a6fa405a88e526f149；cp 第二份返回 `Operation not permitted` exit=1（沙箱只写工作区）。"
tags: [shell, cp, 命令输出格式, 粘贴事故, 按路径核验]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T15:53:04.700692+08:00"
updated_at: "2026-10-28T15:53:04.700692+08:00"
---