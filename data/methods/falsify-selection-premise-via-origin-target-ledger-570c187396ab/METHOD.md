---
method_id: falsify-selection-premise-via-origin-target-ledger-570c187396ab
name: falsify-selection-premise-via-origin-target-ledger
description: 当诊断问题预设『机制X的目标选择逻辑漏了目标Y』时，先证伪前提再找bug：(1)沿上下文已有provenance（EXPERIENCE/回执引用的文件+行号）直接读X的派发点，不做全库泛关键词枚举；(2)对append-only action台账按时间窗口tally origin×target。若X-origin的action数为0，说明X根本不做选择，问题转为『谁负责派发/回执缺收敛可见性』的设计缺口；只有tally显示X确实派发且漏了Y，才回头逆向其选择逻辑。本集借此把『publish为何漏feishu』转为『publish零派发+调用方各自只restart自己在改的服务』的三层根因。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:102:fb0c12ac90943420c381
evidence_refs: learning:learn:2f12888a7920
created_at: 2026-09-24T06:58:53.194696+00:00
updated_at: 2026-09-24T06:58:53.194696+00:00
---
## Trigger
调查问题形式为『某机制（发布/调度/派发/编排）的目标选择为何漏掉某对象』，且系统存在按action落盘、记录origin与target的台账（如 service-control-actions 目录），同时上下文已有指向该机制代码位置的精确 provenance（经验记录/回执直接引用了文件与行号）。

## Discriminator
台账中每条action的origin×target字段：一次tally即可判明『X是否真的做过选择』。本集knowledge-at-time判别事实：窗口内11条restart全部origin=restart、target=web×10+learning×1、feishu×0，且首个检索结果已引用 service_control.py 的 argparse 位置——这两点在进入宽枚举前就已足够把问题从『找selection bug』缩为『数谁派发过什么』。

## Short path
- 明确两个未知量：X 是否创建/如何选择 action 目标；时间窗口内实际发生过哪些 action。
- 沿已有 provenance 直接 grep/读 X 的 handler 与模型侧入口，确认它创建哪些 action（本集：publish=build_deployment+CAS写desired，零action创建；仅update封装publish+restart）。
- 定位并 tally append-only 台账：按窗口统计 origin×target 分布，回答『谁对谁做过什么』。
- 若 X-origin 计数为0 → 前提证伪，转向设计层结论（收敛责任在调用方、回执缺收敛快照）；若计数>0 且确实漏 Y → 才回头读目标选择/默认推导逻辑。
- 交叉验证回执提示与只读信号边界（审计信号不进门禁）后停止，进入修复提案。

## Stop conditions
- tally 已证明 X-origin 的 action 数为0（或>0且对Y的覆盖/遗漏已定），且派发点代码已确认action创建位置——前提真伪已定，停止机制层搜索。
- 剩余未知量只有修复建议与纪律时，停止调查，进入提案/沉淀阶段。

## Verification
- tally 数字与台账逐条JSON的origin/target字段一致，无凭印象计数。
- 代码结论与handler真实调用链一致（如publish不经过 build_restart_plan / worker spawn）。
- 『下次会复发』断言需与窗口外的历史action记录（如上一次全员收敛时点）核对。

## Counterexamples
- 台账不记录origin/target、已被轮转清理或落在别的store——tally不可用，退回代码+事件流交叉。
- X确有选择逻辑（如update按code_root推导restart_target默认值）且台账显示X-origin action漏了Y——前提成立，必须读选择逻辑本身，『证伪即止』分支不适用。
- 纯计算问题（函数返回错值、无action台账可查）——本方法无ledger可tally，不适用。
- 上下文没有任何指向派发点的provenance——应先做窄定位（按命令名grep目标文件），而非直接套用读handler步骤，更不应全库搜泛状态关键词（restart_required等）期望命中机制代码。
