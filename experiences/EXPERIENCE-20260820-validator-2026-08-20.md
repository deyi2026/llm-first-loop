---
title: 误报修正必须同时守住真阳性：validator 改动搬回前先跑声明豁免约束测试（2026-08-20）
scenario: "从 backup 分支 cherry-pick 涉及声明检查器/validator 的提交（如 1e9bbad 方案B 附带的 validator 误报修正）时，必须同时验证\"误报降低\"与\"真阳性保留\"两个方向：跑 test_validator_declaration_exempt.py（含真阳性约束用例），不能只看减少误报的收益。"
root_cause: "误报修正（豁免否定/将来/状态/转述类语句）扩大了豁免面，把身份幻觉句（含创建动词的真阳性来源）也一并豁免——诚实性检查出现假阴性。审查只看了\"减少误报\"的正面，未先验证\"真阳性不丢\"约束（test_validator_declaration_exempt.py 已有该约束测试）。"
solution: 1) 任何 validator/诚实性/声明检查改动，验收标准 = 误报减少 AND 真阳性不丢（既有约束测试全绿）；2) cherry-pick 前先确认目标提交是否包含 validator 类改动，若包含先跑 test_validator_declaration_exempt.py 验证；3) 失败则拆分提交（git cherry-pick -n + git checkout HEAD -- <file> 排除问题文件），保留无害部分；4) 行为变更（如 final_answer 追加命中率尾行）需同步适配断言（startswith 而非 ==），并注释说明属展示层。
evidence: "2026-08-20 cherry-pick 审查：1e9bbad 的 validator 误报修正（声明分类强化）搬回后，test_identity_statement_still_extracted_true_positive 失败——身份幻觉句\"我是 Qwythos，由 Empero AI 创建\"不再被抽取判 False，真阳性捕获失效（诚实性检查漏洞）。已拆分排除 validator.py，保留方案B展示层。137 单测全绿。"
tags: [validator, 真阳性, 误报修正, cherry-pick, 诚实性, 拆分提交]
source: {}
status: active
created_at: "2026-08-20T00:35:59.422756+08:00"
updated_at: "2026-08-20T00:35:59.422756+08:00"
---