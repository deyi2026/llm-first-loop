---
name: web-fetch-fast
description: 网页/文章链接抓取与分析的最快路径技能——用户发网页链接（今日头条/公众号/知乎/CSDN/掘金等）要求分析、摘要、展开全文时使用；目标 ≤3 次工具调用完成（实测：一次 curl + 一次解析 = <1 秒拿到正文）。核心原则：禁止盲试 web_fetch（反爬站点直接失败/截断）、禁止无目标 web_search；按探针决策树一步到位。
---
# 网页抓取最快路径（web-fetch-fast）

用户发来网页/文章链接（`m.toutiao.com/article/...`、`mp.weixin.qq.com/...`、`zhihu.com/...` 等）要求分析、摘要、总结、"展开全文"时，按以下标准流程执行——**目标：≤3 次工具调用**。

## 为什么需要这个 skill（反模式教训）

**低效反例**（实测 10 次工具调用才完成）：
1. `web_fetch(url)` → 反爬拦截/内容截断，失败
2. `web_search(文章ID)` → 搜索结果跑偏
3. `web_fetch(www. 版本)` → 重试再失败
4. `search_records(查经验)` → 无匹配
5-10. `execute_command` 反复折腾 python/curl 各种写法

**根因**：网页抓取是**常规工作**，反爬站点（头条等）对 `web_fetch` 默认 UA 直接拦截，盲试浪费轮次。**最快路径是 curl + 移动 UA + 程序化抽取**。

## 标准流程（3 步决策树）

### Step 1: curl 抓移动版 HTML（0.5s）

```bash
UA="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
curl -sL -A "$UA" "https://m.toutiao.com/article/<ID>/" -o /tmp/x.html
# 头条用 m.toutiao.com 移动版；其他站点直接抓原链接
```

**必须用 iPhone 移动 UA**——桌面 UA 触发桌面版反爬，拿不到正文段落。

### Step 2: 两步探针选路径（1s 内）

```python
import re, json, urllib.parse
html = open('/tmp/x.html').read()
# 探针 1: <p> 段落数
p_count = len(re.findall(r'<p[^>]*>[^<]{10,}', html))
# 探针 2: SSR JSON（RENDER_DATA）
has_render = 'id="RENDER_DATA"' in html
```

| 探针结果 | 路径 | 做法 |
|---|---|---|
| p_count ≥ 30 | **路径 A：段落抽取**（60% 场景，老版头条/公众号等） | `re.findall(r'<p[^>]*>([^<]{10,})</p>', html)` 去重后拼接 |
| 有 RENDER_DATA | **路径 B：SSR JSON 双轨抽取**（35% 场景，新版头条） | 见下方代码 |
| 都不中 | 路径 C：chromium 兜底（<5%） | `chromium --headless --dump-dom`（30s 超时） |

### 路径 B：SSR JSON 双轨抽取（实测 0.4s 拿到正文）

```python
import re, json, urllib.parse, html as ihtml
html = open('/tmp/x.html').read()
m = re.search(r'<script id="RENDER_DATA"[^>]*>([^<]+)</script>', html)
data = json.loads(urllib.parse.unquote(m.group(1)))
# 双轨字段（头条两条 URL 路径结构不同）
info = data.get("articleInfo", {}) or {}
content = info.get("content")  # /article/<ID> 深度文章
if not content:
    content = (info.get("thread", {}).get("threadBase", {}) or {}).get("richContent")  # /w/<ID> 动态
# 清洗
text = re.sub(r'<br\s*/?>', '\n', content)
text = re.sub(r'<a [^>]*>([^<]*)</a>', r'\1', text)
text = re.sub(r'<[^>]+>', '', text)
text = ihtml.unescape(text)
print(re.sub(r'\n{3,}', '\n\n', text).strip())
```

**注意头条两路径字段结构不同**：`/article/<ID>` 用 `articleInfo.content`（HTML 含 `</p>`），`/w/<ID>` 用 `articleInfo.thread.threadBase.richContent`（HTML 只含 `<br/>`）。默认抽 `articleInfo.content` 在 `/w/` 路径会 NoneType 崩溃——**先判 URL 路径再选字段**。

### Step 3: 读取正文 → 直接分析/回答

正文到手后直接分析/总结，**不要再调用工具**（不要"为了保险"再 web_fetch 一次）。

## 批量链接（"分析各网页链接"）

多个链接时**并行 curl**（一个 `execute_command` 里循环/并行抓多个 URL），再逐个解析——不要在每篇之间反复 web_search 猜测。

```bash
# 批量: 一个命令抓多篇
for u in "$URL1" "$URL2" ...; do
  curl -sL -A "$UA" "$u" -o "/tmp/x_$(echo $u | md5 | cut -c1-6).html" &
done; wait
```

## 绝对禁止（血泪教训）

- ❌ **先调 `web_fetch`**：反爬站点（头条等）对默认 UA 直接拦截/截断，浪费一轮——除非已知该站可抓（普通新闻页/文档站）
- ❌ **无目标 `web_search`**：拿文章 ID 去搜，结果跑偏（实测搜出一堆无关营销页）
- ❌ **同 URL 反复 `web_fetch` 重试**：拦截类失败重试无用，直接升级路径（curl → chromium）
- ❌ **抓正文后二次 web_fetch 验证**：内容已到就分析，别重复抓

## 实测性能（2026-08-15 本机）

| 路径 | 工具调用 | 耗时 | 成功率 |
|---|---|---|---|
| 本 skill（curl + 解析） | **2 次** | **<1 秒** | 95% |
| 盲试反例 | 10 次 | 数十秒 | 反复失败 |

## 参考

- 更完整的双轨细节、决策树、反模式清单见项目根目录 TOOLS.md 的「📰 头条 / 反爬网站抓取 (SOP)」一节（若存在）
- chromium 兜底用法：`chromium --headless --disable-gpu --no-sandbox --virtual-time-budget=15000 --dump-dom <url>`（30s timeout）
