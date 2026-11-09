---
method_id: staged-only-new-files-invisible-to-committed-tree-artifact-tiers-4f11b1ecf029
name: staged-only-new-files-invisible-to-committed-tree-artifact-tiers
description: 候选含新增模块但只暂存未提交（porcelain 显示 A、HEAD 不含该文件）且改动代码 import 它时，任何从提交树物化产物的门禁 tier（git archive HEAD / release 打包 / 清洁导出）都看不到该文件：产物内子进程确定性 ModuleNotFoundError → 未登记新红 → 整轮昂贵审查+CI 作废。工作树内定向回归、Pyright、tier0 预检全绿也不覆盖此维度，因为它们读的是工作树。身份核对时已拿到的 porcelain A 清单就是预测信号：起昂贵门禁前先只读确认产物型 tier 的构建树，把一轮约25分钟审查+全量CI的必败往返压成一次只读预检。
aliases: 暂存没提交 CI打包缺新模块, git archive 不含 staged 新文件, 审查PASS但R9红 新文件没进release, 定向回归全绿但 release tier ModuleNotFoundError, 送审前先跑产物型守卫tier
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:69383e7c-24e0-4b5c-a2a7-b22bd17ddad3:0:bb2fbfef11d2244e46e5
evidence_refs: learning:learn:676612923d31
created_at: 2026-11-08T21:02:19.940986+08:00
updated_at: 2026-11-08T21:02:19.940986+08:00
---
## Trigger
送审/门禁前身份核对显示候选含纯暂存新增文件（git status 为 A、HEAD 缺该文件），且被改代码会 import 它；门禁流水线含从提交树（而非工作树/暂存集）物化运行产物的 tier（release/archive/sdist/清洁导出）

## Discriminator
porcelain 中 A 状态新模块不在 HEAD + 只读确认某昂贵 tier 以 git archive HEAD 类方式构建产物 ⇒ 产物内对该新模块的 import 必然失败。该判定只需身份核对已有输出加一次只读脚本/单测检查即可成立，无需消耗审查轮，也不依赖语义审查结论（审查对这一内容面分叉零信息量）

## Short path
- 身份核对时从 porcelain 提取全部 A 状态新文件，将其『在各昂贵 tier 构建树中的可见性』列为送审前必须关闭的未知量
- 只读确认构建树：grep 门禁脚本的 archive/release 打包点，或直接只读跑产物型守卫 tier（如 release sidecar 测试）到真实终态
- 若产物缺新文件或 import 失败：不启动审查，报告 staged↔committed 内容分叉，要求先提交新模块（候选必换 SHA）再重新走身份核对与送审
- 若产物包含全部 A 新文件、或证实该 tier 从工作树/暂存集构建：该维度关闭，按正常协议起独立审查与原版 CI

## Stop conditions
- 产物型守卫 tier 只读预检真实绿，且解包核验每个 A 状态新文件确实存在于产物中
- 证实相关 tier 从工作树或暂存集构建产物（如本集 WebUI tier 从候选源构建），staged 文件可见
- 角色禁止运行任何命令时：仅在报告中写明分叉事实与预检建议，不盲目起昂贵轮

## Verification
- 解包/列出门禁 tier 实际物化的产物，逐个 grep A 状态新文件名确认存在
- 只读跑产物型守卫 tier 至终态，确认无 ModuleNotFoundError/缺文件类错误
- 若最终 CI 仍失败，核验失败点已不在『产物缺暂存新文件』这一确定性维度上

## Counterexamples
- 新文件已全部提交进 HEAD（树干净或与构建树零分叉），不存在该维度
- 门禁产物明确从工作树/暂存集构建（本集 ci_gate 的 WebUI 即从候选构建），staged 文件可见，无需预检此维度
- 新增文件为纯文档/数据，无任何被打包的代码 import，缺席产物无害
- 门禁只含语义审查、无产物/exec tier：此内容面分叉不存在（但确定性守卫预检仍由既有方法卡覆盖）
