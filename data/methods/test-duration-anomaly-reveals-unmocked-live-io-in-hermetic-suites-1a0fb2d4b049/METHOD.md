---
method_id: test-duration-anomaly-reveals-unmocked-live-io-in-hermetic-suites-1a0fb2d4b049
name: test-duration-anomaly-reveals-unmocked-live-io-in-hermetic-suites
description: 被 mock 的单元测试套件实测墙钟时间远超纯进程内逻辑应有量级（本集 35 例 50.7s，补 mock 后 0.2s），且同区域历史上存在被记为『flake/偶发挂起』的失败时，把耗时异常本身当作首要判别事实：先审计该测试类的 mock 覆盖 vs 被测代码调用图，找出未隔离的真实副作用路径（本集 run_warmup 未 mock，每次跑测试都向生产 8901 发真实 warmup 补全——既是历史挂起的根因，也是生产污染），补 hermetic mock 使耗时塌缩后，再独立处理真正的断言语义失败。勿沿用 flake 归因，也勿先在『更新期望/规范化/重装』等断言修复选项间扩散。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4262a65a-bd51-4405-bed5-57af83e2e1ab:1089:446ae9a0d68c37225b1c
evidence_refs: learning:learn:64df06d9eab8
created_at: 2026-10-22T11:51:34.298430+08:00
updated_at: 2026-10-22T11:51:34.298430+08:00
---
## Trigger
单元测试文件设计意图是 hermetic（setUp 已 patch 子进程/健康检查等协作者），但整文件 pytest 回执墙钟时间比进程内预期高约两个数量级；或同一测试区域有先前轮次记为『socket 挂起/flake』的历史失败而未给根因。

## Discriminator
当时已可见的事实对照：① 状态记录载明同文件历史『socket 挂起』被归为 flake；② pytest 回执 '2 failed, 33 passed … in 50.72s'（35 例 mocked 单测不应有网络等待量级耗时；单例重跑 2.05s 仍偏高）；③ 测试类名/配置指向真实服务（LlamaBackendTest/8901）；④ 随后可见 setUp 只 patch 了 run/wait_health 等，未覆盖 warmup 类调用。结论：时间必然流向某条未被 mock 的真实 I/O 路径，且很可能直达被测配置指向的生产端点。

## Short path
- 跑套件并保留逐文件墙钟时间（必要时 --durations）；未知量：失败在哪、时间去哪
- 对耗时异常文件做成本归因：慢例是否聚类在同一测试类？该类 mock 了什么、没 mock 什么；未知量：哪条副作用路径未隔离
- 沿被测代码调用图定向 grep 该类会触发的网络/warmup/服务调用，确认它绕过所有 mock 直达真实端点（如 run_warmup→生产 8901 /completion）
- 为该路径补 hermetic mock 后重跑：文件耗时应塌缩到亚秒级，历史『挂起』flake 归因随之被根因关闭并更新记录
- 耗时正常化后，再逐个处理真正的断言失败（retry 语义、字段规范化等），与隔离缺陷分开决策
- 全套件绿、快、且可证明全程不触生产端点即停

## Stop conditions
- 慢例已定位为未 mock 的真实 I/O，补 mock 后整文件墙钟回落到进程内量级
- 历史 flake 归因被该根因解释，记录已撤回或更新
- 剩余失败确认为真实断言语义差异，已转独立决策路径，不再混同排查

## Verification
- 重跑修复后套件：通过数不降、墙钟时间数量级下降（本集 50.7s→0.2s）
- 隔离证明：测试运行期间对生产端口连接为 0，或将端点改指不存在的地址仍全绿
- 原 flake 场景连续多次复跑不再挂起

## Counterexamples
- 耗时来自合法的进程内重活（加密、大 fixture、重型模块导入）：画像显示瓶颈在 CPU/导入而非网络，不应套用 mock 审计
- 测试本就是显式集成测试，按设计打隔离端口上的真实服务（如本集 8906 实验口）：真实 I/O 是契约，仅生产/共享端点构成危害
- 耗时正常且失败断言语义明确（本集 bootstrap 重试、plist HOME 规范化两例）：直接走断言语义决策，无需寻找隐藏 I/O
