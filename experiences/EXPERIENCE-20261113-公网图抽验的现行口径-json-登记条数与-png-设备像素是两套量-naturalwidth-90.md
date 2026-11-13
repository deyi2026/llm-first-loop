---
title: 公网图抽验的现行口径：json 登记条数与 PNG 设备像素是两套量，naturalWidth>=900 过滤仍会漏图
scenario: 用 CDP clip 抽验公网已发布文章的配图时，登记回执与本地 PNG 数量对不上，且容易把 natural_wh（图片自然尺寸）当成 PNG 像素尺寸去做「逐一相等」校验。本卡取代失效卡 EXPERIENCE-20261112-公网图内容抽验-cdp-clip-截图-懒加载下逐段滚动等图加载完（该卡声称「出齐 4 张且每张 natural_wh 与本地 PNG 尺寸逐一相等」，实测 json 只登记 3 条、第 4 张 PNG 未入账，且 natural_wh 与设备像素无相等关系）。
root_cause: ""
solution: "1) 三个量分开记：json 每条 = 一张图的登记（url + natural_wh 图片自然尺寸 + css_wh 页面显示尺寸）；PNG = 设备像素截图（实测 = css_wh × 2，与 natural_wh 无相等关系），不要拿 natural_wh 去对 PNG 像素；2) 登记完整性要单独核：PNG 张数与 json 条数必须对齐，出图在前、写 json 在后且中途异常会留下「有 PNG 无条目」，收口前逐一对账；3) 漏图边界仍在：脚本按 naturalWidth>=900 过滤并取 items[:4]，小图与第 5 张以后的图会漏，补图要放宽过滤或按 naturalHeight 集合补齐，而不是相信「已出齐」；4) 懒加载页仍需分段下拉等图加载完（scrollBy 分段），否则截图拿到的是未加载完的版面。"
evidence: "2026-11-12 R4 周检实测：docs/promotion/receipts/d79-public-shots.json（mtime 11-12 12:40）只含 3 条（idx 0/1/2）；docs/promotion/receipts/d79_pub_shot0..3.png 共 4 张在册（shot3 mtime 12:41，晚于 json，未入账）；d79_pub_shot0.png 实测 1352×1424 px，json natural_wh=[1000,1053]、css_wh=[676,712]（1352=676×2）；脚本 docs/promotion/_d79_public_shot.py:9 仍按 naturalWidth>=900 过滤、:41 仍 items[:4]。失效卡与本卡互指。"
tags: [公网抽验, CDP, 配图, 口径, 自然尺寸, 登记对账]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T09:16:20.971411+08:00"
updated_at: "2026-11-13T09:16:20.971411+08:00"
---

## 适用信号

- 要对已发布文章做公网配图抽验（CDP clip + 分段滚动等懒加载）。
- 要在回执里写「已出齐 N 张图」「图尺寸与登记一致」之前。
- 看到 natural_wh / css_wh / PNG 像素三组数字要直接做相等比较的时候。

## 不管什么

- 不用 natural_wh 去对 PNG 像素：natural_wh 是图片自然尺寸，PNG 是 css_wh × 2 的设备像素截图，两者是不同量。
- 不把「脚本跑完了」当「图登记全了」：出图与写 json 分两步，中途异常会留下有 PNG 无条目。
- 不信任「已出齐」：naturalWidth>=900 的过滤与 items[:4] 的截断会漏图，补图要放宽过滤或按 naturalHeight 集合补齐。
- 与 EXPERIENCE-20261112-rule28-准入材料上限同时计页面可见正文与稿件全文-只传-artifact-paths-主稿 相邻：那一卡管「送审材料给多少」，本卡管「抽验回执记什么」，别混用。

## 核验方法

1. 数 PNG 与数 json 条数：`ls docs/promotion/receipts/d79_pub_shot*.png` 与 `python3 -c "import json;print(len(json.load(open('docs/promotion/receipts/d79-public-shots.json'))))"`。期望：两者相等。
2. 读 PNG 设备像素：`sips -g pixelWidth -g pixelHeight <png>`；与 json 的 css_wh 比较，期望 ≈ css_wh × 2（不是等于 natural_wh）。
3. 查过滤与截断：`grep -n "naturalWidth\|items\[:4\]" docs/promotion/_d79_public_shot.py`，据此判断是否有漏图边界。

## 核验记录

- 2026-11-13（2026-11-12 触发轮 R4 周检）：json 3 条 vs PNG 4 张（shot3 未入账，PNG mtime 晚于 json）；d79_pub_shot0.png 实测 1352×1424 px vs natural_wh=[1000,1053]、css_wh=[676,712]；脚本仍 naturalWidth>=900 + items[:4]。据此作废失效卡 EXPERIENCE-20261112-公网图内容抽验-cdp-clip-截图-懒加载下逐段滚动等图加载完，本卡为替代卡（正文互指）。

## 失效与替代

本卡替代失效卡 experience:EXPERIENCE-20261112-公网图内容抽验-cdp-clip-截图-懒加载下逐段滚动等图加载完（2026-11-12 R4 周检作废，理由：登记条数与像素相等两项标准均与回执矛盾）。
