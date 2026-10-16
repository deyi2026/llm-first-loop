# Learning 已删除会话修复：ea1d 独立完整 R9 验收

日期：2026-10-16 +08，仅隔离分支，无 main 合并、push 或生产服务变更。

## 精确源代码与独立审核

- 最新冻结基线：ea1d313b7d8706a611b0bd9457f5fc91d4433c8b；本轮 Learning 源码提交：c287e12ccc49c7522652aaee481fb294d3b14f51；Full R9 运行时隔离 HEAD：eb002c3825ec52fde4a07f2d55b636ac3b0844ac。
- 唯一两文件源码 Git binary patch：5550 bytes，SHA-256：925e453fd5baf1632eaa305134a47b2b198762dc26af8b0d222d1bec50981e89，未变。
- 独立GLM-5.3 CodeReviewer child subagent_b18c91b24585；真实 EventStore terminal 51fcbaad-907a-4963-85c2-7367e3b1ae9e；PASS P0=0、P1=0、P2=3，独立审查在完整 R9 之前完成；0 reviewer tools、未自行跑测试。
- 独立审查正式机器回执：docs/governance/receipts/RECEIPT-20261016-learning-source-deleted-ea1d-independent-glm53.json。

## 真正运行原版完整 R9（不是 --quick）

| 阶段 | 实测 |
| --- | --- |
| 原版 bash scripts/ci_gate.sh | 真实退出码 0，末尾 ci_gate 全链路通过 |
| Ruff / EnvPin / Pyright | 全部 PASS；EnvPin扫描866个测试文件；Pyright新增0 |
| WebUI candidate build | PASS |
| Tier0 | 319 passed、0 failed、8875 deselected、3 warnings |
| xdist loadfile，4 worker，完整用例 | 9031 passed、146 skipped、1 failed、13 warnings；314.74秒 |
| 原脚本自动 D-B2-09 单文件串行复核 | 8 passed、0 failed、1 warning；6.01秒 |
| 最后 guard_report | 1 passed、29 deselected |

唯一xdist失败：tests/phase4/test_m1_gap_checkpoint.py::test_b_gap_harvest_skips_remaining。
原版 R9 不修改测试集合，按已有 D-B2-09 规则对 tests/phase4/test_m1_gap_checkpoint.py 完整文件串行复核，得到8/8通过，所以原生脚本最终退出码为0。
必须保留并发测试异常：本次 R9 按项目门禁规则通过，不能写成xdist零失败，也不能把该测试永久列为flaky豁免；后续如有需要应另立并发根因跟踪。

- 全量原始日志（自己worktree ignored）：data/learning-source-deleted-ea1d-r9-20261016/full-native-r9.log，106896 bytes，SHA-256 7006c4418cc529a929013c54d00007e39013ed4b74f94c87601d28760a92e1a6。
- 完整R9生成的18份自己worktree tracked reports已保留原Git binary差异备份（自己worktree ignored）：data/learning-source-deleted-ea1d-r9-20261016/full-r9-generated-report-side-effects.patch，SHA-256 3d50a384951f05901d32d30c894f866930bd4fa765653b0d190e980499c9929f；仅恢复这些自产报告，源码SHA不变，未碰root其他Agent。
- 运行前测试Provider key环境变量已明确unset，复用了已验证的Python-only远程DNS/TCP网络防护；不声称非Python或OS级彻底封网。

## 后续必须取得单独授权

本阶段仅为隔离代码Reviewer与项目原版FullR9通过，不包含main merge、push或服务重启。下阶段先核对最新main、并发任务/脏文件/生产代际，取得用户精确本地main合并授权；Learning-only受管发布还需独立授权与队列、inflight、c8e50cb2回滚及正/反 canary回执。
