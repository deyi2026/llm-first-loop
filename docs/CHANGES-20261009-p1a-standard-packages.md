# CHANGES-20261009: P1-A 标准包层（feat/p1a-standard-packages）

设计依据: `DESIGN-20261009-plugin-ecosystem-integration.md` §5/§6/§8.3/§9/§10.2/§11（P1-A 行）
审查修订: `DESIGN-20260109-plugin-ecosystem-integration-REVIEW.md`（已并入设计）
分支: `feat/p1a-standard-packages`（基于 `feat/p1b-mcp-protocol` 顶端 `7d8332b42`，阶段链线性）

## 新增模块

### `src/llm_loop/extensions/formats.py` — 标准包解析（T15/T16/T17）
- 固定位置 `plugin.json` / `skills/<name>/SKILL.md` / `mcp.json`；不执行包内任何代码/install hook
- 错误隔离（§6 最窄失败边界）: 无效 manifest→整包 unavailable；单技能/单服务器错误→组件级
  invalid/unsupported/needs_configuration，其余有效组件保留；mcp.json 整体坏→degraded（overall 至少 partial）
- 非致命: 未知顶层字段、extensions 非对象、schema_version 缺失/未知 → warning（T15）
- T17: 越界引用与符号链接越界→组件 invalid；`PLUGIN_ROOT`/`PLUGIN_DATA` 占位符仅验证拼写
  （未识别→needs_configuration），不展开不 shell 求值；env/headers 值不进组件记录
- §10.2: 单包组件 ≤200（截断+warning）；description ≤2KB
- `CompatibilityReport`: 组件级 supported/needs_configuration/convertible/unsupported/invalid
  + 总状态 ready/partial/unavailable

### `src/llm_loop/extensions/store.py` — 安装记录（T19/T21/§9.1）
- 布局（`RuntimePaths.extensions_dir` = `<data_dir>/extensions` 派生，无独立 env）:
  `installed.json`（权威）/ `packages/<digest>/`（不可变副本）/ `instances/<install_id>/data/`（PLUGIN_DATA）/ `locks/`
- 单一写路径 `_commit()`: flock 独占 → 读 revision → expected_revision CAS
  （不一致→`RevisionConflictError`，晚到提交失败）→ 变更 revision=N+1 → tmp+`os.replace`+fsync → 读回校验
  （失败→`CommitUncertainError`，不假装成功）
- install_id 绑定 plugin_name（跨版本稳定）→ PLUGIN_DATA 跨更新保留（T21）；digest 变化→新不可变副本
- 同 install_id 不同 source → `InstallRejectedError`（不静默替换）
- 记录卫生: `_scan_sensitive` 序列化前扫描 token/secret/password/authorization；`installed.json` ≤4MB

### `src/llm_loop/extensions/catalog.py` — 目录与预算投影（§8.3/§10.2）
- `skills(scope)`: package-qualified ref（`pkg/name`）+ 来源标注（install_id + catalog_revision）
- `summary()`: 目录注入 ≤8KB，超限截断并标注 omitted 条数
- `skill_page()`: 原文分页 ≤64KB/页，先落盘（包副本）后投影，带 omitted_chars + next_offset
- `servers(scope)`: MCP 服务器登记（P1-C 才接线执行）
- 事实源=不可变包副本（非安装源目录）

## 修改

### `src/llm_loop/skills/loader.py` — 标准解析（T18/§5.2/§11.1）
- 标准 YAML frontmatter（多行，`yaml.safe_load` SafeLoader；frontmatter ≤64KB）
- 原文/解析视图分离: `raw_text`（原文全文，skill_load 用）/ `frontmatter_std` 标志
- `SkillMeta.package` + `scan_skills_dir(package=)`；`find_skills()` package-qualified 精确 + 裸名全部候选
  （冲突返回候选，不静默择一）；`find_skill` legacy 兼容保留
- 无 frontmatter / 非法 YAML → legacy 路径（极简解析降级，fail-open 零回归）
- PyYAML 缺失自动降级（不硬崩）；`pyproject.toml` 声明 `pyyaml>=6.0`

### `src/llm_loop/introspection/tools_skill_files.py` — 工具合并扩展目录
- `skill_list`: 本地技能 + `[已安装标准包技能]` 段（ref + install/rev 来源标注）
- `skill_load`: `pkg/name` → 扩展目录原文分页（provenance 头 + §8.3 污点声明 + 分页元数据）；
  裸名冲突 → 列出全部候选；dsh: 路由与 skill_execution_facts 保留
- 宿主无 catalog / catalog 异常 → fail-open 仅本地技能（零回归）

### `src/llm_loop/introspection/corrections.py` / `src/llm_loop/factory.py` / `runtime/paths.py`
- `CorrectionToolRegistry._extensions_catalog`（`_PUBLIC_MAP` 暴露 `extensions_catalog`）
- factory 装配 `ExtensionStore(RuntimePaths.extensions_dir)` → catalog 注入（try/except fail-open）
- `RuntimePaths.extensions_dir` property（`<data_dir>/extensions` 派生，来源固定）

## 测试（新增 6 个文件 + fixture 包）
- `test_extensions_formats.py`: T15 非致命字段 / T16 组件隔离 / T17 越界与占位符 / §10.2 上限 / 总状态
- `test_extensions_store.py`: 安装布局 / T19 CAS 晚到失败与顺序成功 / T21 数据跨更新 / source 冲突 / 敏感扫描 / 损坏状态拒绝
- `test_extensions_catalog.py`: 来源标注 / 8KB 预算截断 / 64KB 分页 / 禁用排除
- `test_skills_loader_std.py`: T18 多行 YAML / legacy 降级 / 64KB 限制 / package-qualified 与冲突候选
- `test_skill_tools_p1a.py`: 装配闭环（install→list→load，使用回执可查）+ 零回归 + paths 派生
- fixture: `tests/fixtures/std_plugin_demo/`（plugin.json + 2 技能 + mcp.json）

## 边界与遗留
- MCP 服务器组件仅登记（接线执行属 P1-C 装配: register_mcp_tools 合并 installed + MCP_SERVERS legacy，
  身份冲突报告——TASK-004 剩余部分随 P1-C 收口）
- 安装动作 P1-A 为代码 API（`ExtensionStore.install`）；§13 人工确认/配额/白名单工具接口随 P1-C
- epoch / OAuth / 常驻订阅（P1-B 余项）不变
