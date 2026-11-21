---
method_id: least-assumption-submit-unknown-required-params-on-fail-closed-managed-t-c3e60078c7a8
name: least-assumption-submit-unknown-required-params-on-fail-closed-managed-tools
description: 调用共享账本类 fail-closed 受管写工具时，若某必填参数的权威值在全部任务材料中从未出现（如绝对工作树路径），不要凭习惯编造看似合理的字面量，也不要向结构上拿不到该类值的来源（只回相对路径的工作区文件搜索）烧发现调用；改为提交锚定在显式上下文断言上的最小假设值（『当前隔离工作区即目标分支工作区』→ '.'），并省略 schema 声明可自动探测的可选字段（不拿分支候选 HEAD 冒充 main 分叉点）。成功回执中工具探测出的值视为真值，与任务给定事实交叉核验。参数语义未明时先读一次完整 schema，它就是权威合同。
aliases: 必填参数不知道值怎么填, 路径未知能不能直接提交登记, 工具会自动识别就别手动猜, 新工具第一次用先看参数说明, 分支HEAD能不能当分叉基点
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:0:4567a79485975272db7d
evidence_refs: learning:learn:23ecad99955d
created_at: 2026-11-19T01:19:27.370721+08:00
updated_at: 2026-11-19T01:19:27.370721+08:00
---
## Trigger
将调用受管/fail-closed 的账本登记类写工具，某必填参数的权威取值在任务材料中不存在，但上下文已有显式断言指明该参数应引用的实体（如当前工作区即目标 worktree）。

## Discriminator
缺失检验：拟填字面量从未出现在任务材料中（编造信号）；同时工具自述确定性拒绝（失败对策如实返回占用/冲突）或存在标注『缺省自动探测』的可选字段——这意味着最小假设提交的试错成本低，且回执自带可用于核验的真值。

## Short path
- 凡有参数语义未明的受管写工具，先读完整 schema（一次廉价调用，权威合同）
- 逐个必填参数核对：材料中有权威值→直用；没有→找锚定显式上下文断言的最小假设值
- schema 标注自动探测的可选字段一律省略，不用语义不同的已知值（如分支 HEAD）顶替
- 提交后把回执探测出的值当真值与任务给定事实交叉核验；确定性拒绝则按拒绝原因做合同化修复，不换字面量重猜

## Stop conditions
- 回执成功且探测值（HEAD/paths）与任务给定事实一致 → 登记完成，落 checkpoint
- 确定性拒绝点名该参数 → 停止重猜字面量，改从权威来源解析真值或如实上报阻断

## Verification
- 回执返回的自动探测值与用户给定事实逐项比对（探测 HEAD == 候选 HEAD 才算绑定正确）
- 回执中登记的 paths/branch 与任务点名集合逐项完全一致

## Counterexamples
- 材料中本就存在权威绝对路径 → 直接使用，不降级为 '.'
- 工具并非 fail-closed（会静默容错或持久化错误值）→ 错误值会污染共享账本，必须先解析真值再提交
- 当前会话工作区并不唯一对应目标工作树（多 worktree 环境）→ '.' 有歧义，先解析再登记
- 该可选字段没有自动探测声明 → 省略得不到保护，需另寻权威来源，不可拿候选 HEAD 猜分叉点
- 参数错值不可逆或具破坏性（非登记类操作）→ 必须预先解析，不得试错提交
