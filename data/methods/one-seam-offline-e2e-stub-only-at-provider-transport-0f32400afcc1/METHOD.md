---
method_id: one-seam-offline-e2e-stub-only-at-provider-transport-0f32400afcc1
name: one-seam-offline-e2e-stub-only-at-provider-transport
description: 任务书要求在真实多层链路（HTTP route→后台runner→engine→LLM client）上补『唯一一项最小无网端到端正测、零真实外部provider』且允许不合理时退回分段证据时：可行性先由两段既有分段测试的替换点导出——链路中唯一离线不可真实化的环节是provider网络流；若源码中它收口于一个窄transport函数，则只monkeypatch这一个函数喂合成SSE，route/runner/engine/client全部保持真实，断言跨层持久化事实（帧序、provider轮数、ledger全settled、分配值、receipt_ref前缀）而非仅HTTP回执。单seam打不通（解析与传输耦合）则按委派退回分段证据+缺口说明，不扩面。
aliases: 无网贯通测试在哪一层打桩, 零真实provider的端到端正测, 合成SSE喂真实LLMClient, 两段分段测试合并全链路贯通, 最小离线e2e不打真实LLM
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:76ea82c8-bf63-4e1e-b120-1356b5ee8071:0:9155d0b46fb4f8c9681d
evidence_refs: learning:learn:834128ce635b
created_at: 2026-11-14T08:39:42.894909+08:00
updated_at: 2026-11-14T08:39:42.894909+08:00
---
## Trigger
委派/验收要求在贯穿多层的真实链路上只补一项最小无网端到端正测（真实TestClient→真实后台runner→engine→真实LLM client解析，零真实外部provider），且明确允许『技术上不合理时给出分段证据与缺口、不要扩面』

## Discriminator
既有两段分段测试各自暴露了替换点（一段在runner.start处spy、一段在client边界用FakeSSE）——由此可知唯一无法离线真实化的只有provider网络流；可行性判据=该流是否在源码中收口于一个可monkeypatch的窄transport函数，而client的SSE解析仍走真实代码

## Short path
- 读两段既有分段测试，列出各自fake/spy的注入点与覆盖终点（谁被替换、替换发生在哪一层）
- 直读链路源码的调用边（route handler→runner→engine→client），定位provider SSE流进入系统的最窄函数
- 写一条正测：真实TestClient发起请求→真实BackgroundRunner/daemon线程→真实engine→真实client解析，仅对provider transport函数打桩返回合成SSE
- 断言跨层持久化事实：帧序零error、provider轮数、产物落盘、ledger全settled、分配数值、receipt_ref前缀等
- 复跑核对：打桩面积恰为1处且位于网络边界、零真实外呼、原分段测试保留互补（原spy点不再spy）

## Stop conditions
- 已找到单一transport函数且替换后全链路真实 → 写测、跑绿即收，不再扩第二项测试
- provider解析与传输在同一函数强耦合、或后台链路无持久化终态可断言 → 按委派退回分段证据+缺口说明
- 链路某层已有全真集成测试覆盖 → 只补缺失层，不强行贯通

## Verification
- 测试断言包含非HTTP回执的持久化跨层事实（ledger/EventStore/落盘产物），而非仅响应帧
- 逐项核对真实组件清单（route/runner/engine/client）确实未被替换
- monkeypatch点数量=1且在网络边界；离线沙箱下运行确认零真实外呼

## Counterexamples
- 委派要求socket级真实服务或禁止monkeypatch → 应改用本地fake provider HTTP server，本方法不适用
- 两段既有测试替换的是同一层（无互补注入点信息）→ 无法推断唯一边界，需直读源码或退回分段证据
- 链路含测试沙箱外的真实副作用（部署、真实外部账号）→ 单seam不足以保证无网，属必须拒绝贯通的场景
