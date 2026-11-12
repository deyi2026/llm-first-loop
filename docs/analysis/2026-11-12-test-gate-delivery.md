# 测试与门禁完善：交付记录（2026-11-12）

基线：`1c18285d57a49979c0a8ec0d76ac2e1fac3f18f2`。
状态：独立审查、原版完整 R9、本地 main 集成及集成冒烟均已通过。推送目标为 origin/main；远端结果以精确提交 SHA 和 CI 记录核验。

## 已实现

- 静态诊断的修改文件范围覆盖整个交付：GitHub push 使用 before..after，PR 使用目标分支与候选的共同祖先..候选；本地使用主线共同祖先，也可声明经过审查的祖先。打印精确 base/head。CI 事件范围不能被显式参数缩小。历史诊断账本、工具版本和全树新增错误判据均未放宽。
- Release 调用与本地和 CI 相同的 `scripts/ci_gate.sh --release`；在测试前准备固定的 Node/WebUI 依赖，保留版本/tag 检查和后续工件、安装、manifest 验证。发行模式要求 Pyright 完成，不接受并行首轮失败后的复跑放行。
- 共通门禁执行现有 Vitest，限制为最多两个 worker；前端行为失败实际阻断，不增加 skip 或提高阈值。
- 新增可执行回归：多笔代码提交后附文档仍保持覆盖；不接受非祖先和错候选事件；不接受 CI 范围覆盖；发行缺完整类型结果及前端行为回归均被阻断。

## 已验证

- 原实现：交付范围新增的 5 个场景全部失败；类型未完成/前端失败两个负例均未阻断，复现缺口。
- 修复后：相关 Python 测试 45 passed；新增 PR 目标分支推进及畸形事件 4 个场景先红后绿。
- 真实前端：57 个文件、600 项 Vitest passed；既有 React act 警告未作为通过证据隐藏。
- 修改 Python 文件 Ruff、shell 语法、diff-check 通过。
- 代码候选暂存架构声明检查通过（7 个路径完整覆盖）；收口后按原始基线到最终提交核对全部 8 个交付路径；WebUI TypeScript/Vite 构建通过。

## 审查与完整验证

- 有效代码审查：智谱 GLM-5.3，子代理 subagent_d0d93886c35c，真实 PASS / P0=0 / P1=0 / P2=6。
- Host 材料 SHA256：e6ca6fc75af9c45ef56eccd649b52198addf9ea5822361686349e08bef9f52cb；原始补丁 25,539 字节，SHA256：f8e0baaf5aabf316a71f23c066011981a259106595f512a4164f8d0612708526。
- 原版命令 bash scripts/ci_gate.sh --release，真实 exit 0。Ruff、Pyright 均取得 complete；未修改历史债账本、skip、阈值或已知红项登记。
- Python 并行集：14,552 passed / 158 skipped / 3 xfailed，首次并行直接通过；信号串行补集 7 passed，性能串行补集 3 passed；tier0 341 passed。
- 前端构建通过，57 个文件、600 项 Vitest 通过。
- 独立合并审查：subagent_c3aac13e9450，GLM-5.3，PASS / P0=0 / P1=0 / P2=7。
- 本地 main 快进至 a2ff097641f24ffebfb5fe9802f1e93a70e7b1eb；集成后 9 项定向检查通过。
- 另一任务的 FLAKY-PASS 两文件改动及全部未跟踪文件已保留，未夹带入本次提交。其局部冲突仅发生在未提交工作恢复中，不进入交付树。
- 本记录和治理回执在完整 R9 后补齐；代码、测试与 workflow 的 blob 保持与已测提交一致，因此不因文档收口重复全量测试。

## P2 处理与后续优化

1. 已统一 41/45 测试计数与授权、审查、R9 状态，消除同份交付文档的旧状态冲突。
2. CI 和 Release 调用方均在共通门禁之前安装 WebUI 依赖；原有构建本已要求 node_modules。
3. 非祖先 push 继续拒绝，保留失败依据；本次只做正常 main 快进，不强推。
4. 非阻断后续项：将既有 uv --frozen 修复提示与 --locked 指引统一；减少测试桩对私有字面量的耦合。
5. 本轮实际遇到的流程空转：临时文件写入影响绑定、远端锚点瞬态失败丢失进程内资格、模型回执指纹错误。下一轮应优先完善审查事实复用和动作目标核验；本轮未降低或绕过既有准入规则。

## 证据

合并与验证回执：docs/governance/receipts/test-gate-delivery-20261112.json。
完整 R9 日志 SHA256：f57cf33bf7281ce188ba5fc965b547483d215e2f1e927d70dbf86729f24f9861。
