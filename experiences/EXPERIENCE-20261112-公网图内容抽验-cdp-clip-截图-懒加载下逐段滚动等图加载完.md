---
title: 公网图内容抽验：CDP clip 截图 + 懒加载下逐段滚动等图加载完
scenario: 对公网头条文章页做 4 张配图的内容抽验，CDN 直连 403，且 clip 脚本只抓到 3 张
root_cause: 公网 CDN 拒绝直连下载；同时图片懒加载使一次性查询拿到的是尚未加载的元素集合。
solution: ① 图片内容抽验走 CDP clip 截图而非直连下载；② 抽验前按 scrollBy 分段滚动并轮询已加载图的 naturalHeight 集合，补齐后再逐张 clip；③ 抽验结论要区分「数字一致」与「排版瑕疵」（本班图338 窄栏把 except / review_host_admission.py 强制断行，属 P2 不阻断）。
evidence: 本班 d79（2026-11-12）：_d79_public_img.py 直连报 HTTP 403；_d79_public_shot.py 首版只出 3 张（shot0..2），改为 scrollBy 分段下拉并按 naturalHeight 集合补齐后出齐 4 张（d79_pub_shot0..3.png）；read_image 复核图337/图338 关键数字全部一致、无截断，窄栏英文标识符断行登记为 P2。
tags: [公网验收, CDP, 图片抽验, 403]
source: {}
status: invalid
record_kind: experience
verification_state: verified
created_at: "2026-11-12T12:43:48.955118+08:00"
updated_at: "2026-11-13T09:16:01.449949+08:00"
---

公网文章页的 CDN 图片直连返回 403，改用 CDP Page.captureScreenshot 对 <img> 元素逐个 clip 截图落盘后 read_image 复核。懒加载页要按 scrollBy 分段下拉，等已加载图的 naturalHeight 集合补齐再 clip，不能只靠 naturalWidth>=900 过滤（会漏图）。当前性验证：造页后跑 `python3 docs/promotion/_d79_public_shot.py`，输出应含 4 张 PNG（d79_pub_shot0..3.png），且每张 natural_wh 与本地 PNG 尺寸逐一相等。

## 失效与替代（2026-11-12 R4 周检）

本卡按 R3 事实轴 invalidate（2026-11-13 执行，卡内 updated_at=2026-11-13T09:16:01+08:00）：卡内当前性标准「输出应含 4 张 PNG（d79_pub_shot0..3.png），且每张 natural_wh 与本地 PNG 尺寸逐一相等」与一手回执矛盾——docs/promotion/receipts/d79-public-shots.json（mtime 11-12 12:40）只登记 3 条（idx 0/1/2），shot3 的 PNG（12:41）未入账；natural_wh 是图片自然尺寸（1000×1053），PNG 是设备像素（实测 1352×1424 = css_wh 676×712 × 2），二者无相等关系；脚本仍按 naturalWidth>=900 过滤并取 items[:4]，卡内自警的漏图风险未消除。现行口径见替代卡：experience:EXPERIENCE-20261113-公网图抽验的现行口径-json-登记条数与-png-设备像素是两套量-naturalwidth-90（正文互指）。