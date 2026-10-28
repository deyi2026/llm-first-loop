---
method_id: owner-docstring-contract-before-ungrounded-greps-d0a47d3965ac
name: owner-docstring-contract-before-ungrounded-greps
description: 用户要求补齐某系统产物缺失的行为（如“装完没检测模型配置”、“前缀没加载规则/经验/工具”）且无报错栈时，先按包结构定位 owner 模块并读其头部 docstring：这类缺失常是 docstring 明示的有意设计边界（doctor“离线只读、不断言 live model 可用”；universal prompt“intentionally 不含 playbook/SOP/memory”），docstring 同时解释缺口成因并给出扩展契约（离线默认、字节稳定、verbatim 投影+同步测试）。避免对自造复合标识符做无根据 grep（本集 context_prefix/prefix_loader/build_prefix 一次 zero-hit），也不必在已拿到设计契约后再做确认性检索（本集在 prompt.py docstring 已回答后又 grep rules，再次 zero-hit）。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5330df43-269d-4831-8ca6-e26379519674:0:880fc6965539818b98b8
evidence_refs: learning:learn:236e5e1ea295
created_at: 2026-10-20T12:51:53.525625+08:00
updated_at: 2026-10-20T12:51:53.525625+08:00
---
## Trigger
用户报告某生成产物或安装/启动流程缺少一类能力并要求完善；没有 traceback、没有已观察输出指认具体机制标识符；需要在代码库中回答三个未知量：谁拥有该行为、缺失是有意的还是遗漏、在哪里扩展才不违约。

## Discriminator
(1) 包结构列举已暴露真实模块词汇（runtime/{doctor,first_use,onboarding}.py、core/、methods/、skills/ 等），拟 grep 的机制名不出现在任何已观察输出中——这类 token 零命中概率高且零命中无信息量；(2) 此类仓库的 owner 模块 docstring 惯以“intentionally / 不 / only”句式声明能力边界，并附带稳定性契约，是比 grep 更高密度的权威规格。

## Short path
- 读流程文档或入口命令，确认现状行为与命令面（未知量：装完现在到底做什么）
- 在 src 范围内做结构化列举（find/按名 glob，避开 .venv/.releases 快照噪声），按模块名选出各子目标的 owner 候选（未知量：谁拥有被抱怨的行为）
- 读 owner 模块头部 docstring：确认缺失是否为有意边界，抄下扩展必须满足的契约——离线默认、字节稳定、受控投影、同步测试（未知量：为何缺、怎么补才不违约）
- 沿契约接缝实现：默认行为不变，新能力走显式开关或显式参数，扩展内容满足稳定性约束（如前缀资源不变时字节稳定、失败降级为入口提示）
- 回归覆盖“默认路径契约不破坏 + 新路径行为正确”，通过即停，不再做确认性检索

## Stop conditions
- owner docstring 已解释缺口并给出契约，且改动通过其声明的同步/稳定性回归测试
- 结构列举后 owner 不唯一或 docstring 无设计信息——降级为常规代码阅读，此时 grep 词必须取自已读代码中的真实符号

## Verification
- 新能力默认关闭或需显式触发，原默认行为的回归全绿（离线只读测试、前缀缓存/指纹测试不破）
- 扩展产物满足契约声明的稳定性：资源不变时字节稳定、敏感值不泄露、缺失资源时降级而非报错

## Counterexamples
- 拟检索的标识符已由 traceback、用户原话或已读文档给出（grounded）——直接精确 grep 定位更快，先读 docstring 反而是绕路
- owner 模块是薄脚本或 docstring 无实质设计内容——契约读不出信息，应直接读实现与调用点
- 问题是运行时偶发行为（为何没触发、为何慢），而非产物内容缺失——应查调用链与日志，装配契约不适用
