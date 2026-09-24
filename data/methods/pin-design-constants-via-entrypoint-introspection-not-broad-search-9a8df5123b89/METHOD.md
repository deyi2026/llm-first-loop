---
method_id: pin-design-constants-via-entrypoint-introspection-not-broad-search-9a8df5123b89
name: pin-design-constants-via-entrypoint-introspection-not-broad-search
description: 为评测/消融/接口口径设计钉住系统级常量（工具面、活动模型、轮上限、数据体量）时，先沿 harness 代码中已显式存在的入口边——被测模块 import、env/路径常量指向的代码树、settings 加载器——做权威运行时内省，而不是先做文件名/文档宽枚举。探针命令应原子组合（临时目录+env+cd+解析一次完成，shell 状态不跨调用持久），失败报错中列出的必填项清单就是下一次探针的精确输入。每个常量落到可复现探针输出并与既有冻结 manifest 交叉核对，不一致登记为新测量缺陷而非静默覆盖。宽搜索仅作先前艺术检查，未产出被引用事实即弃。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:270:71572f395ebbf774765c
evidence_refs: learning:learn:f5a5ce13937c
created_at: 2026-09-21T02:19:13.102441+00:00
updated_at: 2026-09-21T02:19:13.102441+00:00
---
## Trigger
需要为口径设计钉住被测系统的常量，且当前已读的执行/harness 代码已显式给出被测系统的 import 入口、部署路径与配置加载器

## Discriminator
已读 worker/harness 源码中可见三条显式边：env/sys.path 指向被测代码树、from X import build/engine 入口、settings=load_settings() 配置加载——权威常量来源已被唯一确定，此时再做全仓库文件名枚举不缩小任何未知量

## Short path
- 读上一轮结论/冻结记录：确定已证事实与可引用不重跑的边界，列出设计还缺哪些常量
- 读执行 worker：提取被测代码路径、引擎构建入口、配置加载器三条显式边
- 读协议/臂定义：确定现有差异轴与已证惰性域
- 沿 import 边直接内省 factory/registry：数工具面、确认注册结构，不做文件名宽枚举
- 原子探针 settings 加载（临时数据目录+env+cd+解析一次完成）：取活动模型、轮上限；报错列出的必填 env 即补齐项
- 直接度量任务数据体量得出分层/溢出判断；全部常量有来源即停止，落盘设计并把未决点收敛为显式裁决项

## Stop conditions
- 设计绑定的每个常量均有可复现探针输出或明确文件度量作来源
- 宽搜索（文档/文件名枚举）未产出任何进入设计的被引用事实时，立即放弃该分支
- 口径文档落盘且未决点已收敛为显式裁决项后停止，不再补读

## Verification
- 逐常量标注来源（探针命令输出 / settings 解析字段 / 字节度量），可由第三方重放
- 与既有冻结 manifest 交叉核对模型、上限、路径，不一致登记为新测量缺陷而非覆盖
- 探针失败时将报错必填项清单与实际提供的环境对账后才重试

## Counterexamples
- 任务目标本身就是文档/文献综述或先前艺术调研——宽搜索是正题而非绕路，不适用
- import 边指向 stub、vendored 副本或 env 未解析的占位路径——必须先解析真实运行路径，直接静态读文件会误导
- 权威运行时探针需要不可得的凭据/外部服务——只能退回静态配置默认值并显式声明未验证，不能当作已钉住
