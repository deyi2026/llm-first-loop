---
method_id: budget-named-gate-rejection-recover-accounting-then-split-verified-units-29dee38d72a8
name: budget-named-gate-rejection-recover-accounting-then-split-verified-units
description: 门禁回执按字面量分两类，对策相反：预算命名型（如 exceeds_<N>）是确定性合同，重试无用，必须改材料；可用性型（*_unavailable）材料无辜，冻结+退避。对预算型：先用错误字面量 grep 门禁源码恢复『度量口径+法定补救』（本例注释明示超限须拆分），再单条命令量化材料构成组件（tracked diff、untracked 逐文件），按算术重组——只 commit 已持独立 PASS 证据的单元收口、隔离经验证的外来 untracked 文件（审后放回），重测达标再重提交。历史补救成功一次不构成本次同因证据；一次定向补救失败即转核算，不再换参数重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f14553ff-29f5-4d15-a5a8-ee029c618df1:727:d678cd9a8c302c86c14f
evidence_refs: learning:learn:69fd8a6f0678
created_at: 2026-10-20T23:38:33.041088+08:00
updated_at: 2026-10-20T23:38:33.041088+08:00
---
## Trigger
本地门禁/准入工具以确定性预算错误（回执字面量含 exceeds、上限数值或条目数限制）拒绝提交物；同一门禁还发出另一类外观相似的服务可用性失败回执（*_unavailable/timeout）；或历史上同类错误用某补救（如清理运行时产物）成功过一次， tempting 直接复用。

## Discriminator
回执字面量命名的是确定性阈值检查而非服务状态（exceeds_<N> vs unavailable）；门禁源码本地可 grep 到检查行、材料构成函数与注释中的法定补救；材料组件当时即可用单条命令量化。分流依据是回执类别而非历史经验；一次定向补救失败后即应转入核算模式，不再原样或换参数重试。

## Short path
- 收到预算命名回执：以错误字面量 grep 门禁工具源码。未知量=门到底度量什么、法定补救是什么。得到检查阈值、构成规则（committed_delta+working diff+untracked 全文）与注释明示的超限处置（如 deterministically require splitting）。
- 按与门禁相同的口径本地量化各组件（git diff 字节数、untracked 逐文件大小）。未知量=污染还是真超。污染→定向清理后重试一次；真超→下一步。
- 按协议法定补救重组：核对 merge-base 关系确定可压缩项；只把已持独立 PASS 回执+全量绿证据的单元 commit 收口（禁止 commit 未审查工作来压体积），其余改动作为独立审查单元。
- 对拟移出的 untracked 文件先读头部验证来源（本例确认为他任务计划文档）→ 移出隔离并记录原名与位置，审后放回，不盲删。
- 重测材料 ≤ 阈值再重提交，确认新 Accepted SHA 对应预期单元。并行规则：unavailable 类回执不动材料，冻结 SHA+间隔退避或延迟排程。

## Stop conditions
- 材料按门禁同口径重测 ≤ 阈值且重新 Accepted，新 SHA 对应预期的独立审查单元
- 连续多次 unavailable 判定为基础设施持续故障：转延迟排程重试+如实上报，不紧循环、不改材料
- 隔离的外来文件已在门禁通过后放回原位并核对 git status 复原

## Verification
- 重提交前用与门禁一致的构成规则本地重算材料总字节数，而非只看单一 diff
- 被 commit 收口的单元必须已持独立 PASS/全量绿回执，不得借 commit 未审查改动绕过预算
- 外来文件隔离前后各核对一次 git status，确保只有预期变量变化

## Counterexamples
- 回执为 *_unavailable/timeout 等可用性类：材料无辜，冻结+退避；此时重结构材料反而改变已 Accepted 的 SHA、引入新变量
- 超额明显且可归因于已知可再生成的运行时产物：一次定向清理重试可接受，无需全量核算
- 审查单元必须原子（跨文件不变式）且协议无拆分路径：上报或询问，不得拆分或 commit 未审查内容压体积
- 门禁为远端不透明 API、源码不可 grep：以官方文档或二分定位替代源码核算
