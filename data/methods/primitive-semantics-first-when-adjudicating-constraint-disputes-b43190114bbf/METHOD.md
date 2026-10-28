---
method_id: primitive-semantics-first-when-adjudicating-constraint-disputes-b43190114bbf
name: primitive-semantics-first-when-adjudicating-constraint-disputes
description: 当用户/评审断言某条设计约束（如禁自证门、独立评估门）'卡住工作流、没法使用'时，若该断言的真假取决于约束所依赖原语（episode/session/task_ref）的实际粒度或语义，应先读该原语的权威定义与 resolver，再读约束代码，然后才下结论。本集先做宽文件名搜索（返回 venv/.releases 噪声）、探测不存在目录，直到最后一步才读 resolver 定义；而用户消息早已点名 host.current_episode_ref()。其 docstring（一次人类提问粒度）直接证伪了'卡住跨轮复用'的前提，把争论重定向到真实缺口（改进不继承状态、衰减惩罚未评估卡），并能明确保留不该动的约束。先宽枚举文件、把决定性未知量（原语粒度）留到最后，是可避免的绕路。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:abf83187-242a-4d8d-81bc-1d377b72db19:123:34ee21bfd28990f24b3f
evidence_refs: learning:learn:ac12c97ede49
created_at: 2026-10-17T23:30:58.207358+08:00
updated_at: 2026-10-17T23:30:58.207358+08:00
---
## Trigger
用户（或自己上一轮结论）质疑某条门/约束导致'没法使用/卡住改进'，请求修改建议，且断言成立与否取决于该约束所依赖的具名原语（episode、session、task_ref 等）的实际粒度或语义

## Discriminator
争议文本中已出现该原语的权威符号名（如 host.current_episode_ref()）；其定义或运行时 resolver 的 docstring/推导式（如 stable_episode_ref(session_id, user_message, turn_ref)）会直接给出粒度。这一个当时可得的事实即可判定约束到底禁止哪个具体场景（同轮自证 vs 跨轮复用），无需宽枚举文件或目录

## Short path
- 写出双方断言，定位真假分叉点依赖哪个原语的语义（未知量1：该原语的粒度）
- grep 用户消息中已点名的符号，读其权威定义/resolver 的 docstring（1-2 次定向查找，不先做全目录文件名枚举）
- 读消费该原语的门/约束代码，确认比较字段与禁止集合（未知量2：约束实际拦截什么场景）
- 把粒度代入禁止集合：用户声称的阻断场景是否可达；不可达则先纠正前提，并区分'前提错误'与'真实缺口'
- 仅对已证实的真实缺口枚举改进项；对前提被证伪的部分明确保留约束并给出理由

## Stop conditions
- 原语粒度与约束比较逻辑已共同判定用户声称的阻断场景是否可达，事实验证即停止，不再回扫无关源文件
- 纠错与改进建议已分离陈述：前提纠错完成，改进项只针对已证实的真实缺口

## Verification
- 约束检查代码引用的字段确实由该 resolver 派生（而非调用方自报），即语义判定与约束检查作用在同一个原语上
- 取一个边界场景（如同会话下一轮人类提问）代入粒度定义，验证它落入或不落入禁止集合，与最终结论一致

## Counterexamples
- 争议纯属偏好或权衡（命名、易用性、成本），不存在可查证的原语语义分叉点：直接进入设计讨论，不必先查定义
- 原词语义已是双方共识，分歧在'应不应该这样设计'而非'它实际是什么'：查定义不改变任何断言的真值
- 原语只是平凡透传参数（纯字符串、无独立 resolver 或粒度概念）：读它的定义不会缩小任何场景空间
