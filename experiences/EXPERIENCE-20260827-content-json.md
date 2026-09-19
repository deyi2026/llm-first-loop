---
title: 紧急压缩空转根因：压缩预算只看 content、守卫看全字段 JSON（口径不一致）
scenario: "glm/glm-5.3 会话载荷 90 万 tokens 超限，守卫拦截后自动紧急压缩连续 4 次空转（载荷 906,641→907,343 只增不减），38 轮全部被拦，用户被迫新建会话。排查方向：逃生机制提示\"成功\"但指标不动 → 两套口径不一致。"
root_cause: "守卫（routing._estimate_request_chars:380）按提交视图全字段 JSON 估算（reasoning_content+tool_calls+schema），压缩器（history.py 13 处统计点）只看 len(content)——reasoning_content 实测占载荷 47% 却对压缩器不可见，两预算永不相交；glm/glm-5.3 窗口 1M 时 effective_budget=300K chars，content 永远追不上阈值 → emergency_compact 恒空转，逃生提示照发。"
solution: 在 history.py 新增 _wire_size（content+reasoning_content+tool_calls 参数，与守卫口径对齐）+ _dict_wire_size（to_llm_dict 后视图用），压缩预算判定 13 处统计点切换 wire 口径，纯展示统计（压缩目录文案等）不动。验证：单元回归 93/93 全绿；合成复现（30 轮 reasoning-heavy：content 376 chars vs wire 240K，修复前恒不压/修复后归档 48 条）。
evidence: "镜像区实证（fb8f8987 会话）：全字段 598,276 chars（reasoning_content 286,574 占 47%，content 仅 159,100）；守卫按全字段拦 38 轮全拦（request.meta=0），压缩按 content 判 159K<255K 恒不触发（cache_compacted 事件 0，归档文件仅 12KB）；载荷 906,641→907,343 tokens 只增不减。修复：3ddd74a，93/93 回归全绿+合成复现验证。"
tags: [emergency_compact, 口径不一致, 预算判定, reasoning_content, 压缩空转, 镜像区修复]
source: {}
status: active
created_at: "2026-08-27T00:38:27.717526+08:00"
updated_at: "2026-08-27T00:38:27.717526+08:00"
---

口径不一致型 bug 特征：逃生/兜底机制反复触发但指标不动（载荷只增不减、审计事件有记录但产物体积不变）。排查步骤：①分别提取两侧统计口径的代码点（守卫估算函数 vs 压缩判定函数）；②用真实会话数据按字段分布统计（json.dumps 逐字段），找出"守卫看得见、压缩看不见"的字段（本案 reasoning_content 占 47%）；③合成最小用例复现（轻 content+重 reasoning），修复前后对比归档数。修复模式：写一个与守卫口径对齐的 _wire_size helper，替换预算判定点；纯展示统计不替换（避免语义污染）。