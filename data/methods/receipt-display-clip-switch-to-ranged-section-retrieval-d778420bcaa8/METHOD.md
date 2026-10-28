---
method_id: receipt-display-clip-switch-to-ranged-section-retrieval-d778420bcaa8
name: receipt-display-clip-switch-to-ranged-section-retrieval
description: 长文档读取回执为 success 且声明总行数，但实际展示内容在中途截断（末行号远小于总数、句子断在半截）时，同参数重读只会得到同一首屏。把『如何取到未展示区间』当作立即未知量：改用带 start/limit 的区间/分页读取，并按任务真正需要的章节锚定范围（锚点可由早前检索命中的行号推出）；疑似重复副本先一次性哈希比对，一致则只读一份。本集以此省去两次原样重读 488/251 行文件的零信息往返。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:162:48f532eb105daeaa03bf
evidence_refs: learning:learn:428c58817120
created_at: 2026-10-22T00:23:25.729634+08:00
updated_at: 2026-10-22T00:23:25.729634+08:00
---
## Trigger
read 类工具回执为 success，但声明的总长度与实际展示内容的末行明显不符（内容中途截断），且任务只需要文件内特定章节/清单/逐字原文，不需要全文通读。

## Discriminator
回执内部两个可观察数字可直接比对：声明的总行数（如 488/251）vs 实际展示内容的最后一行行号（如 40，且断在半句）。两者不一致即证明展示窗口截断而非读取失败，重发同参数读取必然返回同一首屏，是零信息动作。

## Short path
- 比对回执：展示末行 < 声明总行数 ⇒ 判定首屏截断，禁止原样重发同一 read
- 由早前线索（search_files 命中行号、章节标题位置）定位任务所需锚点区间，改用带 start/limit 的区间读取取代整文件重读
- 区间回执若含 next_start/complete 等分页元数据，按页推进直至覆盖全部锚点章节（如权威 P0 清单 §11 与被引逐字原文）
- 多份疑似重复副本先一次性 md5/sha 比对，确认一致后只读其一
- 取得目标章节逐字内容并通过行号与上游文档引用核对一致后即停，不追求全文通读

## Stop conditions
- 任务所需的权威清单/逐字原文已从区间回执取得，且行号与上游文档引用一致
- 某次回执 complete:true，或展示末行==声明总行数且所需区间已被覆盖

## Verification
- 抽查产出物中每条『逐字原文』都能在区间读取回执中按行号定位到
- 副本取舍以哈希回执为依据而非文件名直觉，未重复读第二份

## Counterexamples
- 回执展示末行已等于声明总行数（无截断征兆）→ 直接进入分析，不加分页调用
- 读取是显式 failure（超时/权限）而非 success 但截断 → 重试原调用可能是正确动作，判别信号不同
- 任务确实需要全文通读且无区间参数 → 分段读完整文件本身就是目标，方法不改变动作
- 截断只发生在无关尾部、所需内容已完整出现在首屏 → 无需任何额外读取
