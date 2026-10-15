# Rule28 P0-D 受控 Web-only canary —— 待授权 Runbook

> 状态：**未授权执行**。此文档仅定义精确资格步骤，不能当作 merge、push、publish、restart 或真实 Provider/副作用授权。

## A. 发布前四把锁（任一失败即 NO-GO）

1. **版本身份**：重新读取 `main`、目标候选、本机 Git/Diff 当前 SHA；先做隔离合并、独立 GLM-5.3 Review P0/P1=0 + 原版 full R9 对**即将发布的最终合并树**再次取证；不得用旧 SHA 或本阶段的单独隔离 R9 替代。
2. **权限与 reviewer**：Code Reviewer 仅证明代码资格；对实际 `git push` 应另由真正独立 Push Reviewer 审核准确 remote/ref，且取得用户授权；程序的 release 权限独立于文稿审核。绝不自动化未授权 push。
3. **并发稳定性**：读取 live Web/Feishu/Learning runtime manifests、部署 generation/commit/PID、活跃主会话/子代理、in-flight 工具动作、Learning queue。若存在不可中断的活动作业，先让任务自然完成或请求明确安全切换方案，不抢占别的 Agent。
4. **回滚边界**：先确认并记录之前的 Web live release identity、当前配置/密钥挂载、Web-only 启动/stop 权限及可恢复版本。任何一步的权限或实体证据不充分，停止；不得顺带重启 Feishu/Learning。

## B. Web-only 候选上线验收（需独立用户明确批准）

- 有权限的运维执行一次受控 Web-only 切换，固定真实 generation / commit / PID / 进程配置，不通过重启主工作树中的试验代码来碰运气。
- Web 正常登录/消息收发、SubAgentRunner 启动及 terminal、`review_admission` Full/Compact schema 正常可用。
- 使用受控的假动作/试验仓库/私密文章草稿，不触发实际远端推送或对外发表：未审完整测试/推送/明确文章发布在**物理副作用前**拒绝（Fake actuator 派发 0），符合资格的真实 Reviewer terminal + 精确 SHA 可单次放行，改变文件后失效；普通只读、编辑和定向测试不误拦。
- `retry_tool` 转发 `execute_command` 时再次经过原审核门；DSH 下游、非 click/HTTP/CDP 类发布仍按**未覆盖**记录，不得在 UI 宣称所有三闸均已全域生效。
- 检查 Web 错误率/超时、工具 schema、EventStore 审核回执、对象存储与用户可见状态；若异常、弱模型卡死、资格失配或误阻，则停止扩张、按先前 release identity 受控回滚。

## C. 扩展到 Feishu/Learning 前的证据

需要新的各通道真实动作用例、Reviewer/授权/审计能力可见性、活跃会话处理和回滚演练；Web-only PASS 不自动授予 Feishu/Learning 推广资格。

**发布结论口径**：只确认被实测的直接 Host 入口。不能用 `main` 已有代码、用户曾经允许重启或“审查已经完成”替代当前这一笔变更的权限。
