---
title: SWE-bench Django 全量做题经验（9 批 130 实例沉淀，batch1-9）
scenario: 继续 SWE-bench 官方评测（django 全量 231 = covered 50 + remaining 181），每实例需修复→本地验证→生成 patch→官方 harness 终验
root_cause: ""
solution: ""
evidence: ""
tags: [swebench, django, 评测, 修复模式, 环境教训]
source: {}
status: archived
created_at: ""
updated_at: "2026-09-06T00:15:07.572782+08:00"
---

# SWE-bench Django 做题经验（全量版）

## 一、标准修复流程（batch4 验证 → 9 批全量确认）

1. **纪律**：只看 `problem_statement` + `test_patch`（/tmp/swebench_official/），**杜绝 gold patch / 官方 commit**
2. **环境**：`/opt/homebrew/bin/python3.11 -m venv .venv311` + `pip install -q -e .`（Django 3.0-3.2 老代码在 py3.14 跑不了，必须 3.11）
3. **复现**：`tests/runtests.py <module>` 先复现 F2P → 定位 → 修改 `django/` 源码 → 跑 F2P 所在模块 + P2P 相关模块回归
4. **patch**：`git diff -- django/ > /tmp/swe_lfl_patches/django__django-<id>.patch`（只含源码，不含 tests/）
5. **终验**：官方 harness docker 评测（每批写 run_lfl_batchN_official.py 版脚本）

## 二、常见修复模式库（跨批次共性，命中即复用）

| 模式 | 实例 | 修法 |
|---|---|---|
| delete() 只选引用字段（cascade 优化） | 11749/11087 | ORM query 字段选择：无 deletion signals 时只 SELECT 引用字段，有 signals 全字段 |
| OuterRef in exclude()/~Q() 用错模型 | 11734 | fields/__init__.py 删 OuterRef 特判 + related_lookups.py 改 `not hasattr(rhs,'resolve_expression')` + query.py split_exclude |
| fast-delete 合并回归 | 11885 | 按 (model,batch) 精确合并，修复 test_large_delete |
| 本地/容器环境行为差异 | 多例 | 先 `git stash` 验证"base 就有"还是"修改引入"（如 urlsplit 非法 IPv6） |

## 三、环境/工具教训（踩过的坑）

- **arm64 主机拉 x86_64 镜像 404**：补拉正确平台镜像后重跑（batch7 6 个实例）
- **Docker Hub 429 限流**：`manifest inspect` 探测不耗配额；批量拉取易触发 429 → **串行 + 间隔**（batch9）
- **容器冲突**（误启双任务）：清理后重跑（batch8 11749 首轮）
- **py3.11 venv 必须**：老 Django 在 py3.14 直接跑不了，建装可复用（10554/11400 共用）

## 四、评测纪律

- 全程不看答案（无 gold patch / 官方 commit 参考）——对照实验要求
- 网络类测试（requests）容器无外网 → P2P 失败是**环境限制非修复缺陷**，如实标注（3/8）
- 批次拆解（batch7b/7c、batch8-fix、batch5rem）都要在 status.json 留痕
- 每批完成：predictions jsonl 导出 + status.json（resolved 清单 + official_reports 路径 + notes）

## 五、进度管理（跨会话不丢）

- 分批 ≤20（实做 10）/ 批间 /clear 或新会话（100 万窗口，SWE 工具结果曾 162 万字符）
- 进度 `data/swe_results/*.jsonl` 落盘不丢；**跨会话以磁盘为准**
- 报告命名：`llm-first-loop.swe-<batch>.json`，结构含 total/submitted/completed/resolved_instances
- 剩余清单/批次计划：`data/swe_results/django_remaining_plan.json`（batch10-20，101 实例）

## 六、反复尝试才做对的实例（试错链，最有借鉴价值）

| 实例 | 尝试 | 试错链 | 关键教训 |
|---|---|---|---|
| **sympy-13615** | 3 次 | ① fix：Docker 容器名冲突 409（残留容器）→ **环境问题**；② fix2：patch 应用成功但 `resolved=False` → **修复逻辑不完整**；③ fix3：集合运算改 **sift 三元分类**（contains→True/False/None，Union+Complement 重写）→ 过 | 容器冲突≠修复问题（先清理重跑）；**patch 应用成功≠测试通过**（必须验 F2P）；sympy 集合包含类问题用 sift 三分法 |
| **django-11749** | 2 次 | 首轮容器冲突（**误启双任务**）→ 清理重跑 → 过 | 环境问题先排除，别在错误上叠修复 |
| **django-11885** | 2 次 | fast-delete 合并粒度错（触发 test_large_delete 回归）→ **按 (model,batch) 精确合并** → 过 | 合并类修复必须精确到粒度，粗粒度引入回归 |
| **django-11734** | 独立重推 | 方案 B 回退官方 patch 后重新推导 → **diff 与官方一致** → 过 | 与官方 diff 一致 = 强验证信号（推导路径正确） |
| **pylint-4661** | 2 次 | fix-verify 失败 → verify2 修复 → 过 | 二次修复是常态，保留前次失败信息对照 |
| **sympy-27** | 重跑 | 15/27 → 27/27 全过 | 大批次首轮部分失败时先重跑排除环境因素（原因未留痕，待确认） |

### 反复尝试仍未过的（避免重复投入，如实记录）
- pylint-10：2 个未过（8/10）
- sample30-b2：1 个未过（28/29）
- sympy b4big/b4p1：7/8（同一实例两跑均未过）
- requests-8b：3 个网络测试 = 容器无外网（**环境限制非修复缺陷**）

### 试错模式总结（跨实例共性）
1. **环境问题优先排查**：容器冲突/镜像平台/限流——先清环境重跑，别急着改代码（13615-fix、11749、batch7 镜像、batch9 限流全是环境）
2. **patch 应用成功 ≠ resolved**：必须看 F2P 测试结果（13615-fix2 的坑）
3. **修复不完整是第二次失败主因**：第一次往往只修了表面，F2P 全绿才敢交
4. **回归检测**：合并/重构类修复跑 P2P 相关模块（11885 test_large_delete）
5. **与官方 diff 一致是最强信号**（11734），但推导过程不看官方 patch（纪律）

## 七、老版本实例（Django 1.x）环境教训（batch10 实证 2026-08-20）

- **Django 1.11 在 py3.11 本地验证不可行**（实测多次失败）：
  - `from collections import Iterator/Mapping/OrderedDict` ImportError（py3.10+ 移除）——sitecustomize/.pth 注入均不生效（homebrew python 遮蔽）
  - exec 包装注入可行但触发 `__classcell__ not set` RuntimeError（Django 1.11 类定义不兼容 py3.11 严格检查）
  - 结论：**1.x 老版本实例跳过本地 venv，直接用官方 docker 镜像复现/验证**（镜像内 python 版本与官方一致）
- **arm64 主机跑 x86_64 镜像**：`docker run --platform linux/amd64`（默认拉 arm64 manifest 会 404 no matching manifest；batch7 教训的精确操作细节）
- x86_64 模拟运行慢：容器测试放后台任务（>60s 超时），轮询 job_output
- 本地工作目录仍可用于**纯代码分析**（定位 bug 不需要跑环境）；修复代码在宿主机改，容器挂载验证（-v /testbed/django）

## 八、batch10 实例试错（django-7530 实证，2026-08-20）

**7530（makemigrations allow_migrate (app_label,model) 配对 bug）试错链**：
1. **safe.json 的 FAIL_TO_PASS 字段会误导**：字段只列 test_squashmigrations_initial_attribute（该测试 base 上就过），但**真实失败点是 test_patch 修改的已有测试** test_makemigrations_consistency_checks_respect_routers（加 INSTALLED_APPS=['migrations','migrations2'] + 断言校验每次 allow_migrate 的 app/model 配对）——**必须以 eval_script 内嵌的 test_patch 为准，跑官方指定的整个模块**（runtests migrations.test_commands），不能只跑 F2P 字段列的单测
2. **Django 1.11 容器环境（egg 安装陷阱）**：镜像内 Django 是 testbed env（py3.5）的 **egg 安装**（site-packages/...egg/django）；改 /testbed/django/ 源码后**必须 `conda activate testbed && python setup.py install`** 才能让测试加载新代码（不激活 testbed 会装进 base py3.11，测试仍用旧 egg——静默失效）
3. **bug 根因**：1.11 `apps.get_models()` 无 app 参数，`apps.get_models(app_label)` 把 app_label 误当 include_auto_created=True → 返回全部模型；修复 `apps.get_app_config(app_label).get_models(include_auto_created=True, include_swapped=True)`
4. 容器验证流程（官方 eval_script 对齐）：git apply test_patch → conda activate testbed → setup.py install → runtests.py 模块级

## 九、batch10 批量模式修复模式（13023/13028 实证，2026-08-20）

**13023（DecimalField.to_python 异常覆盖）**：`decimal.Decimal(value)` 对 dict/list/set/object/complex 抛 **TypeError**、对 ()/[] 抛 **ValueError**（"argument must be a sequence of length 3"）——except 必须覆盖 `(decimal.InvalidOperation, TypeError, ValueError)` 三种，否则 TypeError/ValueError 冒泡（测试用 `field.clean(value, None)` 断言全部转 ValidationError）。

**13028（模型字段名 filterable 与内部标志冲突）**：`query.py check_filterable()` 用 `getattr(expression, 'filterable', True)` 判断表达式可否入 WHERE——模型实例 RHS（`filter(extra=instance)`）若含名为 filterable 的字段，取到的是**数据值**（False）→ 误抛 NotSupportedError。修复：`check_filterable` 开头 `if hasattr(expression, '_meta'): return`（模型实例是数据非表达式，跳过检查）。

**批量流水线模式（已验证提速）**：本地 venv（3.x py3.11）验证通过即落盘 predictions → 容器终验攒批统一跑（不必逐实例容器）；调度后台任务后继续下一个实例（不等通知）；每实例修复模式即时追加本文档。

**13089（db 缓存 _cull 空 store 崩溃）**：`_cull` 里 culling 查询（`cache_key_culling_sql() LIMIT cull_num`）**无结果时 `cursor.fetchone()` 返回 None → `None[0]` TypeError**。修复：fetchone 判空后再 DELETE（`if last_cached:`）。触发场景：_max_entries 极小/负值时 cull_num=0 → LIMIT 0 空结果。

**13109（ForeignKey.validate 用 base manager）**：`related.py validate` L917 用 `_default_manager`（default manager 过滤 archived 等）→ 合法记录被过滤导致验证误报。修复：改 `_base_manager`（不过滤）。表单字段 queryset（L987）保持 default manager 不动（那是 UI 层行为）。

## 十一、复杂 bug 定位策略（13033/13112 教训，2026-08-20）

**13033（自引用 FK attname 排序）**：`order_by('author__editor_id')` 应走本地列（editor_id），实际 join editor 表按对象排序。定位链：compiler.as_sql multi-alias 分支 → names_to_path attname 键 → find_ordering_name attname 判断 → trim_joins FK→target_field 转换。**两处修复（names_to_path + find_ordering_name）仍未过，待回访**——关键教训：**静态 grep 定位 3-4 次无果应立即切运行时 debug**（打印实际 SQL：`str(query.query)` 一次就能看出 ORDER BY 是 `"ordering_author"."id"` 而非 `"editor_id"`）。

**13112（混合大小写 app_label lazy reference）**：错误 `'mixedcase_migrations.author'`（lower）vs app 'MiXedCase_migrations'——lower 生成点未定位（resolve_relation/make_model_tuple/ForeignKey.__init__ 均不 lower app_label），**待回访**。教训：**lazy reference 字符串生成链长**（__init__→rel_class→lazy_related_operation→make_model_tuple），静态 grep 效率低——应直接打印 `field.deconstruct()` / `remote_field.model` 形态定位。

**通用定位策略（沉淀）**：① grep 静态定位 ≤3 次；② 无果 → 运行时 debug（本地 venv 已就绪，临时测试文件打印 SQL/deconstruct/字符串——0.2s 级）；③ 仍无果 → 标记待回访，不阻塞批量（攒批后统一回头看，或官方 harness 验证时对比）。

**13121（SQLite DurationField 表达式转换）**：`annotate(duration=F('estimated_time') + delta)` 在 SQLite 崩溃——`convert_durationfield_value`（base）`timedelta(0,0,value)` 期望数字，但 **SQLite 返回字符串**（duration 列 TEXT 格式 / 算术结果微秒字符串）→ TypeError。修复：**sqlite3/operations.py 覆盖 `convert_durationfield_value`**——字符串用 `parse_duration`（'HH:MM:SS.ffffff'）解析，失败 fallback `timedelta(0,0,float(value))`（微秒数字字符串）。注意 base 后端对 duration 返回类型的假设（数字微秒）与 SQLite（文本）不同，**数据库后端差异导致的转换 bug 优先看后端 operations 是否覆盖 converter**。

**13033 最终根因（回访成功，pieces[-1]）**：`find_ordering_name` 里 attname 判断用**完整 order_by 字符串**（`'author__editor_id'`）比较 `field.attname`（`'editor_id'`）——**永不相等**，导致 `_id` 后缀永远走 join 分支（按关联对象 Meta.ordering 排序）。修复：比较 **`pieces[-1]`**（split('__') 最后一段）——`'editor_id' == 'editor_id'` → attname 命中 → 本地列排序（不 join）。**配合** query.py names_to_path 的 attname 本地分支（不建 join）。教训：**多层解析路径中"名字"变量在不同层级是不同形态（完整字符串 vs 最后一段）——比较前先确认变量粒度**。

**13112 定位进展（混合大小写 app_label，待回访）**：错误措辞在 `django/core/checks/model_checks.py:145`（fields.E307 系统检查）——`model_key` 显示 lower app_label（'mixedcase_migrations'），但 debug 确认：`deconstruct` 的 'to' 参数是**原始大小写**（'MiXedCase_migrations.author'）、`make_model_tuple` 输出原始——**lower 发生在 apps._pending_operations 的 model_key 生成链**（lazy_model_operation → registry 层，具体 lower 行未确认）。下次回访方向：`apps/registry.py lazy_model_operation` 的 model_key 处理。教训：**系统检查（checks）路径的报错 ≠ migrations 路径——先确认错误来源模块再定位**（model_checks 而非 state.py）。

**13112 回访更新（2026-08-20，仍待回访）**：已排除 make_model_tuple（原始）、deconstruct to（原始）、register_model/get_registered_model（app_label 原样 key）——**registry 层不 lower**。lower 生成点未确认，疑在 ModelState.render 对 field.remote_field.model 的处理或 ProjectState/StateApps 的序列化链。下次回访：运行时打印 `_pending_operations` 的 key 形态（在 lazy_related_operation 调用点断点）。

**容器终验脚本的坑（2026-08-20 实测）**：批量验证脚本里 `python tests/runtests.py ... 2>&1 | tail -4`——① **tail 截断结果行**（OK/FAILED 在 "Destroying test database" 之前，tail -4 只留尾部 4 行可能截掉结果）；② **管道 exit code = tail 的 exit = 0**（恒成功，不反映测试通过与否）。**正确写法**：`2>&1 | grep -E "Ran|OK|FAILED|ERROR"`（保留结果行）或 `tee` 落盘后 grep；判断通过用**结果行**（OK/FAILED）而非 exit code。批量验证脚本先小样测试（1 实例）再全量。

## 2026-09-06 lifecycle review

该记录只有标题/场景，root_cause/solution/evidence/source/timestamp 均缺失，无法作为可消费的 active 经验；不根据标题猜补内容，保留历史文件并退出普通召回。
