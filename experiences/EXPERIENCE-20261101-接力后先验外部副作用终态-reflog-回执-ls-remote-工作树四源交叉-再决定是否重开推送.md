---
title: 接力后先验外部副作用终态：reflog/回执/ls-remote/工作树四源交叉，再决定是否重开推送闸
scenario: "跨会话接力快照（来源会话未结算 push 指令）后接管任务：快照说\"推送未完成\"，但快照时刻之后来源线仍在运行并可能已完成外部副作用。"
root_cause: ""
solution: "先判\"外部副作用是否已被来源线自行完成\"，再决定是否重开闸周期：ls-remote 直取远端真值 + origin/main reflog 更新方式 + 收口回执提交（docs/governance/receipts/）+ 工作树 dirty 状态四源交叉。任一证据表明来源线已完成或仍在活跃 ⇒ 不重放、不并发推。"
evidence: "镜像仓 docs/governance/receipts/push-review-20261101-origin-main-desktop-browser-closure.json（提交 c766ae9b3，pushed_at=11:58，两段 PASS，final_remote_main=441dcf509）；本会话 11:42 观察 ahead=32（陈旧 origin/main=55b53ab81），12:1x 复核 ls-remote=441dcf509、reflog 两条 update by push、回执 JSON 字段 intentionally_not_shipped 明示剩余提交属活跃线；正在运行的 --range 扫描（job-9f92319b78cd4c22b7e2）按过时范围终止。"
tags: [cross-session-relay, git-push, side-effect-verification, concurrent-writer, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-01T12:15:36.323090+08:00"
updated_at: "2026-11-01T12:15:36.323090+08:00"
---

接力快照只承诺"来源会话当时状态"，不承诺外部副作用未完成。本例：快照（11:25）之后来源线继续工作，11:56-11:58 完成两段推送、12:05 写收口回执提交；若按快照字面重启推送闸周期会与活跃线竞争并重复劳动。
核验顺序（全部只读，零副作用）：
1. git status + git log -5 + rev-list ahead/behind 取当前事实；
2. ls-remote origin main 直取远端真值（本地 remote-tracking ref 可能陈旧）；
3. git reflog show origin/main 看更新方式（fetch=他人推过 / update by push=本仓推过）；
4. 搜 docs/governance/receipts/ 下最新回执 JSON（本安装推送收口都写回执提交）；
5. 工作树出现非本会话的 dirty 文件/新未跟踪目录 ⇒ 有活跃并发写者，停止一切写侧动作。
坑：git reflog show --format='%ci' 显示的是**提交日期**不是 reflog 操作时刻，时间线要用 ref 文件 mtime + 回执 pushed_at 交叉验证。
另：merge 提交会让 diff-tree 无输出 → 安全扫描 --range 退化扫该提交全树（本仓 ~8k 文件/merge，实测 35 分钟，脚本注释自记 577s 量级）；扫描只回执文件 mtime 可作旁证。