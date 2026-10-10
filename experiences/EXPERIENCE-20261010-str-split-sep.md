---
title: str.split(sep) 对不含分隔符的字符串恒返回非空单元素列表，勿用作包含性判断
scenario: "在适配器/解析器中检测配置值里的模板变量（如 ${CLAUDE_PLUGIN_ROOT}、${VAR}）并决定组件状态时"
root_cause: "Python str.split 在分隔符不存在时返回 [原串]，列表恒非空；把它当作包含性判断是语义误用"
solution: "先判包含再 split：`if \"${\" in residual:` 之后才进入 split 循环提取变量名；或 re.findall(r\"\$\{([^}]*)\}\", s) 一步到位。复现（缺陷形态）：grep -n '\"\${\" in residual' src/llm_loop/extensions/vendor_formats.py 无命中时 .venv/bin/python -m pytest tests/unit/test_extensions_vendor_formats.py -q 会成批失败；当前性验证：该 grep 命中 + 18 passed。"
evidence: "evidence://v1/5f8a57d44dcc7a68d242e73ed1d3bfff51794f290712a93ea08a709d9f1b1b（修复前 18 测批量失败记录）；evidence://v1/09a1d2a7214b071644327d9e4500b0812c52ad2f5ebf29a4d0c964fc1ce81977（修复后 18/18 通过）"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T05:52:39.579681+08:00"
updated_at: "2026-10-10T05:52:39.579681+08:00"
---

实现 vendor_formats.py 的 ${VAR} 残余检测时，用 result.split("${") 的返回列表是否非空来判断"是否含未识别变量"。对无 "${" 的普通字符串（如 URL "https://example.com/mcp"），split 返回 [整串]，恒非空 → 每个无变量的合法值都被误判 needs_configuration。第一次修复后重构时又把同样的模式写回（漏加 "${" in residual 前置判断），导致 18 个单测同一根因批量失败。判断"字符串是否包含子串再解析"必须先做包含性测试，再 split/tokenize。测试价值：先断言一个"全字面值条目应为 supported"的负对照用例，可在成批断言失败前一步暴露这类全局误判。复现（修复前形态）：sed -n '186,194p' src/llm_loop/extensions/vendor_formats.py 若无 'if "${" in residual' 前置判断则为本缺陷形态；验证修复存在：grep -n '"\${" in residual' src/llm_loop/extensions/vendor_formats.py 应命中，且 .venv/bin/python -m pytest tests/unit/test_extensions_vendor_formats.py -q 应 18 passed。