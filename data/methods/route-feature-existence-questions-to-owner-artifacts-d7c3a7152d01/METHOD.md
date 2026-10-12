---
method_id: route-feature-existence-questions-to-owner-artifacts-d7c3a7152d01
name: route-feature-existence-questions-to-owner-artifacts
description: 用户问『X 功能实现了吗/为什么页面上看不到』并伴随运行态问题时：先把问题拆成独立未知量，给每个未知量指定 owner artifact（运行态→status API/持久 journal；页面可见性→该页面组件源码；API 面→路由表；工具能力→工具实现），在 owner artifact 上做最小 grep/read 并取回执（含零命中等负回执）。docs 索引与服务日志不是功能存在性的裁决权威；docs miss 是『这是代码问题』的信号，不是扩大目录枚举的许可。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d0721026-9d2f-493f-ad09-a5560e92b589:0:cc9487bc5446405eebb2
evidence_refs: learning:learn:e6c7e2865011
created_at: 2026-10-13T04:22:40.352469+08:00
updated_at: 2026-10-13T04:22:40.352469+08:00
---
## Trigger
用户询问某功能是否已实现、是否在指名页面上可见（如『为什么我在 P 页看不到 X』），常伴随运行态问题（队列/积压/状态）；项目自带前端页面源码与后端路由。

## Discriminator
进入搜索前的两个当时已知事实：① 用户原话明确指名页面——该页面的渲染组件与其数据端点是『可见性』的唯一裁决 artifact；② 会话最初的工具回执即来自 status/audit 通道——运行态的权威是 status API/持久 journal，而非服务日志。此时 docs 检索 miss 即应转向 owner artifact，而不是目录枚举+日志尾读。

## Short path
- 把用户问题拆成独立未知量（当前状态？功能已实现？页面上可见？）
- 给每个未知量指定 owner artifact 类别：运行态→status API/活跃 journal；页面可见性→指名页面的组件源码（grep 功能关键词）；API 面→路由文件；工具层能力→工具实现
- 对 owner artifact 分别做最小读取/grep，保存回执作为证据（含负回执：关键词零命中、路由枚举为空）
- 仅当 owner 证据不足时做补充计算（如任务 fresh/stale 分类、最老等待时长）
- 成稿时每个断言挂 artifact ref，未知量全部有回执即停止

## Stop conditions
- 每个未知量都拿到 owner artifact 回执，包括『grep 零命中』『路由为空』这类负回执
- 动态数字由权威 journal/status API 现算得出，而非转录服务日志

## Verification
- 最终稿中每个数字/引用能回指到具体文件、端点或 journal 回执
- 『没实现/看不到』的结论必须落在显式负回执上，不靠记忆缺位；『实现了但看不到』需工具层/路由存在与页面组件缺失同时举证

## Counterexamples
- 用户问『行为为何/何时变化』类因果问题：答案在 git 历史/docs/时间线，页面源码无法解释因果，本方法不适用
- 用户无法指名页面或入口（『系统里反正有个…』）：无 owner 指针时目录级 discovery 才是正确第一步
- 功能可能『已实现但未发布/在 flag 后』：判『实现』需路由+工具层与 docs/flag 交叉验证，UI 组件 grep 零命中只能证明『不可见』
