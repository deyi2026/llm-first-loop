---
method_id: stop-refinement-chase-after-mechanism-decides-design-1b7a77266c5e
name: stop-refinement-chase-after-mechanism-decides-design
description: 提改进/演进建议类任务：当一条机制级源码事实已确定建议的设计结构（甚至证伪了用户字面前提）时，立即转入撰写提交；不能再改变结构的子细节以 open question 写进建议正文。本例中 grant 生命周期（进程内一次性、owner 死后结构性丢失、跨进程 claim 必然无 grant）已把『grant 释放后重试』证伪并确定『瞬态有界退避 + 永久 re-arm』二分后，又为 runner.start() 的瞬态条件枚举了 6+ 次查找（路径查询、code_structure×2、正则报错、内容搜索×2 无命中、宣称 grep 未执行），最终未用其任何结果即提交——这段尾迹是纯损耗。另：起步时应用用户消息中的字面 token（grant）直接做代码检索，可一次同时命中实现、既有经验文档与调度器符号，避免在事件流里用 paraphrase 关键词试错。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5adf278f-405b-44db-95e5-3d3b94e1b8d9:235:f87de584862bedd8f037
evidence_refs: learning:learn:c0ef8f74914f
created_at: 2026-09-19T12:13:21.632020+00:00
updated_at: 2026-09-19T12:13:21.632020+00:00
---
## Trigger
任务是基于现状提一条改进/演进建议；已读到一条机制级事实（分支语义、资源生命周期、跨进程移交规则）足以确定建议的分类与修复方式；此时又冒出『再核一个小细节』的冲动，且预判该细节的答案不会改变建议的结构；或表现为：同一未知量已连续 1~2 次检索失败（索引无命中、正则报错），仍在切换第三、第四种查找工具。

## Discriminator
对每个待核子问题问一句：它的答案会改变产出的结构（失败分类、修复方式、可行性）吗？判据用已读事实：若各候选分支的行为已被直接读到的代码覆盖（例：无论 start() 因何返回 None，该分支都无条件 return True 永久消费；grant 已被证伪为结构性不可恢复），则该子问题只影响措辞——判为非必要。辅 signal：检索连续两次无进展仍换工具=扩散，不是收敛。

## Short path
- 用用户请求中的字面 token（如 grant）直接做代码内容检索，预期一次同时命中：实现位置（reason=grant_unavailable 所在行）、同主题既有经验文档、相关模块符号（wake_grant）；解决的未知量：机制现状 + 是否已有同类提案
- 读经验/提案记录，取得既有 EVO id 与证据 URI，查记录完成去重定位（本次是补充而非重复）
- 读实现命中行附近，建立分支分类表：哪些失败路径可重试（return False 由调度器重试）、哪些永久消费（return True）
- 读机制所属模块的生命周期代码（创建/持久化/跨进程 claim/清理），判定用户字面前提是否成立；若证伪（本例：grant 进程内一次性、不落盘、owner 死后 claimer 必然拿不到），改写为正确前提下的设计（瞬态→有界退避；永久→re-arm）
- 一次轻量状态检查（pending/executing 演进数）确认无冲突后，直接撰写并提交建议
- 未能闭合的子细节（如 start() 返回 None 的瞬态条件细分）以 open question 列入建议正文，不再为其发起检索

## Stop conditions
- 决定建议结构的事实已从源码直接读到（分支语义 + 资源生命周期），且用户前提真伪已判定
- 任一剩余子问题被判定为『答案不改变结构』→ 转为建议文本内的 open question
- 同一未知量的检索连续 2 次失败（无命中/工具报错）→ 停止换工具枚举，降级为 open question 或向用户求证
- 去重关系（与既有 EVO/经验的补充或重复）已写明，且无执行中演进冲突

## Verification
- 提交前自查：建议中每个机制断言是否都能指到已读的源码行或事件记录，无凭记忆外推
- 自查：不存在『宣称要做但未做』的验证（如已宣布 grep 却未执行）——若有，删除断言或降级为 open question
- 自查：被放弃的子细节已在建议中以 open question 显式列出，而非静默消失

## Counterexamples
- 若子问题答案本身决定设计分类（如瞬态 vs 永久尚未判定、修复方式依赖它），必须查清后再提建议，不得用 open question 豁免
- 安全/数据完整性/权限相关断言，即使设计已定也须完全验证后才能写入建议
- 若子问题是一次确定性查找（符号与行号已知、单次 grep 必中），顺手做掉成本低于写 open question——本方法反对的是工具循环枚举，不是核对本身
- 开放式探索/研究类任务没有『设计已定』的锚点，不应套用此停止规则
