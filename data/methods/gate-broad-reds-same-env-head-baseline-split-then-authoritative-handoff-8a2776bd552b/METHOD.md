---
method_id: gate-broad-reds-same-env-head-baseline-split-then-authoritative-handoff-8a2776bd552b
name: gate-broad-reds-same-env-head-baseline-split-then-authoritative-handoff
description: 全量门禁在与权威环境不同的受限通道（回执持续声明沙箱策略）跑出大面积红时，第一未知量是红的归因而非修复：同一通道对 HEAD 复跑同一失败子集做基线差分，把红分为环境红（基线复现）/diff 环境条件红（读测试源码找 mock 面与真实行为面错位）/真红三档；条件红的通过依赖本通道缺失的性质时，把门禁执行交回权威环境（宿主终端一行命令），拒绝把通道环境红登记进共享 registry 洗绿。与单静态守卫红方法互补：那条禁基线对照，本条以大面积+跨子系统+环境声明为触发。
aliases: 门禁一片红先跑HEAD基线分环境红, 沙箱里跑CI全红怎么对账, 测试大面积失败先分环境红和diff红, 嵌套沙箱门禁假红别登记registry, 同环境复现HEAD判断环境红, 门禁跑不绿交给宿主终端
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8f138285-6159-4a14-b4b4-aa385dc29d8f:0:dbc4f589bd1a582cba6a
evidence_refs: learning:learn:8ce53198eeb3
created_at: 2026-11-01T06:38:55.354637+08:00
updated_at: 2026-11-01T06:38:55.354637+08:00
---
## Trigger
全量门禁（机检已过、进入 ci_gate/CI）跑出几十条红，横跨 PTY/TTY/IME/skills/env 等环境敏感子系统，远超本次少量文件的 diff 触碰面；且执行通道已知与门禁权威环境不同（每条回执带沙箱/受限声明，或已有权威环境探针、历史绿门禁证据在别处）。

## Discriminator
三条当时已知事实同时成立即可把『逐条修红/登记豁免』缩成『先归因』：① 本通道回执持续声明沙箱/受限策略——环境差是显式声明的，不是猜的；② 已有回执证明门禁规范环境在别处（如宿主探针 rc=0 非嵌套、历史门禁全在宿主跑绿）；③ 红簇横跨的子系统数 ≫ diff 触碰面（如 6 文件 vs 终端/skills/env/sandbox 多簇）。

## Short path
- 不修红、不登记豁免：先在 detached worktree、同一解释器、同一通道对 HEAD（不含暂存 diff）复跑门禁失败的同一测试子集，把基线红清单落成文件（清单求差用文件+comm/awk 两步走，不依赖 /bin/sh 进程替换，也不手抄清单）。
- 求差集 门禁红−基线红：基线复现的即环境红；对差集逐条读测试实现，定位『测试 mock 的面 vs 新实现实际行为』的错位（如只 mock 二进制存在性而新实现实跑探针），分出环境条件红与真红。
- 环境条件红的通过条件若正是本通道缺失的性质（嵌套致探针被拒）且权威环境可用：机械修正入口错误（如提交前缀按回执自述白名单改）后，把门禁命令交付权威环境（宿主终端）执行；绝不把通道环境红登记进共享 external_red_registry 换绿——那会把通道污染进规范环境登记表。
- 输出对账表（每红一档：环境红/环境条件红/真红 + 证据来源），明确声明提交未完成、终态以权威环境门禁回执为准。

## Stop conditions
- 对账闭合：环境红均有 HEAD 基线复现证据、diff 归因红均有源码级机制解读、权威环境门禁命令已交付。
- 差集中出现与 diff 同子系统、非 mock 错位的实质断言红 → 停止环境归因，按真红修复。
- 本通道即门禁权威环境（无环境差）→ 无 handoff，只保留步骤 1-2 的差分定位。

## Verification
- 基线红 ⊆ 门禁红且数量对账成立（差集非空且逐条可解释）。
- 每条环境条件红都能在测试源码中指出 mock 面与真实行为面的具体错位位置。
- 终态以权威环境（宿主终端）门禁回执为准；本通道结果不得用于宣布完成或登记豁免。

## Counterexamples
- 门禁只有一条红且是纯静态对账守卫（AST 计数/allowlist vs 外置 fixture，无 PTY/env 依赖）→ 适用 single-static-ratchet-red-guard 方法：失败分布已排除环境红，禁止先做基线对照。
- 本通道就是门禁权威环境（无环境差）→ 基线差分只为定位真红，不存在交付宿主终端一说。
- 红清单集中在 diff 真正触碰的子系统且有非 mock 的行为断言 → 那是真红，环境归因不成立。
- 执行通道已结构性死亡（连 no-op 命令都失败）→ 适用 dead-channel delegation 方法：问题是通道本身，不是红归因。
