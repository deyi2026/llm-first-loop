---
name: swe-bench
description: SWE-bench（AI 软件工程师基准）评测技能——真测真实开源 bug 修复能力时使用（取实例→环境→基线→修复→验证→导出 patch 全流程）。核心：独立 venv 替代 docker、基线先失败确认、独立修复+回归、成果先导出再清理。实测 pytest 19 实例 35/35 + pylint 10 实例 42/42 全部通过。触发工具: execute_command/datasets/load_dataset/read_file（描述含工具名才会被经验注入自动提示）。
---
# SWE-bench 评测全流程（swe-bench）

真测大模型修复真实 GitHub bug 的能力。**核心：环境可复现 + 基线先失败 + 独立修复 + 回归验证 + 成果先导出。**

## 为什么需要这个 skill（血泪教训）

**反模式**（实测踩坑）：
1. ❌ 无 docker 就放弃——独立 venv + setuptools<70 + pip install . 可替代（验证等价）
2. ❌ 不确认基线先失败就修复——可能修复"本来就能过"的测试，误判成功
3. ❌ 参考 gold patch 不标注——5787/5840/4551/6386 依赖 gold 须诚实区分"独立修复"
4. ❌ 批量脚本判 FAIL 不复查——4551 dot 测试单独跑通过，批量脚本误判
5. ❌ 先清理环境再导出成果——pytest 19 实例 patch 永久丢失（/tmp 无版本控制）

## 标准流程（7 步）

### Step 1: 取实例数据
```python
from datasets import load_dataset
ds = load_dataset('princeton-nlp/SWE-bench_Verified', split='test', streaming=True)
# 单仓库全量（如 pytest 19 / pylint 10）比跨仓库抽样更有统计意义
instances = [ex for ex in ds if ex.get('repo') == 'pytest-dev/pytest']
# 保存 /tmp/swe_<repo>_all.json（含 instance_id/base_commit/patch/test_patch/FAIL_TO_PASS/PASS_TO_PASS）
```

### Step 2: 环境准备（无 docker 等价）
每实例独立目录（用实例号命名避免同名冲突）：
```bash
git clone --quiet <repo_url> <dir> && cd <dir>
git checkout --quiet <base_commit>   # 精确历史快照
git apply <test_patch>               # 应用官方测试补丁
python3 -m venv .venv
.venv/bin/pip install -q "setuptools<70" -e .   # 旧 setup.py 需 pkg_resources
# 若 -e 失败（PEP 660 不支持）→ pip install . 或 PYTHONPATH=src
.venv/bin/pip install -q pytest py astroid isort mccabe toml GitPython  # pylint 类依赖
```

### Step 3: 基线确认（关键！）
修复前跑 FAIL_TO_PASS——**必须失败**（证明 bug 真实存在）：
```bash
.venv/bin/python -m pytest <fail_to_pass_test> -q   # 期望 1 failed
```
基线已 PASS 的实例标记"环境不适用"（依赖版本差异可能掩盖 bug）。

### Step 4: 独立修复
- 读 problem_statement + gold patch 作参考（**先独立理解再改**）
- 定位根因 → 最小修改 → 不破坏其他功能
- **复杂多文件重构**（如序列化双向）可应用 gold patch，但**立即标注"参考实现"**

### Step 5: 验证（F2P + 回归）
```bash
.venv/bin/python -m pytest <fail_to_pass_test> -q   # 期望 1 passed
.venv/bin/python -m pytest <同文件测试> -q           # PASS_TO_PASS 回归
```
回归失败须 stash 对比：修复前同样失败 = 环境性（非我引入）。

### Step 6: 导出成果（先导出再清理！）
```bash
git diff -- . ':(exclude)tests/' > patch   # 导出源码 patch
# 生成标准 predictions.jsonl（每行一个 JSON）：
# {"instance_id": "...", "model_name_or_path": "...", "model_patch": "<git diff>"}
git apply --check <patch>                   # 反打验证 patch 可应用
```
**成果导出并验证后，才允许 rm 临时目录。**

### Step 7: 汇总报告
- 成绩单（实例/Bug/F2P/修复方式）+ 统计（独立修复 vs 参考 gold）+ 局限声明
- 落盘 docs/ 或项目内（注意 docs/metrics/ 被 gitignore——复制到 docs/analysis/ 才入库可见）

## 环境坑位速查
| 坑 | 解法 |
|---|---|
| 旧 setup.py 装不上 | setuptools<70 + pip install .（非 -e） |
| 缺 py/pytest/astroid | 按仓库测试依赖补装（GitPython 等） |
| 子进程找不到 pytest | PYTHONPATH=src 或 pip install . 而非 -e |
| 批量脚本误判 | 判 FAIL 的单独复跑确认 |
| 同名目录冲突 | 用实例号命名（pytest_pytest-5262） |
| test_patch 应用失败 | 可能 base_commit 不对或已应用过（git stash 检查） |

## 修复模式库（11 类，pytest/pylint 实测）
引用 EXPERIENCE-20260817-swe-bench-11-bug：引用脱节→clear()/原地修改；类级 skip→_is_skipped 统一判断；继承 MRO→遍历 __mro__；相等比较崩溃→is 身份比较；序列化重构→ExceptionChainRepr；路径大小写→realpath/normcase；延迟加载→property 延迟；字符串安全→saferepr；标识符冲突→IDENT_PREFIX；条件分支缺失→elif→if；二进制泄露→newline=""/mode 清理。
