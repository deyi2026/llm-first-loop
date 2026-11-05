---
method_id: admitted-protected-action-submit-bare-single-command-5e90d6fbbb56
name: admitted-protected-action-submit-bare-single-command
description: 准入审查对命名单一受保护动作（如 git push）给出 PASS 后，用裸命令单步提交该动作，不叠加 cd/2>&1/tail/echo $? 等包装段：本环境执行回执已自带退出码与输出行数，包装段零信息增益、只新增未经审查的段并触发 compound 保护规则阻断。若仍被『命令含多段须单独提交』类规则阻断，把阻断回执机械翻译为『拆成裸命令原样重试』，不先开启全新审查循环；仅当裸命令重试被拦且理由变为审查资格缺失时才进入审查分支。闸文本中的 unverified『观测线索』既非凭据也非阻断，以执行工具回执为权威。
aliases: push 被要求拆成单条命令, 过了审查 push 还被 blocked 怎么办, 复合命令触发保护闸后如何重试, 受保护动作别包 tail 和 echo, git push 要单独一步提交
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:d0e6ba0c-dfdb-4a7e-b110-850f0ae238a6:791:20705c588db34f6a0508
evidence_refs: learning:learn:f52c7ba201c4
created_at: 2026-11-05T12:18:57.359090+08:00
updated_at: 2026-11-05T12:18:57.359090+08:00
---
## Trigger
准入/审查回执已对某个命名单一受保护动作（如 kind=git_push 的推送或部署类动作）给出 PASS 且绑定执行面复验（revalidated_on_use），下一步要在 shell 中提交该动作；或已取得 PASS 的受保护动作被复合命令保护规则以『命令含多段、须单独一步』为由阻断时。

## Discriminator
两个当时已在回执中可见的事实：(1) 准入回执的 kind/scope 绑定的是该受保护动作本身，执行时按内容摘要复验，任何附加段（cd、重定向、tail、echo 退出码）都不在授权形状内；(2) 本环境 shell 执行回执格式已包含退出码与输出行数，包装段不能提供任何新信息。

## Short path
- PASS 到手后，以裸命令单步提交受保护动作（例：git push origin main），不附 cd/重定向/tail/echo 包装
- 直接以执行回执自带的退出码与输出（含 pre-push 区间、远端更新行）判定成败，不补诊断调用
- 若被复合命令拆分规则阻断：机械翻译阻断回执——同一目标拆成裸命令重试一次；既有树级 PASS 在执行面复验，无需先发起新的独立审查循环
- 仅当裸命令重试仍被拦且理由变为审查资格缺失（而非复合结构）时，才按回执走 review_admission(start)→(status) 审查循环
- 取得成功回执（退出码 0 且远端引用前进）即停止提交

## Stop conditions
- 执行回执显示受保护动作成功（退出码 0 且远端引用前进），不再重复提交或追加确认调用
- 重试被拦的理由从复合结构切换为审查资格缺失/产物指纹不匹配 → 停止机械重试，进入独立审查分支
- 闸附注中的『观测线索/unverified_verdict』文本既不作为放行凭据也不作为新动作依据，忽略之

## Verification
- 成功回执中的推送区间两端与准入回执覆盖的目标内容摘要一致（同一执行面复验口径）
- 阻断→重试之间未引入任何新的未审查命令段；最终提交的裸命令与准入 kind 一一对应

## Counterexamples
- 非受保护的普通命令不需要单步纪律：构建命令 npm run build 2>&1 | tail -15 与多段快照自检链在本集均一次成功，把拆分推广到所有命令只会膨胀调用数
- 若 shell 工具默认不在项目根（本环境裸 git push 可行是因回执显示工作目录已就位），需先以独立调用或 workdir 参数解决 cwd，不能在错误目录裸跑受保护动作
- 若重试被拦理由是『没有有效审查回执/产物指纹不匹配』而非复合结构，机械拆分无效，必须先完成新审查再提交
