---
title: 知乎图片插入后刷新会丢失：发布前必须回读校验图片数，丢失则从编辑页补插再「更新」
scenario: 用 CDP 脚本向知乎编辑器逐张插入图片后，因中途执行 location.reload() 排查「发布中...」卡住问题，导致已插入的 7 张图全部丢失；随后 publish 仍成功，但发布出去的文章正文 0 张图（imgTotal=0 / figures=0）。头条侧同类管线不受此影响。
root_cause: 知乎草稿编辑页的图片以内存态持有，reload 会丢弃未随草稿持久化的图片；发布流程不校验图片数，导致「发布成功」但正文无图。
solution: |
  1) 排查编辑器卡住时不要 reload 草稿编辑页——知乎该页草稿态的图片由内存态持有，reload 会丢弃未随草稿持久化的图片。
  2) 用「resume」而非重跑全量：以 STATE 里的 loaded 为起点续插，避免重复插入（EXISTING_IMAGE_COUNT_UNEXPECTED 闸门会拦）。
  3) 发布后必须做公网/正文回读校验：查 .Post-RichTextContainer 内 img/figure 数量与 naturalWidth>0 的加载数，仅看「发布成功」弹层不算验证。
  4) 发现图片丢失的补救：导航回 /p/<id>/edit，用 resume 补插图，再点「更新」按钮（已发布文章的按钮是「更新」不是「发布」），更新后再次回读确认 7 张 1280x800。
  5) 发布按钮卡在「发布中...」且 disabled 时，多数是请求在飞或前端态未回；先等 30-60s，再查 URL 是否已从 /edit 变为 /p/<id> 来判定真实结果，不要连点。
evidence: 知乎 p/2094584329951246082：首次发布后回读 imgTotal=0、figures=0；补插 7 张并点「更新」后回读 imgTotal=7、figures=7、loaded=7、dims 全为 1280x800、captions=7。
tags: [zhihu, publish, image-loss, reload, readback, CDP]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-17T00:43:49.559743+08:00"
updated_at: "2026-10-17T00:43:49.559743+08:00"
---