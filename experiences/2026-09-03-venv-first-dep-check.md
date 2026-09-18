# 经验：断言"依赖缺失"前先查项目 venv（PEP 668 误报教训）

## 场景
子代理交付报告称"lark_oapi/pypdf/PIL 因 PEP 668 无法装入当前环境，15 个 skip 待完整环境回归"。主会话独立终验时发现项目 .venv 内三个包齐全，`PYTHONPATH=src .venv/bin/python -m pytest tests/unit` 全量可跑（3591 passed），"待完整环境回归"决策项实为误报。

## 根因
排查用了系统 python3（PEP 668 外部管理，拒绝 pip install），未先检查项目 .venv——把"系统 python 装不了"误判为"依赖不可得"。

## 解法
- 断言"依赖缺失/不可安装"前，先执行 `.venv/bin/python -c "import X"`（或 ls .venv/bin/python*）确认项目 venv 现状；
- PEP 668 报错 ≠ 依赖不可得，先找项目 venv / 容器 / 用户级路径；
- 子代理的环境类结论（尤其"做不到"类）必须独立复验后才能进用户决策项。

## 证据
- `.venv/bin/python -c "import lark_oapi, pypdf, PIL"` → OK（2026-09 tool_loop_guard 收口验证）
- /tmp/pytest_final_venv.log：全量 3591 passed / 56 failed / 25 skipped，原先因缺依赖 error 的文件全部实跑
