---
method_id: repair-query-on-explicit-syntax-error-receipt-1d3b71a68e1c
name: repair-query-on-explicit-syntax-error-receipt
description: 当工具回执是确定性输入语法错误（如 PatternError: unterminated subpattern at position N）时，回执本身已完整诊断缺陷：输入无效，重试相同参数必然复现。正确动作是把回执当一次性修复指令——转义元字符或降级为字面/固定字符串搜索——并先核对先前成功命中是否已覆盖目标引用点，已覆盖则直接跳过该搜索。禁止对同一 syntax 类错误回执做原样或近似重发；transient 类回执不适用此规则。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:1212:18d2c3d463008c5d09de
evidence_refs: learning:learn:2f9c410a1be8
created_at: 2026-10-08T10:33:40.310285+08:00
updated_at: 2026-10-08T10:33:40.310285+08:00
---
## Trigger
工具返回明确命名失败类别的语法/输入无效错误回执（regex PatternError 且给出出错位置），而下一步的自然倾向是原参数重试或换措辞再搜同一目标。

## Discriminator
错误回执文本本身区分了两类失败：本例为 'PatternError: missing ), unterminated subpattern at position 15'——属 invalid-input/确定性错误（重试必复现），而非 transient（timeout/连接/锁）或 no-match（语义问题）。当时该回执已完整可见，却仍连续重复触发了同类失败。

## Short path
- 读到错误回执，先读类别与出错位置，机械分类为 invalid-input / transient / no-match 三类
- invalid-input 类：禁止原参数重发；修复查询——转义括号等元字符，或改用字面子串搜索
- 修复前先核对既有成功命中：若目标引用点已在先前成功搜索结果中（本例 T2 关键引用已命中），直接放弃该查询
- 用修复后的查询重试一次，确认回执为正常命中而非错误回执
- 回到主线任务，继续原计划的读取/实现步骤

## Stop conditions
- 修复后的查询返回正常命中结果
- 所需目标事实已由先前成功命中覆盖，无需再搜
- 修复重试一次后仍失败：升级为换工具/换路径或人工确认，不进入循环重试

## Verification
- 重发参数与失败参数逐字节不同（可机械 diff）
- 最终结果覆盖了原查询意图的目标符号/引用点
- 同一会话内同类 syntax 错误回执不再重复出现（本轨迹中同类 PatternError 连续复现 ≥3 次，即为未验证信号）

## Counterexamples
- 瞬时性失败回执（timeout、连接拒绝、锁竞争）：原参数重试可能正是正确动作，本方法不适用
- '无匹配'类回执：属查询语义/范围问题而非语法错误，换措辞或换搜索面仍有意义
- 回执为模糊通用失败（无类别信息的 500/opaque error）时，不能仅凭一次失败断定输入无效并跳过重试
