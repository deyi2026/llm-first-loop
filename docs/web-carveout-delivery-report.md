# Web Carveout 交付报告：deepseek/chatgpt 页面自动化通道剥离为独立项目

- 日期：2026-10-14　状态：交付完成（中间件全量回归 8687/0；发布 gen256；
  G4 真机往返等价验证完成——生产进程内生效待 restart 终态后核验，§5）
- 设计：docs/web-carveout-m0.md（M0 调查 + grill_me 评审 + D1-D6 用户确认
  「按倾向定」2026-10-14T00:18）
- Goal：GOAL-20261013-a36699bb
- 独立项目：~/Project/lfl-web-providers（@ e74fd98，157 passed）

## 1. 问题与结果

deepseek/chatgpt 页面自动化 client（Playwright transport，单窗口可达 120s）
与中间件内核耦合：provider 注册/配置/观测三面硬编码，影响面 12 源文件 +
18 配置字段 + webui 观测路由族。剥离后中间件 web 域为零 web 通道代码
（G2），通道实现独立演进（D1-D6 决策），引擎契约面收敛为 duck 协议 +
7 符号 import（契约测试锁定）。

## 2. 交付内容

### 2.1 独立项目 lfl-web-providers（M2，5f21f07 → 33e07dd）
- 12 模块内聚迁移（llm/ 10 + runtime/ 2 平铺），相对 import 修正 15 处；
- 14 测试迁移 + conftest 数据目录隔离（宿主 LFL_DATA_DIR 指向中间件生产
  data/，不隔离则 hmac 语义测试假红）；
- 契约测试 3 项：pin 0.6.32（git_head 0072fbc0c 快照）+ 7 符号面
  （run_context 两符号为 ContextVar 验 .get，实测修正断言错误）+ duck 协议；
- registration.py（M3）：web_provider_specs / web_client_factories duck 契约
  + 必填校验语义与旧 finalize 对齐（chatgpt 必填缺失 warning 不注册——
  生产 .env 实态即此形，行为与剥离前一致）；
- config.py：通道明细配置自 .env（env > dotenv 优先级）；.env 真实值迁入。

### 2.2 中间件接缝（M3，6db89d6b5）
- 新增 llm/web_provider_registration.py：importlib 动态加载（D3），失败
  分级——未配置静默 / 配置失败 warning+不注册（不阻断构建）；module_path
  注入 sys.path（独立项目免安装加载，无 pip 级循环依赖）；
- providers.py 双硬编码注册段（-105 行）→ 外部 spec 注入，id 冲突拒绝；
- factory.py 双注册段 → 外部 factories + effective_refs 过滤（语义保持）；
- config.py：18 字段 + 6 校验函数 + 快照区 → web_providers_module(+path)；
- resolver.py：18 TOML 映射删 + carved-out 前缀 fail-closed（写入旧 section
  报错并指迁独立项目 .env——防「写了但无人消费」的静默无效配置）；
- webui（D1）：观测面移除（notifier/probe 挂载 + provider-binding/
  bindings/health/gc-plan/gc 四路由 + store helpers + GcRequest，-330 行）；
- 删除 12 源 + 14 测试（M3 后零残留，G2 grep 证据在提交）；M5 脚本退役标注。

### 2.3 测试改写（4 接缝测试 → 新语义）
- registration×2 → test_web_provider_registration（7 项：注入/懒挂/
  冲突/失败分级×2/path 注入/未配置）；
- catalog → 外部注入后目录暴露 + 未配置无 web 条目（2 项）；
- observability 6 项 → 移除断言（路由 404 + state 无 notifier，2 项）；
- runtime section 4 项 → carved-out fail-closed 断言（1 项，两前缀×两形态）。

## 3. 测试与不变量

- 中间件全量：**8687 passed / 0 failed**（611s，2026-10-14T01:0x 终验；
  首轮 11 failed 全部定位修复：_BARRIER_QUEUE_CAP 误删/arch 守卫基线 3 处
  合法漂移/M5 退役脚本 ratchet 撞车/runtime section 测试语义过时）；
- 独立项目：146 passed（143 迁移+契约 + 3 registration）；
- ruff 改动面 0 error；
- Phase6 七条语义红线（G5）：chat_stream 零变化/Stop 四态/P1-6/单次结算/
  guard 无死锁/peek fail-open/配置门逃生舱——全部在中间件全量回归中保持
  （phase6 测试集原样绿）。

## 4. 发布

- 提交链：bbab0dc9b（M1 定稿）→ 6db89d6b5（M3 接缝+删除）→ 501ead7d0
  （M2/M3 记录）→ 7b79c7ace（发布前置树收口，混合来源机械提交已标注）；
- publish **generation=256**（deploy-f39b2c60c4a6447989653da1a1124097，
  git_head=7b79c7ace，webui 产物 sha=1ed83575…5264 零改动沿用）；D5 预期
  的 255 已被并行会话（00:12，cff9339d）占用，顺延 256；
- restart svc-8944f762977447ad905f1f6309c351a5 已受理（两阶段等待 requester
  退出后异步执行；终态核验 service_control(status)）。

## 5. G4 真机核验结果与遗留（2026-10-14 上午补验）

### 5.1 G4 发现并修复的两个真实缺陷（真机核验的价值所在）

- **发现路径**：`/api/v1/providers` 运行时计数与 raw 磁盘一致（5/28，
  无外部条目）→ 进程外复现外部模块加载 → 定位。
- **#1 dotenv 布局缺陷（6220dfc）**：`_package_root()` 在 src 布局返回
  `src/`，读不存在的 `src/.env`（真实 .env 在项目根）→ 双通道静默
  `enabled=False` → specs 空、无 warning（fail-soft「未配置」形态）。
  修复：平铺（上溯 2 级）→ src 布局（上溯 3 级）候选搜索，src 内
  .env 优先（本地覆盖）；布局单测 + 本 checkout 条件回归。
- **#2 闭包劫持（ae87bee）**：两通道块复用局部名 `duck`，闭包按引用捕获
  → 双通道同时 enabled（生产形态）时 chatgpt 块重绑定劫持 deepseek lambda，
  deepseek builder 收到 chatgpt duck（无 deepseek_web_* 属性）→「未完整
  配置」错。此前测试只断言 factories 键集合未实际调用 builder。修复：
  分名绑定 + 双通道 builder 实调用回归（假 build 捕获收到的 settings）。
- **#3（Phase6 候选 1 范畴，e74fd98）**：停止控件 aria-label 选择器对当前
  deepseek UI 结构性 miss（控件无 aria-label，发送/停止共体仅 svg path
  切换）→ 升级实测 svg 特征探测。详见 docs/phase6-delivery-report.md §5.2。

### 5.2 G4 真机往返（等价路径验证完成）

- **路径与生产同构**：中间件 `web_provider_registration` 接缝（importlib
  动态加载）→ `lfl_web_providers.registration.web_client_factories` →
  `build_deepseek_web_model_client`（settings duck 透传中间件 data_dir，
  D4 lease 连续性）→ CDP surface → 真页面。
- **结果**：specs 注册 `deepseek-web`；真页面 chat 往返 7.7s，
  finish=stop，回显 `OK-G4` 精确匹配。工件
  reports/web-carveout/g4/ROUNDTRIP.json。chatgpt-web 维持必填缺失
  不注册形（stderr warning 明示，与剥离前语义一致）。
- **真机 t_effect（Phase6 候选 1 一并收口）**：cancel→早退抛错
  41/507/714ms（n=3）+ 停止释放点击生效（取消后发送图标回归、文本停止
  增长）——回填 docs/phase6-delivery-report.md §5.2。

### 5.3 待下会话核验（restart 终态后）

- restart svc-cbbc2f575e46419ebe2b264ce507f354 已受理（两阶段：等本
  会话退出后执行）——生产进程需重启重新 import 修复后的外部模块（模块
  缓存不热更新）；
- 核验点（2026-10-14T10:10 用户裁决后修订）：`/api/v1/providers`
  运行时计数**不含 deepseek-web**（lfl-web-providers/.env
  `DEEPSEEK_WEB_ENABLED=0`，通道退役；chatgpt-web 未被提及不受影响）；
  ~~生产 API 走 deepseek-web 一次真机往返~~ **撤销**——用户裁决弃用
  deepseek，§5.2 G4 等价路径验证即为该通道最终实测存档；
- venv editable 指针指向 .releases 发布快照（gen 部署机制）：裸 python 与
  pytest(pythonpath=src) 加载不同代码，调试/脚本须走 pytest 路径或显式
  sys.path——已记录设计稿 §5 M3 段。
