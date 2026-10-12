---
method_id: read-guard-code-after-deterministic-rejection-4c305d6c17de
name: read-guard-code-after-deterministic-rejection
description: 对可读源码的状态机（方法生命周期、部署线、审批流）发起转换被拒、且回执是规则陈述型确定性错误（如 'candidate cannot become active directly; qualify independently first'）时，把回执当规格：grep 错误字符串定位并读取守卫代码的判定条件，按代码写明的中间状态逐跳完成转换；不要先猜『缺某前置』就补一个动作再盲试同一转换。本集猜测『qualification 未注册』补注册后重试 activate 再次同错，读 store.py:552 才知规则是必须两写（先 qualified 再 active）。区分瞬时失败与确定性拒绝是适用关键。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:356:09ea76261a3066bfc8a7
evidence_refs: learning:learn:a3d6d7ace741
created_at: 2026-09-23T13:37:38.715138+00:00
updated_at: 2026-09-23T13:37:38.715138+00:00
---
## Trigger
对带状态机的本地系统（生命周期 store、部署状态、审批流）发起状态转换被拒；回执是确定性、规则陈述型错误（ValueError/断言，错误文本自身已说明所需前置或中间状态）；且执行该规则的源码在本地可 grep 可读。

## Discriminator
失败回执是本地确定性拒绝而非 transient timeout/权限/网络错：错误文本已陈述规则（'qualify independently first' 直接指向必须先经中间状态），且 grep 错误字符串一步即可定位守卫代码。这把『哪种前置条件缺失』的开放假设空间（未注册？顺序错？权限？）缩成『守卫代码写明的那一条合法转换路径』。

## Short path
- 转换被拒后先复述回执原文：规则陈述型错误的文本已指明方向（未知量：合法转换路径是什么）
- grep 错误字符串定位守卫代码并读完整判定函数（未知量：确切判定条件，以及是否还要求其他前置如已注册的 qualification）
- 若守卫要求某前置（如注册记录），先按代码要求补齐该前置；若不要求则跳过
- 按代码写明的中间状态逐跳执行转换（如 candidate→qualified→active），每跳以成功回执确认
- 重读权威状态记录验证终态后停止

## Stop conditions
- 守卫代码写明的路径已走通，且权威记录显示目标状态已落盘
- 读码后发现失败实为 transient/外部错误（守卫代码不解释该失败），转基础设施排查而非继续调整转换序列

## Verification
- 重读状态记录/生命周期字段确认目标状态
- 对中途做的猜测性写操作（如补注册）核对是否为守卫代码明确要求的前置；非要求则标记为冗余动作

## Counterexamples
- 错误是 timeout、网络、权限类瞬时/外部失败：重试或排查基础设施更合适，读守卫代码无益
- 错误源是远端或闭源第三方服务，源码不可 grep：只能依赖官方文档或最小探针
- 消息已唯一指出可修复的输入错误（参数拼写、缺失字段）：直接修复重试即可，无需读代码
- 该状态机的守卫规则此前已读过且确认未变：直接按已知路径执行，不必重读
