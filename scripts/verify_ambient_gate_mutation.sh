#!/usr/bin/env bash
# D4 变异验证（2026-10-20 实施期定稿）：验证 ambient-env-gate 门禁的检测力。
#
# 臂1（conftest 批次5 剥离停用 → 泄漏敏感切片）：实施期实测 UNDETECTED——
#   test_workspace_resolution.py 每用例自带 monkeypatch.delenv 防御，
#   test_terminal_cli.py 全量被 serial_signal marker 排除；批次5 对该切片
#   是纵深防御冗余而非检测点。故本臂只如实报告，不作为失败条件。
# 臂2（queries.py B1 回归变异：部署绑定 LFL_WORKSPACE_ROOT 反超 cwd-upward）：
#   门禁切片中的 subprocess 免疫测试必须变红。这是门禁检测力的主导来源
#   （免疫测试显式构造 env、不依赖 ambient 注入，任何环境都有检测力）。
# 臂2 UNDETECTED 才判失败（门禁恒绿摆设化）。
# 用法：bash scripts/verify_ambient_gate_mutation.sh
set -euo pipefail
# 免疫部署泄漏：真实 LFL web 派生 shell 连 PYTHONPATH 一起泄漏（指向
# .releases/<hash>/src 旧快照），不剥离会测到旧代码而非本仓库源码，
# 令变异结论失真（假 DETECTED）。
unset PYTHONPATH

restore_all() { cp /tmp/conftest_backup_mutation.py tests/conftest.py 2>/dev/null || true; cp /tmp/queries_backup_mutation.py src/llm_loop/terminal/queries.py 2>/dev/null || true; }
trap restore_all EXIT

# ── 臂1：停用 conftest 批次5 ambient 剥离（如实报告，不作失败条件） ──
cp tests/conftest.py /tmp/conftest_backup_mutation.py
python3 - <<'PY'
from pathlib import Path
p = Path("tests/conftest.py")
src = p.read_text()
old = '    for key in _DEPLOYED_WORKSPACE_IDENTITY_VARS:\n        monkeypatch.delenv(key, raising=False)\n'
new = '    # mutation: for key in _DEPLOYED_WORKSPACE_IDENTITY_VARS:\n    #     monkeypatch.delenv(key, raising=False)\n'
assert old in src, "mutation target not found"
p.write_text(src.replace(old, new, 1))
PY
export LFL_WORKSPACE_ROOT=ci-ambient-leak-stub
echo "--- 臂1：批次5 停用后跑泄漏敏感切片（进程内切片，实测预期全绿=纵深冗余） ---"
ARM1=DETECTED
if uv run python -m pytest tests/unit/test_workspace_resolution.py tests/unit/test_terminal_cli.py -q -m "not real_llm and not serial_signal"; then
  ARM1=UNDETECTED
  echo "臂1 MUTATION UNDETECTED：进程内切片对批次5 停用免疫（用例自带 delenv 防御 + serial_signal 排除）——批次5 定位为纵深防御冗余"
else
  echo "臂1 MUTATION DETECTED：批次5 停用导致进程内切片失败"
fi
cp /tmp/conftest_backup_mutation.py tests/conftest.py
unset LFL_WORKSPACE_ROOT

# ── 臂2：B1 回归变异（部署绑定反超 cwd-upward），subprocess 免疫测试必须变红 ──
cp src/llm_loop/terminal/queries.py /tmp/queries_backup_mutation.py
python3 - <<'PY'
from pathlib import Path
p = Path("src/llm_loop/terminal/queries.py")
src = p.read_text()
old = '    bound = _normalize_workspace_value(values.get("LFL_WORKSPACE_ROOT"))\n    cwd_root = _cwd_project_root()\n'
new = ('    bound = _normalize_workspace_value(values.get("LFL_WORKSPACE_ROOT"))\n'
       '    if bound is not None:\n'
       '        return Path(bound).expanduser()  # mutation: B1 回归——部署绑定反超 cwd-upward\n'
       '    cwd_root = _cwd_project_root()\n')
assert old in src, "mutation target not found"
p.write_text(src.replace(old, new, 1))
PY
echo "--- 臂2：B1 回归变异后跑 subprocess 免疫测试（期望变红） ---"
if uv run python -m pytest tests/unit/test_ambient_leak_immunity.py -q; then
  echo "MUTATION UNDETECTED：B1 回归未被免疫测试捕获——门禁检测力不足，需重新设计" >&2
  exit 1
else
  echo "MUTATION DETECTED：B1 回归导致 subprocess 免疫测试失败（门禁有效，检测力主导来源）"
fi
echo "=== 变异验证结论：臂1=${ARM1}（信息性）；臂2=DETECTED（决定性）==="
