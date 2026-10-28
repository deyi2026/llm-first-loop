---
method_id: classify-batch-cherrypick-stops-empty-vs-conflict-verify-by-stat-06f486a790e9
name: classify-batch-cherrypick-stops-empty-vs-conflict-verify-by-stat
description: 批量 cherry-pick 移植多分支提交时，禁止用无差别 skip 循环处理非零退出：git 回执语义本身可区分两类停止——『补丁已空』（nothing to commit, working tree clean，无 UU 文件）可安全 skip；『内容冲突』（error: could not apply <sha> + CONFLICT (content) + UU 状态）必须逐文件解决后 --continue。批后用预先记录的每 commit --stat 对照目标分支 log 做完整性核验：任何有真实插入行的 commit 不在 log 中即为误丢，须单独重放该 sha。本集排空循环曾吞掉功能 commit（wire.py 语义收紧 +38 行测试），靠 stat 对照才发现并补回。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:269:5bcd4263b4937a3027b0
evidence_refs: learning:learn:973c3153fb73
created_at: 2026-10-17T02:33:08.318928+08:00
updated_at: 2026-10-17T02:33:08.318928+08:00
---
## Trigger
需要把多条分支/多组提交按序 cherry-pick 到同一集成分支，或任何用脚本循环批量应用 git 补丁、对失败自动 skip/retry 的场景

## Discriminator
停止时刻的回执文本与工作区状态：'nothing to commit, working tree clean' 且无 UU 文件 = 补丁已空可 skip；'error: could not apply <sha>' + 'CONFLICT (content)' 或 status 出现 UU = 真冲突必须解决。辅以事前已知的源 commit --stat（文件数/插入行 > 0 即携带真实内容，不可被 skip 吞掉）

## Short path
- 移植前先记录每条源分支的 commit sha 列表与各自 --stat（内容足迹），形成预期清单
- 逐条/逐族 cherry-pick；每次停止先读回执分类：空补丁 → --skip；内容冲突 → 查看冲突块两侧 diff，解决后 git add + --continue；绝不让自动 skip 循环跨越冲突失败
- 每族批后将预期清单与集成分支 log 对照：有非零 stat 的 commit 缺失 = 误丢，单独重放该 sha 并解决冲突
- 对补回的目标文件 grep 其关键新增内容（如新测试函数名）并跑定向测试验证完整
- 全部 commit 均有 applied 或 skipped-empty 的回执证据后停止

## Stop conditions
- 预期清单中每条 commit 均出现在目标 log，或附有『补丁已空』回执佐证 skip 合法
- 所有冲突文件均已逐块判定保留侧且有依据，相关定向测试通过

## Verification
- git log 对照预期 sha 清单；对每个有插入行的源 commit，在目标分支 grep 其新增测试/函数名确认存在
- 冲突解决后运行该文件相关定向测试（如被冲突的测试文件全量）
- 最终集成分支跑族相关测试子集确认无回归

## Counterexamples
- 源 commit 本身 --stat 为空（纯记录点/空提交）——skip 无需补验
- 该分支处置策略本来就是 keep-ours/丢弃，skip 是逐分支显式裁定并留痕，而非循环默认行为
- 使用 merge/squash 而非 cherry-pick 的工作流，不存在空补丁与冲突混淆
- 单条 cherry-pick 且人工逐步操作，无循环吞错风险
