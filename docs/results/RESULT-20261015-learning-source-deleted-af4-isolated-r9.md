# Learning 已删除会话无效重试：最新 main af4 隔离修复完整 R9

日期：2026-10-15；目标分支：fix/learning-source-deleted-af4-20261015。

## 精确范围与 TDD

- 冻结 main：af4e26fae9ef78263de486ec6e7f01123aed453f；本地源码提交 **e49e3e03769e2366474d51a14a4c9efc16afb87a**。
- 两文件 patch 5550 bytes SHA-256 **925e453fd5baf1632eaa305134a47b2b198762dc26af8b0d222d1bec50981e89**，与真实独立Reviewer看到的全部补丁完全一致。
- 仅处理 memory_extract 线程内返回的真正 SessionDeletedError：LearningJournal.cancel(job_id, source_session_deleted) 持久落盘，不再重复尝试；其它错误仍按原路径抛出/可重试，前台预占优先级不改，不读取用户已删除的原文，不调用Provider。
- 三个回归：假 deleted-session 1 次取消，跨工作区真实 SessionStore tombstone + MemoryExtractor 无 Provider，非目标 RuntimeError 保持失败路径。先仅增测试，实测 RED **2 failed/1 passed**，原始 ignored red.log SHA **4e9605078a8b618779706da9dfc71db5002c955c187f6995fd911b5c683832c3**。修源码后八个真测试文件定向 **114 passed/1 warning**，focused-green.log SHA **83d0d5cc705544bf24b5e01c69bd3aacc72672a2af24e396927136bdfefacc73**。
- 第一次组合测试写错了两个不存在的路径，pytest 退出4且实际0 tests；随后纠正为真实文件，不把这种调用错误冒称源回归失败或测试 PASS。
- Ruff touched-files PASS；真实 staged security scanner 2 files PASS；原版 Pyright ratchet 1.1.411 historical45/current16/new0/touched0 PASS。
- 独立GLM5.3 child subagent_74e34a55cf2e、唯一真实 EventStore terminal 884fcd53-8396-4010-a077-19badbc37ce3，PASS P0=0/P1=0/P2=2；见 docs/governance/receipts/RECEIPT-20261015-learning-source-deleted-af4-independent-glm53.md。

## 原版完整 R9 物理执行（独立 Reviewer PASS 之后）

| 原项目门禁 | 实际结果 |
| --- | --- |
| Ruff ratchet / EnvPin / Pyright | PASS；EnvPin 863 test files |
| WebUI candidate build | PASS |
| Tier0 | **319 passed、8,820 deselected、3 warnings** |
| 4-worker xdist loadfile full | **8,977 passed、146 skipped、0 failed、13 warnings、197.01s** |
| Serial fallback | 未触发；xdist 自身全绿 |
| 最后 guard report | 1 passed、29 deselected |
| 原版 bash scripts/ci_gate.sh exit | **0 / ci_gate 全链路通过** |

原始 ignored full-native-r9.log：SHA-256 **040e0e6badd81106867c9ddc0c64127e6477065222aebcda7677601c51df9c79**。原版CI未跳阶段、未调历史错误基线、未缩减选择。Provider密钥自CI环境解除，本隔离树没有 .env；使用事先已测试的 Python-only remote socket/DNS guard（SHA a66fd43421b2f3232bbd5b7960339ea3e988c6c47aa8a442283a9ae110866961），不宣称 OS 层面完全封网。

完整CI停止之后自动变更的18份 tracked reports 按精确白名单留取原diff再只恢复这些报告，side effect diff SHA **058485e777cadf0fde97621ac0aa2c78ea223effb8e946b99b198590393424ce**；代码/test reviewed patch SHA前后不变，未碰其他Agent工作树。

**结论：ISOLATED REVIEWED CODE + CANONICAL FULL R9 PASS。尚未 main 合并、未 push、未部署重启 Learning/Web/Feishu；后续 main 集成/生产上线须单独授权并重新核对 currentness、Learning 排队状态、在跑会话和回滚身份。**
