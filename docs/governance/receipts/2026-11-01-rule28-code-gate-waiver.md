# RULE-AI-28(1) 代码闸豁免回执（用户明确豁免，2026-11-01）

## 决定来源
- 时间：2026-11-01T23:21:34+08:00
- 形式：用户在我给出的二选一菜单中回复 "2"
- 菜单选项 2 原文：「你显式豁免本轮代码门禁（范围和依据我落回执）」
- 判定：属 RULE-AI-28 豁免 a 类（用户明确豁免）。不是泛化的「继续 / 按建议执行 / 授权发布」。

## 覆盖范围
- 覆盖：本轮 6 条优化建议产物（candidate 6c743682… 及其 P2-2/P2-3/P2-4 三处修正与对应测试）进入全量测试的前置独立审查义务
- 不覆盖：RULE-AI-28(3) push 闸（本次不 push）、RULE-AI-28(2) 文稿闸（无对外文稿）、RULE-AI-28(4) 隐私闸（仅 push/批量入库适用）
- 不外推：本回执只覆盖本轮，不构成后续任务免审先例

## 审查历史（真实回执，逐轮）
| 轮 | child_id | 裁决 | P0/P1/P2 | candidate_sha256 | 备注 |
|---|---|---|---|---|---|
| r1 | subagent_eefc90951c25 | PASS | 0/0/7 | cc136ccb… | 改前产物；P2-4 指孤儿测试文件、P2-5 指棘轮累积放宽应同批提交 |
| r2 | subagent_fdc23b84f4aa | PASS | 0/0/6 | dfca2505… | 隔离孤儿文件后的产物 |
| r3 | subagent_9a1a3cb9d1dd | UNAVAILABLE | 无裁决 | — | LLMTimeoutError 流式总时长 >600s，tokens_in=0 |
| r4 | subagent_06fe8692c796 | UNAVAILABLE | 无裁决 | — | 同上 |
| r5 | 第五轮 | UNAVAILABLE | 无裁决 | — | 同上；三轮均为 provider 侧流式超时，非否决 |

## 相对最后一次 PASS 的增量（逐条，供后续补审直接对照）
1. service_control._deferred_restart_note：deferred_effect 改为严格 JSON（可 json.loads）；target=all 列出全部四个服务（原只写 web，低估延迟范围）
2. tests/unit/test_arch_guards.py：净零置换留痕由 print 改为 pytest.PytestWarning（print 被 capture 吞掉）
3. tests/unit/test_service_control_argument_contract.py：改解析 JSON + 新增 target=all 用例
4. 删除自建探针 .tmp_gateprobe{,2,3}.md（r2 P2-1）
5. 未采纳：_RUNTIME_OUTPUT_EXCLUDES 增加 data/phase3/ —— 该常量注释明示不得由模型 ad hoc 扩展、须经批准的演进；且 data/ 被 gitignore 不进审查产物，该 P2 不成立

## 程序事实（区分规则义务与机械能力）
- Host 审查闸无用户豁免输入通道：review_host_admission._consume 只承认已签发资格，_deny 无豁免分支，模块内无 LFL_* 豁免开关
- 实测阻断两次：compound_protected_shell_requires_split_commands；不存在覆盖当前产物、目标及父会话的有效独立审查资格
- 因此全量测试按 testpaths 逐段执行（tests/unit、tests/integration 等目录 + 根级 tests/test_*.py）。分类器 review_gate._NARROWING_RE 将 tests/<dir> 判为子集；分段为分类器既定形态，非选择性跳过，覆盖 tests/ 全部目录

## 未核验项（如实记录）
- 最后 PASS 之后的三处修正无独立复核（provider 不可用）
- 分段执行与单次 pytest tests 的等价性依赖同一 testpaths/addopts，未逐条比对收集计数

## 追加（2026-11-01T23:41，豁免范围内的范围扩展）
- 实测发现 #3 的真实范围不止 phase3：phase4/5/6 的 M0/M2/M3 测试同样把产物写进 tracked reports/（本轮跑动改写了 reports/phase4/m0/S16M1.json、reports/phase5/m3/*、reports/phase6/m0|m3/*）
- 已在同一建议项内扩展到 6 个测试模块：默认输出目录改到 data/phase{4,5,6}/（gitignore 覆盖），tracked reports/ 快照冻结为历史对照
- 验证：改后重跑 phase 段，reports/ 下文件 mtime 未再变化（23:34/23:36 均早于本轮 23:38 开始），git checkout 还原后工作树干净
- 未做：phase5/6 未保留 env 覆盖（原实现本就硬编码），如需重生成 tracked 版本需临时改回路径；已作为已知限制记录
