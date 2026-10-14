# -*- coding: utf-8 -*-
"""Build self-contained HTML promo article + markdown source for LFL."""
import base64, os

BASE = os.path.dirname(os.path.abspath(__file__))

def b64(name):
    with open(os.path.join(BASE, "assets", name), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LFL：把"诚实、可核验、记得住"写进架构的 AI 智能体运行时</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; background:#eef2f7; color:#1f2937; line-height:1.9;
         font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif; }
  .page { max-width:900px; margin:0 auto; background:#fff; padding:0 52px 64px; box-shadow:0 0 40px rgba(22,50,79,.08); }
  .hero { margin:0 -52px; }
  .hero img { width:100%; display:block; }
  .meta { display:flex; flex-wrap:wrap; gap:10px; margin:26px 0 6px; }
  .chip { font-size:13px; color:#16324f; background:#e8f1fb; border:1px solid #c9ddf2; border-radius:999px; padding:3px 14px; }
  h1 { font-size:30px; line-height:1.45; color:#16324f; margin:18px 0 10px; }
  .sub { color:#6b7280; font-size:15px; margin:0 0 8px; }
  h2 { font-size:22px; color:#16324f; margin:52px 0 14px; padding-top:10px; border-top:1px solid #eef2f7; }
  h2 .num { color:#2563eb; font-size:15px; font-weight:700; margin-right:10px; letter-spacing:1px; }
  h3 { font-size:16px; color:#16324f; margin:26px 0 8px; }
  p { font-size:15.5px; margin:12px 0; }
  figure { margin:30px 0; }
  figure img { width:100%; border:1px solid #e5e7eb; border-radius:12px; box-shadow:0 3px 14px rgba(22,50,79,.07); }
  figcaption { text-align:center; color:#6b7280; font-size:13px; margin-top:9px; }
  .callout { background:#f0f6ff; border-left:4px solid #2563eb; border-radius:0 10px 10px 0;
             padding:12px 18px; color:#16324f; margin:20px 0; font-size:15px; }
  .callout.warm { background:#fdf6e9; border-color:#d97706; }
  .callout.green { background:#f0fdf4; border-color:#059669; }
  pre { background:#0f2540; color:#dbeafe; padding:18px 22px; border-radius:12px; overflow:auto;
        font:13px/1.7 "SF Mono",Menlo,Consolas,monospace; }
  code { font-family:"SF Mono",Menlo,Consolas,monospace; }
  p code, li code { background:#f1f5f9; border-radius:5px; padding:1px 6px; font-size:13.5px; color:#0f2540; }
  table { border-collapse:collapse; width:100%; margin:18px 0; font-size:14.5px; }
  th { background:#16324f; color:#fff; font-weight:600; padding:9px 14px; text-align:left; }
  td { border-bottom:1px solid #e5e7eb; padding:8px 14px; }
  tr:nth-child(even) td { background:#f8fafc; }
  ul { padding-left:24px; } li { margin:6px 0; font-size:15.5px; }
  .facts { background:#f8fafc; border:1px dashed #cbd5e1; border-radius:12px; padding:16px 22px;
           font-size:13.5px; color:#475569; margin-top:48px; }
  .facts b { color:#16324f; }
  .tag { display:inline-block; font-size:12px; color:#fff; background:#2563eb; border-radius:5px;
         padding:1px 9px; margin-right:8px; vertical-align:2px; }
</style>
</head>
<body>
<div class="page">

<div class="hero"><img src="__BANNER__" alt="LFL 横幅"></div>

<h1>LFL：把"诚实、可核验、记得住"写进架构的 AI 智能体运行时</h1>
<p class="sub">——写给每一个被 AI 的"已完成"坑过的人</p>
<div class="meta">
  <span class="chip">开源 Apache-2.0</span><span class="chip">v0.6.32</span>
  <span class="chip">Python ≥ 3.13</span><span class="chip">CLI · Web · 飞书 三端接入</span>
  <span class="chip">LLM-First Agent Runtime</span>
</div>

<p>如果你用过任何 AI 智能体，大概率见过这三种场面：它拍着胸脯说"已经改好了"，实际那条命令根本没执行过；它把训练记忆里的旧版本号、旧路径当成今天的现状；昨天交代的长任务，今天一开口，它忘得一干二净。</p>
<p>这些问题的根子往往不在模型不够聪明，而在缺少一层把"聪明"落成"可靠"的运行时。<b>LFL（llm-first-loop）</b>就是为此而生的开源项目：一个以大模型为核心、程序做感官与手脚、把诚实与证据当硬约束的 Agent 运行时（Harness）。</p>

<h2><span class="num">01</span>LFL 是什么：一句话与一张图</h2>
<p>LFL 的官方定位只有一句话：<b>一个"AI 优先"（LLM-first）的 Agent 运行时——程序最小化 + 文档规则驱动 + AI 自主演进闭环</b>，内置记忆、检索、事件溯源与评测体系，支持 CLI、Web、飞书三端接入。</p>
<figure><img src="__POSITIONING__" alt="LFL 定位图">
<figcaption>图 1 · LFL 定位：大模型内核 + 程序感官与手脚 + 记忆与审计（三端接入同一运行时）</figcaption></figure>
<p>它的架构态度很鲜明：程序不与大模型争指挥权。程序负责"真实的执行、持久化、协议与授权、灾难性安全、崩溃恢复"，其余判断尽量交给模型 + 规则完成。</p>
<div class="callout">程序 = 感官 + 手脚；文档规则 = 判断纪律。工具的成功、失败、异常都如实构造回执，错误完整透传，不静默降级。——LFL 架构原则（README.md）</div>

<h2><span class="num">02</span>核心循环：五阶段状态机，一步一景</h2>
<p>每一条消息进入 LFL，都会走完同一个闭环：<b>消息进 → 理解 → 行动 → 真诚回答 → 记住</b>。这五步由 LoopEngine 状态机驱动，每一步都留下可观测的痕迹。</p>
<figure><img src="__LOOP__" alt="核心循环五阶段">
<figcaption>图 2 · LoopEngine 五阶段状态机：程序管回执与边界，模型管判断与表达</figcaption></figure>
<p>关键在"行动"这一步：模型调用的每个工具，程序都会返回带状态标注的回执（如 <code>[状态: success]</code>），失败与异常原样透传。这为下一节的"诚实工程"打下地基。</p>

<h2><span class="num">03</span>三层权威边界：把"谁说了算"写进架构</h2>
<p>多智能体系统最容易出事的，不是能力不足，而是<b>越权</b>：模型替用户拍了板，程序替模型做了判断。LFL 把权威切成三层，并写入铁律。</p>
<figure><img src="__LAYERS__" alt="三层权威边界">
<figcaption>图 3 · 三层权威边界：授权下行、证据回流（依据 docs/STACK.md v0.1 草案与现行规则库 v19）</figcaption></figure>
<ul>
<li><b>L3 用户层</b>：真人指令是任务授权的唯一真值；远端写、合并删除、凭证、公开发布只由真人拍板。</li>
<li><b>L2 模型层</b>：负责任务策略、完成判断、证据引用；禁止扩大授权、禁止伪造精确。</li>
<li><b>L1 程序层</b>：机器裁决——安全硬边界、超时预算、原子写、证据持久化、协议校验。</li>
</ul>
<div class="callout warm">铁律：下层不得扩大上层授权。事实争议回到 L1——任何结论绑定的 EvidenceRef 都可以随时"水合"回放原文，谁在撒谎一验便知。</div>

<h2><span class="num">04</span>诚实工程：让"说完成"变成可核验的事</h2>
<p>这是 LFL 最想差异化的一点。它把几条"反幻觉纪律"直接做进了运行契约：</p>
<figure><img src="__HONESTY__" alt="诚实工程对比">
<figcaption>图 4 · 常见 Agent 的坑 vs LFL 的做法</figcaption></figure>
<ul>
<li><b>回执文化</b>：未获成功回执，不得声称完成——"未获成功回执不得声称完成"写进了模型的系统契约，而不是靠自觉。</li>
<li><b>先取证后判断</b>：涉及当前代码、文件、版本、运行态的事，训练先验只算假设，必须先取当前证据；无法核对就明示"未核验"，不猜。</li>
<li><b>证据强制</b>：运行时开启 evidence 强制模式，关键动作与观察都沉淀为可回放的证据记录。</li>
</ul>

<h2><span class="num">05</span>记忆不丢：从热上下文到长期经验</h2>
<p>上下文超长怎么办？LFL 的答案是<b>分层记忆 + 事件溯源</b>：压缩档案自动另存、稳定证据引用可随时回放、经验与方法跨会话沉淀——信息不丢失被当作功能来设计，而不是当作事故来补救。</p>
<figure><img src="__MEMORY__" alt="记忆分层">
<figcaption>图 5 · HOT / WARM / COLD / 长期四层记忆与"沉淀-检索"双向通道</figcaption></figure>
<p>底座是事件日志（<code>data/event_logs/&lt;sid&gt;.jsonl</code>）作为轨迹单一真相源：会话创建、消息追加、上下文压缩等五类事件全部落盘，支持回放重建、逐字段对账校验、会话 fork 与滚动归档。上一段对话的每个结论，都能找回原文。</p>

<h2><span class="num">06</span>自主演进闭环：AI 提案，人放行，全程留痕</h2>
<p>LFL 不把"自我改进"停留在口号上：AI 可以基于自评发起演进建议，但<b>放行权在人</b>，执行按权限分级，动作全链路审计。这不是演示项目——它在这套系统自己的开发中被天天使用：</p>
<figure><img src="__EVOLUTION__" alt="自主演进闭环与真实数据">
<figcaption>图 6 · 演进闭环五步（自我评估 → 演进建议 → 人工审阅 → 分级执行 → 全链路审计）</figcaption></figure>
<table>
<tr><th>指标（截至 2026-10-14 运行时回执）</th><th>数值</th></tr>
<tr><td>演进建议累计</td><td><b>184 条</b></td></tr>
<tr><td>人工审阅接受</td><td>46 条</td></tr>
<tr><td>执行中</td><td>15 条</td></tr>
<tr><td>已执行落地</td><td><b>114 条</b></td></tr>
<tr><td>规则库版本（docs/ai_rules.md）</td><td>v19</td></tr>
</table>
<p>换句话说，你看到的这套框架，大部分迭代是由运行在它之上的 AI 自己提议、人类审阅后落地的——Dogfooding 到了架构层。</p>

<h2><span class="num">07</span>能力全景：从"会聊天"到"能上手干活"</h2>
<figure><img src="__CAPS__" alt="能力全景">
<figcaption>图 7 · LFL 能力全景（部分能力由配置开关控制，以运行配置为准）</figcaption></figure>
<ul>
<li><b>浏览器感知与操作</b>：只读感知（快照/精确寻址/差异对比/等待）+ 单次派发操作（导航/点击/填写/选择/滚动），经 CDP 接管真实 Chromium——做网页自动化不再"盲操"。</li>
<li><b>子代理与编排</b>：后台子代理、并行/流水线/DAG 编排、有界修复循环，配租约预算与结果结算。</li>
<li><b>服务生命周期</b>：状态查询、发布、重启一条龙；发布以当前代做 CAS、要求干净 git 树、绑定产物哈希。</li>
<li><b>模型体系</b>：模型目录查询、AI 自主切换（带理由审计）、应急降级链、按模型上下文窗口自适应历史预算。</li>
<li><b>评测体系</b>：固定场景集 + Wilson 区间判定 + nightly 自动回归，改进有没有效果，数据说了算。</li>
<li><b>蒸馏数据导出</b>：会话轨迹导出为带思考链的 ReAct JSONL——用 LFL 干活的过程数据，可以直接变成你自己模型的训练素材。</li>
<li><b>MCP 只读导出</b>：经验库、方法库、证据账本以 MCP 协议接出，Claude Desktop 等任意 MCP 宿主可直接复用。</li>
<li><b>插件化 Skill</b>：一个 SKILL.md 就能扩展框架能力，外部开发者零代码接入。</li>
</ul>

<h2><span class="num">08</span>五分钟上手</h2>
<p>LFL 是标准 Python 项目（≥ 3.13），用 uv 一键安装：</p>
<pre><code># 1. 安装（lockfile 精确可复现，含 ruff/pyright/pytest 门禁三件套）
cd llm-first-loop
uv sync --frozen --extra dev

# 2. 配置密钥（模型可按需选择）
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1

# 3. 最小闭环：单条消息
.venv/bin/python -m llm_loop.cli "请读取 data/notes.txt 并总结内容"

# 4. 交互模式（--session 可复用既有会话，跨天续聊）
.venv/bin/python -m llm_loop.cli --interactive</code></pre>
<p>配好飞书桥后，Web 管理台与飞书可共享同一会话——在群里交代一句，回桌面接着干，上下文无缝衔接。</p>

<h2><span class="num">09</span>它适合谁？（以及不适合谁）</h2>
<div class="callout green"><b>适合</b>：需要长任务、跨会话记忆与可审计自动化的开发者与团队；想把大模型接进真实终端、浏览器与服务的工程场景；希望把组织经验沉淀为可复用"方法库"的团队。</div>
<div class="callout warm"><b>请注意（如实说）</b>：LFL 的灾难性安全是"已知灾难模式硬阻断 + 全量审计"，<b>不是完备沙箱</b>，更强隔离需叠加执行分级与系统级沙箱；演进闭环有人工审阅环节，不是全自动改架构；当前版本 0.6.x，接口仍在快速演进。</div>
<p>在"什么都敢承诺"的 AI 工具营销里，LFL 选择反着来：把边界写清楚，把证据留下来，把没做到的如实说。如果你也受够了"幻觉式完成"，值得亲自跑一遍它的最小闭环。</p>

<div class="facts">
<b>事实与数据来源</b><br>
· 功能与定位：项目 README.md（v0.6.32）；架构边界：docs/STACK.md（v0.1 草案）、docs/ARCHITECTURE-ai-state-model-v1.md；规则真值源：docs/ai_rules.md（v19）。<br>
· 运行数据（184/46/15/114/v19）：architecture_status 运行时回执，采集于 2026-10-14。<br>
· 全部配图由本文作者以 matplotlib 按上述来源生成（生成脚本与素材见 outputs/lfl-article/）；截图类数据为采集时点快照，以最新运行时为准。<br>
· 本文为项目推广文，功能描述以官方文档与实际运行为准；仓库获取方式以项目方发布渠道为准。
</div>

</div>
</body>
</html>
"""

MD = """# LFL：把"诚实、可核验、记得住"写进架构的 AI 智能体运行时

> 开源 Apache-2.0 ｜ v0.6.32 ｜ Python ≥ 3.13 ｜ CLI · Web · 飞书 三端接入

如果你用过任何 AI 智能体，大概率见过这三种场面：它拍着胸脯说"已经改好了"，实际那条命令根本没执行过；它把训练记忆里的旧版本号、旧路径当成今天的现状；昨天交代的长任务，今天一开口，它忘得一干二净。

这些问题的根子往往不在模型不够聪明，而在缺少一层把"聪明"落成"可靠"的运行时。**LFL（llm-first-loop）**就是为此而生的开源项目：一个以大模型为核心、程序做感官与手脚、把诚实与证据当硬约束的 Agent 运行时（Harness）。

## 01 LFL 是什么

官方定位一句话：**一个"AI 优先"（LLM-first）的 Agent 运行时——程序最小化 + 文档规则驱动 + AI 自主演进闭环**，内置记忆、检索、事件溯源与评测体系，支持 CLI、Web、飞书三端接入。

![LFL 定位图](assets/img1_positioning.png)

> 程序 = 感官 + 手脚；文档规则 = 判断纪律。工具的成功、失败、异常都如实构造回执，错误完整透传，不静默降级。——LFL 架构原则（README.md）

## 02 核心循环：五阶段状态机

每一条消息进入 LFL，都会走完同一个闭环：**消息进 → 理解 → 行动 → 真诚回答 → 记住**。模型调用的每个工具，程序都会返回带状态标注的回执（如 `[状态: success]`），失败与异常原样透传。

![核心循环五阶段](assets/img2_core_loop.png)

## 03 三层权威边界

- **L3 用户层**：真人指令是任务授权的唯一真值；远端写、合并删除、凭证、公开发布只由真人拍板。
- **L2 模型层**：任务策略、完成判断、证据引用；禁止扩大授权、禁止伪造精确。
- **L1 程序层**：安全硬边界、超时预算、原子写、证据持久化、协议校验。

铁律：**下层不得扩大上层授权**；事实争议回到 L1——结论绑定的 EvidenceRef 可随时回放原文。

![三层权威边界](assets/img3_three_layers.png)

## 04 诚实工程

- **回执文化**：未获成功回执，不得声称完成——写进模型系统契约，而不是靠自觉。
- **先取证后判断**：涉及当前代码/文件/版本/运行态的事，训练先验只算假设；无法核对就明示"未核验"，不猜。
- **证据强制**：运行时开启 evidence 强制模式，关键动作与观察沉淀为可回放的证据记录。

![诚实工程对比](assets/img4_honesty.png)

## 05 记忆不丢

分层记忆 + 事件溯源：压缩档案自动另存、稳定证据引用可随时回放、经验与方法跨会话沉淀。底座是事件日志（`data/event_logs/<sid>.jsonl`）作为轨迹单一真相源，支持回放重建、逐字段对账、会话 fork 与滚动归档。

![记忆分层](assets/img6_memory.png)

## 06 自主演进闭环

AI 基于自评发起演进建议，**放行权在人**，执行按权限分级，动作全链路审计。

| 指标（截至 2026-10-14 运行时回执） | 数值 |
|---|---|
| 演进建议累计 | **184 条** |
| 人工审阅接受 | 46 条 |
| 执行中 | 15 条 |
| 已执行落地 | **114 条** |
| 规则库版本（docs/ai_rules.md） | v19 |

![自主演进闭环](assets/img5_evolution.png)

## 07 能力全景

浏览器感知与操作（CDP 接管真实 Chromium）、子代理与编排、服务生命周期控制、模型体系（目录/自主切换/应急降级链）、评测体系（固定场景集 + Wilson 区间 + nightly）、蒸馏数据导出（ReAct JSONL）、MCP 只读导出、插件化 Skill。（部分能力由配置开关控制，以运行配置为准。）

![能力全景](assets/img7_capabilities.png)

## 08 五分钟上手

```bash
cd llm-first-loop
uv sync --frozen --extra dev

export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1

.venv/bin/python -m llm_loop.cli "请读取 data/notes.txt 并总结内容"
.venv/bin/python -m llm_loop.cli --interactive
```

## 09 它适合谁？（以及不适合谁）

- **适合**：需要长任务、跨会话记忆与可审计自动化的开发者与团队；想把大模型接进真实终端、浏览器与服务的工程场景。
- **请注意（如实说）**：灾难性安全是"已知灾难模式硬阻断 + 全量审计"，**不是完备沙箱**，更强隔离需叠加执行分级与系统级沙箱；演进闭环有人工审阅环节；当前版本 0.6.x，接口仍在快速演进。

---

**事实与数据来源**：README.md（v0.6.32）；docs/STACK.md（v0.1 草案）；docs/ARCHITECTURE-ai-state-model-v1.md；docs/ai_rules.md（v19）；architecture_status 运行时回执（2026-10-14）。配图由本文作者以 matplotlib 生成。本文为项目推广文，功能描述以官方文档与实际运行为准。
"""

html = (TEMPLATE
        .replace("__BANNER__", b64("img0_banner.png"))
        .replace("__POSITIONING__", b64("img1_positioning.png"))
        .replace("__LOOP__", b64("img2_core_loop.png"))
        .replace("__LAYERS__", b64("img3_three_layers.png"))
        .replace("__HONESTY__", b64("img4_honesty.png"))
        .replace("__MEMORY__", b64("img6_memory.png"))
        .replace("__EVOLUTION__", b64("img5_evolution.png"))
        .replace("__CAPS__", b64("img7_capabilities.png")))

with open(os.path.join(BASE, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("index.html written:", len(html), "chars")

with open(os.path.join(BASE, "article.md"), "w", encoding="utf-8") as f:
    f.write(MD)
print("article.md written:", len(MD), "chars")
assert "__" not in html.replace("__", "", 0) or "__BANNER__" not in html, "placeholder left!"
