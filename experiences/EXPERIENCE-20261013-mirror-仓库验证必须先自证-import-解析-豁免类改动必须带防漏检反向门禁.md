---
title: mirror 仓库验证必须先自证 import 解析；豁免类改动必须带防漏检反向门禁
scenario: 在 llm-first-loop-mirror 仓库验证 validator 改动或复现行为缺陷时；跨会话/跨审查方对同一输入得到矛盾复现结果时；设计任何豁免类（降低误报）改动时
root_cause: ""
solution: "（1）裸 python 复现一律 PYTHONPATH=src 并先打印模块 __file__ 与版本常量自证加载工作区代码；pytest 依赖 pyproject pythonpath=[\"src\"] 可测工作区，但要意识到两者可能测不同代码。（2）豁免类改动必须先写反向测试（真完成声明不得豁免）看红灯再改实现；豁免判定绑定到动词 occurrence 语义类别（名词化吸收×完成体依附），禁止局部 regex 命中豁免整句、禁止以主体词缺失为豁免依据。"
evidence: "commit 0072fbc0c（tests/unit/test_validator_declaration_exempt.py 新增 3 个反向门禁测试，rev1 红灯/rev2 绿灯实收输出）；rev1 复现输出（PYTHONPATH=src 下四反例 -> []）；全量对照 rev1 2 failed/7616 passed vs rev2 2 failed/7619 passed（无新增失败）；sys.path 实测输出（.releases/99069aae6/src 位于 path[0]）"
tags: [validator, declaration-check, PYTHONPATH, editable-install, testing, false-negative, exemption-granularity]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T23:05:15.156134+08:00"
updated_at: "2026-10-13T23:05:15.156134+08:00"
---

llm-first-loop-mirror 仓库验证纪律（2026-10-13 实证）：
1. 环境陷阱：shell 全局 PYTHONPATH 指向 .releases/<hash>/src（发布流程注入的当前生效快照）。裸 python（含 python -c 复现、独立脚本）import 到旧代码；pytest 经 pyproject pythonpath=["src"] 测工作区代码。裸 python 验证必须显式 PYTHONPATH=src，并先打印 __file__/版本号自证加载了哪份代码。症状：不同会话对同一输入复现结果矛盾（一方抽取一方 []），或定向测试全绿但反例明显成立——先怀疑 import 解析，再怀疑逻辑。
2. 反向门禁纪律：降低误报的豁免类改动必须同时设防漏检反向测试（断言真完成声明「不得被豁免」），覆盖中文省略主语句式（"已写入历史记录"）。测试全绿≠方案有效：8d9410ec rev1 的 23 个测试全绿但 4 个无主语真声明全部漏检。豁免粒度原则：局部 regex 命中不得豁免整句；「句内无主体词」不得作为非自身声明的证据（中文常态省略主语）。