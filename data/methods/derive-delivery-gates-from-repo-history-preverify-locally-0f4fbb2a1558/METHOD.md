---
method_id: derive-delivery-gates-from-repo-history-preverify-locally-0f4fbb2a1558
name: derive-delivery-gates-from-repo-history-preverify-locally
description: 向共享远端同步提交前，先从本地已可见证据推导交付契约：git log 中按变更路径配套的治理清单提交（A.5 submission manifest）与 PR-only 合并记录，说明 main 受保护、需 PR + 必需检查 + 变更路径清单精确覆盖。据此在推送前按已有清单归属分组提交、为每个 PR 生成恰好一份路径集合精确相等的 manifest，并用本地门禁脚本预验证，再走分支→PR→检查→合并；而不是直推被拒→开 PR→auto-merge 失败→A.5 检查失败后逐个救火。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:392:607b20c6ad46729901ab
evidence_refs: learning:learn:bf5b8b9e5f61
created_at: 2026-09-19T22:49:58.700542+00:00
updated_at: 2026-09-19T22:49:58.700542+00:00
---
## Trigger
需要把本地领先提交同步到共享/受保护远端分支，且初始状态读取（git log/status）或推送回执中已出现治理信号：PR-merge 提交、按变更路径配套的 submission manifest/清单类提交、或列出必需检查的保护提示。

## Discriminator
推送前第一次状态读取输出中已有多条 'add A.5 submission manifest for ...'、'A.5 提交清单' 类提交，且最近合并均为 'Merge pull request #NN'——当时即可断定该仓交付契约是 PR + 必需检查 + 每个变更路径被清单覆盖；忽略它会必然撞上直推被拒与 A.5 检查失败两道闸。

## Short path
- 初始状态读取时提取交付契约信号：PR-merge 提交、治理清单提交、remote 列表；形成假设：目标远端 main 受保护且变更需清单覆盖
- 用一次廉价调用确认门禁（gh api branches/main/protection 或看上一 PR 的 checks），不把直推 main 当探针
- 先完成内容提交（如 experiences 28 文件），再用 git diff --name-status -z 算出计划 PR 的精确变更路径集合
- 按已有 manifest 归属把提交分组（自带清单的提交独立成 PR）；为每个 PR 恰好一份新 manifest，路径集合与其 diff 精确相等、无 glob；格式不明时一次性读门禁脚本+schema
- 推送前在本地以与 CI 相同方式运行门禁脚本（check_architecture_submission.py 的 --staged 或 base...head 模式），确认无 'missing changed path' 再推分支开 PR
- gh pr checks 到绿后合并（auto-merge 不可用则等绿手动合并），fetch 后核对 ahead=0/behind=0

## Stop conditions
- 目标远端确认无分支保护且无门禁 workflow 在跑 → 直接推送即止，不造 manifest
- 历史中的清单流程已被停用（对应 workflow 缺失或 disabled）→ 以当前实际必需检查为准，不照抄旧契约
- 本地门禁对计划 diff 全绿、PR 全部必需检查通过并合并、本地与目标远端 ahead=0/behind=0 → 交付完成

## Verification
- 推送前本地运行与 CI 同参数的门禁脚本，确认 coverage 报告零缺失、且变更的 manifest 恰好一份
- PR 打开后 gh pr checks 直到全部必需检查通过；auto-merge 未启用时不重试而是等绿手动合并
- 合并后 git fetch 目标远端核对 ahead=0/behind=0，并抽查 manifest 路径数与 PR 变更路径数一致

## Counterexamples
- 个人仓或无保护远端（如 legacy origin、fork）：直推是正确路径，预造清单与查保护规则纯属浪费
- 历史中的治理清单属于已废弃流程（workflow 已删除或不再触发）：须先确认门禁真在运行，否则照抄旧契约会做无用功
- 只推一个不打算立即开 PR 的临时实验分支：PR 级门禁暂不适用，按分支自身 CI 处理即可
