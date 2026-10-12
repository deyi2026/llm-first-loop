# Browser SMC 工具挂载实录（2026-09-18，用户授权 live test）

## 目的
用户指令：把 browser_perceive + browser_semantic_execute 挂到会话，由模型亲自测试。

## 已完成事实
1. 挂载机制确认：env 门控（factory.py:883+），Settings 启动装配冻结，refresh_config 不重建工具表 → 必须 restart web。
2. env 注入链确认：restart_mirror.sh → `python -m llm_loop.web`（CWD=runtime_root）→ `load_env_file(CWD/.env)` 全量键进 os.environ（不受 BUSINESS_KEYS 白名单限制）。
3. `.env` 追加（备份 `.env.bak-20260918-browser-mount`）：
   - LFL_BROWSER_PERCEPTION_CDP_URL=http://127.0.0.1:45918
   - LFL_BROWSER_PERCEPTION_TARGET_ID=B8F5E3C36F5B78A9F799531984964DFE
   - LFL_BROWSER_ACTION_ENABLED=1
4. fixture（全部 loopback-only，setsid 脱离，能活过 web 重启）：
   - HTTP 服务 127.0.0.1:45917（data/browser_mount_test/server.py，pid 见 server.log；页面 `/`=SMC Probe：IncrementCounter 按钮/Twin 双胞胎/NoteInput/GoNext 链接，状态文本可读回；`/next`=Next page）
   - Chrome headless=new 隔离 profile + loopback CDP 127.0.0.1:45918（pid 文件 data/browser_mount_test/chrome.pid）
5. 预检：CDP /json/version OK；page target 唯一且 url 正确；env 三键按 web 启动顺序解析全通（action_enabled=True）。

## 重启后验收（下轮）
- 工具表出现 browser_perceive / browser_semantic_execute（以及 wait 族/browser_action/browser_semantic_operation）
- 模型亲自循环：snapshot → 选 grounding_ref → semantic_execute click/fill/navigate → snapshot 验证状态文本
- 双胞胎 TwinChoice 是模型侧歧义测试（snapshot 应暴露两个不同 ref）

## 回滚
删 .env 中该块 → service_control restart web；fixture 清理：kill $(cat data/browser_mount_test/chrome.pid) + 停 server.py。

## 测试结果（2026-09-18 10:55–11:00，模型亲自循环）
- restart：service_control rc=0 succeeded（action_id=svc-17462c...8002）
- browser_perceive：snapshot ✓（WorldSnapshot + SemanticObject + grounding_ref）；hydrate ✓（availability=available）；diff ✓（净变化 created/removed 精确）
- browser_semantic_execute：click ✓（clicks=1 实读验证）；fill ✓（wait value_text=hello-from-llm 首采样 satisfied）；navigate ✓（url=/next + document_generation 1→2 + "Next page" 实读）
- wait 族：object_text ✓（satisfied 与 indeterminate 两种结果都见过）、scope_url ✓（satisfied）
- 歧义测试：两个 TwinChoice 同名按钮，by-ref（el_b355...）精确命中 Twin B（status: twin=B）
- 关键发现（已验证）：JS `textContent=` 重建的文本节点 identity 不稳定（ref 失效→wait 返回 indeterminate/target_not_observed）；稳定元素（button/input/段落）的 el_id 跨快照不变。验证动态文本应重拍快照+diff 取新节点，或对稳定元素等待属性（如 input value_text）
- 未覆盖：select / scroll（fixture 无相应元素）；browser_action / browser_semantic_operation（同管道的低层变体，未测）

## 2026-09-18 11:07 补测（select / scroll）
- fixture 加 /form 页（FruitSelect 下拉 + FormStatus 回显 + LongList 6000px）；server 重启为 pid 21773，Chrome 未动（target 仍 B8F5E3C3...）。
- navigate /next → /form：回执 ok，document_generation 2→3，实读落地。
- select cherry（ground el_6e90ba04f287cd36c63f）：回执 ok；实读 FormStatus=`fruit=cherry scrollY=0`，change 事件真实触发。
- scroll delta_pages=2 on LongList（ground el_2f451e726377773dc461）：回执 ok；实读 `scrollY=3851`，scroll 事件真实触发。
- 附带发现：① 文本对象 grounding ref 随文本重建而变（el_10c89b→el_2cd1f6→el_26ccc76），receipt 的 identity_unstable_objects 会在事前提示——与首测 20 采样 indeterminate 事故根因一致；② projection_limit 小于对象数时 projection.complete=false，全量在 evidence（recovery_ref 翻页可取）。
- 动词矩阵收口：click ✓ fill ✓ navigate ✓ select ✓ scroll ✓（全部经 snapshot→ground→execute→re-observe 实证，无一跳步）。

## 2026-09-18 追加：切换到可见浏览器（用户围观）
- 已杀 headless 实例（原 target B8F5...）。
- `open -na "Google Chrome"` 起 GUI 实例：user-data-dir=data/browser_mount_test/chrome-profile-visible（绝对路径），CDP 仍 127.0.0.1:45918，新 page target=422BCDCC6FC0D14FCB333488657482FE。
- .env TARGET_ID 已替换；CDP_URL 不变；generation 仍 11（进程重启不 bump deployment generation）。
- 重启 web 后：工具表绑定可见 Chrome，模型操作用户可实时围观（注意 CDP 注入不移动 OS 鼠标光标，页面响应可见）。

## 实测结果（2026-09-18 11:15-11:19，重启后同会话完成）
全部通过：
- snapshot：29 对象 complete 投影；hydrate：exact 对象+TTL retention；diff：created/removed 精确到文本对象级
- click：IncrementCounter ×2、Twin B（双胞胎按 main.children DOM 顺序消歧）、GoNext（回执含 document_generation_changed/scope_changed）
- fill(replace)：NoteInput value_text 回读验证
- navigate(resource_ref)：返回根 URL，wait scope_url 首采样 satisfied
- 验证链：clicks=2 note=hello from llm-first-loop twin=B（水合终态文本实证）

现场学到的语义（已存 experience:browser-smc-actionid-dedupe）：
1. action_id=(target_ref,verb,args) 内容哈希；同 ref 重放 → rejected duplicate_action_id（未派发）；re-observe 取新 ref 再派发即成功（id 含快照谱系）
2. 段落对象无 value_text 投影（property_unobserved）；文本变更=旧 StaticText 对象删除+新对象创建（identity_unstable_objects），wait 旧文本对象返回 target_not_observed——fail-closed 正确
3. receipt ok ≠ 任务完成，每次都以 diff/hydrate/谓词再观察闭环

未覆盖：select / scroll（fixture 无相应元素）；browser_action / browser_semantic_operation（本次只测用户点名的两个工具）
更正：Chrome 以 --headless=new 启动，无可见窗口（上一轮“你会看到窗口”的说法有误）。
