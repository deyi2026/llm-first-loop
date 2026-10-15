# Rule28 P0-C：最新 main 集成、物理入口覆盖与上线资格（2026-10-15）

## 基线和目标

- 上游 `main` 的**已提交**基线：`db4aaa8565ea0d0cc061b12e5701f5398b53698e`。此阶段在新 worktree `fix/rule28-p0c-current-main-20261015` 集成 P0-A 源码 `24a99fa26` 与 P0-B 源码 `7e4efb3dd`，不读取或覆盖主工作树他人未提交的内容。
- P0-A 是模型端“先独立审查”的明确义务；P0-B 是 Host 执行前对**已识别动作**的真实拒绝。不是 OS、任意 CLI 子进程或所有第三方渠道的通用沙箱。
- P0-C 要把可验证的漏拦/误拦分别测试，补最小必要的事实闸，不引入对普通代码编辑、查看、定向测试或协作子代理的普遍限制。
- P0-D 联合验证发现真实 22 文件集成补丁大于 128KB，Host 的 128KB 完整材料上限导致合法全量测试在审查之前即被拒绝（非模型裁决）。容量保持有界地扩到 **192KB**，155KB 完整材料正例与超过 192KB 拒签反例均由测试覆盖；不允许截断/分摘要伪装整包审核。

## 已识别的物理入口与证据类别

| 动作/入口 | 当前边界 | 资格与回归要求 |
|---|---|---|
| `ToolRegistry.execute → execute_command` | full pytest、非 quick ci_gate、已识别 git push 在真实 shell spawn 之前，由 HostReviewAdmission 校验 | 未审与过期 SHA 的动作必须 BLOCKED；定向测试/只读命令仍可调用；后台同入口 |
| `retry_tool` | `factory.py` 的 `correction_ctx.retry_executor` 调用 `registry.execute(_make_tool_call(...))` | 保留完整相同前置闸；此路径不应有独立直接 shell |
| `BrowserSemanticExecuteTool / browser_operate` | 经同一 `BrowserActionAdapter.execute` 到真实 actuator；仅对有文稿编辑器证据且明确 Publish/发表按钮的 `click` 门控 | 未审 actuator 0 次调用，真实 Reviewer PASS 后只放行一次；普通页面控件不误拦 |
| `dsh_task`/其他可启动进程的模型工具 | 独立 DSH 子进程及其自身权限约束，不经 `execute_command` 这道 Rule28 Gate | **未知或未覆盖**：不能宣称其内部 `git push` / 完整测试有 Rule28 同等级独立复审 |
| `service_control publish` | 代码部署而非对外文稿发表，不应误套文章审核 | 维持既有部署/用户授权门禁，不以文章 Reviewer 取代 |
| 未知脚本、`xargs` 的动态组合、直接 Git / HTTP / CDP 发布、网页表单 Enter/submit、其它网站/API | 非完整 shell 语义解释器、非 OS/第三方的原子防旁路 | 仅对能从当前明文命令证明的高信号动作做有界识别并拒签不可信间接执行；其余缺口显式记为未覆盖 |

## 新增的审查前回归

- `xargs -I{} git push`、`xargs -I{} python -m pytest` 不能以分段首词未命中为由在 `ToolRegistry` 无资格直通；也不得给不确定子命令签发错误工作目录资格。
- `pytest -k ''` / `python -m pytest -m ''` 不能被误判为真定向测试；非空明确筛选仍按小范围调用处理，不机械扩充为完整 R9。
- 校验真实 Factory 的 Full 和 Compact 模型工具列表均含 `review_admission`，命令工具和 ReviewAdmission 的 `workdir` 语义一致。
- 保留 P0-B 的真实独立 `SubAgentRunner` terminal/反 steer/一次性 SHA 和浏览器真实物理零派发测试；不复用旧 Reviewer 的 PASS 资格。

## 本阶段的硬性验收次序

1. 在隔离工作树集成最新 main → RED/GREEN + 邻接测试 + schema/误拦/覆盖表；
2. Ruff/Pyright、env-pin、安全扫描、源码冻结 SHA；
3. 新的**独立 GLM-5.3** 只读 Reviewer 核对**整个最新 main 集成补丁**、真实唯一 terminal、全文唯一一致的 P0/P1 计数、P0=P1=0、精确 SHA；失败必须 REVISE；
4. 仅在审核合格且其它任务没有正在跑的完整 CI 时，运行原生完整 `bash scripts/ci_gate.sh`；不能以旧分支 R9 冒充新集成 R9；
5. 仅在完成前述条件后在本隔离分支本地提交源码、复查 commit diff SHA；将脱敏回执和完整日志摘要另行本地提交。R9 自身引起的报告文件变更须精确归档后按白名单恢复。

## 生产上线 NO-GO 条件

- 当前 P0-B/P0-C 的“受保护入口集合”仍非**所有**可能实际执行 push / 全量测试 / 对外文章发布的入口，且独立 DSH/复杂 shell/部分网页/外部 API 的绕行未全部闭合；因此**不能宣称 Rule28 三闸已全域生产生效**。
- 即使本地真实 Reviewer 与完整 R9 全部 PASS，也只证明这份隔离补丁的开发资格。上线还需要：最新 main 差异检查与受控集成资格、明确用户授权、发布前检查 in-flight 会话和生产 Web/Feishu/Learning 进程绑定、Web-only canary 的真实拒绝与正常动作正反试验、受控回滚、再决定其它通道。
- 在上述证据不足时给出 **NO_GO_FOR_UNIVERSAL_PRODUCTION_GATE**，不得以文字“仅提醒不阻断”解除用户要求的独立审查义务，也不得凭此全面限制其它无关工具。
