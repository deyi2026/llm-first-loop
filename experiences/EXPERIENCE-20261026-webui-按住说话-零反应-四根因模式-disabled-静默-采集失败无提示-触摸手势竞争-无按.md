---
title: "WebUI 按住说话\"零反应\"四根因模式（disabled 静默/采集失败无提示/触摸手势竞争/无按压视觉）与修复接线法"
scenario: "WebUI 实时语音\"按住说话\"用户实测长按零反应；环境为 macOS 沙箱（execute_command workdir=REPO 才可写仓库）+ 分叉分支部署（live 0cd9c5248 / desired 829dd546 分叉，web restart 曾 failed）"
root_cause: ""
solution: "四根因逐一修复并全量回归：1) disabled 静默吞按压→aria-disabled+按压即时闪示原因(realtime-hint)；2) getUserMedia 失败无提示→micCapture 分类错误(not-allowed/not-found/not-readable)经 sessionController getter 透传，useRealtimeVoice 映射可操作文案走 realtime-error 展示；3) 触摸长按易断→pointerdown setPointerCapture + touch-action:none/user-select/callout 抑制 + contextmenu preventDefault；4) 按压零视觉反馈→接线既有 CSS 设计系统(data-recording/indicator 分态色/动态文案\"正在聆听…松开发送\")。部署：merge 分叉(fee62a5ff)→修复(be9413318)→publish gen 326。"
evidence: webui vitest 536 passed（新增按压反馈/指针捕获/重试连接/聆听文案 4 例）；后端 tests/web+tests/realtime 964 passed；git commit be9413318；service_control publish generation=326 回执 deployment_id=deploy-28bdebebf72f400381d6f406b6e0f4ca
tags: [webui, realtime-voice, push-to-talk, ux, pointer-events, touch, deployment, publish-gate]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T16:04:32.622778+08:00"
updated_at: "2026-10-26T16:04:32.622778+08:00"
---

## 根因（四类，系统性检查清单）

用户报"长按语音按钮没反应"，实测后逐层定位出四条独立根因，全部命中：

1. **disabled 静默吞事件**：按住说话按钮 `disabled={!canTalk}`，连接未 ready 时浏览器不派发 pointer 事件，零反馈。
   修法：改 `aria-disabled` + handler 内 guard，按下时闪示原因（"连接建立中/失败/会话结束"）。测试断言 `toBeDisabled()` 在旧 jest-dom 不识别 aria-disabled → 用 `toHaveAttribute("aria-disabled","true")`。

2. **异步资源失败无提示**：`getUserMedia` 权限/设备失败只返回 false，上层仅 setMicEnabled(false)，用户零感知。
   修法：micCapture catch 分类错误（NotAllowed→not-allowed 等）→ controller getter 透传 → hook 映射可操作文案（"请在浏览器地址栏允许麦克风"）→ 组件 role=alert 展示。**返回类型不变（boolean），用实例字段暴露错误，避免破坏测试 mock 契约**。

3. **触摸端手势竞争**：onPointerLeave 直接 release（手指微滑出按钮即断）；页面滚动触发 pointercancel；iOS 长按呼出菜单。
   修法：pointerdown `setPointerCapture(event.pointerId)`（jsdom 无实现须 `?.`）+ CSS `touch-action:none; user-select:none; -webkit-touch-callout:none` + `onContextMenu preventDefault`。

4. **零按压视觉反馈**：CSS 设计系统早已备好（data-recording 红边框、indicator 分态色、44px 触摸目标）但 TSX 从未接线。
   修法：接线 data-recording/data-state/分态类名 + 动态文案（"正在聆听…松开发送"）。**改 TSX 前先搜 tokens CSS：可能存在未接线的设计意图**。

## 排查路径（有效顺序）

用户"没反应"类投诉：① 按钮 disabled？→ ② handler 是否触发但异步失败无提示？→ ③ 触摸/鼠标事件是否被系统手势打断？→ ④ 触发了但无视觉变化（用户以为没反应）？四层都要看，单看代码 handler 存在就下结论会漏 2/3/4。

## 部署侧配套事实

- publish 前 webui/ 下不能有 untracked 文件（vitest 临时目录 .tmp-vitest 也会拦），发布前 `git status --porcelain webui` 检查。
- web restart 两阶段：先等 requester 会话（当前活跃的 web 对话）结束，再等目标空闲才执行。受理后 status=waiting_for_requester_exit 不是卡死；用户活跃期间 restart 排队，历史 stage_facts 的 failed 多属此类等待被记失败。
- 后端语音栈健康度：mlx-audio 8000 + POST /api/v1/realtime/sessions 返回 201 可作为"后端正常，问题在前端交互层"的快速分界探针。