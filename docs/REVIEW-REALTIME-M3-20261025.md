# 独立代码审查：realtime_multimodal M1 客户端闭环 + M3 视觉端到端（2026-10-25）

> **复审与修复记录（2026-10-25 04:5x，LFL 追加；细节见文末"复审闭环"章节）**
> 首轮 FAIL 后已完成 5 轮修复 + 3 轮独立复审：服务端半 PASS、前端半 PASS、修复集聚焦复审 PASS（均 P0=0/P1=0）。
> 全量门禁**未运行**（2026-10-25 复核口径：当时未提交的安全批次现已提交；本候选 = 分支 `fix/evo-e0bff8ee-p2-int-20261025`，其 R9 函数体积基线已由本分支 guard(r9) 提交重登记，全量数字待最终门实测填充，详见文末）。

- 审查者：独立代码审查子代理（GLM-5.3，只读审查，未修改任何代码/测试）
- 仓库：llm-first-loop-mirror 本地镜像工作树（全部审查对象均为**未提交改动**）
- 范围：src/llm_loop/{realtime,web} 改动+新增（13 文件）、tests/realtime 新增（6 文件）、
  webui/src/core/realtime 全部 + components/conversation/realtime 全部、
  Composer.tsx/realtimeEvents.ts/mediaSessionClient.ts/playbackQueue.ts/wiring.test.ts 改动、
  docs/M3-KEYFRAME-WIRE-CONTRACT.md（共 28 个未跟踪文件全数列入核对）。
- **产物哈希核验**：`git diff -- src/llm_loop webui/src` + 未跟踪文件逐个 sha256 汇总 =
  `ae539549bc557ea2e6dc73ce6b853a58efde7a5d9cb78228f721f0e2b39c77e4` ✅ 与委派期望一致。
- 必读真值：.codeartsdoer/specs/realtime_multimodal/{design,tasks}.md 相关章节、
  docs/M3-KEYFRAME-WIRE-CONTRACT.md、docs/ai_rules.md RULE-AI-24/28/01。
  注：委派所列 `acceptance.md` 实际不存在；该目录需求索引为 `spec.md`（tasks.md:5/13 自述"索引非权威"），
  本审查以 design.md/tasks.md + 契约文档为真值锚点。

## Verdict

**FAIL**：P0=0，**P1=3**（均已有可运行复现或静态逐行证据）。按结论规则不能给 PASS。
P2/nit 共 12 条，列于后，不影响 FAIL 判定本身。

## P0

无。未发现安全/隐私直接泄露（下行事件、日志、UI 均不含 data_b64；WS 鉴权/归属/epoch 校验严密；
唯一证据库 WorkspaceArtifactStore 无第二套；路径由服务端生成 id 构造，无穿越）。

## P1（3 条）

### P1-1 视觉 turn 的任务派发链路断裂：evidence refs 在两条生产派发路径上都无法进入任务输入
- 证据链（file:line）：
  - `src/llm_loop/web/__init__.py:226-276`：sink 把 `attachment_facts=[{"kind":"realtime_visual_evidence", "evidence_refs":[...], ...}]` 冻结进 HumanTurnQueue；
  - `src/llm_loop/web/routes.py:289-307` `_queue_claim_matches`：浏览器正式 /chat/stream 须使 `list(claimed["attachment_facts"]) == list(attachment_facts)` 全等，而 `attachment_facts` 只能由 `_resolve_chat_attachment_facts`（上传附件 store 的 public_facts）产生——**结构上永远不可能等于 realtime 形状**（复现：见下）；
  - `webui/src/core/conversation.ts:1035-1042`：前端 relay 把 `f.ref` 映射为 `attachment_ref`，realtime facts 无 `ref` 字段 → undefined → `src/llm_loop/web/schemas.py:16` `^attachment://[0-9a-f]{32}$` 校验 422；
  - `src/llm_loop/web/queue_recovery.py:212-224`：服务端兜底 `_execute_claimed` 调 `runner.start(...)` **不传 attachment_facts/user_metadata** → 60s 后以纯文本执行，视觉证据静默丢失。
- 违反：契约 docs/M3-KEYFRAME-WIRE-CONTRACT.md §2.4（任务输入可见 artifact ref）、
  design.md §相关章节（绑定帧以独立结构化注记传递到任务输入）；
  `web/__init__.py:228` docstring"真实调用链（与浏览器文本提交同一入口）"与事实不符（诚实性问题）。
- 测试盲区：`tests/realtime/test_web_assembly.py:151-189` 只验证 enqueue 落队，未覆盖派发匹配。
- 最小复现（/tmp/repro_realtime_dispatch.py，只读仓库）：sink→`q_9aae2d56840b`；
  `dispatch_claim` 后 `_queue_claim_matches(最优payload, claimed, [])` → **False**；
  前端映射 ref → UNDEFINED（422）。
- 修复建议：为 realtime 视觉项提供机械直通——或让 `_queue_claim_matches` 认可
  `origin=realtime_visual` 冻结项（跳过 attachment_facts 全等并以服务端冻结值为准入任务输入），
  同时 `QueueServerFallback._execute_claimed`/`runner.start` 链补传 `attachment_facts`→`user_metadata`；
  两条路径都要修，并补一条"claim→/chat/stream 成功且 run 输入含 evidence_refs"的集成测试。

### P1-2 disable/页面刷新后实时语音永久无法再启用（M1 客户端闭环生命周期断裂）
- 证据链：
  - `src/llm_loop/realtime/media_registry.py:63-72`：同一 LFL 会话存在未关闭记录且不带 `take_over` → 409；
    记录仅在 REST DELETE（`close()`，106-121）或 `take_over` 时关闭，WS 断开**不会**关闭；
  - `webui/src/core/realtime/useRealtimeVoice.ts:270-281`：`disable()` 只 close WS（无 DELETE、无 take_over）；
    `:152-175` `enable()` POST 不带 take_over；grep 全 webui 无任何 `DELETE /api/v1/realtime/sessions` 调用；
  - 复现（/tmp/repro_reenable_409.py）：首次 POST→201，第二次 POST（模拟 disable 后/刷新后）→ **409
    "media session already has an active writer"** → 用户只会看到"实时语音会话建立失败"，无自愈路径。
- 测试盲区：`useRealtimeVoice.test.ts:65` fetchImpl mock 恒 `ok:true`，409 语义完全被 mock 掉。
- 修复建议：`disable()`/卸载时 fire-and-forget `DELETE /api/v1/realtime/sessions/{id}`（keepalive fetch），
  且 `enable()` 遇 409 时带 `take_over:true` 重试一次；补 disable→enable、刷新→enable 两条接线测试。

### P1-3 服务端音频运行缓存无字节/时间上限（RTM-RET-04 / D12 未实现）
- 证据：`src/llm_loop/realtime_session_runtime.py:196-206` `handle_binary` 只 extend `self._pcm`；
  仅 `:236-243`（commit 后）与拒绝路径清空；全文无 max_bytes/max_duration（grep 证实）。
- 违反：design.md:704/1006/1230（D12）"整段音频取自**有界运行缓存**（字节+时间双限，RTM-RET-04）；
  缓存溢出时明确暂停/降级"。长时间不发 commit 的连接内存无界增长（16k PCM16 ≈32KB/s，1h≈115MB/连接）。
- 修复建议：`_pcm` 增加字节+时间双限，超限发 `error{rate_limit/capacity}` 并丢弃最旧数据或暂停接收，
  补超限行为测试。

## P2 / nit（12 条，不影响 PASS 判定）

1. `realtime_ws.py:86-96 + realtime_session_runtime.py:198-206`：奇数字节二进制 → ValueError →
   连接被 except 关闭；design 要求"显式错误并拒绝该帧"。`test_unaligned_frame_rejected` 只断言 raises。
2. `keyframe_pipeline.py:70/133`：`share_start/share_stop/ingest` 接受 `source_epoch=0`，契约 §2.1 从 1 起。
3. `realtime_ws.py:138-147`：`payload.get("version") != 1` 对布尔 `True==1` 放行（epoch 同理）；
   未校验 seq/event_id 必填（契约 §1）；信封错误回执未带 `reply_to=event_id`（§1 要求）。
4. `realtime_session_runtime.py:268-273`：bind_commit 被拒（如 frame_already_bound）时音频已被清空，
   用户须重说；契约未明示该丢弃。
5. `keyframe_pipeline.py:388-396`：先写工作区文件再建 artifact 记录，`create` 抛错会遗留孤儿 png 并断连。
6. `keyframe_pipeline.py:785-806`：会话删除后 `KeyframeServiceRegistry._pipelines` 与 store 元数据
   （含 Expired 帧）不回收，长生命周期服务内存缓慢增长。
7. `visualShare.ts:447-451`：帧"已发送但被拒"（如 rate_limited）后仍更新 `lastSentB64`，静止画面后续
   同帧被当 identical 跳过 → 永无注册帧（低概率：客户端≥1s vs 服务端 0.2s 频控）。
8. `RealtimeVoiceBar.tsx:108-120`：按住说话仅 pointer 事件，无 `onPointerCancel`（触摸取消可能滞留按下态）；
   键盘用户无法按住（A11Y-05 部分覆盖）。
9. `useRealtimeVoice.ts:65 + Composer.tsx:66`：sessionId 取 `getState()` 非响应式；无会话时 fallback
   `"local"`，视觉 sink 会为不存在的 "local" 会话入队。
10. `visualShare.ts:408`：持续非频控拒绝（如 epoch mismatch）每帧一条 onNotice（1-2s/条）→ 提示刷屏。
11. `mediaSessionClient.ts:166-188`：下行 envelope 断言失败直接抛异常（onmessage 内未捕获）。
12. `playbackQueue.ts:31-46`：`onEnqueued` 注释称"成为当前或在队列追加后通知"，实际仅成为当前时回调
    （行为正确，注释不准）。

## 契约一致性（维度 4）

抽样全表比对 docs/M3-KEYFRAME-WIRE-CONTRACT.md §2.1(start 字段/epoch 语义)/§2.2(registered 字段)/
§2.3(stop epoch 必须等于当前登记值)/§2.4(committed 的 evidence_refs/task_ref/visual)/§3(stop 后 history 可用、
current 拒绝)/§5(拒绝码全集逐一对齐，含 session_closed、duplicate_frame_id)/§6(隐私)——客户端
`realtimeEvents.ts` REQUIRED_BY_TYPE、服务端实现与文档**一致**；仅 §1 的 seq/event_id 校验与 reply_to
有小缺口（P2-3）。

## 回归风险（维度 5，RULE-AI-24）

- Composer.tsx/realtimeEvents.ts/playbackQueue.ts 改动为**纯增量**（wiring.test.ts +110 行 0 删改，
  未削弱既有断言）；playbackQueue 构造器/`format` 均向后兼容；关闭实时语音时 hook 不订阅、零交互变化
  （有测试覆盖）；文本-only 路径 `input.commit` 不触发 sink（test_text_only_commit_never_touches_sink）。
- provider_adapter 签名放宽默认值不影响既有调用。未发现回归。

## 实际运行的命令与输出摘要

- 哈希核验命令（见上）：输出 `ae539549…9c77e4` ✅ 与期望一致。
- `.venv/bin/python -m pytest tests/realtime -q` → **329 passed** (0.89s)。
- `cd webui && npx vitest run src/core/realtime src/components/conversation/realtime` →
  **141 passed**（7 文件：sessionController 27、wiring 17、domWiring 13、m3Wiring 35、
  RealtimeVoiceBar 17、useRealtimeVoice 16 等）；`npm run typecheck` → **0 错误**。
- 两个 /tmp 复现脚本（不触碰仓库）：P1-1 输出 mismatch/False/UNDEFINED；P1-2 输出 201→409。
- 备注：tests/realtime/test_local_voice_stack_transport.py:199 有一条**条件性 pytest.skip**
  （本机 127.0.0.1:8000 无 mlx-audio 服务时跳过真机传输测试）——环境型跳过，可接受，如实记录。

## 测试质量（维度 6）

单元/接线层断言真实有效（严格事件序列、无伪造字段、失败路径与幂等覆盖良好）；无 xfail/@ts-ignore/
it.skip。系统性盲区有三：① 派发链 mock 断层（P1-1 测试止于 enqueue）；② REST 会话生命周期 mock
恒成功（P1-2）；③ 运行时音频缓存无超限测试（P1-3）。三者恰对应全部 P1。

## 诚实性（维度 7）

`web/__init__.py:228-242` docstring 与实现不符（见 P1-1）；其余注释/文档与实现抽样一致；
未验证项如实列于下节。

## 未覆盖 / 未验证项

- 未做真实浏览器联调（getDisplayMedia/AudioContext/扬声器；jsdom 之外的真机行为均未验证，
  代码自身也声明 RTM-EVD-06）。
- 未跑全量测试套件与 ci_gate（按纪律禁止）；server-fallback 60s 后 runner.start 的真实执行行为
  为静态读码+repro 推断，未长跑观察。
- 逐行精读：keyframe_pipeline.py、realtime_session_runtime.py、keyframe.py、visual_context.py、
  routes 派发相关段、上述全部 webui realtime 文件；**风险抽样**（非逐行）：realtime_ws.py 中段、
  media_session.py、micCapture/modality/capturePipeline 后半、audioPlayback 后半、
  m3Wiring/domWiring 测试主体、routes.py 未改动部分。
- 并发多连接共享 KeyframePipeline 的竞态只做了锁的静态检查，未压测。

## 复审闭环（2026-10-25，LFL 追加）

### 修复轮次与复审结论（审查者均为 GLM-5.3 独立只读子代理）
| 轮次 | 范围 | 结论 | 关键证据 |
|---|---|---|---|
| A | P1-1/P1-2/P1-3 | 已闭环 | 冻结 facts 直通派发；keepalive DELETE + 409 take_over 重试（上限 2）；pcm 双限（字节+时长） |
| B | P2-1/2/3/5/7/10 | 已闭环 | pytest tests/realtime 348 → 359 passed |
| C | P2-4/6/9 服务端 + P2-8/9b/11/12 前端 | 已闭环 | pytest 359 passed；vitest realtime 161 passed；typecheck 0 错误 |
| D | 新增 P2-9c（共享 identity/会话一致性） | 已闭环 | vitest 164 passed |
| **R1 复审（服务端半）** | runtime/pipeline/registry/ws/routes/契约 | **PASS**（P0=0,P1=0） | 6 条新 P2/P3，见下 |
| **R2 复审（前端半）** | realtime hooks/运输/UI | **PASS**（P0=0,P1=0） | 4 条新 P2/P3，见下 |
| E | R1/R2 的 7 项 | 已闭环 | 代次守卫、closed-record 守卫、shouldContinue、reconnectTimer/explicitlyClosed、AudioContext.dispose、catch 回收、注释 |
| **R3 聚焦复审** | 轮次 E 的 9 个文件 | **PASS**（P0=0,P1=0） | pytest 366 passed；vitest 172 passed；typecheck 0 |

### R1/R2 发现并已修的真实缺陷
1. **音频前缀删除竞态（P2）**：`_finalize_with_visual` 在 `await` 转写期间若缓冲被 413 清空，成功路径按 `len(segment)` 删前缀会吃掉新音频 → 引入 `_pcm_generation` 代次守卫，代次变化即跳过删除。
2. **take_over 不断旧连接（P2）**：registry 置 closed 但旧 WS 仍可 ingest → 收包循环内 `_record_closed()` 判定，命中后发 `error(409, session_closed)` + close(1000) + break。
3. **startShare 身份时窗（P2）**：`getDisplayMedia` 等待期间切会话会以旧 identity 上送 share.start/帧 → `startShare(shouldContinue?)` 在 resolve 后、上送前二次校验。
4. **重连僵尸 socket（P2）**：`close()` 未清重连定时器 → `reconnectTimer` + `explicitlyClosed` 双守卫。
5. **AudioContext 泄漏（P2）**：每次 enable 新建且不 close → `audioPlayback.dispose()` 于 disable/unmount 调用。
6. **enable 失败路径媒体会话泄漏（P3）**：`created.json()` 抛错时未 DELETE → catch 内尽力回收并清 ref。

### 仍未闭环（残留，非阻塞）
- `_record_closed` 读取 registry 私有 `_by_id`（fail-open 方向，建议改公共 API）。
- 服务端 409 未带机器可读 `reason`（前端按状态码重试，当前语义单一，无功能影响）。
- mediaSessionClient 测试注入式调度器与生产句柄映射不精确（测试侧）。
- `_finalize_with_visual` 中视觉拒收路径重复卫语句（无行为影响）。

### 全量门禁：未运行（本候选待最终门实测填充）
- 历史时点记录（2026-10-25 04:07–04:41，**非本候选**）：当时工作树同时含另一条工作流的**未提交安全加固批次**（security_guard、cache_guard、auth、escalation HMAC、fs delete token 等）仍在写入 → `review_admission` 冻结 sha 在 PASS 后数秒漂移，连续 4 次无法取得资格（reviewer_unavailable / 敏感模式命中）。
- 历史时点记录（隔离快照 = 当时 HEAD + 全部未提交改动，**非本候选**）：门禁审查员 **REVISE**——唯一 P1 为 `tests/guards/function_size_baseline.json` 未刷新而 `ExecuteCommandTool.execute` 170→约 368 行（属安全批次改动）；同时明确 realtime 改动逐项有回归测试、三个 P1 已真正修复。
- 现状（EVO-20261025-e0bff8ee）：安全批次已提交；R9 基线未刷新问题已由本分支（`fix/evo-e0bff8ee-p2-int-20261025`）guard(r9) 提交 `7e0ba341d` 全量重登记（execute 实测 553 行进 legacy）。本候选全量门禁 = **未运行**，数字待最终门实测填充——本文不引用任何历史数字冒充本候选结果。

### 本报告未验证边界（不可视为已验证）
真机探针（M0）、30 分钟长会话、真实设备弱网、真实屏幕共享帧率/延迟、视觉任务真实端到端执行、以及上述 4 条残留项。

