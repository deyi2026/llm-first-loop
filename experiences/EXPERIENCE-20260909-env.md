---
title: 环境直读参数导致测试精确断言跨环境漂移：必须 env 钉扎 + 静态门禁
scenario: 仓库测试在默认环境全绿，但换机器/fresh CI 上出现无法复现的红；或本地偶发红。典型于测试断言精确数值而数值推导链里有 float(os.environ.get(...)) 直读环境变量的场景（压缩比、预算系数、阈值类配置）。
root_cause: ""
solution: "1) grep 定位精确断言与 env 直读参数的交汇点；2) 给测试加 autouse fixture 用 monkeypatch.setenv 钉住环境（delenv/setenv 显式化）；3) 把\"精确断言必须声明环境依赖\"固化为静态扫描门禁（文本模式：预算 stat 键 × builder 入口名 ⇒ 必须出现 env 名或 pin fixture 名），接入 ci_gate 并做故意违规负例演练；4) 双环境验证：默认环境 + 恶意注入环境都必须绿。"
evidence: ""
tags: [pytest, environment-leak, flaky-test, static-gate, ci_gate, monkeypatch, r817]
source: {}
status: active
qualification: 2026-09-18 batch2/3 per-file review: retained（methodology self-evident：步骤可机械复现或含实测细节；evidence 内嵌正文）
created_at: "2026-09-09T01:27:01.704823+08:00"
updated_at: "2026-09-09T01:27:01.704823+08:00"
---

症状：pytest 单文件全绿、CI/fresh 环境翻红，无代码改动。根因：环境变量（本例 COMPACT_RATIO）被 load_env_file() 从 .env 残留或 ambient 注入，压缩阈值 = max_chars × ratio 随之漂移，携带精确数值断言的用例红/绿取决于环境。修复模式：(1) 测试内 autouse fixture monkeypatch.setenv 钉住（幂等于断言可加 ratio 同步断言）；(2) 静态门禁固化——凡"引用精确预算 stat 键 + 调用 builder 入口"的测试文件必须出现 env 名或 pin fixture 名（scripts/check_test_env_pins.py，接入 ci_gate [2/5]），负例演练验证阻断。推广：所有 env 直读参数参与计算的精确断言，都适用"声明依赖或被门禁拦截"。