---
method_id: classify-errno-write-denial-as-environment-before-code-triage-32e51ee0e266
name: classify-errno-write-denial-as-environment-before-code-triage
description: 沙箱化测试执行（回执带 sandbox/exec 上下文标记）全量套件失败时，先看单测 traceback 的异常类别：若是 OS 级 errno 写拒绝（PermissionError / Operation not permitted）落在宣称可写的报告/缓存工件路径上，而非断言失败，先按『执行环境类』分类——原样重跑一次该测试判定瞬态/持续；只有持续才用同上下文写探针+后台任务对照探针隔离沙箱维度。本集在重跑已通过（瞬态成立）之后仍做了 evidence 水合、grep 写点、stat、后台探针等后置动作；traceback 当时已点名精确路径与 errno，无需再查代码。注意：天花板效应→暂缓正式跑的教训与既有 ceiling-probe 方法同机制，不另立卡。
aliases: 全量红但单测重跑绿 怎么判定, Operation not permitted 写报告 测试失败, 沙箱误杀 pytest 写报告文件, 测试失败重跑就过 还要不要查代码, 前台写被拒 后台任务能写, 环境错误和断言失败 分诊
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c5f52ba4-0dd0-440d-ab8e-d4b02bb2ed41:1720:091025a858321e6a8dad
evidence_refs: learning:learn:6a25027d7e5e
created_at: 2026-10-25T21:14:44.761045+08:00
updated_at: 2026-10-25T21:14:44.761045+08:00
---
## Trigger
带沙箱/exec 上下文标记的命令回执下，全量测试套件非零退出，且单测 verbose traceback 显示对名义上在允许写范围内的工件路径（工作区内 reports/日志/缓存目录）抛 OS errno 异常（如 PermissionError: Operation not permitted），而不是 assert 失败

## Discriminator
失败当时已可见三点：(a) 异常是 OS 级 errno 写拒绝而非断言失败；(b) 被拒路径位于沙箱回执声称允许写的范围内（工作区内）；(c) 每条命令回执都带沙箱标记，提醒执行上下文本身是一个变量。这三点在第一次看到单测 traceback 时就把『产品 bug / 测试逻辑 bug / 环境问题』缩到『环境类，待测瞬态』

## Short path
- 全量失败输出只提取 FAILED/ERROR 行定位失败测试；stderr 中标明『仅告警不阻断』的审计项是噪声，不逐条枚举
- 单独 verbose 重跑该测试，读异常类型与被拒写路径
- 异常为 OS errno 写拒绝且目标路径在允许写范围内 → 判环境类；未知量收窄为『瞬态还是持续』
- 完全不变地重跑一次该测试：通过 ⇒ 瞬态沙箱/OS 干扰，记录（路径、errno、上下文）后继续，产品与测试代码零改动
- 仅当持续失败：在同执行上下文对精确目录做写探针，并用后台任务/无沙箱上下文对同路径做对照探针；前景被拒而后台可写 ⇒ 沙箱 profile 问题，换执行上下文而非改代码；两边都被拒 ⇒ 真实文件系统权限问题
- 在原失败上下文重跑原失败范围（该文件或全量），确认绿后才进入下一阶段（如烧真实调用预算）

## Stop conditions
- 失败测试原样重跑即通过，且原失败范围在原上下文复绿——环境瞬态成立，记录后停止根因收集，不再做水合/grep 写点/stat 等动作
- 对照探针已分离出执行上下文原因（前景被拒、后台可写），换上下文后套件绿
- 确认本次失败未引起任何产品/测试代码 diff

## Verification
- 同一（原本失败的）执行上下文中，失败测试不变重跑通过，且文件级/套件级范围复绿
- git diff 证明环境类失败零代码改动；若做了改动，说明分类错误需复盘
- 若使用探针：同一路径在两种执行上下文各探一次，结论能相互解释（沙箱维度 or 文件系统维度）

## Counterexamples
- 测试写目标真的在沙箱允许范围之外（家目录 dotfiles、系统目录）：持久 PermissionError 是预期行为，应改测试用 tmp_path/策略内路径，而不是按瞬态环境处理
- traceback 是断言失败（如 assert 恰有一条回执）：产品/测试逻辑问题，必须读代码定位，不能『重跑通过就算了』
- 重跑仍失败且前景/后台探针均被拒：真实权限/属主问题，或活进程持有文件的 TOCTOU——转相应权限修复/活数据方法
- 确定性（每次必现）的权限错误：不得贴瞬态标签，必须先做探针隔离再下结论
