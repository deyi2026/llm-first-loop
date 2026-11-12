---
method_id: publish-freeze-delta-trim-derivatives-not-rewrite-a785591e3f30
name: publish-freeze-delta-trim-derivatives-not-rewrite
description: 用户明令冻结迭代（'别再改、赶紧发布'）且一次性状态回执已显示机械闸门（build/audit/index/caption）全 PASS、稿件 sha 冻结时，最后一公里按纯执行处理：为下游（审稿/准入）产派生材料时优先复用盘上已在预算内的同族制品；确需新生成，则在首次输出打印出字符数后，按 chars−budget 的实测差值对已序列化结果做定量裁剪，字段绑定只用回执里实际出现过的键名。避免连环重写生成器导致的超限断言、KeyError、守卫阻断循环。
aliases: 赶紧发布别再改了怎么收尾, 审稿包超字数反复失败, 按超限差值定量裁剪材料, 发布前最后一公里少走弯路, 机检全过了接下来做什么
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:9d6fa5ef-aebe-4139-9dc8-362769390812:1591:0e7ebed8da66113fc570
evidence_refs: learning:learn:70dad997f3f0
created_at: 2026-11-12T12:55:40.155200+08:00
updated_at: 2026-11-12T12:55:40.155200+08:00
---
## Trigger
用户已给出'停止重复修改、立即发布'类指令，且一次状态 dump 已显示机械闸门全 PASS、内容 sha 冻结；此时仍需为下游消费者生成带硬字符预算的派生制品（审稿包/准入材料）

## Discriminator
同一份状态回执里已同时存在三件事：门禁全 PASS + 当前 sha；盘上同族制品各自的字符数（本集 6 个包全部 ≤ 预算 31698）；源回执的实测键集（BUILD 行并无 img_sha256）。首次生成又打印了精确 chars（33537/33404）→ 超限差值是已知数，裁多少不需要靠重写选择逻辑去猜。

## Short path
- 读一次性状态 dump：门禁全 PASS、sha 冻结 → 切换执行模式，后续动作只服务发布链路
- 需要审稿材料：若盘上最新同族包 ≤ 预算且与当前稿仅措辞级差异，直接复用或增量补充；否则一次性生成并先看打印出的 chars
- chars 超预算：按 chars−预算 的差值从低优先级行定量裁剪已有序列化输出，不重写生成器、不动字段绑定
- 引用任何回执字段前，先核对 dump 中实际出现过的键名，杜绝 KeyError 与默认值双向错
- 发布走已验证分阶段脚本：session 内 sha ≠ 当前稿件 sha 即视为陈旧 tab，重跑 open/prepare，不从旧状态续跑
- 公网实见验收命中后立即收口，不再产任何新脚本、新包

## Stop conditions
- 派生制品 chars ≤ 预算且关键行仍覆盖裁决所需 → 立即送下游，不再打磨
- 公网 URL 实见且标题/图注/AI 声明命中 → 收口
- 门禁全 PASS + 用户冻结指令在位 → 禁止'再确认几个'式的额外读取与枚举

## Verification
- 裁剪后 chars ≤ 预算且 key_rows 仍覆盖全部数值断言（本集 42→16 属过度裁剪，应复核覆盖面是否被削弱）
- 发布时 session 记录 sha == 当前稿件 sha == 机检回执 sha
- 最终公网页面标题、配图、图注、AI 声明逐项命中后判 PASS

## Counterexamples
- 盘上同族包对应的稿件与当前差异不止措辞级（数字/结论已变）→ 复用会审错文本，必须按当前 sha 重新生成
- 下游消费者没有硬字符预算 → 整个裁剪循环无必要，全量送审即可
- 所需字段在源回执键集中根本不存在 → 是数据缺失而非命名错位，应回源头补采，不是裁剪或重试能解决的
- 机械闸门尚未全 PASS 或 sha 未冻结 → 仍处修改阶段，'执行模式'不适用，该改的内容还得改
