---
title: CI 门禁 flake vs 确定回归的四步判别协议（v0.6.29 发布实测）+ wake 续跑轮 method 账本不可写
scenario: "发布 PR 的远端 CI 门禁失败，需区分\"本 PR 引入的确定回归\"与\"runner 环境偶发 flake\"，决定修什么、不修什么"
root_cause: ""
solution: "四步判别协议（每步一手结果工件）：①本地复现单用例；②本地按 CI 原命令全量复跑排除顺序交互；③gh run rerun --failed 同代码重跑判 flake；④对真源 remote（非 legacy 镜像）取 PR diff 复核\"相关文件零改动\"+ main 历史 CI 绿记录。确定失败才修；flake 记录观察不做投机硬化。"
evidence: "CI run 38058513176 首跑 2 failed（--log-failed 回执）；rerun 同 run 1 failed 8505 passed（gh run view 回执）；本地全量 8525 passed 420.61s（execute_command 回执）；git diff lfl/main...HEAD 对 service_control.py/该测试文件零行变更（execute_command 回执）；CI 38060715451/38060715479 success + merge fb77cf1c0 + tag v0.6.29 + Release published 15:08:04Z + publish gen228（各工具成功回执）；method_manage record_use 两次失败回执\"当前 Episode provenance 不可用\"。"
tags: [github-actions, ci-flake, release, root-cause, evidence-discipline]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T23:10:42.300806+08:00"
updated_at: "2026-10-10T23:10:42.300806+08:00"
---

v0.6.29 发布（PR #67）CI 门禁失败排查实录：2 用例失败，其一确定（test_save_filename_kebab_case：9e8f3abd9 改 sanitize_slug 保留 Unicode 后旧断言仍要求纯 ASCII，修测试对齐新契约，提交 1026fa164），其一 CI-only（test_idle_timeout_fails_closed rc=4：idle 门被放行→binding 拒绝；机制假设=探针瞬时非 confirmed_busy，未复现故未证实）。判别协议四步各出确定性结论：①本地单测复现（确定失败 vs 本地通过）②本地全量同命令复跑（tests/ -q -m "not real_llm" 8525 passed，排除顺序交互）③gh run rerun --failed 同代码重跑（1 failed 8505 passed，flake 转 pass）④PR diff 对真源 remote 复核（origin 指向 legacy 镜像，改用 lfl/main：service_control.py 与该测试文件零改动 + main 历史 CI 绿 ⟹ 非 PR 回归）。结论：只修确定失败，flake 不做投机硬化。另：定时续跑（wake）轮里 method_manage record_use 确定性失败"当前 Episode provenance 不可用"（重试同败），方法使用登记须回到真人 run 或另行落账。