---
method_id: continue-truncated-receipt-via-range-pointer-or-blob-identity-c99bd6d36f11
name: continue-truncated-receipt-via-range-pointer-or-blob-identity
description: 工具回执被定长窗口截断（complete:false、next_start 存在，或肉眼可见截断在结构中段），而任务需要的字段不在已见前缀里时，不要对 Evidence 库换关键词搜索，也不要重复拉取同一段前缀：先用回执自带的 range 指针从 next_start 续读，或用 integrity.blob_sha256/evidence_ref 内容地址直接定位存储的完整工件、按字段名定点提取；取到任务所需事实即停，回到既定下一动作。
aliases: 回执被截断继续读后半段, complete false 从 next_start 翻页, 按 blob sha256 直接定位原文, status 输出没看全先续读别去搜索, 水合回来的还是同一段前缀怎么办, 截断 JSON 回执里缺的字段去哪找
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:3704:14131c5ca7c378809f96
evidence_refs: learning:learn:4c9ecf9f173b
created_at: 2026-10-28T20:22:40.150451+08:00
updated_at: 2026-10-28T20:22:40.150451+08:00
---
## Trigger
工具回执输出被有界窗口截断（可见 range/next_start/complete:false，或明显截断在 JSON 结构中段），且任务所需字段未出现在已见窗口内

## Discriminator
回执自身的 range/integrity 元数据（next_start、complete:false、blob_sha256、evidence_ref）证明完整内容存在于已知地址——缺失字段就在这份工件里，属于'未读到的字段'而非'需要另寻来源的信息'

## Short path
- 识别截断回执：把未知量定义为'这份回执未读窗口内的具体字段'，而不是'去哪里能找到这些信息'
- 若元数据给出 next_start，从 next_start 续读（或调大 limit），直到出现所需字段或 complete:true
- 续读不可用时，用 blob_sha256/evidence_ref 内容地址直接定位存储工件，按字段名定点提取（只打印所需键），跳过无关的 ref_index/目录层
- 以实测值核验交接结论（desired/generation/restart_required），随后用回执里的准确参数执行既定变更动作
- 变更受理后按交接协议立即收尾，不追加任何工具调用

## Stop conditions
- 任务所需字段已从与原回执同一内容身份（blob_sha256/range 一致）的工件中取得并核验
- 既定变更动作已用回执准确参数发出并被受理

## Verification
- 提取值所在工件的 blob_sha256/range_sha256 与原回执元数据一致
- 发起变更所用的 generation 等于回执中的最新 generation

## Counterexamples
- 回执完整可见（无截断、complete:true）→ 直接使用，不做任何恢复动作
- 截断源于生产方本身只产出部分内容（coverage 标 source_partial 且 producer 未完成）→ 续读无用，应重新调用生产工具或等其完成
- 所需字段根本不属于该回执的 schema（属于另一类 artifact）→ 此时目录/检索式发现才是正确手段
- 省略只是显示层折叠、生产工具支持过滤参数重查 → 优先带过滤重查，而非绕道读存储 blob
