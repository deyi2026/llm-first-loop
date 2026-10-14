---
method_id: literal-anchor-resolves-layout-contract-and-consumption-scope-4fd76f834978
name: literal-anchor-resolves-layout-contract-and-consumption-scope
description: 任务描述常同时给出唯一字面量（完整 API 路由、独特字段名）与未锚定的相对路径（如 static/app.js、modules/*.js）。先用唯一字面量做一次内容搜索：命中文件路径前缀即披露包布局（免去猜测目录的读失败），命中处的处理器又链到权威契约实现；再在第一方消费目录（排除 vendor/*.min.js）探测被消费字段字面量，miss 即"零消费"事实，把"改造既有"翻转为"新增"，先修订验收留痕再写实现。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:54:fd62c572819d542b25bb
evidence_refs: learning:learn:b28ab3574664
created_at: 2026-10-14T14:47:47.420133+08:00
updated_at: 2026-10-14T14:47:47.420133+08:00
---
## Trigger
任务/验收文本同时含可搜索的唯一标识（含版本前缀的完整端点路径、独特字段名）和含糊相对路径，或验收隐含"既有消费面存在"但未经证实；需在不熟悉布局的仓库中做消费侧（前端/客户端）改动。

## Discriminator
任务文本自带的唯一字面量本身即可作锚：一次内容搜索既定位权威契约源（路由→聚合实现→确切响应字段），又通过命中路径前缀（如 llm_loop/web/routes.py ⇒ 前端在 llm_loop/web/static/）消解相对路径歧义；字段字面量在第一方 JS 中 verified-miss 即证明消费面为零。三者均只用任务开始时已知信息。

## Short path
- 从任务文本提取最独特字面量（完整路由/字段名）做内容搜索；未知量：契约源在哪、仓库布局前缀是什么
- 读命中的处理器并沿其调用的聚合实现确认响应字段结构；未知量：确切契约（而非假设的六桶卡片）
- 在布局前缀下的第一方目录（排除 *.min.js/vendor）探测字段字面量；未知量：既有消费是否存在（hit=改造；miss=零消费→范围翻转）
- 范围翻转时先修订验收并留痕（acceptance_revised），再读 index.html / els 表 / 一个样板模块掌握惯例
- 实现后 grep 字段字面量核对消费、字段集与生产者源码对齐；goal 声明 API 冻结则确认数据面零 diff，停止

## Stop conditions
- 契约字段已从生产者源码（非假设/非旧摘要）确认
- 消费面存在性已有裁决：第一方目录已探测且 vendor 误中已排除
- 范围翻转已落入验收修订留痕，才允许开始写实现
- 实现后 grep 验证通过，且 diff 范围与 goal 声明的改动面一致

## Verification
- grep 消费侧文件确认读取目标字段（structural_zero/zero_reason 类）并渲染
- 响应字段集与生产者聚合源码逐一对齐，而非与任务描述对齐
- 范围翻转时任务验收存在修订留痕
- goal 声明不动数据面时，diff 仅出现在消费侧文件

## Counterexamples
- 字面量不唯一（如 'metrics'、'status'）会在 vendored/生成代码中泛滥命中：不能用它定布局，应回退仓库根列表/文档锚点
- 纯前端仓库、API 在远端：本地无路由源可锚定，契约须来自 API 文档或抓包，布局走根目录枚举
- 任务已给出从仓库根起的完整路径并明确"新增"：布局锚定可跳过，消费探测只剩廉价保险
- 探测命中仅出现在 *.min.js（如 katex.min.js 内容误中）：vendor 命中不构成消费存在的证据，须在第一方源码确认后再裁范围
