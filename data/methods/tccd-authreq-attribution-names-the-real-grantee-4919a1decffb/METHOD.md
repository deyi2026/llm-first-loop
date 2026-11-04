---
method_id: tccd-authreq-attribution-names-the-real-grantee-4919a1decffb
name: tccd-authreq-attribution-names-the-real-grantee
description: macOS TCC 类权限（辅助功能/屏幕录制等）被静默拒绝、用户在设置列表找不到对应条目时，不要在请求方反复换姿势探测或考古部署方式：从目标二进制触发一次真实访问后，直接读授权方 tccd 的决策日志——AUTHREQ_ATTRIBUTION 的 responsible/accessing/requesting 三元组直接给出权限记在哪个 App 名下，同日志的 entitlement 报错解释 prompt 为何静默短路。请求方的布尔信任接口可能假阳性，只有真实 AX 调用的错误码（-25204=kAXErrorAPIDisabled）才是权威判定。
aliases: mac 隐私设置里找不到要勾的那一项, 系统权限到底算在谁头上, 为什么勾的是终端不是 python, AX 被禁用错误怎么定位, 等不到授权弹窗
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1421:58c6b606c652fcaf84af
evidence_refs: learning:learn:b940d1d28241
created_at: 2026-11-04T15:40:48.562171+08:00
updated_at: 2026-11-04T15:40:48.562171+08:00
---
## Trigger
macOS 上脚本/解释器类进程的 TCC 权限静默失败：权威状态回执 ax_trusted=false 且 ax_error 为空、真实 AX 调用报 -25204/-25205，用户报告设置面板没有对应条目、或等待 prompt 对话框始终不出现，需要回答『用户到底该给哪个 App 开权限』

## Discriminator
布尔探测与观测当场矛盾：prompt=1 申请瞬间返回 True 却没有任何对话框、宿主状态仍报未授权。该矛盾本身证明请求方接口不可信；而 tccd 对每次请求都记录 AUTHREQ_CTX/AUTHREQ_ATTRIBUTION，其 responsible 的 identifier/pid 一次性回答『记在谁名下』与『为何不弹框』两个未知量，无需先排除沙盒/launchd/签名等备择假设

## Short path
- 用权威状态回执确认拒绝为静默（ax_trusted=false、ax_error=null）；未知量：是否真的被拒
- 从目标运行时二进制发起一次真实 AX 调用（如 AXFocusedApplication），以错误码 -25204 确认 API 被禁；不采信布尔信任接口；未知量：拒绝的具体形态
- 立即用 log show 查 tccd 近几分钟记录，读 AUTHREQ_ATTRIBUTION：responsible 的 identifier/pid 即用户该去设置的 App，同段 entitlement 错误解释 prompt 短路原因；未知量：授权对象是谁、为何不弹框
- 把 responsible App 的精确设置路径交给用户；用户操作后复跑第 2 步，错误码 -25204→0 即闭环

## Stop conditions
- tccd 日志已给出 responsible 归属且向用户指明对应设置条目
- 复验真实 AX 调用返回 0（不再出现 API disabled 错误码）

## Verification
- 归属结论必须引用 tccd AUTHREQ_ATTRIBUTION 原文且 accessing 的 binary_path 与目标运行时吻合，而非从进程树/签名推断
- 授权前后同一真实 AX 调用错误码发生变化才宣布修复

## Counterexamples
- 规范签名的 .app 首次申请会正常弹框，走标准用户流程即可，无需日志取证
- 请求从未到达授权方（日志无 AUTHREQ 条目）：问题在触发前置条件而非归属，须先制造一次真实访问再读日志
- 日志关键字段被 <private> 脱敏（受管设备 profile）：归属不可读时回退到 codesign/bundle 假设验证，而不是反复换谓词重查
- 非 macOS 或授权方没有可查询的决策日志：方法退化为读授权方文档/规范
