---
name: push-review-gate
description: push 审查闸（RULE-AI-28 第 3 条）——git push 前的独立子代理审查清单，防夹带、防错目标、防盲目重试
---
# push 审查闸（推送前）

触发：任何 `git push` 前必走（RULE-AI-28）。审查者有 BLOCK 权：不通过就不推。

## 前置义务与资格
审查是强制前置义务。父 agent 主动安排对应独立审查子代理，取得覆盖当前产物的有效 PASS 回执后方可执行目标动作；缺失、未完成、未通过或失效时暂缓该动作，继续其他可推进工作。核实真实子会话终态、审查类型、产物指纹及实际覆盖；completed、工具文本中的 PASS 或父 agent 自查均不构成资格。改动后走窄复审并保留覆盖关系。泛化的“继续 / 按建议执行 / 授权发布”不构成免审；用户明确豁免须留痕。程序观测提示不等于有效回执。

## 前置事实收集（只读命令，逐条留痕）
1. `git status --porcelain`（全量，不只前 15 行）——区分 staged / modified / untracked。
2. `git log --oneline @{upstream}..HEAD` 与 `git log origin/<branch>..HEAD`、`git log lfl/<branch>..HEAD`——本仓库双 remote（`lfl` 主仓 / `origin` legacy）各查一遍，确认待推集合与目标 remote。
3. `git remote -v` 核对 URL 与预期目标一致。
4. `git diff --stat <range>` 看待推变更规模。

## 审查清单
1. **提交清单 vs 预期**：待推提交逐条与任务声明比对，多出的提交要能说出来历。
2. **夹带检查**：untracked 且未被 ignore 的文件/目录逐个定性（如未忽略的 `audit-id/` 类目录）；**禁止 `git add .`，一律显式路径**；.gitignore 盲区（新增的临时目录、备份文件）登记并建议补 ignore。
3. **敏感文件模式**：密钥/凭据（.env、*token*、*secret*）、代理配置（*.conf）、运行时备份（*.bak、runtime 数据）、含个人信息的回执。
4. **大文件**：单个 >5MB 的待推文件逐个确认必要性。
5. **历史覆盖**：默认禁止 force-push 与历史改写；确需时单独向用户申请。

## 推送执行纪律（父会话执行，审查者不推）
- 提交用显式路径 add；push 前可先 `git push --dry-run`。
- push 成功后 `git ls-remote <remote> <branch>` 核对远端 SHA == 本地 HEAD，才算收口。
- **失败诊断**：non-fast-forward → 先 fetch 再分析分叉，给出 rebase/merge 建议，禁止盲目重试同一命令、禁止直接 force。

## 回执（落盘 docs/governance/receipts/）
```json
{"gate": "push", "reviewer": "<subagent_id>", "verdict": "PASS|REVISE|BLOCK",
 "commits": [...], "remote": "lfl|origin", "branch": "...", "carried_files_removed": [...],
 "sensitive_checks": "clean|findings", "push_sha_local": "...", "push_sha_remote": null,
 "artifact_sha256": "...", "target_ref": "...",
 "failure_diagnosis": null | {"cause": "...", "action": "..."}}
```

push_sha_remote=null 仅用于 push 前独立审查阶段，表示尚无推送后远端证据；push 成功后由父 agent 使用 git ls-remote 取得真实远端 SHA，并在独立的推送收口回执中写入 push_sha_remote 与验证结果。不得将预审 null 或 PASS 冒充推送成功。

## 沉淀循环
每次 BLOCK/夹带/失败诊断都 save_experience（pattern + 判据）；.gitignore 盲区发现同步补 .gitignore；清单缺陷改回本 skill。
