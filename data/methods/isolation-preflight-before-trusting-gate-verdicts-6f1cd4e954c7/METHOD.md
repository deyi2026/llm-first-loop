---
method_id: isolation-preflight-before-trusting-gate-verdicts-6f1cd4e954c7
name: isolation-preflight-before-trusting-gate-verdicts
description: 在隔离 worktree/克隆中对候选线跑全量门禁前，先验证「验证环境」本身：解释器实际解析哪棵源码树、会话环境变量是否泄漏进测试子进程、是否存在并行全量测试抢共享资源、测试依赖的未跟踪文件是否随 merge 丢失。红灯出现时先按环境签名分类（缺文件/错树/污染变量/端口冲突），确认非环境所致后才改代码。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:149:b80badcfb4fe11ac0650
evidence_refs: learning:learn:6ce257cc90be
created_at: 2026-09-19T02:05:49.040541+00:00
updated_at: 2026-09-19T02:05:49.040541+00:00
---
## Trigger
在新建 worktree/克隆/独立环境中运行全量测试或门禁，且该环境与日常开发检出不同；尤其当仓库配置或历史中记录过环境敏感的假红（editable 安装、PYTHONPATH、runtime root 变量、端口冲突），或当前会话存在会被被测代码读取的环境变量时。

## Discriminator
跑门禁前已可见的判别事实：pyproject 留有历史假红修复注释（.venv editable 指向主区 src、需 pythonpath 隔离才能镜像测镜像）；导入检查显示裸 python 解析到主仓、src-first 才命中 worktree；源检出 git status 存在被测试引用的未跟踪 fixture；同时还有另一个全量测试后台任务在跑。任一为真，即先做隔离预检再解读红绿。

## Short path
- 在隔离检出中先做验证环境预检：确认 import 解析指向本检出；枚举并清空/覆盖被测代码读取的会话环境变量（如 *RUNTIME_ROOT*、PYTHONPATH）；终止或错开与其它全量测试任务的并行运行。
- 对比源检出与隔离检出的未跟踪文件（git status --porcelain / git clean -nxd），凡被测试引用而未入库的 fixture（契约 JSON、协议文档）先补提交或显式登记。
- 在净化环境（必要时克隆 venv）中跑一次全量门禁；对每个红灯按签名分类：FileNotFoundError/缺 fixture→未跟踪依赖；路径或身份指向主仓→环境泄漏；端口/资源占用→并行冲突；其余才进入代码调试。
- 只修复确认为代码/契约问题的红灯，重跑至全绿后冻结候选，push 后用远端 SHA 核对作为终验。

## Stop conditions
- 预检消除的环境因素已使全部红灯消失，且全量门禁在净化后的隔离环境中通过
- 每个剩余红灯都有指向具体代码/契约改动的失败断言，而非环境签名

## Verification
- 重跑前先 dump 子进程实际 import 路径与读到的环境变量，确认均来自隔离检出
- 修复后在开发检出与隔离检出双侧各跑一次受影响测试，排除环境偶然
- 冻结前 ls-remote 核对远端 SHA 与本地一致

## Counterexamples
- 红灯失败断言直接指向刚合并的具体代码 diff——先修代码，环境预检无增益
- 在同一开发检出内做单文件 lint 或快速单测，未跨越隔离边界
- CI 已在密封容器运行且无会话变量可泄漏——环境净化可跳过（未跟踪文件检查仍适用）
- 被测代码不读取外部环境变量、也不依赖未入库文件——预检退化为一次导入确认即可
