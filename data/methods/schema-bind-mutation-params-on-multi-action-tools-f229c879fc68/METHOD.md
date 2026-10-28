---
method_id: schema-bind-mutation-params-on-multi-action-tools-f229c879fc68
name: schema-bind-mutation-params-on-multi-action-tools
description: 对多 action 控制面工具发起本会话首次 state-changing 调用（restart/publish 等）前，参数契约的唯一权威是 get_tool_schema，不是记忆、也不是同工具相邻 action 的字段：本集 restart_target 属 update，而 restart 必填 target，凭交叠记忆猜名导致一次契约拒绝。先读一次 schema 绑定 action→必填/enum 字段，配最新 status 观察值一次构造完整调用；被拒时按回执 missing 清单一次性修正全部字段，不逐字段试探。受理≠完成：按 action_id 查一次状态，若门禁含 requester 会话结束则本轮停止，登记下次会话验证。同类教训：具体路径/参数名这类未核实细节不得进入 mutation 调用或对用户的断言（/root/... 假路径与 restart_target 同源翻车）。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7f2be023-db54-4395-9854-c784b5295062:449:8257e88e28103cb30047
evidence_refs: learning:learn:34dc750b14c7
created_at: 2026-10-20T12:59:17.637552+08:00
updated_at: 2026-10-20T12:59:17.637552+08:00
---
## Trigger
即将对同一工具名下多个 action 各有不同/交叠参数契约的控制面工具，发起本会话首次 state-changing 调用；或已收到『参数契约不满足: missing=<field>』类回执。

## Discriminator
本会话任何回执中都未出现过将要使用的参数名（它只存在于记忆或相邻 action 的 schema 段），且目标是不可轻易撤回的 mutation——这一可观察缺口用一次 get_tool_schema 即可闭合；契约回执本身也显式提示该出口并要求一次性修正全部字段。

## Short path
- 确认 mutation 前置事实（进程 cwd/editable pth/git 状态），明确这次调用会作用于哪个部署面
- 本会话未读过该工具 schema 时，先 get_tool_schema(tool) 一次，绑定本 action 的必填字段与 enum（未知量：这个 action 到底要哪些字段）
- 用 schema 字段 + 最新 status 观察值（如 expected_generation）一次性构造完整调用并发出
- 若仍被契约拒绝：按回执 missing 字段清单一次性修正全部字段后重发，禁止逐字段试探
- 受理后按回执给出的终态入口查一次状态；门禁含 requester 会话结束则本轮终止，把 action_id 与验收项移交给下次会话

## Stop conditions
- mutation 调用被受理（拿到 action_id/generation），且后续验证入口已明确
- schema 已读且与本次调用字段一致，不再重复读 schema

## Verification
- 发出的 mutation 参数逐字段对照 get_tool_schema 核对
- 重发一次即被受理，无第二次同类契约拒绝
- 受理回执的 action_id 可在 status 入口查到非终态事实（如 waiting_for_requester_exit）

## Counterexamples
- 本会话已多次成功调用同一 action 且契约稳定（如只读 status）：预读 schema 是纯开销，直接调用
- 失败回执是传输层瞬时错误（timeout/5xx）而非契约错误：修法是重试，不是读 schema
- 单 action、签名平凡的工具：按注册说明直接调用即可，无交叠字段可混淆
- 读 schema 后环境契约已变（工具热更新）：以当前回执为准重新绑定，不沿用旧 schema
