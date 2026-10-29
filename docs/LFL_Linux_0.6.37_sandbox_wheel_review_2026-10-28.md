# LFL Linux / macOS 0.6.37：沙盒、wheel 资源与自检一致性跨平台审查建议

- 日期：2026-10-28（21:45 v2 拷问修订；22:17–22:36 v3 Linux 现场取证与 wheel 旁路 E2E；v4 增补 macOS 审查和最新分支复核；23:47 v4.1 勘误提交归因并更新至 ce22e2912）
- 性质：**只读分析 / 修复建议**；本报告不代表已落地、已审查 PASS、已通过 R9 或已推送发行。
- 依据：用户提供的 Linux 现场报告、v3 Linux 现场回执、v4 只读核对的 Mac 开发仓库代码及已有 Mac 沙盒事故 Experience。
- 核验范围注意：**v3 已于 2026-10-28 22:17–22:36 连接 Linux 现场（ssh 只读探测 + fix wheel 旁路验证，见 §2.5/§2.6）**；仍未读取 `<home>/lfl-workspace/rules-version-wheel-layout.patch` 原文，17 项失败集未独立复跑。活动 Linux 0.6.37 的 `rules_version` 当时确为空。**v4 Mac 结论基于源码与已有实测 Experience；未对签名、公证后的正式 Mac 安装包进行新的真机 E2E。**
- 仓库快照：初稿为 `feat/web-model-admin-ship-20261028@99b250121f`；v2 为 `fix/rules-version-wheel-install-20261028@19758ec79`，落地 6 文件打包与版本入口修复（原补丁未读，不能认定同一性）。**v4 复核快照 `fix/rules-version-wheel-install-20261028@2c569426466b`**：`installation.rules_doc_candidates()` 已删除 `sys.prefix` / site-packages 回退，`tests/unit/test_rules_version_resolution.py` 已补三项负向测试（v4.1 勘误：该修复实际由 `ae62c6cab` 提交，`2c5694264` 仅为 docs 样式提交，快照点已包含前者）；**23:33 `ce22e2912` 已将 `cli.check_install()` required 纳入 lite 并按版本门控**（manifest 显式列 lite，或版本 ≥ `LITE_RULES_MIN_VERSION=0.6.38`；同号 0.6.37 pre-fix 存留版降级 warn 不阻断）。本报告在 v4 核对时为 Git untracked；§2.5/§2.6 保留历史时点的事实，不等于已正式发行。

## 1. 核心结论

问题不是“沙盒必须放宽”，而是三层边界被混淆：

1. **程序资源层（Linux/Mac 共性）**：wheel 模式 `rules_version` 为空的直接成因是 lite 未打包和版本读取路径错误。`19758ec79` 已补清单与统一入口，**`ae62c6cab` 又删除 `sys.prefix`/site-packages 回退并补三项负向测试**（v4 原误记为 `2c569426`，见 §0 勘误）；`ce22e2912` 已将 lite 纳入 `check-install` required 版本门控，真实 wheel smoke 与 pre-fix 升级/回滚互操作的正式成品验收仍待完成（§9.5-1）。
2. **Agent 工具层**：Agent 的工作区文件工具没有权限直接读取 release 目录，不等于程序级规则查询接口不可用。不能用 `read_file` 被拒推导出“规则真值源不存在”。
3. **诊断/安装层**：`doctor` 已能索引规则/方法/技能，`check-install` 已有 manifest 哈希验证，安装器也已调用 `check-install`，但它们尚未强制/直观证明 `ai_rules.lite.md` 的存在、版本解析，以及规则正文检索通道的一致性。**拷问新增（盲点 3，最高风险）：`install_linux.sh:582` 升级前会重新校验当前活动版本、`:540` 回滚前会校验回滚目标，两者都以 `check-install` ok=true 为硬门——若简单把 lite 加入 required，从/回滚到任何 pre-fix 存留版本都会被旧 manifest 阻断，升级路径被砖化。必须版本门控。**

4. **Mac 执行权限层**：`execute_command` 将 `workdir` 当作 `sandbox-exec` 可写根，`read_file(snapshot=true)` / `edit_file` 则受 `workspace_base()` 约束；外层 MCP Console、内层 LFL 沙盒和宿主 TCC/服务控制权限再叠加，导致误拦截及 shell 绕行。与 wheel 资源缺陷是**两条独立故障链**。

**决策建议：保留 Linux wheel 最小补丁独立收口，不用 Mac 权限改造阻塞它；Mac 另做有边界的工具一致性修复，共用跨平台成品验收。** 新 wheel 严格检查 lite，旧 0.6.37 存留包按受信安装身份兼容；Mac 将命令 cwd 与已授权写入根拆开，复用工作区注册、`doctor`、`check-install` 和正式服务控制接口。

## 2. 代码证据与诊断修正

| 源码（历史 v2 快照 `19758ec79`；当前 delta 以 §9.5 为准） | 当时观察 | 含义 |
|---|---|---|
| `src/llm_loop/introspection/status.py:941-952` | `_rules_version()` 直接 `return rules_version()`（fail-open 包裹） | 已收敛到唯一入口；初稿所述 `parents[3]` 直推算法已不存在 |
| `src/llm_loop/runtime/causality.py:61-64` | 同样委托 `installation.rules_version()` | 已收敛；两读取点与索引同源 |
| `src/llm_loop/runtime/installation.py:40-79` | 新增 `rules_doc_candidates()` + `rules_version()`；候选序：bundle 根 → 源码根 `parents[3]` → **`sys.prefix/docs` → `site-packages/docs`（回退根仍在）** | 统一入口已建；**但拷问盲点 1：回退根未删，`_bundled` 损坏而 venv/docs 恰有旧 lite 时会读到值、掩盖 bundle 损坏——与初稿 §3.2 自己的告诫相悖，属剩余修复项** |
| `setup.py:12-15` 与 `MANIFEST.in:3` | 均已包含 `docs/ai_rules.lite.md`（`19758ec79` 落地） | 打包遗漏已修复；有 `test_wheel_payload_ships_lite_rule_file` 源文本断言 |
| `src/llm_loop/cli.py:1184` | （v2 历史快照）`required` 仅 `{"docs/ai_rules.md", "webui/dist/index.html"}` | v4.1 更新：`ce22e2912` 已按版本门控纳入 lite——manifest 显式列 lite 或版本 ≥ 0.6.38 才强制，缺 lite 的新格式 wheel 会 fail，pre-fix 存留版降级 warn（见 §3.4 任务 2 / §9.5-1） |
| `src/llm_loop/runtime/doctor.py:156-189` | `inspect_installation_assets()` 实际统计规则/方法/经验/技能，warn/pass 分级 | “doctor 只查路径存在”不准确；应在现有检查上补充版本/可检索性字段 |
| `src/llm_loop/introspection/search.py:259-261` | `bundle_root() or parents[3]` 定位规则正文索引 | 与 wheel 真实布局一致，无需改动 |
| `scripts/install_linux.sh:277-291` | `verify_release_dir` = wheel SHA + `lfl --version` + `check-install` ok=true 硬门 | 不必重建安装事务 |
| `scripts/install_linux.sh:540,582` | **回滚前校验回滚目标、升级前重新校验当前活动版本**（均走 `check-install` 硬门） | **拷问盲点 3：required 加 lite 若无版本门控，会把从/回滚到 pre-fix 存留版本的路径全部阻断** |
| `tests/unit/test_rules_version_resolution.py` | 4 个用例：源码解析、fake-bundle 解析、两读取点同源、源文本打包断言 | **拷问盲点 2：monkeypatch 只换 bundle 根，测试进程仍在源码检出内、回退根可达，抓不住“回退根遮蔽损坏”场景；无真实 wheel 构建产物检查** |
| `docs/ai_rules.md:1-6` 与 `docs/ai_rules.lite.md:1-6` | `ai_rules.md` 是规则 SoT；`lite.md` 为 Agent/维护 playbook，头部 `version=20` | `rules_version=20` 不等于全文指纹；判正文一致性用 manifest 内 `docs/ai_rules.md` 的 SHA-256 |

另需纠正：Linux 报告中 8/13/37 的索引数量**只能辅助证明资源形态相近**，不能单独证明为同一个 release/wheel。正式同一性用 `lfl --version`、安装包 SHA-256、`check-install`、实际 `llm_loop.__file__`、manifest version/hash 交叉核验。

> **拷问口径说明（v2）**：版本解析正则 `version\s*=\s*(\d+)` 取前 512 字符首个匹配，返回字符串；`version=020` 会原样返回 `"020"` 与 `"20"` 不等——若做严格相等比较应先 `int()` 归一（小项，随手修）。`rules_version()` 全失败静默返回 `""` 无原因码，运行态可接受（向后兼容），诊断态必须给 `error_code`（§4.2）。

### 2.5 Linux 现场实测（2026-10-28 22:17–22:36，ssh 只读探测）

| 现场（yyj@192.168.3.164，Deepin） | 实测回执 |
|---|---|
| 活动 release | `<home>/.local/share/lfl/releases/LFL-0.6.37`，venv 为 python3.13，`lfl --version` = 0.6.37 |
| 原始 wheel | `llm_first_loop-0.6.37-py3-none-any.whl`，5,747,264 B，sha256 `e3de7657fc5db8cbbab7406a4f527e800f93881c035e15d282157457599bce20`（10-28 14:21） |
| 现场 `causality.py:62-70`（pre-fix 存留） | `workspace = Path(llm_loop.__file__).resolve().parents[2]` → `site-packages/docs/ai_rules.lite.md` 不存在 → `OSError` → 返回 `""` |
| 现场 `installation.py`（pre-fix 存留） | 仅 35 行、2 个函数（`bundle_root`/`installed_identity`），**无** `rules_doc_candidates`/`rules_version`——与 fix 分支结构不同，升级/回滚互操作须按此现状设计 |
| 活动版本实测 | 活动 venv 中 `causality._rules_version()` 返回 `''`（bug 现场成立） |
| `path_registry.json` | `<home>/lfl-workspace/docs/ai_rules.md` 记录 `exists:false`（source=tool:query.stat）；且 `~/lfl-workspace/docs/` 目录本身不存在——该缓存是真阴性，与本 bug 正交 |

### 2.6 fix wheel 现场 E2E（2026-10-28 22:33–22:36，旁路安装，未动活动版）

- **构建与传输**：fix 分支 `19758ec79` 本地 `uv build --wheel` → `llm_first_loop-0.6.37-py3-none-any.whl`（5,908,041 B，sha256 `47958304e11ce37a4b9b0a13943fabc2cec96125286e5d0b695d72450cd22990`）；wheel 内确认含 `llm_loop/_bundled/docs/ai_rules.lite.md`（4,681 B）、`_bundled/docs/ai_rules.md`（98,174 B）、`_bundled/manifest.json`；scp 后远端 sha256 与本地一致。
- **旁路安装**：现场 `python3 -m venv ~/lfl-fixtest` + `pip install --no-deps --ignore-requires-python`（现场系统 python3 为 3.12.13，而 pyproject 要求 ≥3.13；活动 release venv 本身是 3.13，正式升级路径不受此影响；探测模块 import 面为纯 stdlib + llm_loop 自身）。
- **探测回执**（同一解释器）：`bundle_root()` = `~/lfl-fixtest/…/site-packages/llm_loop/_bundled`；`rules_version()` = `'20'`；`causality._rules_version()` = `'20'`；`status._rules_version()` = `'20'`；`lite exists: True`（文件头即 `# docs/ai_rules.lite.md — Agent/维护 playb…`）。
- **对照与未动确认**：同一探测在活动 0.6.37 venv 中仍返回 `''`；活动 release 原始 wheel 未变（大小/sha/14:21 时间戳不变），`lfl --version` 仍 0.6.37。
- **定位**：这是旁路 smoke，回答"fix 装上后 Linux 现场能否解析出版本"；未覆盖 §5 验收矩阵的 `-I`/离仓库/`PYTHONPATH` 剥离与全量门禁层级。**未部署、未切指针、未重启**；现场遗留 `~/lfl-fixtest` venv 与 `/tmp/llm_first_loop-0.6.37-py3-none-any.whl` 可随时清理。

## 3. P0：最小必要代码修复（v2 改写：已完成主体 + 剩余 delta）

初稿三项 P0 的前两项主体已由 `fix/rules-version-wheel-install-20261028@19758ec79` 落地；本节改写为剩余增量。

### 3.1 打包清单 —— 已完成，余一口

- 已完成：`setup.py` DOCS 与 `MANIFEST.in` 均含 `ai_rules.lite.md`（`19758ec79`），并有 `test_wheel_payload_ships_lite_rule_file` 源文本断言；版本头解析已复用 `rules_version()` 唯一实现，无第二套正则。
- **剩余**（v2 历史快照）：`check_install()` 的 `required` 未加 `docs/ai_rules.lite.md`——**该代码修改已由 `ce22e2912` 完成**（版本门控同上）；任务 2 剩余的是验证部：真实 wheel/独立环境 smoke 与 pre-fix 升级/回滚互操作验收（§9.5-1）。
- 不改变 `ai_rules.lite.md` 的身份：**维护 playbook 仅作为资产和诊断依据，不注入普通用户每轮 prompt**。保留既有 prompt 瘦身测试。

### 3.2 唯一版本解析入口 —— 主体已完成，回退根未收敛（盲点 1）

- 已完成：`runtime/installation.py` 的 `rules_version()` 是唯一实现，`status`/`causality` 均直接委托。
- **剩余**：`rules_doc_candidates()` 仍含 `sys.prefix/docs` 与 `site-packages/docs` 回退根，且候选选择是“试到找到为止”——若 `_bundled` 损坏而 venv/docs 恰有旧 lite，会从回退根读到值、掩盖安装包损坏，正是本节最初告诫的模式。应收敛为：**wheel 模式只看 `bundle_root()/docs/ai_rules.lite.md`；源码模式只看明确的源码根 `/docs/ai_rules.lite.md`**，模式确定后不跨根试探；继续排除 `sys.prefix`、任意 `site-packages`、CWD、`DATA_DIR`、用户 home 作为扫描候选。
- 运行中无法读版本维持向后兼容的空串返回；诊断接口明确原因，**不静默将缺失版本当作健康**。

### 3.3 安装验收复用现有路径 —— 现状已满足

- `verify_release_dir -> lfl check-install` 的预激活与切换后检查已实现，继续复用；必需资产缺失/损坏时切换指针前失败、保持旧版可用；DSH 网络失败、空记忆不加入阻断。
- 为避免回归，保留一个真正验证已安装 wheel 的最小 smoke，不加反复重试、多轮审批或新的常驻后台任务。

### 3.4 v2 当时剩余修复总表（历史快照；当前状态以 §9.5 为准）

| # | 任务 | 优先级 | 验收标准 |
|---|---|---|---|
| 1 | 删除 `rules_doc_candidates()` 的 `sys.prefix`/`site-packages` 回退根，模式确定后不跨根试探 | P0 | 新增负向单测（盲点 2）：monkeypatch `bundle_root→None` 且在 `sys.prefix/docs` 放置 lite，断言 `rules_version()==""`；现有 4 用例不回归 |
| 2 | `check_install` required 加 lite，**必须版本门控**：仅当 manifest version ≥ 本次修复版（或 manifest 显式含 lite 条目）才强制，对 pre-fix 存留版本降级为 warn——否则 `install_linux.sh:582`（升级前校验当前活动版）与 `:540`（回滚前校验回滚目标）会把与 pre-fix 存留版本之间的升级/回滚全部阻断（盲点 3，砖化升级路径） | P0 | 从/回滚到 pre-fix 存留 release 不被校验阻断；新版 wheel 缺 lite 仍 fail（ok=false） |
| 3 | doctor 规则资产检查补 `source_kind / rule_body_retrievable / rules_version / rule_body_sha256 / error_code`（字段与错误码全集见 §4.2），并与 `rules_version()` 同源 | P1 | 源码/wheel/损坏 bundle 三态下 doctor 输出正确的 `error_code` |
| 4 | 版本比较先 `int()` 归一（`"020"` vs `"20"` 不等） | P2 | 一行单测 |

## 4. P1：沙盒边界与可观测性（小范围增量）

### 4.1 权限模型

保持三种根目录的明确职责：

- **package/bundle root**：只读、不可作为 Agent 任意文件工具的开放工作区；通过 `search_records` / `search_docs` 等受控 API 查询规则。
- **workspace root**：供 Agent 读写用户授权的项目文件；不能从“包位于工作区外”推出软件故障。
- **data root**：可持久写会话、记忆、状态；不能写到只读安装目录。

不建议全局开启 `dangerous` 模式、放开 release 目录通配访问、给予 sudo、把 wheel 复制到用户工作区或解除系统沙盒。需要源码修改时，提供**明确范围的隔离工作树**和对应权限，而不是升级整个 LFL 安全级别。

### 4.2 诊断事实与错误分类

在既有 `doctor` 的 `context_assets` 检查附近补一条精简规则资产检查，并让 `architecture_status` 复用同一底层事实函数；推荐最少字段：

```json
{
  "source_kind": "wheel|source|override",
  "rule_body_retrievable": true,
  "rules_version": "20",
  "rule_body_sha256": "<manifest中docs/ai_rules.md的哈希或按需计算>",
  "error_code": null
}
```

- `rule_body_retrievable` 必须根据**程序真实检索路径**判断，不能只凭源目录存在或 Agent 是否能直接读。
- `rules_version` 仍是 lite 头部版本；判断**规则正文内容**是否与上一版本相同，优先使用 manifest 中 `docs/ai_rules.md` 的 SHA-256（当前打包流程已生成，不需要第二套签名体系）。如果 `DOCS_DIR` 被显式覆盖，应标记 `override`，并对实际有效文件取哈希；不要错误拿包内哈希代表覆盖文件。
- 推荐错误码区分：`asset_missing`、`asset_unreadable`、`version_parse_error`、`rule_lookup_failed`；Agent 直接读 release 被拒单列为 `sandbox_denied`，**不等价于** `asset_missing`。
- 默认输出可提供逻辑路径（如 `wheel:docs/ai_rules.md`）和哈希；本地 `--verbose` 才提供完整磁盘绝对路径，避免对普通模型不必要地暴露主机文件结构。
- `doctor` 仍保持离线、只读、不请求模型、不触发安装；结果不要注入正常会话的 prompt 前缀。

### 4.3 DSH / memory 的判定

- DSH 插件索引暂以可选网络依赖处理：提供 `network_unreachable`/`timeout` 等原因，显示可用的本地功能与降级能力，但不让它阻断 LFL 基础安装。需要进一步确认 Linux DNS/代理/证书时另行定位。
- `memory_state=0` 对全新会话可能正常；仅在字段明确表示索引健康/错误时再判故障，避免把“无记录”与“索引失败”混为一谈。

## 5. 最小验收矩阵（原有测试 + 一次 wheel 端到端 smoke）

| 场景 | 验收条件 |
|---|---|
| 源码运行 | `status` 与 `causality` 读到相同非空版本；规则检索有结果 |
| 干净 venv 安装 wheel | `env -u PYTHONPATH PYTHONNOUSERSITE=1` 且 `python -I`、工作目录离开仓库；导入来源确认是 venv/site-packages；`rules_version` 非空且一致 |
| 正文程序检索 | `search_records(kind='rule', query='RULE-AI-24', limit=3)` 或同等正式 API 返回真实规则卡；不要依赖 Agent 直接读 release |
| 完整性 | `lfl check-install` 对完好 wheel 返回 ok=true；删除/篡改 lite 或正文后返回 ok=false |
| 沙盒阻断 | 原始文件读取 release 可被拒，但**程序级受控规则检索**仍成功，`doctor` 不误判缺失 |
| 诊断口径 | `architecture_status.rules_version`、causality 和 `doctor` 版本一致；明确可读性/原因分类 |
| 可选服务断网 | DSH 索引失败只警告；离线安装自检不受影响 |
| 升级回滚 | 新候选的必需资产损坏时不激活新版本，旧安装指针与数据保留 |
| 回退根遮蔽（负向，v2） | `bundle_root()` 为 None 且 `sys.prefix/docs` 恰有 lite 时 `rules_version()==""`——防回退根掩盖 bundle 损坏（§3.4 任务 1） |
| pre-fix 存留版本互操作（v2） | required 加 lite（版本门控后）不阻断从/回滚到 pre-fix 存留 release 的升级与回滚（§3.4 任务 2） |
| 门禁 | 先定向回归与真实 wheel smoke，再独立 GLM-5.3 审查 / 原版完整 R9；不把无 git 历史导致的归档树 17 项失败直接当作主仓库豁免 |

建议核心 wheel 探针：

```bash
# 仅为验收思路：按实际 release 路径填 VENV，确认在 wheel 安装环境运行
cd /tmp
# python -I 忽略 PYTHONPATH/用户 site，同时再次去掉 PYTHONPATH 防止 CLI 受污染
env -u PYTHONPATH PYTHONNOUSERSITE=1 "$VENV/bin/python" -I - <<'PY'
from pathlib import Path
import llm_loop
from llm_loop.runtime.installation import bundle_root
from llm_loop.introspection.status import _rules_version as status_version
from llm_loop.runtime.causality import _rules_version as causal_version
root = bundle_root()
assert root is not None and (root / 'docs/ai_rules.md').is_file()
assert (root / 'docs/ai_rules.lite.md').is_file()
assert 'site-packages' in str(Path(llm_loop.__file__).resolve())
assert status_version() and status_version() == causal_version()
print('wheel assets and rule version: PASS', status_version())
PY
```

## 6. 对现有补丁与 EVO 的收口建议

1. **v2 状态更新：修复分支已存在并落地主体**。`fix/rules-version-wheel-install-20261028@19758ec79` 的改动面与“6 文件补丁”同构（未读补丁原文，不作同一性断言）；初稿“不要在 feat 分支直接 `git apply`”的告诫已被取代。剩余动作收敛为：在 fix 分支完成 §3.4 任务 1-4，再走门禁合并。
2. **核对修复分支与补丁意图的差异**：当前 `rules_doc_candidates()` 仍含 `sys.prefix`/`site-packages` 回退根，与初稿 §3.2 告诫冲突，需确认是有意保留还是落地遗漏；`check_install` required 未加 lite。若确需与补丁原文比对，从最新主线建隔离 worktree、`git apply --check` 冻结 SHA 后只读核对；原归档树 `f5fec37c1` 不自动等同于当前主线。
3. **合并重复 EVO**：`EVO-20261028-75b3a730` 的安装诊断改进保留最小范围，优先复用 `doctor`/`check-install`；不另建新的广义“沙盒治理平台”、权限代理、定时巡检或审批级联。
4. **验证并发布**：在正式 GLM-5.3 独立审查 PASS（P0/P1=0）、原版完整 R9 退出码 0、真实 wheel/安装器验收 PASS 后，按用户授权走 main 集成与后续发布。分析阶段不擅自 push、重启或发布。

## 7. v2 历史执行任务（勿直接重放；现行指令以 §9.5 为准）

> 目标：最小修复 Linux wheel 的规则版本空值与误诊，避免过度工程化。保留沙盒，不新增宽泛权限。
>
> 1. **v2 起点**：`fix/rules-version-wheel-install-20261028` 已完成打包与唯一版本入口（§3.1/§3.2 主体），勿重复实现；剩余任务即 §3.4 总表，按序执行。**fix wheel 已在现场旁路 venv 通过 E2E（§2.6，三处读取点均返回 '20'）；现场活动 0.6.37 为 pre-fix 存留结构（§2.5：causality 直推 site-packages 路径、installation.py 无版本入口），升级/回滚互操作按该现状设计，勿假设现场已含 fix 分支结构。**
> 2. 删除 `rules_doc_candidates()` 的 `sys.prefix`/`site-packages` 回退根；补负向单测——monkeypatch `bundle_root→None` 且在 `sys.prefix/docs` 放置 lite，断言 `rules_version()==""`（防回退根掩盖 bundle 损坏）。
> 3. `check_install` required 加 lite 并**版本门控**：manifest version ≥ 修复版（或 manifest 显式含 lite 条目）才强制，pre-fix 存留版本降级 warn；验收 `install_linux.sh:540/582` 的升级/回滚路径不被阻断。
> 4. 复用 `doctor` 已有资产索引结果，补充“正文是否能通过真实程序接口检索”“版本值/解析错误原因”（`error_code` 区分 asset_missing/version_parse_error/sandbox_denied 等）。通过 Agent 原始文件工具被沙盒拒绝时，不得误报规则缺失。
> 5. 真实 wheel smoke 使用独立 venv、工作目录离仓库、`env -u PYTHONPATH` 和 Python `-I`；增加缺失/损坏文件与沙盒拒读回归。DSH 断网/新会话空 memory 不作为安装阻断。
> 6. 同一候选完成定向回归、独立 GLM-5.3 审查 PASS、原版完整 R9、Linux 安装/回滚（含 pre-fix 存留版本互操作）验收；只报告真实回执。未经本轮单独授权不得 push、合并 main、部署或重启。

## 8. 不建议做的事

- 不要为读规则而取消 Agent 沙盒或将 release 目录开放给所有文件工具。
- 不要增加 `sudo`、系统级服务、后台轮询或依赖在线网络的启动自检。
- 不要把规则计数相同视为发行包身份认证。
- 不要把 `lite` 的版本号 20 视为 `ai_rules.md` 全文未变化的证明。
- 不要因同一类失败重复跑多次全量 R9；一次有效、可核验的完整门禁回执加真实 wheel smoke 更有价值。
- 不要在无版本门控的情况下把 lite 加入 `check-install` required 上线——会把与 pre-fix 存留版本的升级/回滚路径全部阻断（§3.4 任务 2，拷问盲点 3）。

**最终落地标准**：程序确实可以检索规则正文；版本和正文哈希可追溯；Agent 仍不可任意读受保护的 release 目录；`check-install` 在安装前阻止必需资产损坏的候选；正常用户无需额外操作或审批。

---

## 9. v4 补充：Mac 沙盒专项审查（2026-10-28）

本节补充 **macOS 开发/维护工具的执行权限链**；§2.5/§2.6 的 Linux 现场数据原样保留。Mac 侧的观察来自源码、已有实测 Experience 和测试设计，**不是新一轮生产宿主实操回执**。必须区分四层边界：安装包内只读资源、LFL 会话工作区工具、MCP Console 外层通道沙盒、macOS 系统 TCC/签名/Keychain/服务权限。

### 9.1 逐项证据与裁决

| 证据定位 | 事实 | 裁决 / 影响 |
|---|---|---|
| `src/llm_loop/config.py:52-56`；`tools/sandbox.py` | `EXEC_SANDBOX=auto`；Mac 优先 `sandbox-exec`，采用 `(allow default)(deny file-write*)` + 指定写入根；**不隔离一般读和网络** | 不能声称是完整的安全沙盒；不能靠全局关沙盒修复使用问题 |
| `tools/builtin/execute_command.py:555-567, 740-750`；`tools/sandbox.py:260-305` | `workdir` 主要检查目标是已有目录，随后被加入沙盒可写根；`cd` 只改变进程 cwd，不更新原先写入白名单 | **Mac P0：执行位置被误用为写入授权**。会误拒合法跨目录任务，也可能让更宽的 `workdir` 扩大写面 |
| `tools/builtin/read_file.py`；`workspace/file_service.py:135-145`；`tools/builtin/edit_file.py` | `read_file(snapshot=true)`、版本化 `edit_file` 经 `workspace_base()` 及 `WorkspaceScopeMismatch` 限制；命令工具与文件工具权限口径不同 | **Mac P0：被迫改用 shell patch/printf**，绕开正式 snapshot→expected_snapshot_ref 一致性工作流 |
| `experiences/EXPERIENCE-20261026-macos-sandbox-exec-下写仓库须显式-workdir-参数-cd-不等效.md`；`EXPERIENCE-20261028-execute-command-的-workdir-参数会绑定沙箱写权限-不给-workdir-时工.md` | 历史实测 `touch` 跨根 EPERM；显式 `workdir` 后成功；文件编辑工具仍报 scope 不匹配 | 支持上述实际可用性故障；这两条 Experience 的 shell 绕行属于**临时操作经验**，不是目标架构 |
| `experiences/EXPERIENCE-20260924-mcp-console-channel-actor-seatbelt-lfl-exec-worksp.md` | 外层 channel-actor 实测对工作区外写入、`ps` / `lfrt` 观察造成 EPERM；`dangerous` 不等于宿主不受限 | **Mac P1：进程不可观察 != 服务已停止**；重启资格不得因沙盒观察失败而冒充满足 |
| `tests/env_channel.py:49-73`；`tests/test_sandbox_backend.py:264-282` | 工具内再启动 `sandbox-exec` 可遇 `sandbox_apply: Operation not permitted`；现有测试对该环境 skip | **Mac P1：双重沙盒限制是环境资格差异**；不得将 skip 当成真实 OS 隔离验收 PASS |
| `experiences/EXPERIENCE-20261027-macos-沙箱内桌面自动化可行性基线-坐标系-权限-依赖三项实测.md` | `osascript` System Events 返回 -10004，但现有回执无法区分 TCC 未授权还是沙盒拦 Mach IPC | **待归因**；不得直接把桌面自动化失败归咎于沙盒或直接要求授予全盘权限 |
| `scripts/build_macos_cli_pkg.py:43-68, 116-146` | .app 内以 `uv pip install --offline` 安装 wheel；复制重定位后执行 `--version` 与 `check-install` | **Mac/Linux 共用 wheel 资源风险**；未安装/未签名成品之前已有的 smoke 仅证明当时 `check-install` 覆盖到的项目，lite 未进入 required 时仍有盲区 |

### 9.2 Mac P0：分离“在哪执行”和“允许写哪里”

**目标不在于让 Agent 更容易绕过沙盒，而是让已明确授权的工作区正常工作，同时拒绝非授权路径。** 用已有 `workspace/store.py` 的注册/选择机制和会话绑定根作为可信授权来源，不让任意 `execute_command(workdir=...)` 自动扩大 `file-write*` 允许范围。

最小可实施调整：

1. 给 `execute_command` 的 **cwd** 与沙盒 **writable roots** 分别确定事实：`workdir` 只指定工作目录；可写根从经过验证的当前工作区/显式授权工作区与既有必要临时、缓存目录派生；路径须 resolve/canonicalize 并限制过宽根及 symlink 越界。未经授权的 cwd 可以用于合法只读操作，但不能因 cwd 存在而获得任意写权限。
2. `read_file(snapshot=true)`、`edit_file(expected_snapshot_ref=...)` 只需支持**经同一授权体系确认的工作区**（含明确登记的隔离 worktree），保留同路径、同工作区、同版本快照、durable effect journal 与 symlink/held-out 防护。不能以取消 `WorkspaceScopeMismatch` 的全局校验替代修复。
3. 当前 `EXEC_SANDBOX_MACOS_WRITABLE` 属于宿主侧管理配置，不应让模型自行追加；保留原有临时/缓存根，但对列表进行安全校验并在诊断中报告授权来源/沙盒模式。不能把 `dangerous`、`none`、`<home>`、`/` 当作默认应急方案。
4. **避免大规模 API 重构**：优先把当前授权 workspace 的精确根传给 `sandbox_exec_argv`，保持 Linux `bwrap/docker` 现状；若二者也存在相同 cwd=write_root 语义，则以独立小补丁/测试解决，不在这个 Linux wheel P0 候选中重做执行引擎。

### 9.3 Mac P1：外层沙盒、系统权限与真实服务状态分层

- `MCP Console` 的 `permission_mode=dangerous`、`filesystem_scope=workspace`、`host_access=false` 是不同维度；**无需也不能**据此推断已获得完整 macOS 宿主权限。要先报告工具调用所处的实际 channel/工作区/沙盒层，不假定本会话与历史案例一模一样。
- 普通 Agent shell 不承担正式服务停启控制；继续使用现有 `runtime/service_control.py` 控制路径和已核验的宿主资格。`ps` 被拒、`lfrt` 观察为空只能归类 `observation_denied/unknown`，不能推断 PID 已消失或自动触发重启。
- `sandbox-exec` 嵌套启动失败、临时目录回退、TCC/Accessibility/Automation 缺权、Keychain/签名身份不可达是**不同错误类别**。`doctor` 或调用回执只补充关键阶段、实际后端与原因码；不加后台巡检或假“权限自动修复”。
- 需要真实系统 TCC/Gatekeeper/notarytool 行为的测试应在**受控原生 Mac 宿主**进行；嵌套沙盒测试标记为未取得资格/跳过原因并另留必跑的真机验收记录，不允许用 skip 替代签名、公证、干净安装或恢复链验证。

### 9.4 Mac 与 Linux wheel 的共同发行验收

`scripts/build_macos_cli_pkg.py` 已做移动后的 .app `--version`/`check-install`，应在既有流程最小补充规则资产 smoke，而不是重建安装器。**同名 `0.6.37` pre-fix/fix wheel 可并存**（§2.5/§2.6 SHA 和字节数已证明），严格校验必须绑定实际 wheel SHA/manifest asset list/安装解释器模块来源，不能只比较版本号。

| 验收面 | 必须取得的实际证据 | 终态口径 |
|---|---|---|
 Mac wheel → .app/.pkg | 明确 wheel SHA、.app 内 `_bundled/docs/ai_rules.md` 与 `ai_rules.lite.md`、manifest hash、`rules_version=20`、受控规则检索成功；离开源码根运行 | 完好新候选 PASS；缺/坏 lite 的**新候选** FAIL |
 Linux 当前版 → 新版 / 旧版回滚 | 活动旧轮已安装文件不可被新包名/版本混淆；旧 legacy 自检兼容，新候选严格检查，升级/回滚均保留数据 | pre-fix 存留 release 不被“同版新 required”错误砖化；损坏候选绝不激活 |
 Mac 沙盒授权工作区 | 已授权根读、snapshot、edit、exec 写均成功；未授权根写拒绝，修改 `workdir` 不增加写权限 | 相同授权范围在四种工具上表现一致 |
 Mac 外层/内层沙盒 | 单层成功；嵌套受限得到明确原因，原生宿主 OS 测试另有真实回执 | 不把嵌套 skip、EPERM 或 shell workaround 算作全绿 |
 Mac 服务/桌面权限 | 服务控制可观察真实 PID/健康；TCC/osascript 失败能与 sandbox/Mach IPC 拒绝区分；真实签名公证/Gatekeeper/安装/保留数据验收 | 未获得宿主授权则标记 BLOCKED/UNKNOWN，不能宣称已完成 |

### 9.5 当前状态与执行顺序（以 v4 仓库证据为准）

**已完成、勿重复施工**：`setup.py` / `MANIFEST.in` 的 lite 打包，`installation.rules_version()` 单一入口，`status/causality` 统一调用；`ae62c6cab` 已将 `rules_doc_candidates()` 收敛为 bundle/source 唯一根并补三项负向测试（v4.1 勘误：原误记 `2c569426`）；`ce22e2912` 已将 lite 纳入 `check_install()` required 版本门控（任务 2 代码部，新增/修改单测与 `test_check_install.py` 回归绿）。§2/§3/§6/§7 记载的 `19758ec79` 待办为**当时快照**，不可再当作现在未完成的工作派给 LFL。

**仍待修复/验证，保持两条最小候选**：

1. **Linux wheel P0（独立收口）**：代码部已由 `ce22e2912` 落地——门控即"受信旧包清单兼容策略"：manifest 显式列 lite **或**版本 ≥ `LITE_RULES_MIN_VERSION=0.6.38` 才强制（非仅 `manifest.version >= 0.6.37`），同号 0.6.37 pre-fix 存留版（无 lite 条目）自动降级 warn 不阻断升级/回滚硬门。**验证部已由 v4.2 完成（本机 macOS，独立 venv，未动生产）**：0.6.37 修复 wheel（sha256 `d2d831d6…`）安装 `check-install ok`/347 文件/`rules_version=20`/doctor pass；突变为 pre-fix 形态（删 lite 文件+manifest 条目）`ok=true`+降级告警、doctor warn 不判死、恢复后 347 全过；0.6.38（sha256 `98f0ae3d…`）剥离 lite `ok=false`/exit 1 硬拦。`doctor` 错误分类已由 `4e109a468` 落地（§3.4 任务 3/4 一并完成：rule_asset_facts 单函数、error_code 分类、版本归一"020"→"20"）。剩余仅第 4 项的门禁流程。
2. **Mac 工具 P0（独立小补丁）**：**已由 v4.2 完成**——`647706c09`（分支 `fix/mac-tool-sandbox-cwd-split-20261028`）：`macos_writable_roots(workspace_root)` 只认授权工作区+白名单缓存/临时根，任意 workdir 仅作 Popen cwd；空 root 防护堵死 `abspath("")=cwd` 放行。专项证明：单元断言 profile 不含任意 workdir；真实 sandbox-exec 实测授权内可写（rc=0）、授权外拒写（`Operation not permitted`、零泄漏）。回归 test_sandbox 24 + execute_command 28 = 52 项绿。
3. **Mac 诊断/原生验收 P1**：区分外层/内层沙盒、进程观测拒绝、嵌套 sandbox/TCC；在受控原生宿主验收真机隔离和 .pkg。历史 Linux 旁路 PASS、现有 Mac 单测/skip、Apple 旧包 Accepted 均不能替代**当前候选**真实验证。
4. 各候选分别做定向回归、精确冻结、独立 GLM-5.3 审查、原版完整 R9 及各自适用的平台 smoke，取得实际回执后再讨论 main/发行；避免一个未完成的 Mac 权限改造卡住已具备收口条件的 Linux wheel 修复。**本报告编辑不授权合并、push、发布、安装或重启。**

**Experience / Method 后续纠偏**：将“`execute_command(workdir=目标目录)` + shell patch 解决任意工作区写入”标记为既有受限环境下的**临时绕行经验**，并以“先登记/核验授权工作区，再使用版本化文件编辑工具”替代长期推荐做法。保留对过去操作事实的历史记录，不删除事故证据；只在真正修复和专项验收后更新执行性建议。

**v4 最终判定**：wheel 规则版本问题与 Mac 工具权限不一致是两条可独立修复的缺陷。保持规则资源私有、保留安全沙盒、允许**已授权的工作区**可靠操作，比全局关闭沙盒、扩大 HOME 写权限或增加多层审批更安全、更简单。
