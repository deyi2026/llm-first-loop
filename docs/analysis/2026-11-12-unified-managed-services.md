# 统一受管发布候选（2026-11-12）

验收记录：独立审查与原版完整 R9 已通过。统一切换按下文受管流程执行，实际发布与重启终态以 service_control 回执为准。
范围：当前 Mac 的 Web、Feishu、Learning、WeCom。Deepin 生产服务不在本轮切换范围内。

## 来源与复用边界

- 远端主线基线：9bde941e6f2374707bc53ac2efb7196a1ce6b30a，包含 WeCom restart-all stable 回执修复及已有发行修复。
- Peer M1 发布候选：16210e882913377dfff1b2310d13d1419e67402c；业务修复来自 c35207640d1d492b48a83fda908973d5d0e023d2，保留 0.6.49 版本面和已入库知识资产。
- Peer M1 既有审查 subagent_8c35258c19b2 为 GLM-5.3 PASS / P0=0 / P1=0 / P2=4；此前原版完整 R9 为 exit 0，双机 wheel 与真实 TTY 验收已完成。该事实仅覆盖原冻结候选，不冒充本集成候选已通过完整 R9。
- 0.6.49 整合候选 fc0f84725 的既有审查 subagent_21de5f62ccc0 为 PASS / P0=0 / P1=0 / P2=6；其完整 R9 已真实 exit 0。上游合并后以本候选重新验证。
- 本轮追加审查基线冻结 c9c75b648、Vitest 沙盒缓存 353464bb7、FLAKY-PASS 区分 2a0c2502a，未重复合入等价 Peer 入口/nonce 补丁。
- 初始 Peer 七个关键业务文件与 M1 候选一致；随后保留远端已审查的 0e933d6d8 reconfirmation 修复。未重做或扩大已完成的双机 QA。

## 冲突与定向验证

- ci_gate 冲突同时保留 --release 的严格失败阻断和开发验证的 FLAKY-PASS 区分。
- 测试冲突同时保留物理 HOME 路径回归与抖动/干净结果区分回归。
- 独立 Python 3.13.13、uv.lock 冻结依赖、独立 node_modules；没有复用外部 node_modules 符号链接。
- CI 定向 11 passed；审查准入与服务身份定向 312 passed；锚点职责抽取后审查准入及架构定向 327 passed。部分验证不替代最终完整 R9。
- 首次统一候选已取得 GLM-5.3 PASS，但 R9 快速预检发现两个函数超出现有长度登记；仅抽取锚点校验与启动失败处理，未调整守卫或基线。修订候选重新独立审查。
- 完整 R9 前已无冲突合入当前已提交的本地 main（594a3bcec）和远端 main（aff86f63d），保留知识资产及公开发行修复。版本随远端对齐为 0.6.50；先前 0.6.49 为历史候选版本。

## 完整门禁暴露的临时目录回归

- 修订候选 606a37be6 的 GLM-5.3 独立审查 subagent_7922886b0b17 为 completed/PASS/P0=0/P1=0/P2=2，材料指纹 0d6001e35387fab307fbe00f4e0993358d12117e3a75123168f52fa3a28152fa。
- 随后原版 `bash scripts/ci_gate.sh --release` 真实 exit 1：并行 37 failed、14590 passed。全局 TMPDIR 被放进工作树，临时的无仓库目录经 Git 向上发现成为候选仓库，破坏隔离/路径用例；串行复现同一 37 项失败。
- 仅把 TMPDIR/TMP/TEMP 限定在 Node 构建和 Vitest 两个进程，继续使用候选私有 Vite 缓存；Python 保留调用方系统临时目录，不改业务代码或断言基线。
- 增加真实门禁桩执行的进程环境回归：两次 npm 获得私有 TMPDIR，pytest 保留调用方 TMPDIR。CI 定向 12 passed；全部 22 个受影响文件 491 passed、6 skipped。
- 经验：先提交候选、再跑 HEAD 口径的架构专项；临时目录隔离必须按进程职责收窄，不能把整套 Python 测试的系统临时目录重绑定进 Git 树。
- 本次收窄修订需重新独立审查和完整 R9，先前 PASS 不冒充修订后的验证。

## 执行与恢复

1. 冻结本候选，取得有效独立 PASS、P0/P1=0，再执行一次原版完整 R9。
2. 在保留主工作区其他任务修改的前提下完成合并/push 资格核验。
3. 构建并校验本候选 WebUI，使用现有 service_control 发布一个新的 desired generation；不使用旧 desired 反复重启。
4. 同一部署代执行 Web/Feishu/Learning 的 all 批次；WeCom 使用单独的受管动作，因为 all 不覆盖它。
5. 核验各服务真实存活、加载 SHA、desired/live/stable 和 verify 回执。仅受理不算生效。
6. 不满足资格则停止物理切换；保留先前部署和原始工作区备份，以现有受管接口复核、接管或回滚，不扩大基线、不强推、不覆盖未提交工作。

主工作区的连续性/压缩、其他文档等未提交修改保存在原处，不进入本候选和不可变发布快照。

## 发布前最终验收回执

- 受测源码 HEAD：`5a58dd70fa0ead6dcbd9d1fa80ec06ef3c57086b`。后续仅补充本验收记录，不更改可执行源码。
- 窄复审：`subagent_bcab71ad4e29`，真实 completed/PASS/P0=0/P1=0/P2=3；材料 SHA256 `db3469c95b6fff1c52456f4f5dc4f46d65f8f2dfff70ae78be9bdf0ff7ea33f6`。其余路径与上一次有效审查逐字节一致，覆盖链保存在本任务 review-r9-03/coverage.json。
- 原版命令：`bash scripts/ci_gate.sh --release`；2026-11-12T23:22:34Z 至 23:29:48Z；真实 exit 0，CLEAN，无失败重跑放行。
- 并行 Python：14628 passed、158 skipped、3 xfailed；serial_signal 7 passed，serial_perf 3 passed；前端 57 文件、600 测试通过。Ruff 和 Pyright 均 status=complete，无新增错误，变更文件零诊断。
- 完整日志 SHA256：`547f9c33e0428b9a3baa82357b1188a19167b790f441cad87095c9f538aa5648`；原始回执与日志位于 `.scratch/unified-managed-services-20261112/review-r9-03/`。
- 推送前已重新 fetch main，远端仍为 aff86f63d，本地 main 为 594a3bcec，均为本候选祖先；隔离树干净，knowledge_flush --check 无待入库资产。共享主工作区的 9 个在途修改和 17 个未跟踪文件另行快照保护，禁止混入发布快照。
