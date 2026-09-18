---
title: 飞书附件 .zip 报 234001：file_type 白名单不含 zip，用无点号文件名回退 stream
scenario: 用 send_feishu_attachment 给用户发 zip 压缩包（92MB DXF 压到 6.6MB），上传即失败 code=234001；另注意飞书单文件上限 30MB，超大 DXF 需 zip 压缩。
root_cause: ""
solution: 把文件复制成完全不含点号的文件名（如「xxx-DXF压缩包」），suffix 为空时代码回退 file_type=stream（合法），发送成功；收件人下载后手动补 .zip 后缀解压。
evidence: "失败两次: open_id 与 chat_id 均 234001（工具回执）；成功: data/incoming/李妙斯、林锦鹏方案修改-20260724-DXF压缩包 → chat oc_88fb84ddbb9bfb4af62e6681ae0f0986，message_id=om_x100b66f58ebf38a4b3bdd608634946b；代码位置 src/llm_loop/feishu/rest.py:640"
tags: [feishu-attachment, 234001, file-type-whitelist, zip, send_feishu_attachment]
source: {}
status: active
created_at: "2026-09-05T21:41:31.935462+08:00"
updated_at: "2026-09-05T21:41:31.935462+08:00"
---

现象: send_feishu_attachment 发送 .zip 文件失败，上传阶段即返回 code=234001 Invalid request param（open_id/chat_id 两种 receive_id 均同错）。根因: src/llm_loop/feishu/rest.py:640 `file_type = Path(file_name).suffix.lstrip(".").lower() or "stream"` 把扩展名直接传给飞书 im/v1/files，而该接口只接受 opus/mp4/pdf/doc/xls/ppt/stream；"zip" 不在白名单。注意文件名里任何点号都会被 Path.suffix 截成后缀（如 "2026.07.24" 的 ".24"），所以改名必须保证整个文件名无点号，不能只去掉 .zip。修复建议: rest.py 增加后缀→合法 file_type 白名单映射，未知后缀回退 stream。