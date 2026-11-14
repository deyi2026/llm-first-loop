---
method_id: full-sha-predicates-and-exit-code-triage-in-batch-git-audit-24a5b8f7409a
name: full-sha-predicates-and-exit-code-triage-in-batch-git-audit
description: 独立复核 caller 声明的 git 拓扑（最终 HEAD、祖先关系、range-diff 等价）时，把回执里的 40 字符全 SHA 钉成变量供一切布尔谓词（is-ancestor/rev-parse/cat-file -e）使用，短前缀只作人读标签；批量判定循环按退出码三档分诊——0=是、1=否、128=git 解析错误（短 SHA 与 tree/blob 对象撞前缀）记为未知并换全 SHA 重跑，不得折叠成 NO。反直觉判定先与同一输出的结构性事实交叉验证，矛盾指向谓词输入异常而非拓扑不符，避免把健康 rebase 误判 REVISE 或多耗重验轮次。
aliases: git is-ancestor 128 不是否, 短 SHA 歧义祖先误报, 复核 rebase 拓扑用全 SHA, 批量 git 检查退出码分诊, commit 前缀撞 tree blob 对象, git 循环判定把报错当 NO
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9120f664-b5f9-4bff-b802-001df07d5892:13:47d35bda9438f7e13ac3
evidence_refs: learning:learn:048060703562
created_at: 2026-11-14T14:15:09.288251+08:00
updated_at: 2026-11-14T14:15:09.288251+08:00
---
## Trigger
对集成/冻结候选做只读审计，需要把 merge-base --is-ancestor、rev-parse、cat-file -e 等布尔判定跑成批量循环，且仓库对象量大（commit/tree/blob/产物 SHA 并存，4~7 位短前缀可能不唯一）。

## Discriminator
任务/回执文本通常已提供全 40 字符 SHA；且同一批量输出内的结构性事实（parents 列表、rev-list --count、merge-base 值）可与循环判定即时交叉对照。若循环出现与父链矛盾的 NO（如 parents 已显示 HEAD^^=main），差异在谓词输入解析（短前缀歧义，rc=128 是 git 错误而非 rc=1 的语义否），不在拓扑本身。

## Short path
- 开局把回执全部全 SHA 钉成 shell 变量；谓词输入一律全 SHA，短前缀仅用于显示标签。
- 批量判定循环按 rc 分档：0→YES；1→干净 NO；≥128→UNKNOWN，立即换全 SHA 重跑，并用 rev-parse --disambiguate=<prefix> 确认歧义对象来源。
- 每轮输出中打印 parents/计数/merge-base 等结构性事实，与循环判定即时交叉；矛盾先诊断谓词（输入歧义/退出码混叠），不直接改拓扑结论。
- 拓扑确证后再做内容级复核：range-diff 全 SHA 复跑、pathspec 限定的可执行面 diff、与 main 推进段做集合级比对。
- 计数类声称与自测不符时按对方原口径复跑（读工具脚本确认计数语义）再裁决；四项声称全部独立复现即出结论。

## Stop conditions
- 四项声称均以全 SHA 独立复现且与回执一致（HEAD 逐字符匹配、range-diff 全部=、可执行面 diff 空、相对 main 文件清单吻合）。
- 全 SHA 谓词 rc=1 干净复现且与父链矛盾无法用输入歧义解释时，才升级为真实拓扑不符/REVISE。

## Verification
- 最终结论中出现的每个 SHA 均为 40 字符全形式且来自权威回执，无一自行扩写。
- is-ancestor rc=0 与 parents 链、rev-list --count 三个独立观测交叉一致。

## Counterexamples
- 小仓库、7 位短 SHA 唯一命中且无 tree/blob 撞前缀——直接用短 SHA 合理，先钉全 SHA 属过度流程。
- 交互式单次查询、失败立即可见且重试廉价的场景，无需预先分诊。
- 需要向下游回报完整 SHA 的场景属 freeze-and-transcribe（回报值逐字转写、禁止自行扩写），本卡只管谓词输入与退出码分诊。
- rc=1 本身就是待验证的真实否定答案（确实非祖先）时，无需做歧义诊断。
