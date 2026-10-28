---
method_id: zero-effect-ui-events-check-disabled-gate-before-subsystem-diagnosis-44c4214fd44d
name: zero-effect-ui-events-check-disabled-gate-before-subsystem-diagnosis
description: CDP/自动化驱动 UI 交互（点击、pointer 按住-释放）回执成功但应用侧零效果（0 发送帧、状态文本纹丝不动）、且传输层已确认 open 时，第一未知量不是麦克风权限、tab 冻结等子系统/环境假设，而是『事件是否到达了活的、未禁用的 handler』：disabled 元素会静默吞掉合成 pointer 事件。先用一次 evaluate 读 element.disabled / 组件门槛实态（本集为 connectionState!=='ready' 使按钮 disabled，源码 disabled={!canTalk}），把状态推过门槛再重跑探针；仍零效果才进子系统诊断。配套纪律：WS 记录器用 prototype.send 级 hook 且先于 reload 注入（否则自动重连的既有实例逃逸记录）；gUM 类可能挂起的页面调用必须带超时包裹；复杂 CDP 脚本写临时文件而非 node -e 内联。
aliases: CDP点击没反应先查disabled, 自动化按钮点击零效果排查, 合成pointer事件被静默吞掉, 按住说话没反应怎么查, 前端按钮状态机门槛未满足, UI事件没触发handler先看禁用
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:4053:cd864faa7405d7ca4c9e
evidence_refs: learning:learn:ba113dd4d418
created_at: 2026-10-26T11:48:57.415742+08:00
updated_at: 2026-10-26T11:48:57.415742+08:00
---
## Trigger
自动化/CDP 驱动的 UI 交互（点击、pointerDown/Up 序列、dispatchEvent）执行回执成功，但应用侧零效果：无 WS/网络帧发出、状态节点文本多次采样完全不变；而底层传输已确认通畅（WS 已 open、HTTP 201/200）

## Discriminator
目标元素在 DOM 中的交互门槛实态：element.disabled===true 或组件状态机前置条件未满足（本集 connectionState!=='ready' → disabled={!canTalk}）。disabled 元素静默吞掉合成事件；交互前或零效果后一次 evaluate 读 btn.disabled/aria-pressed/data-state，即可把『事件根本没到 handler』与『子系统（麦克风/权限/环境）故障』二分开，不必枚举子系统假设

## Short path
- 驱动交互前先读目标元素门槛实态（disabled/aria-pressed/状态节点文本），确认 live 再派发；未知量：控制件此刻是否真的可交互
- 零效果时先重读这一门槛实态而不是枚举子系统/环境假设；若 disabled → grep 组件源码中 disabled={...} 的门槛条件，把状态推过门槛（等待/重连/enable）后再交互
- 门槛通过后重跑交互探针；此时仍零帧才进入子系统诊断（gUM/权限/冻结），且 gUM 类挂起调用必须带超时包裹
- 流量记录器用 WebSocket.prototype.send 级 hook（能捕获已存在实例），并在任何 reload 之前注入，避免页面自动重连的实例逃逸记录
- 帧计数>0 且服务端事件可见即停止诊断

## Stop conditions
- 按钮 enabled 且交互产生帧/状态变化、服务端消息可见
- 确认元素无门槛且页面日志显示 handler 已触发 → 转入子系统或事件派发方式分支，不再查门槛

## Verification
- 交互前后各读一次 btn.disabled/门槛状态并对比
- 事件后状态节点文本变化或 WS out 帧计数 >0
- 若靠源码定位门槛，核对 DOM 实态与源码 gating 条件一致

## Counterexamples
- 交互有部分效果（状态先变化再卡住）→ 门槛已开，直接查子系统，勿再查 disabled
- 元素无 disabled 门槛且日志显示 handler 已进入 → 可疑点是事件可信度/派发方式（isTrusted），应换 CDP Input 而非 dispatchEvent
- 按钮 enabled 且帧在发、只是服务端无回包 → 是服务端/链路问题，不是交互门槛
- 非 UI 的纯协议客户端调用零响应（无元素层）→ 本方法不适用
