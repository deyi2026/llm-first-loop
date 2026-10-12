---
method_id: recover-truncated-ref-via-inband-identity-links-d0c55a754df8
name: recover-truncated-ref-via-inband-identity-links
description: 当 search/快照已定位目标对象记录、但显示截断在 grounding_ref/id 等必需字段之前时，不要从 offset 0 对同一 evidence blob 线性翻页。先把未知量收窄为『已定位记录的单个字段』；跳过前次已展示的区间；若能看到目标的子/后代对象，直接读其 relations.parent.target_id，配合已确认统一的 ref 模板（同一 observed_version）组装目标 ref 作为待验假设，用回执 target_id 回显 + 重感知效应做廉价验证；回显不符或父子层级存疑时才回退为按定位偏移的定向翻页。本质是把『扫整个 blob 找字段』缩成『沿已观察到的身份边取一个 id』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:409:2bda235c951fb13278f6
evidence_refs: learning:learn:b3db9bc0080c
created_at: 2026-09-18T03:13:11.108724+00:00
updated_at: 2026-09-18T03:13:11.108724+00:00
---
## Trigger
结构化 evidence blob（snapshot 或 search_evidence 命中）已定位目标对象的记录，但返回窗口截断在执行所需字段（grounding_ref/id）之前；blob 支持 range 寻址且分页读取，记录内嵌身份信息（id、parent target_id）

## Discriminator
唯一未知量是『已定位记录的单个字段』而非『哪个对象』；且当时已观察到：(a) 记录字段有序，grounding_ref 紧邻 attributes；(b) 子对象记录携带 relations.parent.target_id 指向父对象 id；(c) 同一 snapshot 内所有记录共享 observed_version、ref 模板完全统一；(d) blob 头部区间已被前次工具显示覆盖，从 offset 0 重读属重复调用

## Short path
- 把未知量写成一句话：目标对象的确切 ref/id（不是重新感知整页）
- 用 search 命中或上次显示确定记录大致区域；hydration 起点跳过已展示区间，不做 offset 0 起步的线性扫描
- 若可见子对象（如 selected 的 option）携带 parent target_id，取该 id 加当前 observed_version 按统一模板组装目标 ref，标记为待验假设
- 带假设执行/查询：action 回执必须逐字符回显相同 target_id，随后重感知读真实效应（状态文本、scrollY 等），不把回执 status=ok 当完成
- 回显不符、或父子之间可能隔层（optgroup/包装容器）时，回退为按定位偏移定向翻页，仍不做全量枚举
- 同页后续版本可复用布局先验：未重写的结构对象 id 跨 mutation 稳定，可先按旧偏移/旧 id 直取再验

## Stop conditions
- 回执 target_id 与推导/读到的 id 一致，且重感知确认预期状态效应：停止检索，进入下一动作
- 直接读到含确切 grounding_ref 的完整目标记录：停止
- 连续两个定向区间仍未出现目标记录或可用身份边：升级为全量分页或重新 snapshot（此时才允许宽搜索）

## Verification
- 比对 action 回执回显的 target_id 与推导/读到的 id 逐字符一致
- 动作后重感知，从权威观察（状态文本、scrollY）确认效应，而非只看回执 ok
- 复用跨版本布局先验前，确认 document scope/scope_ref 未变；文本类对象内容一变 ref 即换，必须当前版本重取

## Counterexamples
- 可见子对象的 parent 是中间包装层（optgroup、容器 div）而非目标本身：推导 ref 会指向错误对象，必须靠回执回显兜底或先读父记录属性
- 跨 navigate 后 document generation/scope 变更：旧版本的对象偏移与 id 全部不可复用，只能重新 snapshot+search
- 文本类对象身份不稳定（内容更新 ref 即换）：不能拿上一版本 ref 直接寻址
- 策略强制『必须逐字观察到的 ref、禁止模板组装』时：退化为定向翻页，但仍应跳过已展示区间
- 目标对象本身尚未被定位、无任何身份边可借时：本方法不适用，broad 感知/搜索才是正确下一跳
