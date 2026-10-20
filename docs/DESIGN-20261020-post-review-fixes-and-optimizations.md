# DESIGN-20261020 审查后修复与优化需求设计书

- 来源：v0.6.33→v0.6.36（10-17 至 10-20，73 commits）审查结论（1 确认 bug + 2 观察 + 7 优化建议）
- 设计方法：两轮 grill_me 强制盘问 + 锚点机械重验（本会话内全部重新核实，不依赖审查会话记忆）
- 状态：设计定稿，待实施。D1 为 P0。

---

## 0. 证据锚点（本会话重验，全部属实）

| 锚点 | 事实 | 验证方式 |
|---|---|---|
| `src/llm_loop/terminal/queries.py:87` | `supplied.workspace or values.get("LFL_WORKSPACE_ROOT") or Path.cwd()`，env 压过 cwd | read_file |
| `src/llm_loop/terminal/queries.py:357-359` | env 存在即 `workspace_explicit=True` → `require_registered` | read_file |
| `src/llm_loop/terminal/records.py:18-31` | 注册表存在且 workspace 未注册时**无条件** raise（`:30`，与 require_registered 无关） | read_file |
| `src/llm_loop/runtime/service_control.py:2635` | 派生服务进程注入 `"LFL_WORKSPACE_ROOT": code_root` —— **泄漏源头** | search_files |
| `src/llm_loop/runtime/identity.py:19-21,82-91` | env 为 tier1 显式源，cwd-upward 为 fallback；**部署契约，不改** | read_file |
| `src/llm_loop/runtime/resolver.py:663-680` | `LFL_RUNTIME_ROOT` 已优先，`LFL_WORKSPACE_ROOT` 仅历史 fallback；**不改** | read_file |
| `src/llm_loop/cli.py:1104-1120` | 服务启动绑定路径 env 优先并回写 bindings；**不改** | search_files |
| `src/llm_loop/subagent/runner.py:2451-2566` | `_bounded_child_wire` docstring 承诺"拒绝静默截断"，`:2563-2566` 的 `isinstance(m, dict)` 却静默丢项 | read_file |
| `tests/conftest.py:133-192` | 部署泄漏隔离批次1-4（web auth / compact / provider admin / task budget canary），autouse delenv 模式 | read_file |
| `tests/unit/test_terminal_cli.py:317` | sigterm 信号类测试锚点 | search_files |
| `scripts/check_static_diagnostics.py:26,95,132` | r9-static-diagnostic-ratchet/v1，count-ratchet + 900s 墙钟预算注释 | search_files |
| `src/llm_loop/web/__init__.py:454-476` | KnowledgeScoreLoop，env 可调 interval/batch | search_files |
| `src/llm_loop/runtime/briefing.py` | 安装简报生成入口 | search_files |
| `src/llm_loop/memory/evidence_legacy.py` + `session_lifecycle.py:180-183` | legacy sidecar 迁移与挂钩点 | search_files |

**携带值待复测**（审查会话实测，本设计未复测，实施第一步先复测再定预算）：
- legacy sidecar ~700 个全量扫 ~30s、web ready 预算 90s（注意与 pyright 的 900s 是两回事）。
- 审查期实测：LFL 运行时内跑 pytest，`test_terminal_cli.py` 8 例确定性失败；剥离 env 后 180 全过。

---

## 1. D1【P0】`LFL_WORKSPACE_ROOT` 双语义拆分（B1 环境泄漏）

### 问题
同一变量承载两种语义：**部署绑定**（服务进程知道自己的 code root）与**用户 workspace 选择**（我坐在哪个 workspace 查询）。web 终端/execute_command 派生 shell 继承部署绑定值（`.releases/<hash>`），查询 CLI 把它当用户选择，导致：硬失败"Workspace is not registered"或在已注册目录下**静默列出错误 workspace 的会话**。

### 目标
交互式只读查询按用户所在位置解析 workspace；部署绑定语义零改动。

### 非目标
- 不改 identity.py 守卫、resolver.py、cli.py 服务路径（部署契约）。
- 不重命名/废弃 `LFL_WORKSPACE_ROOT`。
- 不做写路径（查询全部只读）。

### 方案
1. **优先级反转（仅 queries.py）**：`--workspace` > cwd 向上找 `pyproject.toml`（与 identity.py:87-91 同构）> ambient env（stderr 警告"使用部署绑定"）> 裸 cwd。所有值经 `str(v or "").strip()` 归一；`--workspace=""` 视为未提供并告警。
2. **`workspace_explicit` 重定义**：仅 `--workspace` 触发；env 存在不再隐式升级 `require_registered`。
3. **歧义诊断兜底（exit 3）**：cwd-upward 解析结果 resolve() 后 == ambient env 值（web 终端 cwd 位于 `.releases/<hash>` 部署根内的典型场景）→ 不猜测，stderr 输出两候选 + `--workspace` 用法示例，exit 3。比较必须用 `Path.resolve()` 后的路径，规避字符串/symlink 差异误判。exit 3 需同步 CLI help 与文档（防脚本把 3 当通用错误）。
4. **降级列举防跨租户枚举**：workspace 未注册时降级到 `data/sessions` 根列举**仅当注册表 workspace 总数 == 1**（输出 `degraded:true` + stderr 警告）；总数 >1 时拒绝，只报数量不列路径，提示 `--workspace`。依据：`_check_owner` 只护单会话读取，根列举会暴露全部 workspace 的会话 ID/标题。
5. **conftest 批次5**：`_DEPLOYED_WORKSPACE_IDENTITY_VARS = ("LFL_WORKSPACE_ROOT",)`，autouse delenv，沿用批次1-4 模式。已核实 6 个依赖该变量的测试文件均走测试体内 `monkeypatch.setenv`，不受影响。

### 验收
- T1 env=/nonexistent + cwd=已注册 workspace → 解析到 cwd workspace。
- T2 env=部署根 + cwd 在部署根内 → exit 3，两候选可见。
- T3 未注册 cwd + 注册表 1 个 workspace → 降级列举，`degraded:true`。
- T4 未注册 cwd + 注册表 2 个 workspace → 拒绝，无路径泄漏。
- T5 `--workspace` 压过一切。
- T6 LFL 运行时内跑 pytest：terminal CLI 测试全绿（原 8 failed → 0）。
- T7 identity/resolver/cli 服务路径既有套件零回归。
- T8 `sessions show <id>` 在降级/拒绝路径下行为与列举一致（不出现列举拒绝但 show 放行的旁路）。

### 回滚
纯代码改动，查询只读无数据风险；revert 即回滚。不设 feature flag（避免新增配置面）。

---

## 2. D2【P1】`_bounded_child_wire` 投影契约（B3）

- **方案**：投影后全量校验 dict；任一违规 → `return [], f"投影契约失败(第{N}项 type={type(m).__name__})"` + ERROR 日志（有界 repr）。不发送、不静默丢弃，兑现函数自身 docstring。
- **验收**：注入非 dict 项的单测 → 返回失败串含序号与类型；既有 wire 契约套件零回归。
- **回滚**：revert。

---

## 3. D3【P1】终端信号类测试偶发（B2）

- **方案**：`serial_signal` marker（conftest 路径清单单点打标，沿用 tier0 模式）+ xdist 排除 + 时限 2x。**验收改为可执行口径**：本地脚本连续 50 次 + nightly CI stress job；push CI 零增量成本（第一轮拷问盲点：原"连续50次"在 push CI 不可执行）。
- **回滚**：marker 移除即回滚。

---

## 4. D4【P2】CI ambient-env 门禁 job

- **方案**：新增 job，以 ambient 变量（`LFL_WORKSPACE_ROOT=/tmp/fake-release-root` 等）预设跑 terminal/runtime/workspace 相关切片（~300 例，非全量控成本）。**变量清单从 conftest 批次常量自动派生**（import tests.conftest 读取批次元组），防第二处手工清单漂移。
- **验收**：D1 落地后全绿；**变异验证**——临时恢复 ambient 依赖，job 必须变红（证明真的能抓到 B1 这类回归）。
- **依赖**：D1（conftest 批次5）。

---

## 5. D5【P2】legacy sidecar 冷启动：惰性迁移优先

- **第一性方案（拷问修订）**：把"启动全量扫"改为"**首次访问按需迁移**"（挂钩点已存在：`session_lifecycle.py:180-183`），web ready 不再等待扫描。
- 增量索引（`path→(mtime,size)` + 短校验）仅作首次访问延迟加速器；索引写失败/校验失败 → 回退按需全量扫 + 告警，**绝不阻断**；索引 tempfile+`os.replace` 原子替换，多进程最后写者胜。
- **验收**：ready <10s（带 legacy 语料 fixture）；索引损坏回退测试；首次访问 P95 <1s。
- **实施前置**：复测 "~700 项 / ~30s / 90s 预算" 携带值，据实修正目标。

---

## 6. D6【P2】pyright ratchet 语义化

- **方案**：count-ratchet 保持硬门禁；900s 墙钟降级为 advisory 遥测字段（写入 ratchet 报告，不拦截）。不改 runner 规格（成本高收益低，拷问决策）。
- **验收**：以代码审查 + 报告字段存在性为准；既有 ratchet 套件零回归。

---

## 7. D7【P2】检索两段式：词法粗筛 + 语义重排

- **方案**：现有中文二元组粗筛 top-N（默认 200）→ embedding 重排 top-K（默认 20）。
- **安全边界（拷问新增）**：默认**本地模型**（vendored 或首启下载至缓存，版本锁定，体积预算 ≤50MB，平台矩阵为实现期决策点）；API 模式需显式 opt-in + 文档警示内容出网。
- **韧性**：模型缺失/加载失败 → 降级纯词法并在结果标记 `semantic_unavailable`（不失败）；向量缓存 keyed `(text_sha256, model_id)`，tempfile+replace 原子写，读失败=miss。
- **验收**：离线环境 gold/filler 判别 AUC 显著高于词法基线（S0/S1 复测集，filler 翻 21 的病灶）；既有检索套件零回归；首查 P95 含推理时间仍达标。

---

## 8. D8【P2】knowledge_score 接入 briefing

- **方案**：`runtime/briefing.py` 安装简报增"知识健康度"段 ≤3 行（最新分、Δ、趋势符号）；分数文件缺失或超 TTL → 整段省略；不含任何会话内容。
- **验收**：briefing 快照测试更新；TTL 过期省略有测。

---

## 9. D9【P3】文档与入口

- CLI help 写明 workspace 解析优先级与 exit code 语义（含 3）。
- README/CLAUDE.md 钉死测试入口 `uv run python -m pytest`（防裸 PATH 选错解释器，审查期 32 个 Crypto 收集错误即此因）。
- changelog 注明：v0.6.36 webui 提交的实际产物在独立 repo，本 mirror 仅含 docs/pyproject 变更。

---

## 10. 拷问记录（两轮 grill_me + 残余自检）

| # | 盲点 | 落点 |
|---|---|---|
| 1 | cwd-upward 命中 `.releases/<hash>/pyproject.toml`，web 终端 cwd 在 code root 时修复失效 | D1.3 歧义诊断 exit 3 |
| 2 | 未注册降级列举暴露全部 workspace 会话（跨租户枚举） | D1.4 单注册才降级 |
| 3 | embedding 内容出网 | D7 默认本地 + opt-in |
| 4 | 启动扫提速治标，惰性迁移才是本解 | D5 重写 |
| 5 | 空串/空白 env 与 `--workspace=""` 语义 | D1.1 strip 归一 |
| 6 | CI ambient 清单手工维护必漂移 | D4 从 conftest 派生 |
| 7 | "连续50次"验收在 push CI 不可执行 | D3 改本地+nightly |
| 8 | 路径比较需 resolve() 后值（symlink/字符串差异） | D1.3 |
| 9 | exit 3 需同步文档防脚本误判 | D1.3 + D9 |
| 10 | 本地模型体积/平台矩阵未定 | D7 实现期决策点 |

## 11. 实施顺序与依赖

```
D1(P0) ──► D4(P2, 依赖 conftest 批次5)
D2(P1) ──► 独立
D3(P1) ──► 独立
D5/D6/D7/D8(P2) ──► 相互独立，D5 前置复测
D9(P3) ──► D1 落地后收尾（help 文案含最终优先级）
```

建议拆分：D1 一个 PR（queries.py + records.py + conftest + 测试），D2/D3 各一个小 PR，D4 跟随 D1，P2 项按价值排序 D7 > D5 > D8 > D6。

## 12. 开放问题（实施期决策）

1. D7 本地模型选型（尺寸预算内判别力最优）与 wheels 平台矩阵。
2. D5 复测后若真实扫描成本远低于携带值，惰性迁移仍做（体验收益独立于成本），索引优先级可降。
3. exit 3 是否扩展到其他歧义类错误（本次不扩，观察使用情况）。

