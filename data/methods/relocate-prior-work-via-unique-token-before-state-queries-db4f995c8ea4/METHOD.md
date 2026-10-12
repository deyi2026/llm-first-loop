---
method_id: relocate-prior-work-via-unique-token-before-state-queries-db4f995c8ea4
name: relocate-prior-work-via-unique-token-before-state-queries
description: 跨会话回答『先前那段工作的仓库状态/下一步建议』且 cwd 已丢失时，不要从假设的默认 workspace 开始跑 status/diff，也不要做目录级宽枚举；先用上一轮已留下的唯一 token 两步定位：glob 独特相对路径 token（如 src/llm_loop/...）得 repo 根候选，再按实验名 token 过滤 git branch 得唯一分支；任何候选 repo 必须先通过『目标精确路径存在性』检查才值得投入状态查询。本例可把 16 次调用（5 失败+1 超时、错投 ~/workspace/agix/home 倾倒）压到约 4 次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5e09cedf-9412-454e-b7a9-f0247530ef7c:167:99e9a7970d8633a48a0a
evidence_refs: learning:learn:f0b34f11c7d8
created_at: 2026-09-22T17:37:07.887959+00:00
updated_at: 2026-09-22T17:37:07.887959+00:00
---
## Trigger
用户询问某段先前完成工作（上一轮已留下其触及的独特文件相对路径，或实验/分支命名 token 如 mem-citations）的当前 repo/分支状态或下一步建议，而 cwd/会话上下文丢失或不可信。

## Discriminator
任务开始时已知的两个可观察 token：(1) 上一轮结论引用过的独特相对路径 src/llm_loop/memory/extractor.py（及其单 commit 15 行 stat）；(2) 实验命名 token（.tmp-ci/mem-citations-exp、exp_offset_glm53f.json）。任一候选 repo 用一次该精确路径存在性检查即可接受/排除，无需先跑 status/diff/timeout 级查询。

## Short path
- 未知量=目标代码在哪个 tree：用已知独特路径 token 定向 glob（如 ls -d ~/*/src/llm_loop ~/*/*/src/llm_loop），一步得 ≤3 个 repo 根候选；不假设默认 workspace，不倾倒 home 目录列表
- 未知量=工作在哪个分支：对每个候选跑 git -C <P> branch -a | grep -i <实验名token>，唯一命中 experiment/* 分支（本例 experiment/mem-citations-20260922）
- 未知量=当前真实状态：在命中 repo/分支上一次性跑 git log -3、git diff main...HEAD --stat、git status --short | head，取齐回答所需事实
- 口径核对：区分单 commit stat（extractor 15 行）与分支整体 diff（8 文件/+662 含无关修复链），据此给出拆分支/PR 范围建议
- 来源验证通过（目标符号 grep 命中 + commit 存在于该分支）即停止，不再枚举其他 repo 或目录

## Stop conditions
- repo 根与分支唯一确定，且目标文件/commit 在其中被直接验证（grep 命中、hash 存在于该分支）
- 用户问题所需状态事实（log/diff 范围/status）已从该 repo 取齐
- 若路径 token glob 后仍多候选且实验名分支过滤零命中：停止枚举，改按 mtime 取最近副本或向用户确认，不再逐 repo 漫查

## Verification
- git -C <repo> rev-parse --show-toplevel 与 glob 所得根一致
- 在该 repo 内对目标精确路径 grep 目标符号（如 _build_history_text）命中
- git branch -a 含实验分支，且引用的 commit（如 26da66f72）存在于该分支（log/merge-base 验证）
- 状态结论口径已区分单 commit 与分支整体 diff，避免把 commit stat 误当成 PR 范围

## Counterexamples
- token 不独特（src/index.js、README.md 级别）时 glob 命中海量 repo，方法退化：须先收集更独特的 token 或改用实验名/mtime 判别
- 先前工作未提交或未开实验分支：branch 过滤必然零命中，应退到 git status / 最近修改文件定位，而非反复换 glob 深度
- cwd 或上一轮已明确给出 repo 绝对路径：直接跑状态查询即可，定位步骤本身成为浪费
- 存在 mirror+archived 多副本且都含该路径：不能取 glob 第一个结果，必须用分支名或 mtime 二次判别
