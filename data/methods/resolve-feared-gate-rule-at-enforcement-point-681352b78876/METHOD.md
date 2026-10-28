---
method_id: resolve-feared-gate-rule-at-enforcement-point-681352b78876
name: resolve-feared-gate-rule-at-enforcement-point
description: 门禁类数据 artifact（baseline/棘轮/豁免账本 JSON）出现大 diff 或陈旧、并由此产生『提交/门禁会变红』的担忧时，第一未知量是『这条规则是否真的被执行、由谁执行』，而非『数值是否超标』。先全仓 grep 该文件名定位 reader（通常是单一守卫测试），枚举其 test 函数名得到实际执行契约，再只跑该测试文件拿 exit code 回执。artifact 的 meta 自述可能描述根本不存在的测试，已登记键常被豁免；本集先做 AST 复测、读整份 diff 与 meta、grep 脚本约十步，最后才发现 feared 红线无对应测试，自纠『基线没刷新会变红』为错。
aliases: 基线大diff怕挂门禁 先查谁在执行, 棘轮红线真的存在吗 看守卫测试断言, meta里写的FAIL规则测试里没有 算不算数, 怕gate变红先跑那一个守卫测试, baseline enforcement test 枚举断言再裁决
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:1234:f3559191f1f304ef9224
evidence_refs: learning:learn:5a5780ed3a04
created_at: 2026-10-25T07:55:31.076209+08:00
updated_at: 2026-10-25T07:55:31.076209+08:00
---
## Trigger
仓库门禁/棘轮类数据 artifact（函数行数基线、ratchet ledger、豁免清单等）在 git status/diff 中出现大改动或明显陈旧，据此形成『提交会因此被拦』的具体担忧，且尚未拿到任何门禁回执

## Discriminator
全仓 grep 该 artifact 文件名通常只有单一 reader（守卫测试文件），其 test 函数名清单就是实际执行契约；若 meta 自述的规则（如全局行数红线 FAIL）在 test 名清单中无对应项、且存在豁免/ratchet-not-raised 类测试，则 feared rule 当前未被执行——该事实在读 diff、复测数值之前即可取得

## Short path
- git status/diff 显示 baseline/ledger 大改 → 定义未知量：哪条被执行的规则会因此变红（不是数值本身）
- grep artifact 文件名全仓 → 定位唯一 reader（守卫测试）→ 未知量变为：它实际断言什么
- grep '^def test_' 枚举断言清单，与 feared rule 对照：无对应测试即未执行；有则读其豁免/棘轮语义
- 用仓库 venv 只跑该 reader 测试文件（分钟级）→ 当前树是否满足执行契约的直接 exit code 回执
- 绿且全仓无第二执行点 → 关闭该恐惧分支，转真实未知量（如准入、静态分析红灯）；红 → 真实阻塞，进入修复/上报

## Stop conditions
- reader 测试 exit 0 且 grep 确认无其他执行点（脚本/CI workflow/pre-commit）→ 判定 feared rule 非阻塞，停止该调查分支
- 测试红 → 恐惧被证实为真实阻塞，停止 artifact 取证，转修复路径

## Verification
- 全仓 grep 文件名的 reader 清单完整（覆盖 scripts/、CI workflow、pre-commit 配置），确认无旁路执行点
- 以 reader 测试的 exit code 回执为准，而非仅静态读断言文本
- 对缺席的规则做同义 grep（redline/阈值/global 等）确认是真缺席而非漏检

## Counterexamples
- 执行点在仓外（远端 CI workflow、平台侧门禁、pre-commit 钩子）：本地测试名枚举对远端零信息，必须先取门禁配置本体
- 棘轮由 linter 工具自身执行（ruff/pyright 类 ledger）：没有守卫测试可枚举，应直接跑便宜的静态命令拿回执
- feared violation 真实存在（新注册值确实上调且 ratchet-not-raised 会拦）：方法同样适用但结论为红——它加速裁决，不预设立场为绿
- artifact 有多个 reader（守卫测试+运行时检查+脚本）：只枚举一个 reader 会低估契约，须先列全 reader 再裁决
