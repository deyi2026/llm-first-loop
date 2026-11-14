---
title: 头条发表：准入材质上限的 artifact 指纹占用、CDP /json/new 需 PUT、公示核验须剥 CSS 序号
scenario: 今日头条 d 系列文章发表流程：review_admission(article_publish) 受理失败、CDP 新开公开页报 KeyError target_id、公示核验可比行绑定 5 行 miss
root_cause: ""
solution: "①准入超限时逐项裁剪 artifact_paths（指纹也占额度），保留最必要指纹即可过闸；②CDP 新开页用 requests.put(CDP+\"/json/new?url=\"+quote(URL))，取返回体 id 字段，用完 /json/close/{id}；③公示绑定对 md 行剥有序列表序号后再 flat 比较（d83 _comparable_lines 已含此规则，自建脚本须复刻）。"
evidence: d84 发布全链回执：docs/promotion/receipts/d84-admission.json（三次 start 尝试 79056→78378→78138→accepted 41374 chars）；_d84_public_try.py 修复记录（PUT+id）；/tmp/bind.txt（5 miss）→/tmp/bind2.txt（114/114）
tags: [toutiao-publish, review-admission, cdp, public-verify]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T16:14:08.013409+08:00"
updated_at: "2026-11-13T16:14:08.013409+08:00"
supersedes: [EXPERIENCE-20261113-宿主准入-review-material-的-78kb-上限-页面文本被截断-只有主稿与-artif]
---

现象1（准入材质上限）：review_admission(kind=article_publish) 对审查材质有 78000 字符上限（browser_page_review_cap_exceeded），且 artifact_paths 每项指纹（路径+SHA+字节数，约 240 字符/项）也计入材质；md_nonws≈14K、页面≈15K 的稿件附 8 个 artifact 会超限约 1K。处置：artifact_paths 最小化为必要指纹（如仅账本），figures/receipts 留在磁盘由独立子代理审查链覆盖。现象2（CDP 新开页）：Chrome 156 的 /json/new 必须 PUT（GET 返回无 target_id 的错误体），URL 放 query，返回字段是 id 不是 target_id。现象3（公示核验）：头条文章页有序列表序号是 CSS ::marker 渲染、不在 innerText，可比行绑定必须剥 ^\s*\d+\.\s+，否则整组列表行误报缺失。
当前性验证：grep -n "browser_page_review_cap_exceeded" 本会话 d84-admission 三次尝试记录（docs/promotion/receipts/d84-admission-status.json 邻近日志）确认上限行为仍在；重跑绑定时先在比对脚本里 grep -n "sub(r\"^\\\\s*\\\\d+\\\\.\\\\s+\"" 确认序号剥除规则在位，缺失则整组列表行会再次误报。