---
method_id: binding-drift-preflight-before-gated-service-mutation-e6f2166d36f7
name: binding-drift-preflight-before-gated-service-mutation
description: 对共享服务的变更操作（restart/publish 类）先做绑定漂移预检，再修模型侧前置，最后停在 operator 闸门：并行取部署记录与进程版本，若部署记录绑定的代码身份 ≠ 工作区当前 HEAD，直接执行必被 fail-closed；此时优先读并行会话在 dirty 增量中留下的、与该操作同名的教训记录，得到围栏机制与修复链。随后逐项收敛模型侧前置：先跑测试再补提交被已提交代码 import 的未跟踪模块；grep 验证 gitignore 的构建产物是否含新功能（防『后端新前端旧』的静默半上线），陈旧则重建并复验；从当前源码而非旧记录核对 operator-only 命令参数，最后向用户交付唯一一条命令与预期结果（新代数、绑定 HEAD、产物指纹），不反复试探被围栏拦截的操作。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:1256:b06ca686224c69e0d4e1
evidence_refs: learning:learn:32b89cfec7dc
created_at: 2026-09-20T17:26:06.259131+00:00
updated_at: 2026-09-20T17:26:06.259131+00:00
---
## Trigger
用户要求对受管共享服务执行重启/发布等变更操作，或报告『此前承诺的自动/队列式执行没有动静』；环境中存在并行会话痕迹（两次检查之间工作树 dirty 状态发生变化、出现新的未跟踪记录）。

## Discriminator
动手前即可读出的两条事实：(1) 部署记录绑定的 git_head 与工作区当前 HEAD 不一致——预示直接 restart 会被 binding 校验 fail-closed；(2) dirty 增量中存在文件名与本次操作类完全匹配的教训/经验记录——直接给出围栏机制、前置条件与修复链。二者把『直接重启试试』从候选空间中删去。

## Short path
- 并行取部署记录 + 进程版本，比较发布绑定的代码身份与当前 HEAD；未知量：这次变更操作会被什么挡住？
- 发现绑定漂移 ⇒ 放弃直接 restart；扫描 dirty 增量中与本操作相关的教训记录并读取；未知量：围栏与修复链是什么？
- 按记录逐项修模型侧前置：跑测试后补提交被已提交代码引用的未跟踪模块；grep 构建产物验证新功能是否在产物内，不在则重建并复验。
- 从当前源码核对 operator-only 命令的准确参数（不照抄记录里的旧命令），可用一次轻量探测确认围栏仍活跃。
- 向用户交付唯一一条经源码核实的命令 + 预期结果（新代数、绑定 HEAD、产物指纹），停止于用户闸门，待回报后再执行 restart 与核验。

## Stop conditions
- 模型侧前置全部有回执变绿：测试通过、tracked-clean、新功能字符串已出现在构建产物中，且 operator 命令已按当前源码核实并交付。
- 用户回报发布完成后才进入 restart 与结果核验；此前不重复试探已知会被围栏拦截的操作。

## Verification
- restart 后出现新 pid、服务 git_head 等于发布绑定的 HEAD、启动时间为当下、新功能路由/面板可达。
- 构建产物 grep 命中新功能标识，排除『后端新前端旧』的半上线。
- 教训记录所述围栏与当前源码（预检逻辑/命令参数定义）一致；交付给用户的命令以源码为准。

## Counterexamples
- 无部署绑定的本地/沙箱进程重启：不适用绑定漂移预检，直接执行即可，套用即过度预检。
- 部署记录与 HEAD 一致且构建产物新鲜：判别式不成立，应直接执行操作而非先读记录。
- dirty 增量中没有任何与本次操作相关的记录：跳过记录扫描，不要为简单变更全量审计工作树。
- 教训记录已陈旧、围栏在新代码中变更：必须以当前源码重新核实命令，不得照抄记录。
