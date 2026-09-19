---
title: SMC Browser Phase 1 实测：大页 CDP 帧死锁链与三处接口不一致
scenario: SMC Browser Phase 1 工具（browser_perceive/browser_action/typed wait）挂载会话实测：小页全链路 PASS；10MB 大页触发 CDP 帧死锁链，且发现接口描述与实现不一致、轻量谓词错误依赖重量级观察
root_cause: ""
solution: 小页链路直接可用。大页恢复标准操作：shell CDP HTTP /json/new 开新 tab → /json/close 死 tab → .env LFL_BROWSER_PERCEPTION_TARGET_ID 写新 tab id → 服务 restart（需 code_root clean + dist sha 与 desired 一致，否则门禁拒）。正确调用形态：navigate 的 target_id=page scope_ref；object 动作 target_id=裸 el_id。轻量谓词在大页故障中不可用，不能作为等待恢复手段。
evidence: "evidence://v1/ec1b73e50ffd0945d424efa00cb2bb7651425044b02d81a24b0ca4a91ff533dd（navigate ok）; evidence://v1/7f5166f956de94fc0eb7cae0a5a5259a12860a883e18311a112be5da68b959a8（fill ok）; evidence://v1/170655ee180ebac5569401b2e47fdfe906996862c556af3462d92b827155b880（select ok）; evidence://v1/cde48f15a4e5fc1914fad23c07e649342a6162572bb3ee2a232803a991ed2261（click 后语义验证）; 大页死锁：本会话 19:55-20:02 五次失败回执（capture_channel_degraded / wait observer_error / target_ref_unavailable / bound target disappeared）; 门禁拦截：data/service-control-worker.log 20:04:22 rc=1"
tags: [browser-smc, cdp, frame-too-large, deadlock, interface-mismatch, predicate-degradation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T20:07:00.011317+08:00"
updated_at: "2026-09-18T20:07:00.011317+08:00"
---

## 实测链路（2026-09-18 晚，gen28，Chrome 153 loopback CDP）

### 小页全链路 PASS
snapshot→navigate(http)→fill("张三")→select(bj/北京)→click→re-observe：h1="已提交:张三/bj"、input value=张三、select value=北京。语义闭环成立，receipt 全程 running→ok 两段式，dispatch/diff grounding 落盘。

### 大页（10MB huge.html）死锁链 REPRO
1. DOMSnapshot.captureSnapshot 返回 47,305,327 字符 → ConnectionClosedError → capture_channel_degraded[frame_too_large]（错误语义诚实）
2. 同 target 重连成功但帧本身仍超管道（resp_chars 微差 1，确认是能力边界非重连失败）
3. **放大缺陷**：browser_wait_scope_url 等"轻量谓词"依赖完整 capture bundle（predicate.py L410 从 private_capture.scope_observations 读 url/readyState）→ capture 死则谓词全瘫 indeterminate
4. **死锁闭环**：snapshot 死 → semantic_execute 拒绝（需活 snapshot 的 exact ref）→ navigate 无法离开大页 → 模型侧工具族无恢复路径
5. 唯一恢复：shell 侧 CDP HTTP（/json/new 开新 tab + /json/close 死 tab）+ .env TARGET_ID 显式重绑 + 服务 restart

### 接口描述与实现不一致（重要）
- navigate：工具描述说 target_ref=resource_ref；实现（action.py L555）要求 target_id == page scope_ref
- object 动作：工具描述说 target_id=grounding_ref；实现版本校验（L1994）用 target_id 直接查 object_grounding dict，其键是裸 el_id（perception.py L650）→ 传完整 URI 必 rejected:target_not_in_expected_version
- snapshot_id 含 nonce（同页面两次 capture 内容 sha 相同但 id 不同）；navigate 的 version 校验实际靠 page_lineage_same(scope_ref,runtime_generation,page_generation)三元组而非 id 相等

### 建议
1. 大页捕获需分片/子树/节点数过滤（CDP captureSnapshot computedStyles 削减或 DOM.getDocument 深度限制），或在帧>阈值时降级为"AX-only 概要 snapshot"保证基础可用
2. url/readyState 谓词改轻量直读（Target/Page CDP 命令），不依赖重量级 capture
3. 工具描述三处修正或实现层做 URI→裸 id 解析 + navigate 接受 resource_ref
4. 死锁兜底：semantic_execute 在 capture 通道 degraded 时提供显式恢复动词（如 rebind/scope_reset）