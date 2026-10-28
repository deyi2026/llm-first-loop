---
title: "\"加强断言\"前先核数据流方向：清单申报与校验和覆盖可能互斥"
scenario: "修复 GitHub Release 资产校验测试时，在任务书里要求子代理\"加强断言：release-artifacts-manifest.json 必须出现在 SHA256SUMS 文件内容中\"，导致顺序改动并破坏 finalize 资产集一致性检查"
root_cause: ""
solution: "下断言强化任务前先画数据流找互斥对：若 X 与 Y 互为输入输出，则\"Y 覆盖 X\"与\"X 申报 Y\"互斥。查清哪一侧已被消费方硬依赖（此处 finalize 的 declared 比对），保留该侧，只在另一侧收敛。子代理报告的遗留风险要自己核消费方代码后裁定，不当免责声明接受。当前性验证：跑 `grep -n 'declared\|EXIT_ARTIFACT_MISMATCH' scripts/release_finalize.py` 确认比对逻辑仍在，且 `grep -n -A3 'sha256sum \*' .github/workflows/release.yml` 确认校验和步骤位于 manifest 步骤之前。"
evidence: "scripts/release_finalize.py:560-574（declared 比对 + EXIT_ARTIFACT_MISMATCH）；scripts/release_finalize.py:196 optional_artifact_patterns 仅用于 ready 判定；.github/workflows/release.yml 顺序回退后 git diff 为空；CI run 40493687223 三个失败用例实测"
tags: [release, 校验和, 循环依赖, 断言设计, 任务书, 子代理管理]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-27T19:58:14.521624+08:00"
updated_at: "2026-10-27T19:58:14.521624+08:00"
---

现象：为让 release 资产测试通过，我在给子代理的任务书里加了一条"加强断言：manifest 必须出现在 SHA256SUMS 内容里"。子代理严格执行，把 manifest 生成步骤挪到 SHA256SUMS 之前。回执里它自己报了风险：release_finalize.py 会以"多余资产"拒绝转正。我核代码确认风险成立，只能整体回退这一整块改动。

根因：manifest 与 SHA256SUMS 互为输入输出，是循环依赖。
- 方向一：SHA256SUMS 覆盖 manifest ⇒ manifest 不得含 SHA256SUMS 条目 ⇒ manifest 不申报 SHA256SUMS。
- 方向二：manifest 申报 SHA256SUMS（含其哈希）⇒ SHA256SUMS 不得含 manifest ⇒ manifest 不被校验和覆盖。
两者不可同时满足。原设计选方向二（manifest 在后生成），因为 release_finalize.py 的资产集比对要求 Release 上每个资产都在 manifest 里申报，未申报即 EXIT_ARTIFACT_MISMATCH；而 optional_artifact_patterns（含 ^SHA256SUMS$）只影响平台 ready 判定，不影响这条检查——"optional"给人的豁免错觉并不覆盖资产集一致性。

判据：断言强化不是无成本动作。凡"要求 X 出现在 Y 的内容里"，先问 Y 是否已是 X 的输入，或 X 是否已是 Y 的输入。若是，则该断言与反向申报断言互斥，必须二选一，不能"顺便加强"。

正确顺序：先列出该数据流的消费者（此处 finalize 的资产集比对、installer 的校验和消费），看哪一侧已被硬依赖；已被硬依赖的一侧不可动，只允许在另一侧做收敛。再决定断言怎么写。

附带教训：子代理报"遗留风险"时不能当免责声明读——它可能是真实缺陷；审核前必须自己核一遍消费方代码再决定接受或回退。

适用范围：任何存在"清单申报 ↔ 校验和/摘要覆盖"的构建发行链路（release manifest、SBOM、checksums、attestation），以及任何"后置产物记录前置产物哈希"的场景。

当前性验证：先 `grep -n 'declared' scripts/release_finalize.py` 与 `grep -n 'EXIT_ARTIFACT_MISMATCH' scripts/release_finalize.py` 确认资产集比对仍是该实现；再 `grep -n 'optional_artifact_patterns' scripts/release_finalize.py` 确认其仅用于 ready 判定；最后 `grep -n 'sha256sum \*' .github/workflows/release.yml` 与 `grep -n 'release-artifacts-manifest' .github/workflows/release.yml` 确认校验和步骤仍在 manifest 步骤之前。若顺序已变，先重核消费方是否已同步支持。