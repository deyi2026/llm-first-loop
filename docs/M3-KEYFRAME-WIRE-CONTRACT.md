# M3 关键帧 WS 契约（docs/M3-KEYFRAME-WIRE-CONTRACT.md）

适用：`WS /api/v1/realtime/sessions/{media_session_id}/events`（既有控制通道，不新建连接）。
服务端实现：`src/llm_loop/realtime/keyframe_pipeline.py` + `realtime_session_runtime.py`。
帧字节只进 `WorkspaceArtifactStore`（`artifact://v1/<32hex>`）；元数据进 `KeyframeStore`。

## 1. 通用上行信封（所有本契约消息必填）

```json
{"version":1, "type":"visual.share.start", "event_id":"<uuid>", "seq":<int>,
 "connection_epoch":<int>, "session_id":"<str>", "media_session_id":"<str>", ...}
```

- `version` 必须 `1`；`connection_epoch` 必须等于创建会话时返回的当前 epoch；
  `media_session_id` 必须等于 URL 中的会话 id。任一不符 → 下行 `error`（code 见 §4），**不产生任何副作用**。
- `event_id`/`seq` 由客户端自定（建议单调递增 seq）；服务端在回执中原样带回 `reply_to=event_id`（若提供）。
- 连接鉴权 = 既有 WS 握手（cookie `web_sessions` + Origin 白名单），无额外头。

## 2. 上行消息（type 分支）

### 2.1 `visual.share.start` — 用户显式开始共享某来源
字段：`source_id`（`[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`，稳定标识，如 `tab-main`）、
`source_epoch`（该来源代次，从 1 起增；页面刷新/重共享必须 +1）、`label`（可选，≤128 字符，人类可读名）。
服务端：登记活动源（allowlist，未登记源的帧一律拒绝）。同 id 同 epoch 重复发 = 幂等（`resumed:true`）；
同 id **新 epoch** = 旧帧当前有效性失效（变 Stale，仍可作 history 证据）。
下行：`visual.share.started` `{source_id, source_epoch, resumed}`；失败下行 `error`。

### 2.2 `visual.frame` — 上送一帧
字段：`frame_id`（客户端生成，同上标识符规则，**同帧重发幂等**）、`source_id`、`source_epoch`、
`captured_at_ms`（客户端单调时钟毫秒，仅用于帧龄计算，服务端不做墙钟换算）、
`width`/`height`（正整数，≤32768）、`mime`（`image/jpeg|image/png|image/webp`）、
`data_b64`（base64；解码后 ≤512KB；魔数必须与声明 mime 一致）、
`selection`（可选 `{x,y,width,height}` 像素选区，正宽高）。
下行成功：`visual.frame.registered` `{frame_id, content_ref, sha256, path, received_at_s}`。
下行失败：`visual.frame.rejected` `{frame_id?, reason}`（§5 错误码；**不含内部细节/媒体体**）。
建议采样 0.5–1fps；服务端硬限同源两帧 ≥0.2s，超限 `rate_limited`。

### 2.3 `visual.share.stop` — 用户停止共享
字段：`source_id`、`source_epoch`（须等于当前登记 epoch，否则 `source_epoch_mismatch`）。
效果：该源帧当前有效性失效（Stale ≠ 删除）：`current` 指代不再可用，`history` 指代仍可绑定回读。
下行：`visual.share.stopped` `{source_id, frames_staled}`。

### 2.4 `input.commit`（扩展既有消息）
```json
{"version":1,"type":"input.commit","event_id":"...","seq":2,"connection_epoch":1,
 "session_id":"sess-1","media_session_id":"ms-...","visual":{"source_id":"tab-main","kind":"current"}}
```
- `visual` **省略或为 null** → 完全走既有行为（input.final + turn.committed，零变化）。
- `visual.kind` ∈ `"current"|"history"`，**仅是提示**：终稿文本中的指代优先——含
  「刚才/上一页/前面那页/刚才那张」等历史指代按 `history` 解析，含「现在/当前/这页/屏幕上」
  按 `current`；无指代词沿用 kind 提示；**同时含两侧指代** → `visual.clarify`。
- 绑定成功 → 下行 `input.final`（带 `"visual": true`）+ `turn.committed`（新增字段 `evidence_refs:[content_ref...]`、
  `visual:[{frame_id,source_id,source_epoch,kind,content_ref,path,sha256,mime,width,height,...}]`、
  `task_ref`）；视觉证据以独立结构化注记传递到任务输入，**不修改用户原文**。
- 服务端 commit_sink（复用现有 Web 任务提交入口 HumanTurnQueue）未装配 → `error`
  （503 `task_submit_unavailable`）或提交异常 → `error`（503 `task_submit_failed`）：
  **均不伪造 turn.committed**，音频保留（未装配分支）或如实报错。
- 候选缺失/歧义（无当前帧、来源未共享、帧已到期等）→ 下行 `input.final` + `visual.clarify`
  `{turn_id, question}`；**不派发任务**。
- `visual.source_id` 从未登记 → `error`（409 `unknown_source`），**不回退到任意最新帧**。
- 同一帧已绑给其他 turn（绑定互斥）→ `error`（409 `frame_already_bound`）。

## 3. 时序

`visual.share.start → visual.frame… → input.commit{visual} → visual.share.stop`
（history 指代可在 stop 后使用；会话 `DELETE /api/v1/realtime/sessions/{id}` 后全部帧到期，
回读明确失效）。WS 断开 = 全部活动源隐式 stop（Stale，保留）。

## 4. 错误事件（下行 `error`）

`{code:409, reason}`（信封不匹配/epoch 过期/未知来源/重复绑定）或 `{code:503, reason}`（服务端视觉链未装配/任务提交不可用）。
reason 为 §5 之一或 `stale_epoch|wrong_session|unsupported_version|malformed_envelope|visual_unavailable|task_submit_unavailable|task_submit_failed`。有界、可枚举、无内部细节。

## 5. `visual.frame.rejected.reason` 错误码

`unknown_source`（未 share.start）｜`source_not_active`（已 stop）｜`source_epoch_mismatch`｜
`mime_unsupported`（含魔数不符）｜`frame_too_large`（>512KB）｜`rate_limited`（同源 <0.2s）｜
`cache_full`（RET-04 防御码：容量满时服务端自动淘汰**最旧未绑定**预览帧，**已绑定帧永不淘汰**；
仅无可淘汰者时出现，正常策略下新帧总是被接受或触发最旧预览淘汰）｜
`duplicate_frame_id`（同 id 不同字节）｜`malformed`（字段非法）｜`session_closed`。

## 6. 客户端义务

1. 只上送用户显式选择的共享源帧（权限/V8 面板确认），不采集未共享来源；
2. `source_epoch` 随页面刷新/重新共享严格递增，帧消息始终带当前 epoch；
3. `frame_id` 会话内唯一；网络重试用同 id 同字节（幂等）；
4. 收到 `visual.clarify` 必须先向用户澄清，不得自行猜测 source/kind 重发；
5. 日志/UI 不得记录 `data_b64` 或解码画面内容（RET-05）；
6. `input.final` 带 `"visual": true` 时**不得在本地再提交同一终稿**（任务已由服务端
   commit_sink 经既有 Web 任务入口派发），只等待 `turn.committed` / `visual.clarify` /
   `error`（含 503 `task_submit_unavailable|task_submit_failed`）后按结果处理；
   文本-only 的 `input.final` 不带该字段，客户端行为不变。
