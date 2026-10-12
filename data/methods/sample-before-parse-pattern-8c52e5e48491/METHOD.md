---
method_id: sample-before-parse-pattern-8c52e5e48491
name: sample-before-parse-先取样后写提取pattern
description: 需要从文件中按模式提取结构化字段（ID、行、记录）时，若本会话尚未直接观察过该文件的真实格式，不要凭假设先写 regex/grep/awk。先用 head/sed 读一屏代表性样例，从观察到的行导出一条锚定 pattern，执行一次提取，再核对输出数量与形状。本集证据：第 1 步 ls 已确证 iq_R1.jsonl 从未创建（用户问题的答案当时已成立）；后续为生成 40 例 opaque_id 模板时，先猜 pattern 提取出 21 行垃圾 ID（claim-35/search-73…），再宽 grep '^## ' 得到 '##' 占位符的畸形模板，直到 head 样例显示真实标题行 '## 1. `ab4d262187dd`' 后，一条锚定 sed 一次提取出全部 40 个 12 位 hex ID。对同一源文件反复换提取参数，正是本方法要消除的摩擦。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:545:12c81345302d35fd8af7
evidence_refs: learning:learn:a40c81d5d901
created_at: 2026-10-06T01:47:15.285795+08:00
updated_at: 2026-10-06T01:47:15.285795+08:00
---
## Trigger
即将对某文件执行模式提取（regex/grep/sed/awk 解析 ID、行、字段），但本会话内没有任何来自该文件的真实格式样例，pattern 只能凭文件名或经验假设。

## Discriminator
目标文件的确切记录/标题格式是否已在本会话被直接观察到。未观察=任何提取 pattern 都是未验证假设（本集第 2 步猜 regex 时即此状态）；一旦看到真实样例行（如 '## 1. `ab4d262187dd`'），pattern 空间即从无数猜测塌缩为一条可推导的锚定提取。此事实在写 pattern 前用一次低成本读取即可取得。

## Short path
- head/sed 目标文件一屏样例，观察真实记录/标题格式（未知量：目标字段在文中的确切排版）
- 从观察到的行直接导出锚定 pattern，不做第二次猜测
- 执行一次提取
- 校验条数与形状（如 40 条、全部 12 位 hex、与样例行一致）即停

## Stop conditions
- 提取结果条数与格式均与样例观察及文档声明一致（40 例、ID 形状匹配样例行）
- 样例显示目标文件并无结构化记录（如纯散文）→ 放弃模式提取，改为人工阅读

## Verification
- 抽取值与 head 样例中直接可见的行一一对应（首条应为 ab4d262187dd）
- 总条数与权威声明一致（盲表标称 40 例）

## Counterexamples
- 格式已有权威 schema/文档，或文件是本会话自己刚写出的 → 直接解析，取样是浪费动作
- 取样会违反读取约束：本集中 iq_sealed.json 与 iq_R2.jsonl 属盲评封存/他人答卷，'先读样例'不得用于被禁止的源；应改读允许的格式说明（sheet 头部已写明答卷 JSON 行格式）
- 文件格式非均匀（多 section 结构不同）→ 单屏样例不具代表性，需多点采样或读 schema，而非直接套一条 pattern
