---
title: 冻结契约与当前程序事实冲突：以当前事实勘误契约
scenario: "tool_octet_observation 线 M2 评审发现已冻结 M1 spec 与仓库事实冲突：\"blocked=DuplicateGuard 预执行阻断\"假设不成立——ToolResultStatus.BLOCKED 另有破坏性安全守卫/EXEC_MODE 权限/monotonic guard/post-hook/web_fetch SSRF 私网阻断等来源，均经正常 _record_single_receipt 路径产生、有真实 duration 与结果内容；若按原 spec 落码，八元组将对这类 blocked 记下 duration_ms=null/result_digest=null 的错误事实。"
root_cause: "冻结流程激励\"文档不再动\"，把文档稳定误当文档正确；当上游事实模型（状态枚举的真实来源集合）比评审时假设更宽，冻结文档即失真——唯一修复方向是勘误契约，不是让实现迁就错误假设。"
solution: "冻结契约与真实程序事实冲突时：修改契约（补勘误条款），不为\"已冻结\"强迫程序迎合错误假设；勘误≠重开评审，M1 保持 PASS。衍生口径：①观测 digest 必须哈希完整语义内容——先截 4KB 后哈希会制造\"前 4KB 相同+尾部状态不同\"的共谋碰撞，恰好污染未来 actual_result_changed/same-call/no-progress 证据；②dict 参数 canonicalize（json.dumps sort_keys=True）后再哈希，否则键序不同被误判为两次调用；③digest 是 one-way 摘要而非安全脱敏边界，文档不得称\"不可逆脱敏\"；④无消费面的计数器不建状态（选删除而非补接口）；⑤独立数据流仍复用既有 audit sink，单一 writer SoT；⑥观测字段（round_index）显式形参下传，不新建 contextvar。"
evidence: 镜像区 .codeartsdoer/specs/tool_octet_observation/spec.md（勘误块 2026-09-03 M2 R1，M1 保持 PASS）与 design.md（R1 七项修订 + 勾稽表）；主区核实无本线文件。
tags: [架构决策, 冻结契约, 勘误, 观测流, tool_octet_observation, 镜像区工作面]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-03T08:31:55.291989+08:00"
updated_at: "2026-09-11T19:55:09.647912+08:00"
last_verified_at: "2026-09-11T19:55:09.647912+08:00"
---

用户原话（裁决）："冻结不是为了保护旧设计不被修改；发现冻结契约和真实程序事实冲突时，应修改契约，而不是为了'已经冻结'强迫程序迎合错误假设。" 落地记录：M1 保持 PASS 仅补勘误；M2 R1 七项修订（BLOCKED 拆分/canonical args/全语义 digest 32hex/round_index 显式下传/audit sink 单一化/计数器与 ts 清理/T5a+T5b+T7 混合批次）当日落稿并按裁决冻结。另记工作区纪律：所有文件操作经核实仅落镜像区 /Users/yyj/Project/llm-first-loop-mirror，主区 /Users/yyj/Project/llm-first-loop 属其他 spec 目录不写入。

当前适用性说明：该记录中的 DuplicateGuard 仅是 2026-09-03 被证伪的历史假设，不代表当前 runtime 存在或应恢复该机制。