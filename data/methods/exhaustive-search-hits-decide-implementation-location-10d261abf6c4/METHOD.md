---
method_id: exhaustive-search-hits-decide-implementation-location-10d261abf6c4
name: exhaustive-search-hits-decide-implementation-location
description: 在定位某符号/工具的实现或返回契约时，先对已到手的仓库级穷举搜索命中清单做分类（schema 描述串/env 配置/注释引用/观测钩子/注册代码）。若无任何执行体定义，立即结论『实现不在本仓库（schema-only/宿主侧）』，并把问题切换为『从 schema 文本与观测钩子调用点上下文提取可观察契约』，不再继续对『实现位置/返回结构』发局部搜索。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:567:ee016fde4b3af7ecc0c6
evidence_refs: learning:learn:3771122ddc49
created_at: 2026-09-17T15:27:58.320022+00:00
updated_at: 2026-09-17T15:27:58.320022+00:00
---
## Trigger
已持有对目标符号的一次仓库级穷举（全仓）名搜索的完整命中清单，且正准备继续发更小范围的搜索去找『它的实现/返回结构』

## Discriminator
全仓穷举命中清单里只有描述字符串、env 配置项、注释行和 introspection/注册代码，没有任何 handler/executor 定义——穷举本身即构成否定证据：执行体不在本仓库

## Short path
- 对既有全仓命中清单按命中类型分类（描述/配置/注释/钩子/注册），回答未知量：执行体是否在本仓库
- 清单中无执行体 → 结论『宿主侧实现』，把未知量切换为『不动执行体时接入点是什么』（从工具描述与设计文档推出，如报告产物落盘约定）
- 从 schema 描述文本提取目标契约（描述已写明结果中返回何种 stable ref），终止『在仓库里找返回结构实现』这条分支
- 从观测钩子调用点上下文确认可到达的上下文变量（已有 session/run 标识访问模式），决定补观测字段的方式
- 契约与上下文齐备即停止侦察，进入写码

## Stop conditions
- 命中清单中已出现 handler/executor 定义 → 直接读实现，停止推断
- schema 描述 + 钩子调用点上下文已足以支撑本次观测/接入改动 → 停止侦察
- 剩余未知量是运行时实际行为细节且仓内无证据 → 才扩大搜索（真实运行样本/外部文档）

## Verification
- 用调度表/入口注册再核一次：符号到 handler 的映射确认无命中，『不在本仓库』结论才成立
- 由 schema 描述提取的契约与真实运行样本可观察结构（如 session JSON 回执字段形状）交叉一致

## Counterexamples
- 工具经表驱动/动态注册或实现类名不同：字面名搜索无 handler 不等于不在本仓库，须先查 dispatch 表/入口注册
- 先前搜索是局部的（单目录/单文件类型），命中清单不穷举，不能据此断言缺失
- 问题问的是运行时实际返回格式细节：schema 描述可能滞后于运行线，须直接读真实执行样本而非依赖描述
