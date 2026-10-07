---
title: live 进程不产 Method 尾注：代码/配置/数据全排除后的进程级静默分叉与可观测性修复
scenario: "EVO-20261007 B面（method 候选尾注）部署后验收：live web 进程（gen 186, 3c7d85df, 12:45:34 构建）对任何会话都不产尾注，而磁盘代码、配置、数据、venv/Python 版本与全新 build_engine 复现全部正常。约 45 次工具调用完成系统性排除。"
root_cause: ""
solution: 外部不可观测的问题用三招收口：(1) 差分复现——同一磁盘/数据/配置在子进程重建引擎，证明代码侧无缺陷；(2) 全新会话对照（子代理+HTTP直打）证明非会话级 latch 而是进程级；(3) 把 fail-open 的静默分支全部升级为日志 + 把开关暴露进 architecture_config 投影，让下一次一行日志即可分诊。修复性动作：重启重建引擎。
evidence: "evidence://v1/5897594ce7860aabfdbc42cde856cb8345aab45161ff35a9e53ccb7a0d9c753a（live 回执无尾注 sha256 校验）; /tmp/repro_venv2.py 全引擎复现 True; tests/unit/test_method_related_hint.py 7 passed"
tags: [observability, fail-open, deployment-verification, method-hint, diagnosis-methodology]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-07T13:23:29.688833+08:00"
updated_at: "2026-10-07T13:23:29.688833+08:00"
---

排查路径（全部有证据落盘）：
1. 复现失败面：search_records(kind=memory) × 4（sha256 校验回执全文，evidence://v1/5897594c…）+ 子代理新会话 + HTTP 新会话（session 3a5ee8da 审计复核）→ 全部无尾注。
2. 排除代码：search.py collect→searcher 属性→tools_status 渲染→formatter 五环节逐行读 + 双 Python（3.13 venv / 3.14 brew）全引擎 build_engine 复现 → 均产尾注（venv 复现 === 有无尾注 === True）。
3. 排除配置：settings 默认 True、.env 无覆盖（mtime 11:34 早于重启 12:45）、runtime.toml [tools] 白名单不含该键、launch 路径 resolve_effective→apply_to_environ→load_settings 复放 = True。
4. 排除环境：web pid 7357 cwd/venv/PYTHONPATH 均本仓、pyc mtime+size 头与源码匹配（12:27/53957→12:45 重编译）、无旧 worker 进程（ps 全表）。
5. 排除竞态：单发调用一致缺失（非间歇）；子代理/HTTP 新会话同样缺失（非会话 latch）。
6. 排除数据：live kind=method 与复现结果集逐卡一致（同一 _search_method、同 query，restore-from-edit-… 卡均居首）。
残留未知：live 引擎构建于 12:45:34（learning 12:45:21 先拉起且开 semantic method 预热）——进程内状态无法外部观测，根因未定位。
修复动作：fail-open 分支全部加日志（flag off=INFO、store None=WARNING、异常=exception、零行=debug）+ architecture_config 投影 method_related_hint_enabled；重启重建引擎（复现已证明新构建必产尾注）。
教训：静态验证"链路完整"不能替代运行时可观测；fail-open + 零日志 = 把下次排查成本放大 10 倍。发布后应有一次 memory 检索的尾注验证 + 日志核对作为标准验收步骤。