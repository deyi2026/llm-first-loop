---
title: 删分支后证明零内容丢失：clone+unbundle 差分判定法
scenario: "批量删除已合并分支后，验证\"零内容丢失\"的判定方法与陷阱"
root_cause: ""
solution: 用 clone+unbundle 后再 fsck 的差分作决定性判定，配合逐条 git cherry 确认 patch-id 等价；避免大集合运算超时
evidence: "本地 /Users/yyj/Project/llm-first-loop-mirror：unbundle 前 dangling commit=1758，clone+unbundle 后=21；21 条逐条 git cherry 全部返回 '-'（内容已在 main）。归档 /Users/yyj/Project/lfl-merged-branch-archive-20261021/ 含 patch-merged-25-branches.bundle 与 rule31-bgroup-4-branches.bundle，git bundle verify 均 is okay。evidence://v1/f3bb6dc99fa84a3aa04875f958d5de1d1fa62459e50ffd607e65203d59287b92, evidence://v1/a69e27d9dd2fb4824d99ece02980cd9eb2550cbe599c8b9bcb6954dce40c30bc, evidence://v1/a12855aebdf7cc9f747d89154cdced94b8f2c31cfd83939aff0dadca13011ac2"
tags: [git, branch-cleanup, reversibility, fsck, bundle, self-check]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T22:54:07.804280+08:00"
updated_at: "2026-10-21T22:54:07.804280+08:00"
---

问题：批量删分支后，如何证明"零内容丢失"？
仅看 `git branch --merged` 不够——squash/rebase 合并的分支拓扑上不在 main，但内容已在。
仅看 `git fsck` 的 dangling 数也不够——历史 stash 残留会造成大量假阳性。

有效方法（本次实测）：
1. 记基线：`git fsck --no-progress | awk '$1=="dangling" && $2=="commit"{print $3}'` 取悬空提交集。
2. 决定性测试：`git clone --no-local --mirror` 到临时目录 → `git bundle unbundle <各bundle>` → 再 `git fsck`。
   本次：unbundle 前 1758 → 后 21，377 条分支型提交全部被 bundle 覆盖，判定成立。
3. 残留 21 条用 `git cherry main <sha>` 逐条判定（21 条可承受；1758 条会超时，必须分批或用集合运算）。
4. 对"内容已合入但SHA悬空"的提交，`git cherry` 返回 `-` = patch-id 等价在 main。

陷阱：
- `git cherry main $(cat file)` 批量传参会静默只处理 1 个，必须逐条或分批。
- `git bundle verify -v` 的输出解析猜错格式会让 bundle commit 集合算成 0，导致全部误判"未覆盖"。
- `git fsck` 在循环里反复调用极慢（60s 超时），先一次性提取再循环。
- 全量 `git patch-id` 比对 1758 个提交会超时。