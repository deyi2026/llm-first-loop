# SearchFiles 受管发布源码路径误认工作区：定位与修复

## 根因：不是子代理授权问题

正式执行到 search_files.execute 以后，已授权的只读文件搜索收到
"root 位于敏感目录"。此拒绝来自 search_files 自己的路径检查，
而不是 SubAgentRunner 的 tool discovery / Requires.tools 拒绝。

原实现用 __file__ 向上五级确定 project_root。开发环境常为主 checkout，
但受管发布的真实代码根是 .releases/<commit>/，而 docs、experiences、
data/methods 和 docs/promotion/receipts 仍在 runtime_root。
项目内的绝对路径未落在发布包目录下，于是被分类成项目外；
macOS 实际 HOME 包含 runtime_root，又触发 HOME 整树敏感黑名单。

尤其注意：连接器的隔离命令执行器 HOME 可能是临时沙箱目录，
不能用那一环境下“读取成功”推断受管 Web 的真实 HOME 策略。
已通过模拟 macOS 实际 HOME 复现：原版对四个既有工作区目录
全部返回 [越权拒绝]，修复版对同一路径全部返回 SUCCESS。
上述复现没有扫描或输出私钥。

## 最小行为变更

- SearchFilesTool 使用 core.run_context.workspace_base() 确定动态
  搜索根，与 read_file / execute_command 对齐；工作区变化即时生效。
- root 为相对路径时只从 bound workspace 解析，不在不存在时悄悄
  回退到进程 cwd；绝对路径继续遵循已有显式 root 契约。
- HOME 自身及 HOME 上级不允许作为可全量扫描的 trusted workspace；
  工作区外 HOME 下的路径、/etc、/usr 等原有系统目录拒绝规则保留。
- 搜索时不跟随 symbolic link 文件；os.walk 继续不遍历 symlink
  目录，降低工作区内文件引用越界风险。
- 保持 glob/content 交集、max_results、默认略过 .worktrees/data
  等行为不变；显式 root=data/methods 仍能搜索其内容。
- 不改 SubAgentRunner 的工具清单、Reviewer 的只读职责、
  Provider 模型参数、权限审批、业务数据或生产会话。

## 实际文件状态

以下路径本次只读检查确认存在，修复后可以搜索：
docs、experiences、data/methods、docs/promotion/receipts。
docs/ai_rules.md 中的 card-lifecycle 内容检索有真实命中。

docs 中 pattern=*session-notes* 当前返回 **无匹配**；
docs/governance/card-audit 当前不存在，正确结果是 **目录不存在**，
均不能解释成权限拒绝。不得为掩盖缺失而虚构文件。

## 验收约束

验证用例模拟源代码在 .releases/、资料在独立 runtime_root，
并模拟实际 HOME；同时测试默认/相对/绝对 root、
错误 HOME 上下文、真实目录缺失、外部路径、
符号链接文件越界和旧的 glob/content 交集行为。

本次源代码变更应在干净隔离分支正式提交后跑 R9、
整树安全扫描。仅当受管 Web 新 generation 实际运行，
并用真实 Web 用户的 search_files 调用成功证明
正确目录可搜索，才能声称 Web 生产修复上线。

对独立 Reviewer 而言，只读仍然是正确权限；
搜索允许的目录与调用角色是否具备 search_files 权限
是两个独立决策，本次只修正已经获得工具调用权时的误拒绝。
