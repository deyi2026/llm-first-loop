---
title: 内部 API 调用前 grep 三查（类名/签名/返回值），禁止试错探测
scenario: 需要调用项目内部 API（类名/函数签名/返回值结构不确定）时——如验证 provider 注册、调用 pool/registry 方法。
root_cause: 陌生代码库 API 调用前未先查证签名/返回值结构（resolve 返回 tuple、类名 ModelClientPool 非 LLMPool），凭记忆猜测导致连续试错。
solution: "调用内部 API 前三查：① grep 类名/函数名（grep -n '^class \|^def ' 目标文件，1 次拿全）；② 读签名与返回值注释（def 后 10 行）；③ 构造前用 _parse_* 等纯函数先验（不依赖完整装配）。禁止凭记忆猜类名/参数；一次 grep 胜过三次试错。教训实例：ModelClientPool（非 LLMPool）、resolve 返回 (pid, mid) 元组、load_providers 不存在（实际 _parse_providers_dict）。"
evidence: SE-20260817-002-dced：stagnation_rate 0.46（样本 50）。根因：配置治理 P0 验证阶段反复试错导入（LLMPool→ModelClientPool→fallback_candidates→resolve 返回 tuple 结构），4-5 次 execute_command 猜 API。违反 RULE-AI-03 禁止逐个试错探测（应先 search_docs/search_records 查证）。对照：本会话其余阶段（SWE 评测/配置治理主体）效率 0.95。
tags: [停滞率, API调用, grep优先, 试错禁止]
source: {}
status: active
created_at: "2026-08-17T22:50:03.406162+08:00"
updated_at: "2026-08-17T22:50:03.406162+08:00"
---