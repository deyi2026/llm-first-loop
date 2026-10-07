---
method_id: verify-handoff-report-via-named-probes-be1c30bec075
name: verify-handoff-report-via-named-probes
description: 把收到的状态/交接报告当作待核验声明集而非待采信叙事：报告文本中的命名句柄（commit hash、分支名、二进制名、日期、故障组件名）各自对应一条零副作用确定性探测命令（git cat-file/branch、docker info、which --version、docs 检索），逐条裁决。探测失败的错误输出即修复指针（缺失 daemon socket→拉起对应 app；缺 binary→按权威清单装固定版本）。当'故障'声明与本地已观测 healthy 状态矛盾时，说明该名字的 referent 另有所指：先在工作区数据/logs 里 rg 该 token 定位指代物，再做任何修复。优先读改动集自带的 readiness/preflight 脚本作为安装/需求的权威清单，避免猜测要装什么。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1f576ea-8082-441a-9f68-2d1021c05410:0:76dcf3c336a86502c49b
evidence_refs: learning:learn:904665b6d95c
created_at: 2026-10-07T00:29:41.146857+08:00
updated_at: 2026-10-07T00:29:41.146857+08:00
---
## Trigger
收到另一 agent/人提交的状态或交接报告，含多条命名可核验声明（提交/分支/二进制/排期/故障组件），任务是对报告去伪存真、解除可解阻塞后再决定推进方向

## Discriminator
报告文本本身已枚举可验证句柄（精确 hash、分支名、binary 名、日期），每条声明存在一条廉价确定性命令可直接裁决；且行动前本地权威状态已观测——与'断连/不可用'声明矛盾的 healthy 观测（本集 runtime healthy）表明该故障名不指向本地组件，指代物需另行定位

## Short path
- 先取本地权威状态（runtime/goal）作 baseline，标记与报告矛盾的观测（报'断连'但本地 runtime healthy ⇒ 故障名指向别处）
- 对每条命名声明跑最廉价探测：git cat-file/branch/worktree、docker info、which --version、docs 检索
- 用探测失败的错误输出作修复指针：缺失 socket 路径→拉起对应 app；缺 binary→装固定版本
- 报告中的未知组件缩写名，先在工作区 data/logs 里 rg 该 token 确定 referent，再修复或转交
- 读改动集自带的 preflight/readiness 脚本获取权威需求清单（哪些 binary、哪些版本、哪些 provider 档案）
- 复跑关键测试/检查抽验报告数字，输出'已核实事实 vs 未决项/勘误'清单后停止

## Stop conditions
- 所有命名声明均被探测证实/证伪/重分类（如'隔离分支未合入'属实、'daemon 不可用'已解除）
- 剩余阻塞被归为设计内协议门（如请求回执验证、任务集冻结），不属于本会话权限，标记为未决而不绕过

## Verification
- 对报告中的可复验数字做本地交叉复跑而非转述（本集：worktree 复跑 125 通过，覆盖宽于报告的 63 项聚焦，无反证）
- 最终结论区分'带证据的已核实事实'与'未决项/勘误'（如排期时间核出 20:10 勘误报告的 20:00），每条事实可指回探测回执

## Counterexamples
- 报告无命名句柄、纯主观评价（'质量感觉不行'）→ 无句柄可探测，应索取 artifact 或自行度量，不套用本方法
- 探测本身有副作用或破坏性（探测即触发部署/重启生产服务）→ 先评估再探，不盲探
- 声明的事实是本会话自己刚产生的 → 已有本地证据，无需全量复验
- 故障组件指代明确且确实 unhealthy → 直接沿错误信息修复，跳过'rg 定位 referent'步骤
