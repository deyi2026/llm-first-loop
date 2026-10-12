---
title: Positive control before claiming an unmatched property is a real gap (断言属性不可复现前先跑阳性对照)
scenario: "用 browser_perceive wait object_text (field=name, match=equals) 探测某元素，探测失败（unsatisfied），需判断是「对象存在但属性不可复现」还是「谓词链路本身故障」时。"
root_cause: ""
solution: "把「我构造的字符串没命中」和「谓词根本坏了」区分开的三步：1) 对目标对象跑 match=equals 探测并读回 observed_value——它会回显真实属性值，可直接看出差异；2) 换一个已知干净的同页属性做阳性对照（如 equals(\"回到顶部\")→satisfied），证明谓词链路本身正常；3) 只有阴性+阳性同时成立，才可下「属性不可复现」结论，并把它写成带对照的论断。反例：只跑阴性探测就断言「有 bug」——若谓词故障，会得出完全错误的结论。同源变体：实验首轮数据全为空/异常时，先判「harness 功率不足」再重跑，而非当作回归证据（LFL 的 ELIG-20261010-994e30f4 §3 有 max_tokens=500→2000 重跑、首轮 JSON 留档不作通过证据的先例）。"
evidence: "阴性=evidence://v1/22a46d5e5dd326c24a0e42be12be891b2436ef5105398b93bc52d2890986d844 与 evidence://v1/30eb475f751be4b3a0c0a34d5173d9280e5880c5cf7d1d1424751627ac0d676f；阳性对照 evidence://v1/df80b517f6bb4dc24c20bf2acc8fee1b3634d1d574521f354e3c46c62e58513d；schema 证据 evidence://v1/a820e36c80c762298b711f47a1b9e38f1b34fc8c628d2712fd9d90f40a56b906；控制判据与模型×预算交互的先例见 docs/analysis/ELIG-20261010-994e30f4-method-task-type-gate.md §3"
tags: [browser_perceive, grounding, 验证纪律, 阳性对照, 可证伪]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T20:07:48.989800+08:00"
updated_at: "2026-10-10T20:07:48.989800+08:00"
---