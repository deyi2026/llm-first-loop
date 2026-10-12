---
title: SWE-bench django 实例标准修复流程（batch4 验证）
scenario: 继续 SWE-bench 官方评测（django 实例），纪律：只看 problem_statement/test_patch，不看 gold patch/官方 commit；每实例需修复→本地验证→生成 patch→官方 harness 终验。batch4 已完成 4/10（10554/11400/13212/13344）全绿。
root_cause: SWE-bench 评测需要可复现的本地闭环验证，环境兼容性与纪律边界是关键
solution: "标准流程：① read_file 读 /tmp/swebench_official/problem_lfl4_*.txt 与 testpatch_lfl4_*.patch（只看这两个，杜绝 gold patch）；② /tmp/swe_instances/django_django-<id> 已含 base commit+test patch，建 /opt/homebrew/bin/python3.11 -m venv .venv311 并 pip install -q -e .（Django 3.0-3.2 老代码在 py3.14 跑不了，必须 3.11）；③ 用 tests/runtests.py <module> 复现→定位→修改 django/ 源码；④ 跑 F2P 所在模块 + P2P 相关模块回归；⑤ git diff -- django/ > /tmp/swe_lfl_patches/django__django-<id>.patch（只含 django/ 源码，不含 tests/）；⑥ 全部完成后统一跑官方 harness（参照 run_lfl_batch3_official.py 写 batch4 版，docker 镜像评测）。注意：本地 py3.11 与官方 docker 环境差异导致的个别失败（如 urlsplit 对非法 IPv6 行为）需区分\"base 就有\"（git stash 验证）与\"我的修改引入\"。"
evidence: batch4 前 4 实例 10554/11400/13212/13344 均按此流程完成并通过本地测试；10554 与 11400 的 venv311 建装复用
tags: [swebench, django, 评测, 修复流程]
source: {}
status: active
created_at: "2026-08-19T10:19:25.939439+08:00"
updated_at: "2026-08-19T10:19:25.939439+08:00"
---