---
method_id: executable-qualification-before-variant-enumeration-a95d43616564
name: executable-qualification-before-variant-enumeration
description: 用户要求『测试/验证』某仓内能力，而首轮发现同时暴露『可执行验证入口』（如 scripts/qualification/ 下的 live 脚本）与『版本化实验/协议文档』（evals/ 多变体 PROTOCOL/PLAN）时，不要枚举实验变体目录或通读协议文档；先把未知量收窄为『本会话如何执行验证』：用注册表给出的规范工具名选定对应的可执行脚本，读其头部/argparse 取得权威 pass/fail 合同，做最小环境检查后直接运行，以退出码与结构化结果收尾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:265:a628b20456a7558d3325
evidence_refs: learning:learn:ed874cadaefb
created_at: 2026-09-18T02:25:14.535120+00:00
updated_at: 2026-09-18T02:25:14.535120+00:00
---
## Trigger
会话代理收到『测试一下 X 操控/驱动 Y』类请求；X 是缩写或仓内能力名；首轮工作区搜索结果同时列出可执行 qualification/live 脚本命名空间与大量版本化实验协议目录（evals/ 变体）

## Discriminator
搜索回执中已可见带 live/qualification 字样的可执行脚本路径，且方法/工具注册表命中给出该能力的规范工具名（如 browser_semantic_execute）；这两条当时已知事实足以把『十几个 eval 变体目录 + 多个脚本 + 大量单测』缩成『与规范工具名对应的那一个 live 脚本』，无需先读任何 PROTOCOL 文档或枚举 eval 变体树

## Short path
- 歧义术语最小 grounding：一次工作区搜索确认仓内实体及命名空间分布（evals/ vs scripts/qualification/ vs tests/）
- 查方法/工具注册表，取得该能力的规范工具名与核心循环描述（如 perceive→execute→receipt→verify）
- 把未知量收窄为『本会话如何执行验证』：若能力工具未挂载会话工具表，只在已暴露的 scripts/qualification 命名空间内按规范工具名选定 live 脚本
- 读选定脚本头部与 argparse：确认自包含（隔离 loopback 浏览器、退出码约定、断言 schema），即取得权威 pass/fail 合同
- 最小环境检查（目标二进制路径、解释器/venv）后运行脚本，读退出码与结构化 result
- 报告结果并显式声明边界：工具层端到端已验证 ≠ 模型在环已验证

## Stop conditions
- 脚本退出码 0 且其声明的全部断言 PASS，用户所需事实已被该权威来源验证，停止发现并总结
- 发现会话已直接挂载该能力工具：改为亲自执行最小 Observe→Ground→Execute→Verify 循环，不再跑脚本
- 仓库不存在可执行验证入口，或脚本前置条件（环境/版本/资源）不满足：停止并转读协议/PLAN 构造测试

## Verification
- result 中的 git HEAD 与当前工作区一致，断言计数与脚本声明的 schema 完整闭合（pass 计数 = total）
- 最终回答显式区分『工具层已验证』与『模型在环未验证』，不把脚本通过表述为模型能力通过

## Counterexamples
- 用户问的是模型侧能力（轮数门槛、恢复行为、六行 harness 成功率）：evals/ 协议实验线才是目标，先跑工具层 qualification 脚本会答非所问
- 可执行脚本被协议钉死在旧 commit 或与当前接口 schema 不一致：须先核对版本适用性，不能直接运行当前 HEAD 的脚本
- 术语在工作区 grounding 失败（是外部缩写而非仓内实体）：应向用户澄清含义，而不是继续枚举目录
- 脚本需要外部资源、密钥或会改动非隔离的真实环境：先读前置条件并评估影响，不可直接运行
