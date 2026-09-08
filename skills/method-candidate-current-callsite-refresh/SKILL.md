---
name: method-candidate-current-callsite-refresh
description: Repo/API candidate distilled verbatim by Qwen3.8-27B from the parallel-line stale-callsite teacher episode; experimental candidate only, not promoted.
status: candidate
source_model: qwen3.8-27b-mlx-8bit
---
# Qwen-authored candidate (verbatim)

FRICTION
- 调用点清单是"修改前"的快照；之后并行工作线重构了同一文件，行号与调用形态漂移，旧清单失效。
- 实施时沿用旧清单编辑，漏掉了漂移后的调用点。
- 单行 grep 无法展示 multiline call 的完整参数形态，参数是否齐全不可见。
- 定向测试未覆盖全部调用路径，缺失参数问题直到 full gate 才暴露。

DISCRIMINATOR
- 调用点枚举是"编辑时从当前定义对当前树重新反查"（新鲜）还是"复用修改前快照"（陈旧）——这是成败分界。
- 调用形态是"逐条读完整调用块"（multiline 感知）还是"单行 grep 匹配"（参数形态残缺）。
- 验证是"权威 full gate"还是"仅定向测试"。

SHORTEST_PATH
1. 编辑时从当前定义对当前树重新反查全部调用点，丢弃修改前清单。
2. 逐条读完整调用块，确认参数形态（multiline 感知）。
3. 应用修改。
4. 修改后再次枚举调用点，确认无遗漏。
5. src 有实质变化时，最终跑权威 full gate。

GENERAL_RULE
- 调用点清单是时点快照；捕获与使用之间若树发生变化（尤其并行工作触碰同一文件），清单即陈旧，必须在编辑时从当前定义重新反查。
- 签名变更（新增 required 参数）必须对照完整调用形态验证，单行匹配不足以判断参数是否齐全。
- 影响多调用路径的签名变更，定向测试不能替代权威 full gate。

COUNTEREXAMPLE
- 捕获与使用之间树未变化（无并行工作、无重构），旧清单仍有效，重新反查是浪费。
- 变更向后兼容（如新增带默认值的可选参数），不存在 missing-argument 风险，无需全量枚举。
- 调用点均为单行且文件未被触碰，单行 grep 足以判断参数形态。

METHOD CARD
- 名称：签名变更调用点新鲜反查
- 触发：给多调用点方法新增 required 参数（尤其 keyword-only），且并行工作可能触碰同一文件。
- 步骤：
  1. 编辑时从当前定义对当前树重新反查全部调用点，弃用修改前清单。
  2. 逐条读完整调用块，确认参数形态（multiline 感知）。
  3. 应用修改。
  4. 修改后再次枚举调用点。
  5. src 实质变化时跑权威 full gate。
- 验证：full gate 无 missing-argument TypeError。
- 反模式：复用陈旧调用点清单；用单行 grep 判断 multiline 调用；仅靠定向测试验证签名变更。
