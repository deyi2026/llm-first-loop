---
method_id: force-trigger-ab-release-snapshot-vs-worktree-fix-verification-2b4e2bc12749
name: force-trigger-ab-release-snapshot-vs-worktree-fix-verification
description: 修复 commit 已落地但 live 服务仍运行旧 head、且事故触发条件在生产参数下极难自然复现（如子代理上下文超预算第 10 轮熔断）时，验证走单变量代码树 A/B：同一探针脚本直接驱动真实 runner，分别从 live head 的 .releases 快照树与修复后的工作树导入，并覆盖触发条件的控制参数（如 context_limits_resolver 调小窗口）让故障在少数轮次内必现；先确认两臂机制均真实触发（压缩发生、B 臂 wire 含具名违规标记并熔断），再把结果差归因给代码树；同时由 fix commit 时间 vs live git_head 机械推导部署缺口，脏树等发布阻塞交还用户决策。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f2be023-db54-4395-9854-c784b5295062:473:c1f6ec7a7333391400c5
evidence_refs: learning:learn:2a8e0092ecfc
created_at: 2026-10-20T13:02:35.802045+08:00
updated_at: 2026-10-20T13:02:35.802045+08:00
---
## Trigger
事故修复 commit 已存在但 live 服务仍运行旧 git_head，且失败触发条件依赖稀有运行条件（上下文超预算、深轮次、特定负载），等待自然复现不可行

## Discriminator
commit message/回归测试已具名触发条件与完整机制；源码构造器暴露该条件的可覆盖控制参数（如 context_limits_resolver）；仓库存在与 live head 对应的 .releases/<head> 快照树——三点合一把『如何验证修复』缩成一次参数覆盖探针加两次导入路径切换，且无需重推导机制或巡检环境

## Short path
- 取回待办上下文：确认 fix commit、其具名的触发条件与机制，以及 live head 仍为旧版本（fix 提交时间晚于部署 generation 的 git_head），部署缺口由此机械推导
- 以 commit message 具名的函数/参数为锚做一次定向源码读取，定位探针控制点与注入参数（如 _bounded_child_wire 与 context_limits_resolver），不做全库机制重推导
- 写单份探针脚本：直接调用 runner，保留真实 provider 调用/投影/校验/熔断计数，覆盖窗口参数强制触发条件提前出现；脚本回显导入模块 __file__ 钉死被测代码树
- B 臂从 live head 的 .releases 快照树运行，A 臂从修复工作树运行；先核两臂机制均已触发（压缩发生、B 臂出现具名违规与熔断）再对比结果
- 唯一变量为代码树，据此归因；报告受控项（窗口调小、绕过正式入口、工具域裁剪）、部署缺口与发布阻塞（脏工作树），发布方式决策交还用户

## Stop conditions
- 两臂机制均触发且结果按预期翻转（B 失败签名与事故一致、A 通过），归因完成即停止，不追加环境巡检或机制重验
- 任一臂机制未触发（如压缩未发生、未进入失败路径）→ 先调探针参数，不得下修复有效/无效结论
- 部署缺口与发布阻塞已具名（live head 无修复、工作树脏）→ 剩余选择交还用户

## Verification
- B 臂失败签名与事故记录逐字一致：具名违规码、连续重试次数、熔断轮次量级
- 两臂除导入代码树外完全同构（同脚本/模型/提示词），并以模块 __file__ 回显证明各自加载的树
- 受控项（窗口覆盖、直调 runner、工具域裁剪）在结论中显式标注为非生产原样，与生产结论分离

## Counterexamples
- 失败可由固定输入低成本自然复现 → 直接重放最小失败探针即可，无需双树对照与参数覆盖（适用 replay-minimal-failing-probe 类路线）
- 修复差异在配置或运行时状态而非代码树（同 head 下开关不同）→ 代码树 A/B 无判别力，应改查配置生效链
- 两树解释器/依赖环境不一致，或无干净快照可作 before 臂 → 先钉 import site 与夹具不变量，否则 delta 不可归因给代码修复
