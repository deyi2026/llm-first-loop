---
method_id: intent-state-contradiction-probe-veto-gates-6051991d5cf0
name: intent-state-contradiction-probe-veto-gates
description: 当版本控制配置已表达明确意图（如 .gitignore 反选例外、带日期的'入库保全'注释），而该路径在活跃维护的仓库中仍跨会话保持 untracked 时，这不是普通遗漏，而是否决层（pre-commit hook / 安全扫描 / 策略脚本）可能存在的证据。在批量 stage/commit 依赖该例外的路径之前，先廉价探测闸门（git log --all -- 路径找失败痕迹；core.hooksPath 与扫描脚本的路径禁则）；若与较新的治理决定冲突，先以最小粒度修正闸门（仅豁免禁路径规则，内容/体积/密钥检查保持全量）并单独提交，避免在数百文件已 staged 的提交时刻才被拦、被迫中途做策略修改。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:311:868fcaedeac4496802c5
evidence_refs: learning:learn:76301e080889
created_at: 2026-09-19T17:36:09.993069+00:00
updated_at: 2026-09-19T17:36:09.993069+00:00
---
## Trigger
准备批量 stage/commit 一个依赖策略例外的路径（ignore 反选规则、豁免清单、治理注释声明应入库）之前；且该路径虽有明确入库意图标记，却持续 untracked（活跃仓库中多日/跨会话未执行）。

## Discriminator
配置中的显式意图标记（如反选规则 !data/methods/ 加带日期的'入库保全'注释，以及被注释解除的同类规则）与观测状态（该路径仍出现在 ?? untracked）相矛盾，同时 git log 显示仓库每天都有提交——蓄意的治理决定在活跃维护下多日未执行，更可能被某个闸门拦截而非被遗忘。这个矛盾本身把'为什么还没入库'从'许多可能'缩到'被哪道闸拦了'。

## Short path
- git status 盘点 + 读治理配置（.gitignore 等），把每个 untracked 条目分类为 intended-in / intended-out
- 对 intended-in 却长期 untracked 的路径：探测否决层——git log --all -- <path> 是否有失败/尝试痕迹；git config core.hooksPath 与 hook/扫描脚本里是否存在覆盖该路径前缀的禁则
- 若闸门与较新的治理决定冲突：先以最小粒度修正闸门（新增仅豁免'禁路径'的清单项，内容/大文件/密钥检查保持全量），单独提交并附反向用例
- 再做内容分类（二进制安全方式核非文本文件、可再生缓存加排除规则），然后按计划顺序 stage/commit 批量内容
- 验证：批量提交在 hook 正常启用下落地（不绕过）；被禁的同根其他路径仍被拦；最终 porcelain 无计划外残留

## Stop conditions
- 无意图-状态矛盾（路径是新增，或确系遗忘且本地无任何闸门）→ 直接执行，不做闸门探测
- 本地探测未发现任何否决层 → 阻断可能在远端（push 保护/CI 门禁），停止本地探测，把验证计划移到 push 阶段
- 闸门冲突已以最小粒度解决并提交、批量提交成功、反向用例仍被拦截 → 目标达成，停止

## Verification
- 闸门修正后：同根的其他路径（禁则原本覆盖的兄弟目录）提交仍被拦截，证明豁免未过度放宽
- 目标批量提交在 hook 正常启用下成功（未使用 --no-verify 之类的绕过手段）
- git status --porcelain 复查：intended-in 路径已变为已跟踪，剩余 untracked 条目逐条可解释（intended-out 或范围外已上报）

## Counterexamples
- 无 hook 的仓库、遗漏确系简单遗忘：探测只增加一次调用而无收益；不应推广到所有 untracked 路径，仅限'有意图标记却未执行'的矛盾情形
- 意图标记是本会话刚写入的（尚不存在'长期未执行'矛盾）→ 无异常，无需探测，直接执行即可
- 否决层在远端（服务端 push 保护、CI 门禁）：本地闸门探测一无所获，commit 会成功而 push 被拒，方法在 commit 阶段不适用，需改为 push 前验证
