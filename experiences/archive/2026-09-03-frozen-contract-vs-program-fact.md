# 经验：冻结契约与程序事实冲突时，修改契约而不是强迫程序迁就

## 场景
tool_octet_observation 线 M2 评审发现已冻结 M1 spec 的"blocked=DuplicateGuard 预执行阻断"假设与仓库事实冲突：`ToolResultStatus.BLOCKED` 另有破坏性安全守卫、EXEC_MODE 权限阻断、monotonic guard、post-hook block、web_fetch SSRF 私网阻断等来源，均经正常 `_record_single_receipt` 路径产生、有真实 duration 与内容。按旧假设落码会让八元组留下错误事实。

## 根因
冻结流程天然激励"文档不再动"，把"文档稳定"误当"文档正确"；当上游事实模型（状态枚举的真实来源集合）比评审时假设更宽，冻结文档即失真，唯一修复方向是勘误契约。

## 解法
- 冻结契约与真实程序事实冲突时：补**勘误条款**，勘误 ≠ 重开评审（M1 保持 PASS），绝不为"已冻结"强迫程序迎合错误假设；
- 衍生口径（R1 全部落稿验证）：①观测 digest hash 完整语义内容，hash 前绝不截断（先截 4KB 会制造"前 4KB 相同+尾部不同"共谋碰撞，污染 actual_result_changed / no-progress 证据）；②dict 参数 canonicalize（json.dumps sort_keys=True, ensure_ascii=False, separators=(",",":")）再 hash；③digest 为 one-way 摘要，非 secret-redaction/安全边界；④无消费面的计数器不建状态（裁决选删除）；⑤独立数据流 ≠ 独立 writer，复用既有 audit sink 单一 SoT；⑥round_index 等观测字段走显式数据流，不建新 contextvar。

## 证据
- .codeartsdoer/specs/tool_octet_observation/spec.md 勘误块（2026-09-03 M2 R1，M1 保持 PASS）
- 同目录 design.md R1 修订（BLOCKED 拆分 / canonical args / 全语义 digest / round_index 显式下传 / audit sink 单一化 / T5a+T5b+T7 混合批次）
- 工作区纪律：本仓库一切文件操作用镜像区 /Users/yyj/Project/llm-first-loop-mirror，不写主区（用户 2026-09-03 明确指令）
