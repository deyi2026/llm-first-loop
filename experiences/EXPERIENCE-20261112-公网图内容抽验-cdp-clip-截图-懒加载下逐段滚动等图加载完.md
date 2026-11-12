---
title: 公网图内容抽验：CDP clip 截图 + 懒加载下逐段滚动等图加载完
scenario: 对公网头条文章页做 4 张配图的内容抽验，CDN 直连 403，且 clip 脚本只抓到 3 张
root_cause: 公网 CDN 拒绝直连下载；同时图片懒加载使一次性查询拿到的是尚未加载的元素集合。
solution: ① 图片内容抽验走 CDP clip 截图而非直连下载；② 抽验前按 scrollBy 分段滚动并轮询已加载图的 naturalHeight 集合，补齐后再逐张 clip；③ 抽验结论要区分「数字一致」与「排版瑕疵」（本班图338 窄栏把 except / review_host_admission.py 强制断行，属 P2 不阻断）。
evidence: 本班 d79（2026-11-12）：_d79_public_img.py 直连报 HTTP 403；_d79_public_shot.py 首版只出 3 张（shot0..2），改为 scrollBy 分段下拉并按 naturalHeight 集合补齐后出齐 4 张（d79_pub_shot0..3.png）；read_image 复核图337/图338 关键数字全部一致、无截断，窄栏英文标识符断行登记为 P2。
tags: [公网验收, CDP, 图片抽验, 403]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-12T12:43:48.955118+08:00"
updated_at: "2026-11-12T12:43:48.955118+08:00"
---

公网文章页的 CDN 图片直连返回 403，改用 CDP Page.captureScreenshot 对 <img> 元素逐个 clip 截图落盘后 read_image 复核。懒加载页要按 scrollBy 分段下拉，等已加载图的 naturalHeight 集合补齐再 clip，不能只靠 naturalWidth>=900 过滤（会漏图）。当前性验证：造页后跑 `python3 docs/promotion/_d79_public_shot.py`，输出应含 4 张 PNG（d79_pub_shot0..3.png），且每张 natural_wh 与本地 PNG 尺寸逐一相等。