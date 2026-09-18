---
title: 测试必须隔离 LFL_DATA_DIR，防 interop 通知污染真实协调通道
scenario: 新增/修改会写 LFL_DATA_DIR 的测试（job 终态通知、subagent_report inbox 通知等 interop 写方）时，不隔离数据目录会导致测试进程的真实副作用写入 data/interop/lfl_to_dsh/pending/，污染真实协调通道（2026-08-17 实测 10 条 job 通知混入 inbox）。
root_cause: 测试装配未隔离环境变量 LFL_DATA_DIR，工具副作用（_notify_completion 等）直接写真实数据目录；新增 interop 写方功能时测试未同步防护。
solution: "autouse fixture 隔离: monkeypatch.setenv('LFL_DATA_DIR', str(tmp_path))——每测试独立临时目录。推荐放 tests/conftest.py 全局（opt-out 而非逐文件 opt-in；已提交演进 EVO-20260817-38364821）。验证方法: 测试后检查真实 inbox 零新增（ls data/interop/lfl_to_dsh/pending/ 时间戳对比）。"
evidence: "20260817-18:15 实测 10 条 job 通知污染真实 inbox（已归档清理）；修复后 test_execute_command_background/test_dsh_task 加 _isolate_data_dir fixture，重跑零新增"
tags: [测试基建, interop, 数据隔离, LFL_DATA_DIR, 防污染]
source:
  type: incident
  ref: 2026-08-17 inbox 污染
status: active
created_at: "2026-08-17T18:38:06.583675+08:00"
updated_at: "2026-08-17T18:38:06.583675+08:00"
---

## 背景
DSH 021-A 新增 job 终态通知（写 interop inbox）后，跑 tests/unit/test_execute_command_background.py 与 test_dsh_task.py 时，测试 job 的真实完成通知写入了真实 data/interop/lfl_to_dsh/pending/（10 条 20260817-job-*.json）。

## 修复
两测试文件加 autouse fixture：
```python
@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LFL_DATA_DIR", str(tmp_path))
```

## 验证
- 修复后重跑 21 个测试全过 + 真实 inbox 零新增
- 后续 subagent_report 测试同样验证：隔离后真实 inbox 无 sub-*.json 副产物

## 演进
已提交全局化建议 EVO-20260817-38364821（conftest.py 全局 autouse fixture，opt-out 模式），待人工审阅。