---
method_id: activation-gate-first-when-reviewing-reuse-existing-pipeline-c3852342964e
name: activation-gate-first-when-reviewing-reuse-existing-pipeline
description: 审查『复用既有观测/事件/数据链』的设计或计划时，先用 2-4 个定向检查确认该链是否真的开启过并产出数据（配置默认值、短路分支、唯一实例化点、跟踪配置文件），再投入行号级接线核验。默认关闭的链会把『验证接线』问题整个改写为『样本是否存在、如何最低成本采样』。本集在核完约 8 处接线行号之后才发现 knowledge 链默认 off、全部 10 个事件从不产生；gate 检查本可前置，直接改写 P0a 与推荐项的写法。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:126:c14515dca03327d5db43
evidence_refs: learning:learn:9ae8c6a62891
created_at: 2026-10-15T00:06:30.507716+08:00
updated_at: 2026-10-15T00:06:30.507716+08:00
---
## Trigger
需要审查/审计一份计划『复用既有 pipeline、事件流或历史数据』的设计（在其上做投影、对账、覆盖缺口分析），且源码中该链带有 mode/flag/白名单等条件启用结构，而审查目标包括判断建议是否成立并给出下一步时。

## Discriminator
当时已可见的两类事实：稿件自身注明『读源码证明实现，不证明 live 已加载或效果成立』且后续计划依赖『真实样本』；接线核验输出中已出现 mode 短路分支与 getattr 默认值字面量。二者都指向『样本存在性取决于启用默认』，且可用『配置默认值 + 跟踪配置文件 grep』两次定向查询直接裁决，无需先穷尽接线细节。

## Short path
- 读设计稿，抽出『复用既有链』主张与依赖真实样本的计划，标记稿内自带的『实现存在≠生效』限定
- 先做 activation gate 检查：配置 dataclass 默认值、env 解析默认、短路分支、唯一实例化点是否在 gate 之后；grep 跟踪的 toml/env/json/yml/sh 是否设置过该 flag
- 若默认关闭：把『核覆盖缺口』改写为『数据存储中该类事件是否存在』，并评估不改 wire 的最低成本采样手段（如 shadow 模式）作为独立决策
- 仅对仍承重的主张做定向核验（计数用单一 grep、去重范围用行号对照、基线存在性用 ls-tree），已被改写降级的主张可裁剪
- 结论分层输出：对方修正是否成立 / 稿件事实是否准确 / 建议是否建立在可能不存在的数据上

## Stop conditions
- activation 三要素（默认值、短路分支、实例化点）与跟踪配置搜索均有明确结果，能一句话回答『该链在什么条件下产生事件』
- 样本存在性已裁决（必然为零 / 存在 / 取决于环境），受影响的推荐项与后续计划已按此改写
- 剩余每条承重主张均已用一个定向命令核对，或已明确标注未核

## Verification
- 确认默认值取自权威位置（dataclass 字段默认与 env 解析默认一致）而非单点猜测，且跟踪配置搜索覆盖 runtime 配置文件类型
- 确认 gate 分支到唯一实例化点的因果顺序无中间旁路（默认关→不实例化→不产事件）
- 确认结论显式区分『代码在基线已存在』与『链已开启/样本存在』两层，且存在性查询与采样开关被列为独立决策

## Counterexamples
- 稿件或仓库已给出链被启用的直接证据（样本统计、跟踪配置显式开启、近期 receipt）——activation 已有答案，直接进入数据/接线核验
- 审查问题纯属静态代码正确性（命名冲突、API 契约、逻辑 bug），不涉及对既有数据/样本的依赖——gate 检查不改变任何结论
- 该链无条件接线、无任何 flag/mode gate（实例化不受开关控制）——样本问题属于数据保留/清理策略，不是启用问题，此方法不适用
