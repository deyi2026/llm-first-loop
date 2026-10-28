---
method_id: skip-repetitive-audit-array-read-verdict-tail-of-truncated-receipts-a25206985de2
name: skip-repetitive-audit-array-read-verdict-tail-of-truncated-receipts
description: 截断回执按 range 分段水合时，若首分片显示主体是同构重复的审计数组、且 schema/早前回执已点名裁决键在尾部：不顺序扫数组体。先一次探读末端，用 count+complete 钉死精确边界，再从尾部锚点读回裁决字段；边界确立后绝不再发超尾读。用 range 元数据算术替代全量遍历，2-4 段定向读即可取代 8+ 段顺序水合。
aliases: 截断回执倒着读, 重复审计列表不用逐条看, 分段读大JSON先探边界, 探底式分片水合, 从后往前捞关键字段
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:555:beaa8eae712e5a377bde
evidence_refs: learning:learn:ab55637204a4
created_at: 2026-10-27T19:31:48.351727+08:00
updated_at: 2026-10-27T19:31:48.351727+08:00
---
## Trigger
工具回执被截断、需按 range 分段水合完整载荷；首分片可见载荷由同构重复条目的长数组（审计/lag/日志类）主导；本 run 旧回执或工具源码已给出该回执 schema 并点名承载裁决的命名键（如 convergence/stage_facts/live 身份/matches_desired）

## Discriminator
首分片数组条目键名完全同构复现 + 已有 schema 证据 ⇒ 数组体不再缩小任何未知量；range 元数据中 start+count 与 complete=true 可由一次读数精确给出 blob 末端，越过该末端再读必为 count=0 纯浪费（本 episode 实际出现两次超尾空读及多段数组体采样）

## Short path
- 用直接回执首段 + search_evidence（旧回执/工具源码）列出裁决命名键，把未知量缩为『这些键的当前值』
- 发一次靠后探读：由 count 与 complete=true 钉住 blob 精确末端 start+count
- 从末端向前按锚点补读尾部分片，捕获 stage_facts/live 身份/matches_desired/stable 等裁决字段
- 仅当裁决字段仍缺时再向前补一段，不进入数组体
- 全部命名键取到且末端已确立即停

## Stop conditions
- 所有裁决命名字段已在水合分片中实际出现（非 schema 推测）且与受理回执/desired 期望互证一致
- range 报 complete=true 且末端 start+count 已确立，不再发任何 start≥末端的读
- 用户目标转向数组体内某特定条目时，停止跳读、改为对该条目的定向扫描

## Verification
- 核对最终引用字段的字符位置确落在被读分片的 range 区间内
- 末端算术自洽：最末一次有效读 count>0 且 next_start=null；无第二次超尾空读
- 裁决结论与早前 convergence/受理快照（desired generation、lagging 清单）可交叉验证

## Counterexamples
- 数组条目不同构、且用户要找的正是数组中某条异常记录（如某个特定 generation 的异常 lag）时，跳过数组体会漏掉答案
- 无任何旧回执/源码给出 schema 时，须先读头部学习结构，不能直接跳尾
- blob 总长不超过 1-2 个分片时整读更省，探底反而是额外开销
- 水合接口本身支持 blob 内关键词检索时，应直接检索键名定位而非分片算术
