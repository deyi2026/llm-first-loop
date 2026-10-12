---
name: method-self-distill-repo-api
description: Repo/API Method teacher exemplar。用于教模型从真实并行代码改动事故中提炼“当前定义 + 当前 callsite 才是真值、旧 grep 行号只是线索”的方法。样板来自 2026-09-03 必填参数变更后基于旧 callsite 清单编辑，最终 full gate 暴露 missing keyword-only argument 的真实 LFL Experience。
status: teacher
---
# Repo/API teacher: stale callsite inventory

## Real episode facts

- 核心服务方法新增了一个 required keyword-only 参数。
- 早期已经 grep 过调用点，并保存了行号/调用清单。
- 多条并行工作线随后重构了相同文件；调用形态和行号发生漂移。
- 实施时直接按早期清单编辑。
- 定向验证没有覆盖全部调用路径；full gate 新增 2 个 `TypeError: missing required keyword-only argument`。
- 其中存在多行调用，单行 grep 结果不能完整展示参数形态。
- 最终可靠做法：以**当前树**重新从定义反查全项目 callsites，逐条读完整调用块；签名变更后再次枚举；src 实质变化最终跑权威 full gate。

## Teacher distillation

**FRICTION**：把“我之前已经搜过”当作当前 API 真值，随后对旧行号逐点修补。每出现一个 TypeError 再补一个 callsite，会退化成运行时猜漏项。

**DISCRIMINATOR**：任务发生在并行活跃 repo，且 API contract 已改变。这个事实意味着任何旧 callsite inventory 都可能过期；当前定义和当前树引用才是最低成本真值源。

**COUNTERFACTUAL**：
1. 先读当前方法定义，冻结新签名。
2. 在当前树按符号做全项目反查。
3. 对每个命中读取完整调用块，特别是 multiline call。
4. 修改后重新枚举一次，确认没有旧签名 callsite。
5. 定向测试后，再跑项目规定的 full gate。

**GENERALIZE**：在活跃代码库里做 API contract 变更时，旧搜索结果只能导航，不能授权编辑。每次签名变化都要从当前定义出发重新枚举当前 callsite，并检查完整调用形态。

**FALSIFY**：若 API 根本没有变，或调用完全由生成代码/静态类型系统统一更新且已有可靠 compiler gate，则不必机械重复全仓人工审读；应使用更便宜的权威真值源。

## 小模型输出要求

只输出：`FRICTION / DISCRIMINATOR / SHORTEST_PATH / GENERAL_RULE / COUNTEREXAMPLE` + Method Card。不要把具体类名/旧行号写进通用规则。
