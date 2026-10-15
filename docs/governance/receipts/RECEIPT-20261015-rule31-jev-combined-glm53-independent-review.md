# Rule31 + JEV ten-file candidate — independent GLM-5.3 code review receipt

Date: 2026-10-15. Goal: 9956a550-f1ad-4281-aeb4-a4e797fe85ca.

## Exact authority
- Baseline main commit: `c8e50cb2b16c067a22609285d6aaa5eadf3ebdac`.
- Source patch SHA-256: `fac61923ced5c770a162bbf75b826f709ee18abb3cfcadc70abf227b689e0cb0`.
- Source commit: `13b4b87f237ef8ace66c60f92931eb3fcb0a2bf4`.
- Reviewer model: `glm/glm-5.3`; native private child `subagent_9f7178c45dd2` (parent `review-parent-rule31-jev-c8e50-20261015`).
- Real child state: `completed`; result id `result-5637fb3934f44be3b4711f3ce47b5696`; EventStore one terminal `8feea6cb-8eb8-4e61-9026-3a4d08c30d50`; live handle done and result identity verified.
- Final judgment: **PASS**, P0=0, P1=0, P2=4.
- Exact final candidate SHA trailer, count line and verdict line mechanically checked; `27724` bytes reviewed.
- Raw local JSON (ignored, not shipped): `data/rule31-jev-main-c8e50-20261015/review/glm-independent-review.json`; raw SHA-256 `2ed4c19f4b618c105915144023bb50a531b7de75ac70a42c2429883e0ed99198`; answer SHA `a578505085fed98fa2fbd179ab2d247da098630074764baff756c63eb4a7b6f5`.

## Review scope limitation

Reviewer was genuinely independent, read-only, zero registered tools, one round, standalone private parent/EventStore, no parent steering. It assessed the exact frozen Git patch and supplied read-only source/SoT context. It **did not** run tests or inspect the full workspace on its own; the current main runner lacks the experimental `review_isolated=True` API, so this is not an OS-isolated guarantee. This approval is **only for source review** and cannot authorize merging main, pushing or deployment.

## Reviewer full judgment

**独立只读评审结论（针对八文件冻结补丁，未运行任何测试，不复用先前 PASS 结论）**

**1. RuleIndex H2 同级截断（rule_index.py）**
`_SECTION_HEADING_RE = ^##[ \t]+` 只匹配 H2，不匹配 `###`，配合从 `match.end()` 起搜索：规则正文在下一个 H2（含非规则配置章节）截止，H3 嵌套内容保留。这正确修复了“最后一条规则吸收后续维护章节”的截断缺陷。两个新测试分别用合成 fixture（含两个连续 H2）与真实 SoT（断言 31/32/33 存在且末条不含配置章节、source_version_token 一致）双向钉住，且回执路径经 `run_search_records` 验证。行为等价性成立，未改变非末条规则的旧边界（旧逻辑在下一个 RULE heading 截止，新逻辑可能提前到中间非规则 H2——若 SoT 中规则之间夹有非规则 H2，水合内容会变短；但真实 SoT 中 RULE H2 连续排列，且新测试断言真实 SoT 末条边界，风险受控，记 P2 观察）。

**2. JEV wire 类型收窄（wire.py）**
`probs_ok` 蕴含 `probabilities` 为 dict 且 keyset/值/和全过；`confidence_valid` 经 `_finite_in_unit`（排除 bool、要求 finite、[0,1+ε]）。新增 `isinstance` 分支与运行时守卫逻辑等价，不放宽任何 wire 载荷；`isinstance(confidence,(int,float))` 理论上放行 `True`，但被前置 `confidence_valid=False(bool)` 门控，不可达。11 个参数化测试覆盖 None/bool/"0.8"/NaN confidence 不被强转、probabilities None/[]/含 None 值不被判 valid，与“无效保 null 不填 0.5”契约一致。概率和容差 1e-6 路径未被触碰。与 new-main `__init__.py` 导出面、shadow runner 的 `to_facts` 消费兼容。

**3. 备份耐久测试时效修复**
`make_archive(backup_at=backup_module.system_local_now().isoformat())` 只改测试夹具。生产 `cleanup()` 用 `datetime.fromisoformat(...).timestamp()` 与 `system_local_now().timestamp()` 比较，tz-aware 往返一致（naive/aware 混用会抛错而非静默，fail 可见）。未触碰保留逻辑，与 R9 已知失败根因吻合。注意此测试本意是"fresh backup 不被清理"，动态时间正确表达该语义，无隐藏回归面。

**4. 浏览器 fail-closed 负例**
绑定 `127.0.0.1:0` 获取临时端口且不 listen，端口仍被内核预留（避免固定 39099 被真实应用抢占导致 flaky），在 with 块内调用 `attest_port` 保证端口占用存活；仍真实走 lsof、不 mock 判定器、不降断言。移除 `Path` import 是否残留未用取决于未提供的文件其余部分，记 P2。

**5. Rule31 范围与模型代理**
两处 description 更新（registry_introspection.py、tools/registry.py compact）均把 SoT 条款转述为提示语义：≤2 类、每类≤5、同一任务窗口一次、豁免与零命中纪律、时效/适用性由模型裁决——无程序强制、无自动采用，符合“程序角色：无新增”。D3 晋升不清零仅存在于 SoT 正文，本补丁未改 docs/ai_rules.md，无回退风险。台账补登 Rule31 行并如实披露 37/36 口径差异；`test_ledger_covers_all_sot_rules` 改为按正式行首 `^\| RULE-AI-\d{2} \|` 匹配并交叉核对脚本 records 数，防止叙事引用误判缺行，未放宽覆盖断言。

**6. 证据缺口**
合并后十文件全量 R9 尚未执行（原始 R9 的 2 个失败均被本补丁修复；合并专项 214 通过）。这不是代码缺陷但属发布前必须补的回执，不得声称已绿。

P2 发现：(1) 合并全量 R9 未运行；(2) 台账 `records=37` 头字段与正文“真实登记项 36”并存，靠长文说明消歧，未来脚本读者易误读，建议后续把口径字段拆开；(3) RuleIndex 新边界在“规则间夹非规则 H2”假想结构下与旧口径不同，当前 SoT 无此形态但缺守卫；(4) 浏览器测试文件 `Path` import 移除的未用性不可在提供范围内完全核验。

无 P0/P1。补丁正确、安全、最小，保持 Rule31 范围与模型代理，与 new-main JEV/knowledge 运行时变更兼容。

VERDICT: PASS
P0=0 P1=0 P2=4
SHA256: fac61923ced5c770a162bbf75b826f709ee18abb3cfcadc70abf227b689e0cb0

## Status

See `docs/results/RESULT-20261015-rule31-jev-main-c8e50-r9-closure.md` for independently executed Quick, full R9, known-red history and release boundaries.
