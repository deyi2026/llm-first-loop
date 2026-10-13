# Web Carveout 交付报告：deepseek/chatgpt 页面自动化通道剥离为独立项目

- 日期：2026-10-14　状态：交付完成（中间件全量回归 8687/0；发布 gen256
  + 重启受理 svc-8944f762 终态为会话退出后异步事实；真机往返核验见 §5 遗留）
- 设计：docs/web-carveout-m0.md（M0 调查 + grill_me 评审 + D1-D6 用户确认
  「按倾向定」2026-10-14T00:18）
- Goal：GOAL-20261013-a36699bb
- 独立项目：~/Project/lfl-web-providers（@ 47e14c8，146 passed）

## 1. 问题与结果

deepseek/chatgpt 页面自动化 client（Playwright transport，单窗口可达 120s）
与中间件内核耦合：provider 注册/配置/观测三面硬编码，影响面 12 源文件 +
18 配置字段 + webui 观测路由族。剥离后中间件 web 域为零 web 通道代码
（G2），通道实现独立演进（D1-D6 决策），引擎契约面收敛为 duck 协议 +
7 符号 import（契约测试锁定）。

## 2. 交付内容

### 2.1 独立项目 lfl-web-providers（M2，5f21f07 → 47e14c8）
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

## 5. 遗留与候选

- **G4 真机往返（待重启完成后核验）**：生产 .env 已配置
  LFL_WEB_PROVIDERS_MODULE=lfl_web_providers.registration（+PATH 指向
  独立项目 src 目录）；重启后 web 目录应经外部注册出现 deepseek-web 条目（目录端点
  /api/v1/models 或 engine registry），chatgpt-web 维持必填缺失不注册形。
- **真机 t_effect 抽查（自前序交接候选 1 延续，环境已备）**：CDP 9229 存活
  （Chrome 154）、deepseek 标签已开且登录态 LOGGED_IN 实测（2026-10-14
  00:1x 探针）；抽查脚本应基于独立项目 client 栈实施，回填
  docs/phase6-delivery-report.md §6。
- venv editable 指针指向 .releases 发布快照（gen 部署机制）：裸 python 与
  pytest(pythonpath=src) 加载不同代码，调试/脚本须走 pytest 路径或显式
  sys.path——已记录设计稿 §5 M3 段。
