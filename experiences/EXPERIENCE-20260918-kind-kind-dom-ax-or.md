---
title: "结构源 kind 兜底值遮蔽语义源 kind：DOM/AX 合并要用\"无证据让位\"而非 or 短路"
scenario: 浏览器语义对象 kind 由 DOM tag 与 AX role 双源合并（perception.py _kind_for/_merge_kind）；某类元素在 DOM 结构推导里落兜底值时，真值合并表达式会永久遮蔽另一侧的具体语义 kind
root_cause: ""
solution: "合并前把兜底值显式归一为\"无证据\"（generic/unknown→空），任一侧具体值优先；并给 tag_map 补齐该类别标签映射；用真实浏览器会话端到端断言 matched_total>0"
evidence: "commit d808456a3（tag_map h1-h6 + _merge_kind 无证据让位 + 回归测试 tests/unit/test_smc_browser_projection_vision_v01.py::test_heading_kind_is_not_masked_by_generic_dom_kind）；gen17 真实 CDP 会话复测：projection_kinds=[\"heading\"] matched_total=1 且 ProbeTitle kind=heading（本会话 browser_perceive 回执，bsnap-12-6ed2a8fbf1a5600e）；pytest tests/unit -k smc_browser 221 passed"
tags: [browser, perception, kind-merge, projection, cdp]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T14:30:24.559098+08:00"
updated_at: "2026-09-18T14:30:24.559098+08:00"
---

现场：挂测 kinds=["heading"] matched 0，但 h1[aria-label=ProbeTitle] 的 AX role=heading 就在页面上。链路：_kind_for tag_map 缺 h1-h6 → DOM 侧节点 kind=generic；DOM/AX 合并用 `dom.get('kind') or ax.get('kind')`，generic 是真值所以短路，AX 侧 heading 永远不可见。修复：1) tag_map 补 h1-h6→heading；2) 合并改为「generic 与 normalize 缺省 unknown 视为无证据，不得遮蔽对方具体 kind」；3) 回归测试锁定双向（dom specific 仍优先）。启发：结构源与语义源合并时，任何「兜底默认值」（generic/unknown/None）都不是证据，必须让位于另一侧的具体值；投影/过滤面（kinds 过滤）上线前要用真实元素类别做一次端到端非零断言，单元 fixture 若不含该类别元素则测不出。