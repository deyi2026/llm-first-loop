# 方法卡 E2E 链路缺口审计（阶段一·只读）

- 日期：2026-10-20 ｜ 审计员：GLM-5.3（子代理，阶段一只审计不改代码）
- 仓库：llm-first-loop-mirror @ 2d406485f（含未提交写入放宽改动）
- 活库：`data/methods/`（1252 卡）；线上跑 4e2d052e；`SEMANTIC_METHOD_ENABLED=0`、`knowledge_advisor_mode=off`
- 标记说明：【实测】=跑了命令/脚本；【推断】=仅读代码。结论分 通/半通/未通。

| # | 环节 | 结论 | 最严重问题 |
|---|------|------|-----------|
| 1 | 写入 | 通 | 六节已放宽，但 `freshness_action_ok` 正则过窄：单独「验证/核对」不认，纯警示卡被拒 |
| 2 | 检索 | 半通 | 中文整段 run 当一个 term（"如何排查"永不命中）；纯词法，web 语义通道关闭 |
| 3 | 精确水合 | 通 | `method:<id>` 返回完整正文；裸 id 只给发现投影；ref 三处格式一致；截断 id 靠引导语兜底 |
| 4 | 使用回记 | 通 | record_use + settlement 均计入，幂等，无强制使用残留 |
| 5 | 生命周期 | 半通 | invalidate 后仍进默认检索（仅 status 标注），retire 才真排除 |
| 6 | 质量抽样 | 通 | 内容 100% 实质卡；瓶颈是 86% 停 candidate、11 个无卡死目录 |
| 7 | 运行态接线 | 半通 | advisor off 零注入，触发仅靠工具描述软纪律；web 语义 method=False |
| 8 | 部署前置 | 半通 | 核心 src 改动未提交+43 untracked，publish 前须先收敛并过全量审查 |

（详细证据见下方各节，边查边写）

## 1. 写入（method_manage save_candidate）——【实测】通
- 【实测】临时 METHODS_DIR 下走完整工具路径（`execute`→`_run_save_method_candidate`）落一句话卡成功：
  回执 `[save_method_candidate] method:audit-one-liner-3c0922174082 status=candidate content_hash=8d90fbfd…`。
- 【实测】同 name+body 重复提交 → 返回同一 method_ref（幂等，不重复落盘）；目录仅 1 个卡目录。
- 【实测】**隐藏门槛**：一句话卡并非任意句可过——`freshness_action_ok`（tools_experience.py:20-29）要求正文含
  命令/复现/当前性验证/「先…核对」等信号；我的「不同正文版本…」纯陈述句被拒
  （`[参数错误] 卡内未检出『可执行的当前性验证动作』`）。与「写入放宽=只要求非空」的预期存在出入：六节结构确实放宽，但新增了正则启发式门槛，误伤无验证动作的真实一句话经验卡（regs 也放不过纯警示卡）。
- 写入边界（store.py:1569-1614）：`_card_content_missing` 拒空/纯标题正文；parent_ref/teacher_ref 存在性校验；episode ref 必须真（episode: 前缀）。
- 去重 hash（store.py:1605-1608）：`method_id = slug(name)[:72] + "-" + sha256(body)[:12]`；同名不同 body → 不同 id 各自成卡（无语义级去重，但 record_use 侧有 dedupe_slot_heads）。

## 2. 检索（search_records kind=method）——【实测】半通
- 【实测】活库 1252 卡上跑 RecordSearcher（词法）3 个真实任务式查询（limit=3）：
  | 查询 | 命中 | Top3（id 截断）| 相关度评价 |
  |---|---|---|---|
  | 提交前全量测试 审查 | 3 | child-id-c0edbb4e93c1(active)/verify-named-symbol-…dc2b42/verify-named-deliverable-… | 中：围绕"审查回执"，但无一张正对"提交前全量测试" |
  | 如何排查 playwright 超时 | 3 | verify-sink-and-background-…f23d33/verify-out-of-band-receipt-…/verify-inherited-premise-… | 差：Top1 实为"重量级依赖安装预检"卡，仅因含"超时/playwright"字样入围 |
  | 发布失败 怎么定位 | 2 | verify-deploy-liveness-by-content-identity-chain-f2d4bc/…ed6f807 | 好：正中部署核验链两张近重复卡 |
- 【实测】无意义词 → 0 命中，空结果正常返回（无崩溃）。
- 【实测+推断】CJK 分词缺陷：`_search_terms`（store.py:558-566）把整段中文 run 当一个 term（`['如何排查','playwright','超时']`），"如何排查"几乎不可能命中 → 中文任务语只剩孤立名词/英文词参与打分，召回靠运气；
  排序权重 id(10)>name(8)>body(5)>desc(4)+coverage（store.py:735-760），纯词法、无语义。
- 【推断】`SEMANTIC_METHOD_ENABLED=0` 时无语义候选通道（search.py:__init__ semantic_method_enabled），上述词法即为模型能得到的全部。

## 3. 精确水合（query="method:<id>"）——【实测】通
- 【实测】`method:verify-deploy-liveness-by-content-identity-chain-f2d4bc532d53` → 1 命中且 `projection_complete=True`、结果含 body（23 键，含 qualification_entries/freshness）；裸 id（无前缀）→ 1 命中但为词法发现（14 键、无 body，identifier_bonus 路径，属预期）。
- 【实测】截断/错误 ref → 0 命中；空结果回执带指引导语（tools_status.py:833-837 "[Method 查询语义] method: 仅用于已返回的 stable ref 精确水合"）。
- 【实测】ref 格式一致性：`store.get` 同时接受 `method:<id>` 与裸 `<id>`（不接受文件路径）；save 回执发 `method:<id>`；record_use 内部同样走 `store.get`（store.py:960-961）→ 写入/检索/回记三处格式互通，无断链。
- 【实测】注意事项：回执/渲染中 id 常被截断显示（渲染层 `_single_line` 截 180 字符），模型若照抄截断 id 水合会 0 命中——靠引导语兜底而非自动纠错。

## 4. 使用回记（record_use + settlement）——【实测】通
- 【实测】临时库工具路径 `method_manage(action=record_use, method_ref=method:ru-card-3c0922174082, use_decision=applied)` → success，
  回执含 `episode_ref=… decision=applied task_benefit=not_evaluated`；`methods/usage.jsonl` 落 1 条（keys 含 integrity/ledger_seq/ledger_watermark/method_content_hash）。
- 【实测】重复回记 → 幂等回执（slot+submission_hash 折叠，store.py:1050-1053）；`usage_net` 正确算出 net=1/applied=1。
- 【实测】`scan_method_use_ledger`（method_injection.py）能从工具迹识别回记（recorded）与水合（hydrated 列表含 `method:ru-card-…`）→ settlement 降级线索可达。
- 【推断】settlement.py：`_KNOWN_KINDS={"method",…}`（settlement.py:54）；pending 清单含 kind=method 条目（:412-428），submit 按 `store = method_store if kind=="method"`（:743）落账 → method 计入结算，无遗漏。
- 【实测】grep 全 src 无「必须使用 method/强制使用」类校验残留（命中均为 playwright/模型引用等无关文案）→ 无强制使用门槛。

## 5. 生命周期（method_manage 后四个 action）——【实测】半通
- 【实测】`method_manage` 实际枚举为 save_candidate/record_use/record_qualification/**refine/annotate_freshness**（registry_experience.py:77），任务所述 `update_freshness` 即 `annotate_freshness`：仅改 freshness_refs 单键并回执新状态（:489-505）。
- 【实测】record_qualification 走 registry:660-676 → `store.record_qualification`（store.py:1260/1284）落 qualification_entries，且强制真实 episode 溯源（"qualification 写入失败"分支）；audit 落账。→ 通。
- 【实测】refine 转发 transition ∈ {qualify,activate,hold,invalidate,retire,reopen}（registry:110-114）；`store.update_status`（store.py:1466）+ `note_blocked_transition`（:1405）journal 落账。invalidate/retire 有硬门槛：需一次 fail qualification 或 ≥2 不同 episode 的 rejected 使用声明，程序只核事实存在（store.py:1502-1507）。→ 通。
- 【实测+推断】修订保留旧版：save_candidate 幂等从不覆写（annotate_freshness docstring，registry:491-493）；supersedes 链追加修订、不改写历史（store.py:953/1046-1057，父记录校验）。→ 旧卡目录与内容保留。
- 【实测】**invalidate 不影响默认检索**：词法 `list()`（store.py:723）与 `semantic_candidates()`（:831）只过滤 `status == "retired"`；invalidated 卡仍可被默认检索命中，仅 status 标注（inventory 管理视图才分组，:773-775）。retire 则真被两处排除。→ 生命周期闭环在 invalidate 处断开：**半通**。

## 6. 质量抽样（random.seed=20261020，抽 30 目录）——【实测】通
- 【实测】抽样 30：29 有 METHOD.md（1 个空目录）；全库 1252 目录中 11 个无 METHOD.md（死目录，检索不可见）。
- 【实测】29 张内容全实质：thin_body(<40c)=0、thin_desc(<15c)=0、完全相同 body 重复组=0；body 长度全库 p5/p50/p95 = 870/1125/1566 字符。
- 【实测】name 以 `verify-` 开头的机器式命名全库 96/1244≈7.7%（描述性 slug 非纯 hash，尚可读）；抽样内 0 张空卡/纯标题卡。
- 【实测】抽样 status 分布：candidate 25 / hold 3 / active 1 → 内容可用比例≈100%，但**生命周期可用（active）仅 ~3%**：86% 停在 candidate 从未 qualification。内容质量不是瓶颈，流转率才是。→ 通（内容），瓶颈在环节 5 的流转。

## 7. 运行态接线——【实测】半通
- 【实测】`runtime_manifest.web.json`：git_head=4e2d052e（线上），semantic_scopes={memory:T, archive:F, **method:F**, docs:F, experience:T}；`runtime_manifest.learning.json`：git_head 同 4e2d052e，**method:T**——两进程语义通道声明不一致；叠加 `SEMANTIC_METHOD_ENABLED=0`，模型实际只有词法检索。`data/runtime/.learning.json` 不存在（委派任务所述文件名有误，实为 runtime_manifest.learning.json）。
- 【实测】模型侧唯一方法入口 `search_records`（registry.py:100 描述）：含开局纪律"实质多步/工具任务开局选≤2类、每类≤5 做一次 discovery…简单问答豁免；kind=method：失败重试、编辑冲突、超时、浏览器定位…"——**描述确实提到失败/卡住场景**，但属提示性纪律。
- 【实测】`knowledge_advisor_mode=off`：build.py:649-650 直接 return（注释原文 "explicit off: zero knowledge retrieval and wire change"）；knowledge_runtime.py:366-368 同样短路；method_injection.py 开篇即"Reading a method never injects a reminder"（纯 telemetry）。→ off 下零自动注入，坐实。
- 【判断】触发条件=模型开局读工具描述后自觉 discovery；无程序侧提醒/重试钩子（中途卡住时无任何机制把它推回方法库），"是否实质任务/是否简单问答"由模型自判。**触发不硬**，检索质量（环节 2 的中文分词缺陷）进一步压低命中率。→ 半通。

## 8. 部署前置清单（只列不执行）——【实测】半通（路径清晰，但当前不可直接 publish）
现状：worktree HEAD=2d406485f ≠ 线上 4e2d052e；tracked 修改 6 个（**含 src/llm_loop/methods/store.py、methods/reflection.py、introspection/registry_experience.py、tests/unit/test_method_learning.py 等核心改动**）+ untracked 60 个。
程序动作：
1. 收敛工作树：6 个 tracked 改动分类提交（或明确剥离）；60 个 untracked（evals/docs/报告）决定入仓或忽略【用户决策】。
2. 全量测试 + 按 RULE-AI-28 取得覆盖当前产物的独立审查有效 PASS 回执（未满足暂缓 push/publish）。
3. `service_control publish`：要求 tracked 工作树干净 + CAS + webui 产物 hash 绑定；untracked 不影响，但需确认不误入产物。
4. `service_control restart`（web 与 learning 各一次）：显式带 expected_generation=最新 status 观察值；冲突按回执 current 重试。
5. env：维持 `SEMANTIC_METHOD_ENABLED=0` + `knowledge_advisor_mode=off` 则无需改；若开启语义 method 通道【用户决策】，还需对齐 web(method=F)/learning(method=T) 两 manifest。
6. 部署后验证：status 核 git_head==新 commit 且 generation 生效；线上 `search_records kind=method` 抽查命中；method_manage record_qualification/refine 冒烟；web inventory 看生命周期分组。
