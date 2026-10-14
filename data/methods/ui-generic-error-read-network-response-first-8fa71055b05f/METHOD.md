---
method_id: ui-generic-error-read-network-response-first-8fa71055b05f
name: ui-generic-error-read-network-response-first
description: 浏览器自动化（CDP）操作已登录 SPA 编辑器/后台时，若一次保存/发布/预览只得到无细节的通用 UI 错误（如『出现错误』），不要先枚举内容复杂度或 DOM 交互假设反复试错；应在重试前挂网络监听，直接读取该动作对应 API 的状态码与响应体。本集掘金侧先按内容/交互假设排查数轮（连最小 '# hello' 都同样失败），挂监听后一击定位 403 must bind phone——账号权限而非文章问题。UI 错误是有损投影，服务器响应才是权威失败记录。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:210fc8d0-2403-4baa-b382-986c0da37761:100:362cc61e7dfb265a51b7
evidence_refs: learning:learn:3bc9c9806667
created_at: 2026-10-13T23:58:55.030128+08:00
updated_at: 2026-10-13T23:58:55.030128+08:00
---
## Trigger
通过 CDP/浏览器自动化驱动已登录 SPA（富文本编辑器、创作后台），一次提交动作失败且 UI 只弹通用错误（无错误码、无细节文案），而同一连接即可启用网络监听（Network.enable / fetch 包装）。

## Discriminator
两个当时已知的事实：(1) 失败动作必然发出一个可观察的网络请求，UI toast 不含语义而响应体含；(2) 若最小 payload（如 '# hello'）也以完全相同方式失败，内容假设已被证伪——剩余唯一未读的权威事实就在网络层。无需多轮内容缩减/选择器试错后才发现。

## Short path
- 首次失败+通用 UI 错误 → 未知量定为『服务器到底拒绝了什么』，不先改内容/选择器
- 重试前挂网络监听（记录 url/status/body），重试同一动作一次
- 读对应 API 响应并分类：403/401+账号类文案=权限门（停自动化，转用户动作）；4xx 内容校验=修 payload；5xx/超时=平台侧稍后重试
- 把真实状态码+错误文案写入回执，向用户报告被阻真因（如 must bind phone 需用户验证码，不可代办）

## Stop conditions
- 已捕获失败动作对应请求的真实状态码与响应体，并足以归因（权限/内容/平台）
- 监听确认无对应网络请求发出（纯客户端校验）→ 停用本方法，转 console/DOM 调试

## Verification
- 确认捕获的请求与失败动作一一对应（时间与 payload 匹配），且响应错误语义能解释 UI 症状
- 归因为权限后不再做内容侧修改验证，避免在已证伪分支上继续消耗动作

## Counterexamples
- 纯客户端校验失败：请求根本未发出，网络层无记录，应看 console/DOM
- UI 错误弹窗本身已含完整错误码与原因，直接读它即可，无需挂监听
- 响应为 5xx/超时的瞬时平台故障：读 body 后应重试而非归因账号
- 无 CDP/监听权限的环境：退回最小复现+console 日志分层定位
