---
method_id: spawn-brief-context-budget-when-child-whitelist-lacks-offload-821400c1cede
name: spawn-brief-context-budget-when-child-whitelist-lacks-offload
description: 只做编排的父代理无法自测工件规模时，子代理的上下文预算是 spawn 时唯一可控杠杆：白名单仅 read/search 且无 archive/持久化卸载工具时，子代理输入逼近窗口会被运行时正确拒绝静默截断而硬失败，整轮十万级 token 归零、零裁决。任务书必须同时写入（1）有界读取协议：先读主工件（diff/补丁），再只读其点名的文件与行区间，定位用窄检索，不做探索性宽读；（2）降级终态：证据不足时停止读取，输出任务契约已允许的证据不足裁决并列出已得发现与缺口，禁止猜测。二者保证任意窗口条件下都得到可用结算。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:48b09efd-a371-4a19-9375-ddf8ef5f28e9:0:6b36c8128eac579e06e9
evidence_refs: learning:learn:4c119f682ab2
created_at: 2026-10-19T08:42:20.803339+08:00
updated_at: 2026-10-19T08:42:20.803339+08:00
---
## Trigger
向后台子代理委派需读取大体量/多文件工件（补丁+相关源码+测试）的审查或分析任务，且 spawn 回执显示其工具白名单仅 read/search 类、不含任何上下文卸载（archive/分页/持久化）机制；或父代理自身被工具限制、无法预先测量读取集规模

## Discriminator
spawn 回执显式枚举的 tool_scope 无卸载工具（子代理只有『完成或硬失败』两条路），同时任务契约自身已定义证据不足时的合法裁决（如 REVISE）——降级输出是契约允许且当时已知的第三条路；配合读取目标为多工件、规模未知这两点，spawn 当时就足以把『随便读』缩成『预算内读+可降级』

## Short path
- 组任务书时先叠读取协议：先读主工件（diff/补丁），再仅读其点名的文件与行区间；定位文件用窄检索，禁止探索性全量读取
- 写入降级终态：若输入接近窗口或证据不全，停止读取，输出契约允许的证据不足裁决并列出已得发现与缺口清单，不得自信猜测
- 按规定参数 spawn，用回执核对精确模型与白名单确实生效
- 按合同轮询至真实终态：完整 verdict 或降级裁决均为有效结算，如实上报；失败且无降级输出则报告真实终态并停止，不自行代做、不原样重派

## Stop conditions
- 结算回执含契约有效裁决（含降级的证据不足裁决）→如实上报并停止
- spawn 被拒/模型不符/child 失败且无降级输出→报告真实终态并停止，不重派不代做

## Verification
- 结算回执的 tokens 与工具轨迹应显示有界消耗而非持续累积宽读
- 若子代理仍 near-window 硬失败，凭失败回执证明协议不足，申请拆分审查或更换更大窗口/带卸载工具的配置，而非原样重派同一任务书

## Counterexamples
- 白名单含 archive/分页/持久化工具（或 inherit 自带此类机制）时，预检存在卸载路径，预算任务书非必需
- 读取目标小且单一（单个小文件 diff）时，预算协议是多余开销
- 任务契约要求穷尽覆盖、无证据不足裁决（all-or-nothing）时不得教子代理降级，应拆分给多个子代理或先 renegotiate 范围
- 用户逐字固定了子代理任务书、无增写余地时，不得擅改任务书，应在 spawn 前把上下文超限风险报回授权方
