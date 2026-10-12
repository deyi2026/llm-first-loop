---
method_id: emission-level-gate-before-log-absence-evidence-1ca78b9733ac
name: emission-level-gate-before-log-absence-evidence
description: 验收“修复已部署但 live 行为仍旧”类缺口时，把“生产日志缺少某行”当作分支证据之前，必须先过一道机械级别门：从修复 diff 提取『分支→日志级别』表，用已观测状态（flag、store、异常记录）剪出仍可能的分支集合，核对这些分支的日志级别是否 ≥ 生产通道级别。若仅剩分支都在 debug 级而生产是 INFO，日志缺席零信息——禁止继续枚举日志通道（grep 日志文件、logging 配置、/proc fd），直接改为提级决定性复现或先升级插桩，并用引擎层/组装层/live 层各一次复现分层裁决。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:2264:0c736f8869920ed9c108
evidence_refs: learning:learn:63999bb97c60
created_at: 2026-10-07T15:13:12.347341+08:00
updated_at: 2026-10-07T15:13:12.347341+08:00
---
## Trigger
修复已合入并重启、静态面（部署 revision、flag 投影、store 内容、无异常记录）全部通过，但 live 行为仍与预期不符；下一步需要判定『修复内部哪个分支在生效』，而手头证据形式是『生产日志里没有出现某条日志行』。

## Discriminator
当时回执已可见的级别表：修复 commit 的 diff（'flag off → INFO / store missing → WARNING / exception → exception / zero rows → debug'）与当前源码 grep（_LOGGER.debug("method_hint: %d candidate(s) attached"...)）都显示 success 路径两个分支为 debug 级；结合已观测状态（flag=true 投影、store 可检索、日志无 exception 行），仅剩候选分支全部低于生产 INFO 级 ⇒ 『grep 不到 method_hint 行』对该分诊零信息。

## Short path
- 先一次定位调用方进程身份：比对本 agent PID/PPID 与服务 PID，确认 live 调用确实运行部署后的新代码（本集 PPID=37726=新 web 进程），排除『旧引擎』候选。
- 读一次修复 diff（git show 部署 revision），只提取两张表：分支触发条件、分支→日志级别；此时尚不碰任何日志文件。
- 用已观测状态剪枝候选分支：flag 投影 true 排除 off、store 可检索排除 missing、日志无 exception 行排除 exception；对剩余分支核对级别 vs 生产级别。
- 级别门不过（剩余分支均低于生产级别）时跳过日志通道枚举：子进程同数据开 DEBUG 复现同款查询裁决引擎层，再复刻组装 adapter 形态裁决组装层。
- 两层复现均通过而 live 仍失败 ⇒ 唯一不可观测面是 live 注入路径：先做零行为变化插桩升级（级别提到 INFO + 工具读取点暴露判别字段），让下一次 live 调用的一行日志点名分支。

## Stop conditions
- 仍可能分支的级别表已核完，且判别信号在当前生产级别下不可观测 ⇒ 停止寻找日志输出位置。
- 某一层的复现已给出该层裁决 ⇒ 停止在该层追加同义探测。
- 插桩升级后首次 live 调用的日志已点名具体分支 ⇒ 分诊结束，转入该分支对应假设的修复。

## Verification
- 级别核对可程序化：对每个剩余分支，确认其日志调用级别 ≥ 生产 logger 级别后，才允许把『该行未出现』当反证。
- 分层复现各自独立成立：引擎层（同数据+新代码）、组装层（adapter 形态复刻）、live 层（真实调用），层间结论不互相借用。
- 级别表取自实际部署的 revision（本集 7e4cee69a），不是工作区未提交状态。

## Counterexamples
- 剩余候选分支中存在 INFO 及以上分支（如 flag off→INFO）：级别门通过，日志缺席可以正常用来排除该分支，无需提级复现。
- 失败态只存在于 live 进程内（进程内缓存/会话态/store 句柄），子进程无法等价复现：提级复现不可裁决，必须直接升级 live 插桩。
- 判别事实在工具回执或代码里可直接读到、与日志无关的任务：不适用本方法。
