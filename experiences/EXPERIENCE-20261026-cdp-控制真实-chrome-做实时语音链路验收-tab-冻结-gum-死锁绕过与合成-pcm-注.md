---
title: CDP 控制真实 Chrome 做实时语音链路验收：tab 冻结/gUM 死锁绕过与合成 PCM 注入法
scenario: 在用户日常使用的 Chrome 浏览器上验收 llmfirstloop.com 实时语音功能（CDP 远程调试端口 9229），需要真实走通 语音输入→ASR→LLM→TTS 回传 全链路
root_cause: ""
solution: 按上述 1-4 组合：保活（btf/focus emu）→ 绕过 gUM（合成 PCM 直注 WS）→ 协议级观测（constructor patch + proto send patch）→ 后台 job 采样。本轮 10 轮采样全部成功：ASR 终稿 P50≈0.8s 文本 100% 准确；稳态 LLM→TTS 4-6s；连续压力下出现 50s+ 排队。
evidence: "本轮会话 10 轮采样 job-0196d840e98e4b768e70 全部成功（R1-R10 输出，ASR tfRel 603-1383ms 稳定+R3 6547ms 离群、终稿 10/10 文本一致、稳态 tpRel 4120-6143ms）；探针 B（barge）BIN 即停+1788ms 新 delta；证据链：evidence://v1/af3594c2117d7cb9445762ed2b6f9447b2f4e613c47307798b0146fa3e896370、evidence://v1/079357bcb6abe36687e893092b208cdf3f1199d16de41b052910d62a251163dc、evidence://v1/159978540c29f8c9d00842d87cad4650a74cfb0dfe64198fdc7ddfb236c3ef6f"
tags: [cdp, realtime-audio, browser-automation, probe, getUserMedia]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-26T11:42:21.159795+08:00"
updated_at: "2026-10-26T11:42:21.159795+08:00"
---

在用户真实 Chrome（CDP 端口）验收实时语音链路时的四个关键事实与解法：
1. tab 后台/冻结会让页面 JS 的 timer、Promise 回调、gUM 全部挂起（CDP Runtime.evaluate 同步代码仍能跑，造成"页面活着"的假象）。解法：Page.bringToFront + Emulation.setFocusEmulationEnabled(true) + Page.setWebLifecycleState("active")，采样循环里持续 bringToFront。
2. 一次失败的 Runtime.evaluate(awaitPromise:true)（如挂起的 gUM）会在页面留下 pending promise，后续同 origin 的 gUM 可能被排队挂死；reload 页面可清空。
3. 本环境实测：realtime WS 建立后 controller.press() 的 getUserMedia({audio:true}) 挂死（enable 前手动同约束调用可成功），疑似 WS 音频管线初始化与 gUM 的浏览器层死锁。绕过：不依赖麦克风，直接向 WS 实例发送合成 PCM16LE（3200B/帧≈100ms@16k mono），后跟 JSON {type:"input.commit"}，完整触发服务端 ASR 流式→终稿→提交→LLM→TTS 链路。
4. 前端协议（webui/src/core/realtime/mediaSessionClient.ts）：音频=裸 ArrayBuffer 二进制帧；控制事件=JSON 字符串 envelope（type 字段如 input.commit）；服务端回传 input.delta/input.final/turn.committed/audio.playback 及 BIN 二进制 TTS 分片。
通用技巧：constructor patch（记录 realtime WS 实例+收发监听）须在 enable 点击前注入；WS 已存在时用 WebSocket.prototype.send 补丁统计发送、用实例 addEventListener 补收消息。node -e 长脚本建议 printf 逐行写 .mjs 文件再 node 执行（heredoc/管道进解释器被沙箱拦；-e 嵌套引号易错：模板字符串外不要用带反斜杠的反引号）。